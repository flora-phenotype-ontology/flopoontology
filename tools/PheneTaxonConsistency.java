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
import org.semanticweb.owlapi.model.OWLEquivalentClassesAxiom;
import org.semanticweb.owlapi.model.OWLObjectProperty;
import org.semanticweb.owlapi.model.OWLOntology;
import org.semanticweb.owlapi.model.OWLOntologyLoaderConfiguration;
import org.semanticweb.owlapi.model.OWLOntologyManager;

import uk.ac.manchester.cs.owlapi.modularity.ModuleType;
import uk.ac.manchester.cs.owlapi.modularity.SyntacticLocalityModuleExtractor;

/**
 * Consistency of each taxon, one taxon at a time, on the axioms as they are published.
 *
 * A phenotype class is a phene: 'flora phenotype' and 'phenotype of' some Y, where Y is a
 * property of the plant (has part some (petal and has characteristic some white)). A taxon is a
 * class with 'has phenotype' some C for each of its classes. 'phenotype of' is functional and the
 * inverse of 'has phenotype' (Hoehndorf, Oellrich and Rebholz-Schuhmann 2010,
 * doi:10.1093/bioinformatics/btq578), so every plant of the taxon has all the defining
 * properties: "petals absent" (not (has part some (part of some petal))) and "petals white"
 * cannot both hold, given that a petal is part of itself (part of is reflexive).
 *
 * This needs a reasoner for all of OWL 2 DL. For each taxon the part of the ontologies that its
 * classes depend on is cut out (a syntactic locality module, type BOT, of the ontologies together
 * with the definitions of the taxon's own classes), and HermiT tests whether one plant can have
 * all the phenes. For an inconsistent taxon the classes are reduced to a
 * smallest set that still contradicts itself.
 *
 *   java -Xmx12g -cp tools/robot.jar tools/PheneTaxonConsistency.java \
 *       closure.owl definitions.ttl taxa.tsv result.tsv [threads] [timeout seconds] [drop|keep] [classify]
 *
 * closure.owl: FLOPO, PO, PATO and the plant GO import, merged (the release classification input).
 * definitions.ttl: the annotation classes of a flora, in the phene form.
 * taxa.tsv: taxon key, tab, class IRIs separated by spaces.
 * result.tsv: taxon key, status (consistent | inconsistent | timeout | error), the conflicting
 * class IRIs or the error, number of module axioms, milliseconds.
 *
 * drop (default) leaves out FLOPO's own named phenotype classes that the flora does not use: they
 * are names for expressions and cannot change whether a taxon is consistent. keep uses everything.
 * classify also computes the class hierarchy of each consistent taxon's module and reports the time.
 */
public class PheneTaxonConsistency {

    static final OWLDataFactory DF = OWLManager.getOWLDataFactory();
    static final String OBO = "http://purl.obolibrary.org/obo/";
    static final OWLObjectProperty HAS_PHENOTYPE = DF.getOWLObjectProperty(IRI.create(OBO + "RO_0002200"));
    static final OWLObjectProperty PHENOTYPE_OF = DF.getOWLObjectProperty(IRI.create(OBO + "RO_0002201"));
    static final OWLObjectProperty PART_OF = DF.getOWLObjectProperty(IRI.create(OBO + "BFO_0000050"));
    static final String ROOT = OBO + "FLOPO_0000000";
    static final java.util.Map<OWLClass, Set<OWLAxiom>> DEFINITIONS = new java.util.HashMap<>();
    static boolean CLASSIFY = false;

