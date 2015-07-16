import org.jgrapht.alg.*
import org.jgrapht.experimental.dag.*
import org.jgrapht.*
import org.jgrapht.graph.*
import org.apache.lucene.analysis.*
import org.apache.lucene.analysis.standard.*
import org.apache.lucene.document.*
import org.apache.lucene.search.vectorhighlight.*
import org.apache.lucene.search.highlight.*
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


String indexPath = "lucene-index-french"
String ontologyIndexPath = "lucene-index-ontology"

def fout = new PrintWriter(new BufferedWriter(new FileWriter(args[0])))

Directory dir = FSDirectory.open(new File(indexPath)) // RAMDirectory()
Directory ontologyIndexDir = FSDirectory.open(new File(ontologyIndexPath)) // RAMDirectory()
Analyzer analyzer = new StandardAnalyzer(Version.LUCENE_47)
Analyzer frenchAnalyzer = new FrenchAnalyzer(Version.LUCENE_47)

DirectoryReader reader = DirectoryReader.open(ontologyIndexDir)
IndexSearcher searcher = new IndexSearcher(reader)

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

QueryParser parser = new QueryParser(Version.LUCENE_47, "label", analyzer)
new File("glossary/Lexicon-english-french.csv").splitEachLine("\t") { line ->
  def english = line[1]
  def french = line[2]
  if (french && french.size()>0) {
    def frenchpretty = line[3]
    Query query = parser.parse("\""+english+"\"")
    ScoreDoc[] hits = searcher.search(query, null, 1000, Sort.RELEVANCE, true, true).scoreDocs
    if (hits) {
      def doc = hits[0]
      Document hitDoc = searcher.doc(doc.doc)
      frenchname2id[frenchpretty] = hitDoc.get("id")
    }
  }
}

reader = DirectoryReader.open(dir)
searcher = new IndexSearcher(reader)
parser = new QueryParser(Version.LUCENE_47, "description", frenchAnalyzer)


QueryBuilder builder = new QueryBuilder(frenchAnalyzer)
BooleanQuery.setMaxClauseCount(2048)

frenchname2id.each { name, id ->
  frenchname2id.each { name2, id2 ->
    if (id.startsWith("PO") && id2.startsWith("PATO")) {
      Query query = new BooleanQuery()
      //	  name2 = "stigmatic lobes"
      Query q = builder.createPhraseQuery("description", name)
      query.add(q, BooleanClause.Occur.MUST)
      Query q1 = q
      q = builder.createPhraseQuery("description", name2)
      query.add(q, BooleanClause.Occur.MUST)
      Query q2 = q
      ScoreDoc[] hits = searcher.search(query, null, 1000, Sort.RELEVANCE, true, true).scoreDocs
      hits.each { doc ->
	def docId = doc.doc
	Document hitDoc = searcher.doc(docId)
	def sentence = hitDoc.get("description")
	Highlighter highlighter = new Highlighter(new QueryScorer(q1))
	Highlighter highlighter2 = new Highlighter(new QueryScorer(q2))
	highlighter.getBestFragments(frenchAnalyzer, "description", sentence, 50).each { frag1 ->
	  highlighter2.getBestFragments(frenchAnalyzer, "description", sentence, 50).each { frag2 ->
	    int index1 = frag1.indexOf("<B>")
	    def eindex1 = frag1.indexOf("</B>")
	    while (index1 >= 0) {
	      int index2 = frag2.indexOf("<B>")
	      def eindex2 = frag2.indexOf("</B>")
	      while (index2 >= 0) {
		if (eindex1 < index2) {
		  def nf = frag1.substring(0, index1) + "<E>"+frag1.substring(index1+3, eindex1)+"</E>"+frag2.substring(eindex1-3,index2)+"<Q>"+frag2.substring(index2+3, eindex2)+"</Q>"+frag2.substring(eindex2+3)
		  def finalFragment = nf.replaceAll("<B>","").replaceAll("</B>","")
		  fout.println("$name\t$name2\t$finalFragment")
		} else if (eindex2 < index1) {
		  def nf = frag2.substring(0, index2) + "<Q>"+frag2.substring(index2+3, eindex2)+"</Q>"+frag1.substring(eindex2-3,index1)+"<E>"+frag1.substring(index1+3, eindex1)+"</E>"+frag1.substring(eindex1+4)
		  def finalFragment = nf.replaceAll("<B>","").replaceAll("</B>","")
		  fout.println("$name\t$name2\t$finalFragment")
		}
		index2 = frag2.indexOf("<B>", eindex2+1);
		eindex2 = frag2.indexOf("</B>", eindex2+1);
	      }
	      index1 = frag1.indexOf("<B>", eindex1+1);
	      eindex1 = frag1.indexOf("</B>", eindex1+1);
	    }
	  }
	}
      }
    }
  }
}
fout.flush()
fout.close()
