import java.util.logging.Logger
import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.*
import org.semanticweb.owlapi.reasoner.*
import org.semanticweb.owlapi.profiles.*
import org.semanticweb.owlapi.util.*
import org.semanticweb.owlapi.io.*
import org.semanticweb.elk.owlapi.*
import org.semanticweb.owlapi.vocab.OWLRDFVocabulary

def cli = new CliBuilder()
cli.with {
usage: 'Self'
  h longOpt:'help', 'this information'
  i longOpt:'input-file', 'input file',args:1, required:true
  o longOpt:'ontology-output-file', 'output ontology file',args:1, required:true
  a longOpt:'annotation-output-file', 'output annotation file (FLOPO annotations)',args:1, required:true
  t longOpt:'add-taxons', 'adds taxons as subclasses of phenotypes', args:0
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

def fout = new PrintWriter(new BufferedWriter(new FileWriter(opt.a)))

def ontfile = new File("ont/plant_ontology.obo")
def patofile = new File("ont/quality.obo")

def id2super = [:]
def id2name = [:]
def id = ""
def values = new TreeSet()
def attributes = new TreeSet()
def obsolete = new TreeSet()
new File("ont/quality.obo").eachLine { line ->
  if (line.startsWith("id:")) {
    id = line.substring(3).trim()
  }
  if (line.startsWith("name:")) {
    def name = line.substring(5).trim()
    id2name[id] = name
  }
  if (line.startsWith("is_a:") && line.indexOf("!")>-1) {
    def sc = line.substring(5, line.indexOf("!")-1).trim()
    if (id2super[id] == null) {
      id2super[id] = new TreeSet()
    }
    id2super[id].add(sc)
  }
  if (line.indexOf("attribute_slim")>-1) {
    attributes.add(id)
  }
  if (line.indexOf("value_slim")>-1) {
    values.add(id)
  }
  if (line.indexOf("is_obsolete: true")>-1) {
    obsolete.add(id)
  }
}
new File("ont/plant_ontology.obo").eachLine { line ->
  if (line.startsWith("id:")) {
    id = line.substring(3).trim()
  }
  if (line.startsWith("name:")) {
    def name = line.substring(5).trim()
    id2name[id] = name
  }
}

String formatClassNames(String s) {
  s=s.replace("<http://purl.obolibrary.org/obo/","")
  s=s.replace(">","")
  s=s.replace("_",":")
  s
}


OWLOntologyManager manager = OWLManager.createOWLOntologyManager()

OWLDataFactory fac = manager.getOWLDataFactory()
OWLDataFactory factory = fac

def ontset = new TreeSet()
OWLOntology ont = manager.loadOntologyFromOntologyDocument(ontfile)
ontset.add(ont)
ont = manager.loadOntologyFromOntologyDocument(patofile)
ontset.add(ont)

ont = manager.createOntology(IRI.create("http://phenomebrowser.net/ppo.owl"), ontset)

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



def taxon2phenotype = [:]
def phenotypes = new HashSet()
new File(opt.i).splitEachLine("\t") { line ->
  def taxon = line[0]
  if (taxon2phenotype[taxon] == null) {
    taxon2phenotype[taxon] = new HashSet()
  }
  def e = line[2]
  def q = line[4]
  if (q && e && ! (q in obsolete) && ! (e in obsolete)) {
    Expando exp = new Expando()
    exp.e = e
    exp.q = q
    phenotypes.add(exp)
    taxon2phenotype[taxon].add(exp)
  }
}
//println taxon2phenotype

def clSuper = c("FLOPO:0")
addAnno(clSuper,OWLRDFVocabulary.RDFS_LABEL,"flora phenotype")

def count = 1 // global ID counter

def eq2cl = [:]
def edone = new HashSet()
def e2p = [:]
/* Create abnormality of E classes */
phenotypes.each { exp ->
  def e = id2class[exp.e]
  def q = id2class[exp.q]
  if (e!=null && ! (e in edone)) {
    edone.add(e)
    if (eq2cl[e] == null) {
      eq2cl[exp.e]= [:]
    }
    def cl = c("FLOPO:$count")
    addAnno(cl,OWLRDFVocabulary.RDFS_LABEL,id2name[exp.e]+" phenotype")
    //    addAnno(cl,OWLRDFVocabulary.RDF_DESCRIPTION,"The mass of $oname that is used as input in a single $name is decreased.")
    manager.addAxiom(outont, factory.getOWLSubClassOfAxiom(cl, clSuper))
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
  if (e!=null && q!=null && ! (q in e2p[e]) ) {
    e2p[e].add(q)
    def cl = c("FLOPO:$count")
    eq2cl[exp.e][exp.q] = cl
    addAnno(cl,OWLRDFVocabulary.RDFS_LABEL,id2name[exp.e]+" "+id2name[exp.q])
    manager.addAxiom(outont, factory.getOWLEquivalentClassesAxiom(
		       cl,
		       fac.getOWLObjectSomeValuesFrom(
			 r("has-part"),
			 fac.getOWLObjectIntersectionOf(
			   e,
			   fac.getOWLObjectSomeValuesFrom(
			     r("has-quality"), q)))))
    count += 1

    /* now get the trait from PATO and generate a class for the trait */
    /* only if the Q is not already an attribute */
    // do a BFS (maybe change)
    def search = new LinkedList()
    def found = false
    if (! (exp.q in attributes)) {
      if (id2super[exp.q]) {
	search.addAll(id2super[exp.q])
	while (!found && search.size()>0) {
	  def nq = search.poll()
	  if (!(nq in attributes)) {
	    if (id2super[nq]) {
	      search.addAll(id2super[nq])
	    }
	  } else if (id2class[nq] in e2p[e]) {
	    found = true
	  } else {
	    e2p[e].add(id2class[nq])
	    cl = c("FLOPO:$count")
	    addAnno(cl,OWLRDFVocabulary.RDFS_LABEL,id2name[exp.e]+" "+id2name[nq])
	    manager.addAxiom(outont, factory.getOWLEquivalentClassesAxiom(
			       cl,
			       fac.getOWLObjectSomeValuesFrom(
				 r("has-part"),
				 fac.getOWLObjectIntersectionOf(
				   e,
				   fac.getOWLObjectSomeValuesFrom(
				     r("has-quality"), id2class[nq])))))
	    count += 1
	    found = true
	  }
	}
      } else {
	// println exp.q
      }
    }
  }
}

if (opt.t) {
  clSuper = c("TAXON:0")
  addAnno(clSuper,OWLRDFVocabulary.RDFS_LABEL,"taxon")
}

count = 1 // reset counter, add taxons in different namespace

def taxon2class = [:]
/* Now add all the taxons, as subclasses of their phenotypes for now; change later */
taxon2phenotype.each { taxon, phenotype ->
  def tcl = null
  if (taxon2class[taxon] == null) {
    tcl = c("TAXON:$count")
    if (opt.t) {
      addAnno(tcl,OWLRDFVocabulary.RDFS_LABEL,taxon)
    }
    count += 1
  } else {
    tcl = taxon2class[taxon]
  }
  if (opt.t) {
    manager.addAxiom(outont, factory.getOWLSubClassOfAxiom(tcl, clSuper))
  }
  def phenoset = new HashSet()
  phenotype.each { pheno ->
    if (eq2cl[pheno.e] && eq2cl[pheno.e][pheno.q]) {
      def pcl = eq2cl[pheno.e][pheno.q]
      fout.println(tcl.toString()+"\t$taxon\t"+pcl.toString())
      if (pcl) {
	phenoset.add(pcl)
      } 
    }
  }
  if (phenoset.size()>1) {
    if (opt.t) {
      manager.addAxiom(outont, factory.getOWLEquivalentClassesAxiom(tcl,factory.getOWLObjectIntersectionOf(phenoset)))
    }
  }
}
fout.flush()
fout.close()

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
