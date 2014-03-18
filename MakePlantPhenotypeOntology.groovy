import java.util.logging.Logger
import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.reasoner.*
import org.semanticweb.owlapi.profiles.*
import org.semanticweb.owlapi.util.*
import org.semanticweb.owlapi.io.*
import org.semanticweb.elk.owlapi.*
import org.semanticweb.owlapi.vocab.OWLRDFVocabulary

def ontfile = new File("plant_ontology.obo")
def patofile = new File("quality.obo")

def id2name = [:]
new File("quality.tbl").splitEachLine("\t") { line ->
  def id = line[0]
  def name = line[1]
  id2name[id] = name
}
new File("plant_ontology.tbl").splitEachLine("\t") { line ->
  def id = line[0]
  def name = line[1]
  id2name[id] = name
}

String formatClassNames(String s) {
  s=s.replace("<http://purl.obolibrary.org/obo/","")
  s=s.replace(">","")
  s=s.replace("_",":")
  s
}

def cli = new CliBuilder()
cli.with {
usage: 'Self'
  h longOpt:'help', 'this information'
  o longOpt:'output-file', 'output file',args:1, required:true
  //  t longOpt:'threads', 'number of threads', args:1
  //  k longOpt:'stepsize', 'steps before splitting jobs', arg:1
}

def opt = cli.parse(args)
if( !opt ) {
  //  cli.usage()
  return
}
if( opt.h ) {
  cli.usage()
  return
}

OWLOntologyManager manager = OWLManager.createOWLOntologyManager()

OWLDataFactory fac = manager.getOWLDataFactory()
OWLDataFactory factory = fac

def ontset = new TreeSet()
OWLOntology ont = manager.loadOntologyFromOntologyDocument(ontfile)
ontset.add(ont)
ont = manager.loadOntologyFromOntologyDocument(patofile)
ontset.add(ont)

ont = manager.createOntology(IRI.create("http://lc2.eu/temp.owl"), ontset)

OWLOntology outont = manager.createOntology(IRI.create("http://phenomebrowser.net/plant-phenotype.owl"))
def onturi = "http://phenomebrowser.net/plant-phenotype.owl#"

OWLReasonerFactory reasonerFactory = null

ConsoleProgressMonitor progressMonitor = new ConsoleProgressMonitor()
OWLReasonerConfiguration config = new SimpleConfiguration(progressMonitor)

OWLReasonerFactory f1 = new ElkReasonerFactory()
OWLReasoner reasoner = f1.createReasoner(ont,config)

OWLAnnotationProperty label = fac.getOWLAnnotationProperty(OWLRDFVocabulary.RDFS_LABEL.getIRI())

reasoner.precomputeInferences(InferenceType.CLASS_HIERARCHY)

def r = { String s ->
  if (s == "part-of") {
    factory.getOWLObjectProperty(IRI.create("http://purl.obolibrary.org/obo/BFO_0000050"))
  } else if (s == "has-part") {
    factory.getOWLObjectProperty(IRI.create("http://purl.obolibrary.org/obo/BFO_0000051"))
  } else {
    factory.getOWLObjectProperty(IRI.create("http://phenomebrowser.net/#"+s))
  }
}

def c = { String s ->
  factory.getOWLClass(IRI.create(onturi+s))
}

def id2class = [:] // maps a name to an OWLClass
ont.getClassesInSignature(true).each {
  def aa = it.toString()
  aa = formatClassNames(aa)
  if (id2class[aa] != null) {
  } else {
    id2class[aa] = it
  }
}

def addAnno = {resource, prop, cont ->
  OWLAnnotation anno = factory.getOWLAnnotation(
    factory.getOWLAnnotationProperty(prop.getIRI()),
    factory.getOWLTypedLiteral(cont))
  def axiom = factory.getOWLAnnotationAssertionAxiom(resource.getIRI(),
                                                     anno)
  manager.addAxiom(outont,axiom)
}



