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


String indexPath = "lucene-index"
String ontologyIndexPath = "lucene-index-ontology"

Directory dir = FSDirectory.open(new File(indexPath)) // RAMDirectory()
Directory ontologyIndexDir = FSDirectory.open(new File(ontologyIndexPath)) // RAMDirectory()
Analyzer analyzer = new StandardAnalyzer(Version.LUCENE_47)
Analyzer frenchAnalyzer = new FrenchAnalyzer(Version.LUCENE_47)

DirectoryReader reader = DirectoryReader.open(ontologyIndexDir)
IndexSearcher searcher = new IndexSearcher(reader)

Map<String, Set<String>> frenchname2id = [:]
Map<String, Set<String>> name2id = [:]

QueryParser parser = new QueryParser(Version.LUCENE_47, "label", analyzer)
new File("glossary/Lexicon-english-french.csv").splitEachLine("\t") { line ->
  def english = line[1]
  def french = line[2]
  def frenchpretty = line[3]
  Query query = parser.parse("\""+english+"\"")
  ScoreDoc[] hits = searcher.search(query, null, 1000, Sort.RELEVANCE, true, true).scoreDocs
  if (hits) {
    def doc = hits[0]
    Document hitDoc = searcher.doc(doc.doc)
    frenchname2id[french] = hitDoc.get("id")
  }
}

reader = DirectoryReader.open(dir)
searcher = new IndexSearcher(reader)
parser = new QueryParser(Version.LUCENE_47, "description", frenchAnalyzer)
Query query = parser.parse("+fleur +bleu")
ScoreDoc[] hits = searcher.search(query, null, 1000, Sort.RELEVANCE, true, true).scoreDocs
hits.each { doc ->
  Document hitDoc = searcher.doc(doc.doc)
  println doc.score+"\t"+hitDoc.get("description")
}
