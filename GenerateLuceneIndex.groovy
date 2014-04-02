import org.apache.lucene.analysis.*
import org.apache.lucene.analysis.standard.*
import org.apache.lucene.document.*
import org.apache.lucene.index.*
import org.apache.lucene.store.*
import org.apache.lucene.util.*
import com.aliasi.medline.*
import org.apache.lucene.analysis.fr.*

String indexPath = "lucene-index"
String docsPath = null

Directory dir = FSDirectory.open(new File(indexPath)) // RAMDirectory()
Analyzer analyzer = new StandardAnalyzer(Version.LUCENE_47)
Analyzer frenchAnalyzer = new FrenchAnalyzer(Version.LUCENE_47)
IndexWriterConfig iwc = new IndexWriterConfig(Version.LUCENE_47, frenchAnalyzer)
iwc.setOpenMode(IndexWriterConfig.OpenMode.CREATE)
iwc.setRAMBufferSizeMB(32768.0)
IndexWriter writer = new IndexWriter(dir, iwc)

XmlSlurper slurper = new XmlSlurper(false, false)
slurper.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false)

new File("floras").eachFile { florafile ->
  def flora = slurper.parse(florafile)
  flora.treatment.each { treatment ->
    treatment.taxon.each { taxon ->
      Document doc = new Document()
      taxon.feature.each { feature ->
	if (feature.@class.text() == "description") {
	  feature.char.each { character ->
	    def cclass = character.@class.text().toLowerCase()
	    def ctext = character.text()
	    doc.add(new Field(cclass, ctext, TextField.TYPE_STORED))
	    writer.addDocument(doc)
	  }
	}
      }
    }
  }
}
writer.close()