def phenotypes = new HashSet()
new File("plant-data.tsv").splitEachLine("\t") { line ->

  def e = line[8]
  if (e?.indexOf("_")>-1) {
    e = e.substring(e.indexOf("_")+1)
  }
  def a = line[10]
  if (a?.indexOf("_")>-1) {
    a = a.substring(a.indexOf("_")+1)
  }
  def v = line[12]
  if (v?.indexOf("_")>-1) {
    v = v.substring(v.indexOf("_")+1)
  }
  Expando exp = new Expando()
  exp.e = e
  exp.a = a
  exp.v = v
  phenotypes.add(exp)
}

def count = 1 // global ID counter

def edone = new HashSet()
def e2p = [:]
/* Create abnormality of E classes */
phenotypes.each { exp ->
  def e = id2class[exp.e]
  def a = id2class[exp.a]
  def v = id2class[exp.v]
  if (e!=null && ! (e in edone)) {
    edone.add(e)
    def cl = c("APO:$count")
    addAnno(cl,OWLRDFVocabulary.RDFS_LABEL,id2name[exp.e]+" phenotype")
    //    addAnno(cl,OWLRDFVocabulary.RDF_DESCRIPTION,"The mass of $oname that is used as input in a single $name is decreased.")
    manager.addAxiom(outont, factory.getOWLEquivalentClassesAxiom(
		       cl,
		       fac.getOWLObjectSomeValuesFrom(
			 r("has-part"),
			 fac.getOWLObjectIntersectionOf(
			   fac.getOWLObjectSomeValuesFrom(
			     r("part-of"), e),
			   fac.getOWLObjectSomeValuesFrom(
			     r("has-quality"), id2class["PATO:0000001"])))))
    count += 1
  }
  if (e2p[e]== null) {
    e2p[e] = new HashSet()
  }
  if (e!=null && a!=null && ! (a in e2p[e])) {
    e2p[e].add(a)
    def cl = c("APO:$count")
    addAnno(cl,OWLRDFVocabulary.RDFS_LABEL,id2name[exp.e]+" "+id2name[exp.a])
    manager.addAxiom(outont, factory.getOWLEquivalentClassesAxiom(
		       cl,
		       fac.getOWLObjectSomeValuesFrom(
			 r("has-part"),
			 fac.getOWLObjectIntersectionOf(
			   e,
			   fac.getOWLObjectSomeValuesFrom(
			     r("has-quality"), a)))))
    count += 1
  }
  if (e!=null && v!=null && ! (v in e2p[e])) {
    e2p[e].add(v)
    def cl = c("APO:$count")
    addAnno(cl,OWLRDFVocabulary.RDFS_LABEL,id2name[exp.e]+" "+id2name[exp.v])
    manager.addAxiom(outont, factory.getOWLEquivalentClassesAxiom(
		       cl,
		       fac.getOWLObjectSomeValuesFrom(
			 r("has-part"),
			 fac.getOWLObjectIntersectionOf(
			   e,
			   fac.getOWLObjectSomeValuesFrom(
			     r("has-quality"), v)))))
    count += 1
  }
}

manager.addAxiom(outont, fac.getOWLTransitiveObjectPropertyAxiom(r("has-part")))
manager.addAxiom(outont, fac.getOWLTransitiveObjectPropertyAxiom(r("part-of")))
manager.addAxiom(outont, fac.getOWLReflexiveObjectPropertyAxiom(r("has-part")))
manager.addAxiom(outont, fac.getOWLReflexiveObjectPropertyAxiom(r("part-of")))

manager.addAxiom(
  outont, fac.getOWLEquivalentObjectPropertiesAxiom(
    r("part-of"), fac.getOWLObjectProperty(IRI.create("http://purl.obolibrary.org/obo/BFO_0000050"))))


OWLImportsDeclaration importDecl1 = fac.getOWLImportsDeclaration(IRI.create("http://purl.obolibrary.org/obo/po.owl"))
manager.applyChange(new AddImport(outont, importDecl1))
importDecl1 = fac.getOWLImportsDeclaration(IRI.create("http://purl.obolibrary.org/obo/pato.owl"))
manager.applyChange(new AddImport(outont, importDecl1))



manager.saveOntology(outont, IRI.create("file:"+opt.o))
System.exit(0)