    public static void main(String[] args) throws Exception {
        int threads = args.length > 4 ? Integer.parseInt(args[4]) : 4;
        long timeout = (args.length > 5 ? Long.parseLong(args[5]) : 120) * 1000;
        boolean drop = args.length <= 6 || !args[6].equals("keep");
        CLASSIFY = args.length > 7 && args[7].equals("classify");
        OWLOntologyManager manager = OWLManager.createOWLOntologyManager();
        manager.setOntologyLoaderConfiguration(new OWLOntologyLoaderConfiguration()
                .setMissingImportHandlingStrategy(MissingImportHandlingStrategy.SILENT));
        Set<OWLAxiom> axioms = new HashSet<>();
        Set<OWLEntity> used = new HashSet<>();
        // The definitions of the flora's annotation classes are kept apart, by class: a taxon is
        // checked with the definitions of its own classes only. The definition of a class the
        // taxon does not have cannot change the answer, but it is not "local" for the module
        // extractor as soon as all its terms are in the module, and never when it is a negation
        // ("costa absent") or an alternative ("ovate or lanceolate"): cut from all definitions
        // together, the module of one class of the Moss Flora of China held 1,600 definitions of
        // other classes (docs/phene-consistency.md).
        OWLOntology base = manager.loadOntologyFromOntologyDocument(new File(args[0]));
        axioms.addAll(base.getLogicalAxioms());
        axioms.addAll(base.getAxioms(AxiomType.DECLARATION));
        manager.removeOntology(base);
        OWLOntology floraFile = manager.loadOntologyFromOntologyDocument(new File(args[1]));
        used.addAll(floraFile.getClassesInSignature());
        used.addAll(floraFile.getObjectPropertiesInSignature());
        used.addAll(floraFile.getDataPropertiesInSignature());
        for (OWLAxiom axiom : floraFile.getLogicalAxioms()) {
            boolean ofClass = false;
            if (axiom.isOfType(AxiomType.EQUIVALENT_CLASSES)) {
                for (OWLClass c : ((OWLEquivalentClassesAxiom) axiom).getNamedClasses()) {
                    DEFINITIONS.computeIfAbsent(c, k -> new HashSet<>()).add(axiom);
                    ofClass = true;
                }
            }
            if (!ofClass) {
                axioms.add(axiom);  // anything else in the file is general knowledge
            }
        }
        manager.removeOntology(floraFile);
        if (drop) {
            Set<OWLEntity> named = new HashSet<>();
            for (OWLAxiom axiom : axioms) {
                if (!axiom.isOfType(AxiomType.EQUIVALENT_CLASSES)) {
                    continue;
                }
                OWLEquivalentClassesAxiom equivalent = (OWLEquivalentClassesAxiom) axiom;
                boolean composed = false;
                for (OWLClassExpression e : equivalent.getClassExpressions()) {
                    composed |= e.isAnonymous();
                }
                if (!composed) {
                    continue;
                }
                for (OWLClass c : equivalent.getNamedClasses()) {
                    String iri = c.getIRI().toString();
                    if (iri.contains("/FLOPO_") && !iri.equals(ROOT) && !used.contains(c)) {
                        named.add(c);
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
            System.err.println("left out " + named.size() + " named FLOPO phenotype classes, " + (before - axioms.size()) + " axioms");
        }
        // The axioms the phene form rests on (in FLOPO and in RO; stated here so that the check
        // does not depend on which of them the inputs carry), and reflexive parthood.
        axioms.add(DF.getOWLFunctionalObjectPropertyAxiom(PHENOTYPE_OF));
        axioms.add(DF.getOWLInverseObjectPropertiesAxiom(HAS_PHENOTYPE, PHENOTYPE_OF));
        axioms.add(DF.getOWLReflexiveObjectPropertyAxiom(PART_OF));
        used.add(HAS_PHENOTYPE);
        used.add(PHENOTYPE_OF);
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
        Set<OWLEntity> signature = new HashSet<>();
        for (String iri : cells[1].trim().split(" ")) {
            classes.add(DF.getOWLClass(IRI.create(iri)));
        }
        Set<OWLAxiom> definitions = new HashSet<>();
        for (OWLClass c : classes) {
            for (OWLAxiom axiom : DEFINITIONS.getOrDefault(c, java.util.Collections.<OWLAxiom>emptySet())) {
                definitions.add(axiom);
                signature.addAll(axiom.getSignature());  // every term of the taxon's own definitions
            }
        }
        signature.addAll(classes);
        signature.add(HAS_PHENOTYPE);
        signature.add(PHENOTYPE_OF);
        String status;
        String detail = "";
        int size = 0;
        OWLOntology module = null;
        Reasoner reasoner = null;
        try {
            // The module of the ontologies for the terms of the taxon's definitions, and the
            // definitions: together the locality module of (ontologies + these definitions).
            Set<OWLAxiom> cut = new HashSet<>(extractor.extract(signature));
            cut.addAll(definitions);
            size = cut.size();
            module = own.createOntology(cut);
            Configuration configuration = new Configuration();
            configuration.individualTaskTimeout = timeout;
            reasoner = new Reasoner(configuration, module);
            if (reasoner.isSatisfiable(plant(classes))) {
                status = "consistent";
                if (CLASSIFY) {  // a measurement: the class hierarchy of the taxon's module
                    long before = System.currentTimeMillis();
                    reasoner.precomputeInferences(org.semanticweb.owlapi.reasoner.InferenceType.CLASS_HIERARCHY);
                    detail = "classified in " + (System.currentTimeMillis() - before) + " ms";
                }
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

    /** A plant that has a phene of each class: what the taxon's axioms say of every member. */
    static OWLClassExpression plant(List<OWLClass> classes) {
        Set<OWLClassExpression> has = new LinkedHashSet<>();
        for (OWLClass c : classes) {
            has.add(DF.getOWLObjectSomeValuesFrom(HAS_PHENOTYPE, c));
        }
        return has.size() == 1 ? has.iterator().next() : DF.getOWLObjectIntersectionOf(has);
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
            if (!reasoner.isSatisfiable(plant(without))) {
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
