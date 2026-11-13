import java.io.BufferedReader;
import java.io.File;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.semanticweb.HermiT.Configuration;
import org.semanticweb.HermiT.Reasoner;
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.model.AxiomType;
import org.semanticweb.owlapi.model.IRI;
import org.semanticweb.owlapi.model.MissingImportHandlingStrategy;
import org.semanticweb.owlapi.model.OWLAxiom;
import org.semanticweb.owlapi.model.OWLClass;
import org.semanticweb.owlapi.model.OWLClassExpression;
import org.semanticweb.owlapi.model.OWLDataFactory;
import org.semanticweb.owlapi.model.OWLEntity;
import org.semanticweb.owlapi.model.OWLOntology;
import org.semanticweb.owlapi.model.OWLOntologyLoaderConfiguration;
import org.semanticweb.owlapi.model.OWLOntologyManager;

import uk.ac.manchester.cs.owlapi.modularity.ModuleType;
import uk.ac.manchester.cs.owlapi.modularity.SyntacticLocalityModuleExtractor;

/**
 * Consistency of each taxon of a flora, one taxon at a time.
 *
 * A taxon is consistent when one plant can have all its annotation classes at once: "petals
 * absent" and "petals white" cannot. For each taxon the part of the ontologies that its classes
 * depend on is cut out (a syntactic locality module, type BOT), which is small, and HermiT, a
 * reasoner for all of OWL 2 DL, tests the conjunction of the classes on it. For an inconsistent
 * taxon the classes are reduced to a smallest set that still contradicts itself.
 *
 *   java -Xmx16g -cp tools/robot.jar tools/TaxonConsistency.java \
 *       closure.owl definitions.ttl taxa.tsv result.tsv [threads] [timeout seconds]
 *
 * taxa.tsv: taxon key, tab, class IRIs separated by spaces.
 * result.tsv: taxon key, status (consistent | inconsistent | timeout | error), the conflicting
 * class IRIs or the error, number of module axioms, milliseconds.
 */
public class TaxonConsistency {

    static final OWLDataFactory DF = OWLManager.getOWLDataFactory();

    public static void main(String[] args) throws Exception {
        int threads = args.length > 4 ? Integer.parseInt(args[4]) : 4;
        long timeout = (args.length > 5 ? Long.parseLong(args[5]) : 60) * 1000;
        OWLOntologyManager manager = OWLManager.createOWLOntologyManager();
        manager.setOntologyLoaderConfiguration(new OWLOntologyLoaderConfiguration()
                .setMissingImportHandlingStrategy(MissingImportHandlingStrategy.SILENT));
        Set<OWLAxiom> axioms = new HashSet<>();
        Set<OWLEntity> used = new HashSet<>();
        for (int i = 0; i < 2; i++) {
            OWLOntology loaded = manager.loadOntologyFromOntologyDocument(new File(args[i]));
            axioms.addAll(loaded.getLogicalAxioms());
            axioms.addAll(loaded.getAxioms(AxiomType.DECLARATION));
            if (i == 1) {
                used.addAll(loaded.getClassesInSignature());
            }
            manager.removeOntology(loaded);
        }
        // FLOPO's own phenotype classes ("leaf shape" = has part some (leaf and ...)) are names
        // for expressions: unless the flora uses one, it cannot change whether a taxon is
        // consistent, and the release classification has checked it. Without them the cut per
        // taxon is a few hundred axioms instead of more than 20,000.
        Set<OWLEntity> named = new HashSet<>();
        for (OWLAxiom axiom : axioms) {
            if (axiom.isOfType(AxiomType.EQUIVALENT_CLASSES)) {
                boolean composed = false;
                for (OWLClassExpression e : ((org.semanticweb.owlapi.model.OWLEquivalentClassesAxiom) axiom).getClassExpressions()) {
                    composed |= e.isAnonymous();
                }
                if (composed) {
                    for (OWLClass c : axiom.getClassesInSignature()) {
                        if (c.getIRI().toString().contains("/FLOPO_") && !used.contains(c)
                                && ((org.semanticweb.owlapi.model.OWLEquivalentClassesAxiom) axiom).getClassExpressions().contains(c)) {
                            named.add(c);
                        }
                    }
                }
            }
        }
        int before = axioms.size();
        axioms.removeIf(axiom -> {
            for (OWLClass c : axiom.getClassesInSignature()) {
                if (named.contains(c)) {
                    return true;
                }
            }
            return false;
        });
        System.err.println("left out " + named.size() + " composed FLOPO classes, " + (before - axioms.size()) + " axioms");
        // Cut once to what the flora uses at all; the cut per taxon then reads far fewer axioms.
        OWLOntology everything = manager.createOntology(axioms, IRI.create("urn:flopo:everything"));
        Set<OWLAxiom> floraModule = new SyntacticLocalityModuleExtractor(manager, everything, ModuleType.BOT)
                .extract(used);
        manager.removeOntology(everything);
        System.err.println("axioms " + axioms.size() + ", used by the flora " + floraModule.size());

        List<String> lines = Files.readAllLines(Paths.get(args[2]), StandardCharsets.UTF_8);
        AtomicInteger next = new AtomicInteger();
        try (PrintWriter out = new PrintWriter(Files.newBufferedWriter(Paths.get(args[3]), StandardCharsets.UTF_8))) {
            ExecutorService pool = Executors.newFixedThreadPool(threads);
            for (int t = 0; t < threads; t++) {
                pool.submit(() -> {
                    try {
                        OWLOntologyManager own = OWLManager.createOWLOntologyManager();
                        OWLOntology flora = own.createOntology(floraModule, IRI.create("urn:flopo:flora"));
                        SyntacticLocalityModuleExtractor extractor =
                                new SyntacticLocalityModuleExtractor(own, flora, ModuleType.BOT);
                        for (int i = next.getAndIncrement(); i < lines.size(); i = next.getAndIncrement()) {
                            String row = one(own, extractor, lines.get(i), timeout);
                            if (row != null) {
                                synchronized (out) {
                                    out.println(row);
                                    out.flush();
                                }
                            }
                        }
                    } catch (Throwable e) {
                        e.printStackTrace();
                    }
                });
            }
            pool.shutdown();
            pool.awaitTermination(30, TimeUnit.DAYS);
        }
    }

