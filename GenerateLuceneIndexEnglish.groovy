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


String indexPath = "lucene-index-english"
String ontologyIndexPath = "lucene-index-ontology"

Directory dir = FSDirectory.open(new File(indexPath)) // RAMDirectory()
Directory ontologyIndexDir = FSDirectory.open(new File(ontologyIndexPath)) // RAMDirectory()
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

/* Kew African */
def kew = slurper.parse(new File("floras-other/Kew African Flora Species.xml"))
kew.Specieslist.each { species ->
  def family = species."Name.family"[0].text()
  def genus = species."Name.genus"[0].text()
  def sname = species."Name.species"[0].text()
  def subspecies = species."infraepi"[0].text()
  def taxonString = "Family: $family, Genus: $genus, Species: $sname, Sub: $subspecies"
  def description = species."description"[0].text()
  def habitat = species."habitat"[0].text()

  /* now split the description in sentences */
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



/* Flora Malesiana */
new File("flora-malesiana").eachFile { florafile ->
  def flora = slurper.parse(florafile)
  flora.treatment.each { treatment ->
    treatment.taxon.each { taxon ->

      // first try to get the taxon name
      def taxonString = ""
      def name = null
      taxon.nomenclature.homotypes.nom.each { nom ->
	if (nom.@class.text() == "accepted") {
	  name = nom
	  def lastOrderRank = ""
	  nom.name.each { nomname -> /* first we determine the level of the tree in which we currently are; we will reuse information from the higher orders
				     // mentioned before */
	    def cname = nomname.@class.text()
	    if (cname == "author") { author = nomname.text() }
	    if (cname == "year") { year = nomname.text() }
	    if (cname in rankOrder) {
	      lastOrderRank = cname
	      def cvalue = nomname.text()
	      // we delete everything from the end of the list to the current rank from previousCharacters map
		/*	      rankOrder[-1..rankOrder.indexOf(cname)].each {
			      previousCharacters[it] = null
			      previousNames[it] = null
			      }*/
	      previousNames[cname] = cvalue
	    }
	  }
	  rankOrder[0..rankOrder.indexOf(lastOrderRank)].each {
	    if (previousNames[it] != null) {
	      taxonString += "$it: "+previousNames[it]+"; "
	    }
	  }
	  taxonString += "$author; $year"
	}
      }

      // now index the descriptions: first we assemble the description text, then we sentencize, then we create a new document for each sentence
      String description = ""
      taxon.feature.each { feature ->
	if (feature.@class.text() == "description") {
	  feature.char.each { character ->
	    def cclass = character.@class.text().toLowerCase()
	    def ctext = character.text()
	    description += ctext + " "
	    //	    
	  }
	}
      }
      String habitat = ""
      taxon.feature.each { feature ->
	if (feature.@class.text() == "habitatecology") {
	  feature.char.each { character ->
	    def cclass = character.@class.text().toLowerCase()
	    def ctext = character.text()
	    habitat += ctext + " "
	    //	    
	  }
	}
      }
      /* now split the description in sentences */
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
      /* now split the description in sentences */
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
  }
}

/* Final part: we also add all the ontology terms to the index so that we can easier search for them */


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

writer.close()
englishWriter.close()
