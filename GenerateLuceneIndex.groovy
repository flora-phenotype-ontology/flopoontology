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
IndexWriterConfig iwc = new IndexWriterConfig(Version.LUCENE_47, frenchAnalyzer)
iwc.setOpenMode(IndexWriterConfig.OpenMode.CREATE)
iwc.setRAMBufferSizeMB(32768.0)
IndexWriter writer = new IndexWriter(dir, iwc)




def author = null
def year = null
List<String> rankOrder = ["order", "family", "subfamily", "tribe", "subtribe", "genus", "subgenus", "species", "subspecies", "variety"]
Map<String, Set<String>> previousCharacters = [:] // this maps taxonomic rank name to EQs
Map<String, String> previousNames = [:] // this keeps the previously encountered taxon names; ordername -> value


XmlSlurper slurper = new XmlSlurper(false, false)
slurper.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false)

new File("flora-gabon").eachFile { florafile ->
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

      // now index the descriptions
      Document doc = new Document()
      doc.add(new Field("taxon", taxonString, Field.Store.YES, Field.Index.NO))
      taxon.feature.each { feature ->
	if (feature.@class.text() == "description") {
	  feature.char.each { character ->
	    def cclass = character.@class.text().toLowerCase()
	    def ctext = character.text()
	    doc.add(new Field("description", ctext, TextField.TYPE_STORED))
	  }
	}
      }
      writer.addDocument(doc)
    }
  }
}
writer.close()

