import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.model.*;
import org.semanticweb.owlapi.reasoner.*;
import org.semanticweb.elk.owlapi.ElkReasonerFactory;

/** Direct reasoner taxonomy, not a traversal of asserted/transitive subclass triples.
 * Compile against the repository's ROBOT jar. Input must be the offline merged closure.
 * Reports unsatisfiable classes instead of letting one bad candidate abort the batch.
 */
public class FlopoReasonerReport {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("input.owl output.tsv");
        OWLOntologyManager manager = OWLManager.createOWLOntologyManager();
        OWLOntology ontology = manager.loadOntologyFromOntologyDocument(new File(args[0]));
        if (!ontology.getImportsDeclarations().isEmpty())
            throw new IllegalArgumentException("Expected an offline, import-free closure");
        OWLReasoner reasoner = new ElkReasonerFactory().createReasoner(ontology);
        try {
            reasoner.precomputeInferences(InferenceType.CLASS_HIERARCHY);
            if (!reasoner.isConsistent()) throw new IllegalStateException("Inconsistent ontology");
            List<OWLClass> classes = new ArrayList<>(ontology.getClassesInSignature());
            classes.sort(Comparator.comparing(c -> c.getIRI().toString()));
            try (PrintWriter out = new PrintWriter(Files.newBufferedWriter(
                    Paths.get(args[1]), StandardCharsets.UTF_8))) {
                out.println("relation\tsubject\tobject");
                for (OWLClass c : classes) {
                    String id = c.getIRI().toString();
                    out.println("class\t" + id + "\t");
                    if (!reasoner.isSatisfiable(c)) {
                        out.println("unsatisfiable\t" + id + "\t");
                        continue;
                    }
                    for (OWLClass parent : reasoner.getSuperClasses(c, true).getFlattened())
                        out.println("parent\t" + id + "\t" + parent.getIRI());
                    for (OWLClass eq : reasoner.getEquivalentClasses(c).getEntities())
                        if (!eq.equals(c)) out.println("equivalent\t" + id + "\t" + eq.getIRI());
                }
            }
        } finally { reasoner.dispose(); }
    }
}
