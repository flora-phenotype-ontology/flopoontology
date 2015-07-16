@Grab( 'com.xlson.groovycsv:groovycsv:1.0' )

import static com.xlson.groovycsv.CsvParser.parseCsv

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


String indexPath = "lucene-index-solana"
String ontologyIndexPath = "lucene-index-ontology"

Directory dir = FSDirectory.open(new File(indexPath))
Directory ontologyIndexDir = FSDirectory.open(new File(ontologyIndexPath))
Analyzer analyzer = new StandardAnalyzer(Version.LUCENE_47)
IndexWriterConfig iwc = new IndexWriterConfig(Version.LUCENE_47, analyzer)
iwc.setOpenMode(IndexWriterConfig.OpenMode.CREATE)
iwc.setRAMBufferSizeMB(32768.0)
IndexWriter writer = new IndexWriter(dir, iwc)

IndexWriterConfig iwcEnglish = new IndexWriterConfig(Version.LUCENE_47, analyzer)
iwcEnglish.setOpenMode(IndexWriterConfig.OpenMode.CREATE)
iwcEnglish.setRAMBufferSizeMB(32768.0)
IndexWriter englishWriter = new IndexWriter(ontologyIndexDir, iwcEnglish)




def author = null
def year = null
List<String> rankOrder = ["order", "family", "subfamily", "tribe", "subtribe", "genus", "subgenus", "species", "subspecies", "variety"]
Map<String, Set<String>> previousCharacters = [:] // this maps taxonomic rank name to EQs
Map<String, String> previousNames = [:] // this keeps the previously encountered taxon names; ordername -> value



XmlSlurper slurper = new XmlSlurper(false, false)
slurper.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false)


def stext = new File("solana/descriptions.csv").getText()
def data = parseCsv(stext)
for (line in data) {
  def description = line.Description
  def taxonString = line."Taxon Name"
  def habitat = line.Distribution
  SentenceModel sentenceModel = new SentenceModel(new FileInputStream("models/en-sent.bin"))
  SentenceDetectorME sentenceDetector = new SentenceDetectorME(sentenceModel)
  def sentences = sentenceDetector.sentDetect(description)
  sentences.each { sentence1 ->
    sentence1.split(";").each { sentence ->
      Document doc = new Document()
      doc.add(new Field("taxon", taxonString, Field.Store.YES, Field.Index.NO))
      doc.add(new Field("description", sentence, TextField.TYPE_STORED))
      writer.addDocument(doc)
    }
  }
  println "Added $taxonString"
}
/*
  SentenceModel sentenceModel = new SentenceModel(new FileInputStream("models/en-sent.bin"))
  SentenceDetectorME sentenceDetector = new SentenceDetectorME(sentenceModel)
  def sentences = sentenceDetector.sentDetect(description)
  sentences = sentenceDetector.sentDetect(habitat)
  sentences.each { sentence1 ->
    sentence1.split(";").each { sentence ->
      Document doc = new Document()
      doc.add(new Field("taxon", taxonString, Field.Store.YES, Field.Index.NO))
      doc.add(new Field("habitat", sentence, TextField.TYPE_STORED))
      writer.addDocument(doc)
    }
  }
}


*/

/* Final part: we also add all the ontology terms to the index so that we can easier search for them */

/*
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
*/
writer.close()
englishWriter.close()
