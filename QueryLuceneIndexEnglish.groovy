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


String indexPath = "lucene-index-english"
String ontologyIndexPath = "lucene-index-ontology"

def fout = new PrintWriter(new BufferedWriter(new FileWriter(args[0])))
def foutEnv = new PrintWriter(new BufferedWriter(new FileWriter(args[1])))

Directory dir = FSDirectory.open(new File(indexPath)) // RAMDirectory()
Directory ontologyIndexDir = FSDirectory.open(new File(ontologyIndexPath)) // RAMDirectory()
Analyzer analyzer = new StandardAnalyzer(Version.LUCENE_47)

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

reader = DirectoryReader.open(dir)
searcher = new IndexSearcher(reader)
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
	    fout.println(hitDoc.get("taxon")+"\t"+id2name[id]+"\t$id\t"+id2name[id2]+"\t$id2\t"+doc.score+"\t"+hitDoc.get("description"))
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
