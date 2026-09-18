import java.io.File;

import org.semanticweb.HermiT.ReasonerFactory;
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.model.OWLOntology;
import org.semanticweb.owlapi.model.OWLOntologyManager;
import org.semanticweb.owlapi.reasoner.OWLReasoner;

/** Run HermiT consistency checking without the much costlier full class classification. */
class CheckOwlConsistency {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) {
            throw new IllegalArgumentException("usage: CheckOwlConsistency OWL_FILE");
        }
        OWLOntologyManager manager = OWLManager.createOWLOntologyManager();
        OWLOntology ontology = manager.loadOntologyFromOntologyDocument(new File(args[0]));
        OWLReasoner reasoner = new ReasonerFactory().createReasoner(ontology);
        boolean consistent = reasoner.isConsistent();
        reasoner.dispose();
        System.out.println("hermit_consistent=" + consistent);
        if (!consistent) {
            System.exit(1);
        }
    }
}
