import org.jgrapht.alg.*
import org.jgrapht.experimental.dag.*
import org.jgrapht.*
import org.jgrapht.graph.*
import org.apache.lucene.analysis.*
import org.apache.lucene.analysis.standard.*
import org.apache.lucene.document.*
import org.apache.lucene.index.*
import org.apache.lucene.store.*
import org.apache.lucene.util.*
import org.apache.lucene.search.*
import org.apache.lucene.queryparser.classic.*
import com.aliasi.medline.*
import org.apache.lucene.analysis.fr.*
import edu.stanford.nlp.process.*
import edu.stanford.nlp.ling.*
import edu.stanford.nlp.trees.*
import edu.stanford.nlp.parser.lexparser.LexicalizedParser


LexicalizedParser lp = LexicalizedParser.loadModel("edu/stanford/nlp/models/lexparser/englishPCFG.ser.gz");
TreebankLanguagePack tlp = new PennTreebankLanguagePack();
GrammaticalStructureFactory gsf = tlp.grammaticalStructureFactory();

String indexPath = "lucene-index-english"
String ontologyIndexPath = "lucene-index-ontology"

def fout = new PrintWriter(new BufferedWriter(new FileWriter(args[0])))
def foutEnv = new PrintWriter(new BufferedWriter(new FileWriter(args[1])))

Directory dir = FSDirectory.open(new File(indexPath)) // RAMDirectory()
Directory ontologyIndexDir = FSDirectory.open(new File(ontologyIndexPath)) // RAMDirectory()
Analyzer analyzer = new StandardAnalyzer(Version.LUCENE_47)

DirectoryReader reader = DirectoryReader.open(ontologyIndexDir)
IndexSearcher ontSearcher = new IndexSearcher(reader)

Map<String, Set<String>> frenchname2id = [:]
Map<String, Set<String>> name2id = [:].withDefault { new TreeSet() }
Map<String, String> id2name = [:]

new File("ont").eachFile { ontfile ->
  def id = ""
  def fname = ""
  ontfile.eachLine { line ->
    if (line.startsWith("id:")) {
      id = line.substring(3).trim()
    }
    if (line.startsWith("name:")) {
      def name = line.substring(5).trim()
      id2name[id] = name
      name2id[name].add(id)
   }
  }
}

reader = DirectoryReader.open(dir)
IndexSearcher searcher = new IndexSearcher(reader)
parser = new QueryParser(Version.LUCENE_47, "description", analyzer)

name2id.each { name, ids ->
  ids.each { id ->
    name2id.each { name2, ids2 ->
      ids2.each { id2 ->
	if (id.startsWith("PO") && id2.startsWith("PATO")) {
	  Query query = parser.parse("+\"$name\" +\"$name2\"")
	  ScoreDoc[] hits = searcher.search(query, null, 1000, Sort.RELEVANCE, true, true).scoreDocs
	  hits.each { doc ->
	    Document hitDoc = searcher.doc(doc.doc)
	    def sentence = hitDoc.get("description")
	    Tree parse = lp.parse(sentence)
	    GrammaticalStructure gs = gsf.newGrammaticalStructure(parse)
	    List<TypedDependency> tdl = gs.typedDependenciesCCprocessed(true)
	    //	    println hitDoc.get("description")
	    DirectedGraph<String, DefaultEdge> dg = new DefaultDirectedGraph<String, DefaultEdge>(DefaultEdge.class)
	    tdl.each { dep ->
	      String labelDep = dep.dep().label().toString()
	      String labelDepClean = labelDep.substring(0, labelDep.lastIndexOf("-"))
	      String labelGov = dep.gov().label().toString()
	      String labelGovClean = labelGov.substring(0, labelGov.lastIndexOf("-"))
	      dg.addVertex(labelDep)
	      dg.addVertex(labelGov)
	      dg.addEdge(labelGov, labelDep)
	      //	      println labelDep+" "+labelGov+" "+dep.reln().toString()
	    }
	    FloydWarshallShortestPaths fwsp = new FloydWarshallShortestPaths(dg)
	    def s1 = new TreeSet()
	    def s2 = new TreeSet()
	    dg.vertexSet().each { v ->
	      def lab = v.substring(0,v.lastIndexOf("-"))
	      if (lab.length()>=3) {
		if (name.indexOf(lab)>-1 || lab.indexOf(name)>-1) {
		  s1.add(v)
		}
		if (name2.indexOf(lab)>-1 || lab.indexOf(name2)>-1) {
		  s2.add(v)
		}
	      }
	    }
	    s1.each { v1 ->
	      s2.each { v2 ->
		def dist = fwsp.shortestDistance(v1, v2)
		if (dist < 3) {
		  fout.println(hitDoc.get("taxon")+"\t"+id2name[id]+"\t$id\t"+id2name[id2]+"\t$id2\t"+doc.score+"\t"+hitDoc.get("description"))
		  println(hitDoc.get("taxon")+"\t"+id2name[id]+"\t$id\t"+id2name[id2]+"\t$id2\t"+doc.score+"\t"+hitDoc.get("description"))
		  //		  println "$v1\t$v2\t"+fwsp.shortestDistance(v1, v2)
		}
	      }
	    }
	    //	    println(hitDoc.get("taxon")+"\t"+id2name[id]+"\t$id\t"+id2name[id2]+"\t$id2\t"+doc.score+"\t"+hitDoc.get("description"))
	  }
	}
      }
    }
  }
}
parser = new QueryParser(Version.LUCENE_47, "habitat", analyzer)
name2id.each { name, ids1 ->
  ids1.each { id ->
    if (id.startsWith("ENVO")) {
      Query query = parser.parse("+\"$name\"")
      ScoreDoc[] hits = searcher.search(query, null, 1000, Sort.RELEVANCE, true, true).scoreDocs
      hits.each { doc ->
	Document hitDoc = searcher.doc(doc.doc)
	foutEnv.println(hitDoc.get("taxon")+"\t"+id2name[id]+"\t$id\t"+doc.score+"\t"+hitDoc.get("habitat"))
      }
    }
  }
}
fout.flush()
fout.close()
foutEnv.flush()
foutEnv.close()
