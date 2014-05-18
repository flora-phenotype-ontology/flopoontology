import java.util.logging.Logger
import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.reasoner.*
import org.semanticweb.owlapi.profiles.*
import org.semanticweb.owlapi.util.*
import org.semanticweb.owlapi.io.*
import org.semanticweb.elk.owlapi.*
import org.semanticweb.owlapi.vocab.OWLRDFVocabulary

OWLOntologyManager manager = OWLManager.createOWLOntologyManager()

OWLDataFactory fac = manager.getOWLDataFactory()
OWLDataFactory factory = fac

OWLOntology ont = manager.loadOntologyFromOntologyDocument(new File(args[0]))

def id2label = [:] // maps a name to an OWLClass
OWLAnnotationProperty label = fac.getOWLAnnotationProperty(OWLRDFVocabulary.RDFS_LABEL.getIRI())
ont.getClassesInSignature(true).each { cl ->
  def annos = cl.getAnnotations(ont, label)
  annos.each { anno ->
    if (anno.getValue() instanceof OWLLiteral) {
      OWLLiteral val = (OWLLiteral) anno.getValue()
      println cl.toString().replaceAll("<http://phenomebrowser.net/plant-phenotype.owl#","").replaceAll(">","") + "\t" + val.getLiteral()
    }
  }
}

