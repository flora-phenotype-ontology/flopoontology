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
import opennlp.tools.sentdetect.*
import opennlp.tools.dictionary.*
import opennlp.tools.tokenize.*
import opennlp.tools.util.*
import opennlp.tools.chunker.*
import opennlp.tools.postag.*
import opennlp.tools.namefind.*
import java.util.concurrent.*


String ontologyIndexPath = "lucene-index-ontology"

Directory ontologyIndexDir = FSDirectory.open(new File(ontologyIndexPath))
Analyzer analyzer = new StandardAnalyzer(Version.LUCENE_47)
IndexWriterConfig iwc = new IndexWriterConfig(Version.LUCENE_47, analyzer)
iwc.setOpenMode(IndexWriterConfig.OpenMode.CREATE)
iwc.setRAMBufferSizeMB(32768.0)

IndexWriterConfig iwcEnglish = new IndexWriterConfig(Version.LUCENE_47, analyzer)
iwcEnglish.setOpenMode(IndexWriterConfig.OpenMode.CREATE)
iwcEnglish.setRAMBufferSizeMB(32768.0)
IndexWriter englishWriter = new IndexWriter(ontologyIndexDir, iwcEnglish)

FieldType fieldType = new FieldType()
fieldType.setStoreTermVectors(true)
fieldType.setStoreTermVectorPositions(true)
fieldType.setStoreTermVectorOffsets(true)
fieldType.setStoreTermVectorPayloads(true)
fieldType.setIndexed(true)
fieldType.setTokenized(true)
fieldType.setStored(true)
fieldType.setIndexOptions(FieldInfo.IndexOptions.DOCS_AND_FREQS_AND_POSITIONS_AND_OFFSETS)

def ontologyDirectory = "ont/"
new File("ont").eachFile { ontfile ->
  def id = ""
  ontfile.eachLine { line ->
    if (line.startsWith("id:")) {
      id = line.substring(3).trim()
    }
    if (line.startsWith("name:")) {
      def name = line.substring(5).trim()
      Document doc = new Document()
      doc.add(new Field("id", id, Field.Store.YES, Field.Index.NO))
      doc.add(new Field("label", name, TextField.TYPE_STORED))
      englishWriter.addDocument(doc)
    }
    if (line.startsWith("synonym:")) {
      def syn = line.substring(line.indexOf("\"")+1, line.lastIndexOf("\"")).trim()
      Document doc = new Document()
      doc.add(new Field("id", id, Field.Store.YES, Field.Index.NO))
      doc.add(new Field("label", syn, TextField.TYPE_STORED))
      englishWriter.addDocument(doc)
    }
  }
}

englishWriter.close()