    static String one(OWLOntologyManager own, SyntacticLocalityModuleExtractor extractor, String line, long timeout) {
        String[] cells = line.split("\t");
        if (cells.length < 2 || cells[1].trim().isEmpty()) {
            return null;
        }
        long start = System.currentTimeMillis();
        List<OWLClass> classes = new ArrayList<>();
        for (String iri : cells[1].trim().split(" ")) {
            classes.add(DF.getOWLClass(IRI.create(iri)));
        }
        String status;
        String detail = "";
        int size = 0;
        OWLOntology module = null;
        Reasoner reasoner = null;
        try {
            Set<OWLAxiom> cut = extractor.extract(new HashSet<OWLEntity>(classes));
            size = cut.size();
            module = own.createOntology(cut);
            String dump = System.getenv("FLOPO_TAXON_MODULES");
            if (dump != null) {
                // The same question as a file for another reasoner: is urn:flopo:taxon satisfiable?
                OWLOntology copy = own.createOntology(cut);
                own.addAxiom(copy, DF.getOWLSubClassOfAxiom(DF.getOWLClass(IRI.create("urn:flopo:taxon")), all(classes)));
                own.saveOntology(copy, new org.semanticweb.owlapi.formats.FunctionalSyntaxDocumentFormat(),
                        IRI.create(new File(dump, cells[0].replaceAll("[^A-Za-z0-9]+", "_") + ".ofn")));
                own.removeOntology(copy);
            }
            Configuration configuration = new Configuration();
            configuration.individualTaskTimeout = timeout;
            reasoner = new Reasoner(configuration, module);
            if (reasoner.isSatisfiable(all(classes))) {
                status = "consistent";
            } else {
                status = "inconsistent";
                detail = String.join(" ", conflict(reasoner, classes));
            }
        } catch (org.semanticweb.owlapi.reasoner.TimeOutException e) {
            status = "timeout";
        } catch (Throwable e) {
            status = "error";
            detail = (e.getClass().getSimpleName() + ": " + e.getMessage()).replaceAll("\\s+", " ");
            if (detail.length() > 300) {
                detail = detail.substring(0, 300);
            }
        } finally {
            if (reasoner != null) {
                reasoner.dispose();
            }
            if (module != null) {
                own.removeOntology(module);
            }
        }
        return cells[0] + "\t" + status + "\t" + detail + "\t" + size + "\t" + (System.currentTimeMillis() - start);
    }

    static OWLClassExpression all(List<OWLClass> classes) {
        return classes.size() == 1 ? classes.get(0)
                : DF.getOWLObjectIntersectionOf(new LinkedHashSet<OWLClassExpression>(classes));
    }

    /** A smallest contradicting subset: drop each class in turn and keep it only if needed. */
    static List<String> conflict(Reasoner reasoner, List<OWLClass> classes) {
        List<OWLClass> kept = new ArrayList<>(classes);
        for (OWLClass candidate : classes) {
            if (kept.size() == 1) {
                break;
            }
            List<OWLClass> without = new ArrayList<>(kept);
            without.remove(candidate);
            if (!reasoner.isSatisfiable(all(without))) {
                kept = without;
            }
        }
        List<String> iris = new ArrayList<>();
        for (OWLClass c : kept) {
            iris.add(c.getIRI().toString());
        }
        return iris;
    }
}
