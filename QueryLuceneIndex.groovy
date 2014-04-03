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

Directory dir = FSDirectory.open(new File(indexPath)) // RAMDirectory()
Analyzer analyzer = new StandardAnalyzer(Version.LUCENE_47)
Analyzer frenchAnalyzer = new FrenchAnalyzer(Version.LUCENE_47)

DirectoryReader reader = DirectoryReader.open(dir)
IndexSearcher searcher = new IndexSearcher(reader)
QueryParser parser = new QueryParser(Version.LUCENE_47, "description", frenchAnalyzer)
Query query = parser.parse("fleur rouge")
ScoreDoc[] hits = searcher.search(query, null, 1000, Sort.RELEVANCE, true, true).scoreDocs
hits.each { doc ->
  Document hitDoc = searcher.doc(doc.doc)
  println doc.score+"\t"+hitDoc.get("description")
}
