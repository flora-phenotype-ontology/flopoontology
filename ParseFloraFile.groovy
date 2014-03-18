import opennlp.tools.dictionary.*
import opennlp.tools.tokenize.*
import opennlp.tools.util.*
import opennlp.tools.chunker.*
import opennlp.tools.postag.*
import org.apache.commons.io.IOUtils
import opennlp.tools.namefind.*
import java.util.concurrent.*

def MINLENGTH = 3 // minimum length of a token to recognize

def name2id = [:]
new File("ont").eachFile { ontfile ->
  def id = ""
  ontfile.eachLine { line ->
    if (line.startsWith("id:")) {
      id = line.substring(3).trim()
    }
    if (line.startsWith("name:")) {
      def name = line.substring(5).trim()
      if (name2id[name] == null) {
        name2id[name] = new TreeSet()
      }
      name2id[name].add(id)
    }
    if (line.startsWith("synonym:")) {
      def syn = line.substring(line.indexOf("\"")+1, line.lastIndexOf("\"")).trim()
      if (name2id[syn] == null) {
        name2id[syn] = new TreeSet()
      }
      name2id[syn].add(id)
    }
    if (line.startsWith("xref:")) {
      if (line.indexOf("\"")>-1) {
        def syn = line.substring(line.indexOf("\"")+1, line.lastIndexOf("\"")).trim()
        if (name2id[syn] == null) {
          name2id[syn] = new TreeSet()
        }
        name2id[syn].add(id)
      }
    }
  }
}

/* Now add the glossary terms, many of which will not be in one of the ontologies */
new File("glossary/Plant_glossary_term_category.csv").eachLine { line ->
  if (!line.startsWith("#") && line.length()>5) {
    def tok = line.split(",").collect { it.replaceAll("\"","") }
    if (name2id[tok[0]] == null) {
      name2id[tok[0]] = new TreeSet()
    }
    name2id[tok[0]].add(tok[-1])
  }
}

/* Now add the french - english translations */
new File("glossary/Lexicon-english-french.csv").splitEachLine("\t") { line ->
  def english = line[1]
  def french = line[2]
  def frenchpretty = line[3]
  if (name2id[english]) {
    if (french?.length()>1) {
      name2id[french] = name2id[english]
    }
    if (frenchpretty?.length()>1) {
      name2id[french] = name2id[english]
    }
    name2id[frenchpretty] = name2id[english]
  }
}

TokenizerModel tokenizerModel = new TokenizerModel(new FileInputStream("en-token.bin"))
Tokenizer tokenizer = new TokenizerME(tokenizerModel)

def tokens = name2id.keySet()
Dictionary dict = new Dictionary(false)
tokens.each { tok ->
  tok = tok?.toLowerCase()
  if (tok && tok.length()>MINLENGTH) {
    StringList l = tokenizer.tokenize(tok)
    dict.put(l)
  }
}
DictionaryNameFinder finder = new DictionaryNameFinder(dict)

XmlSlurper slurper = new XmlSlurper(false, false)
slurper.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false)
def flora = slurper.parse(new File(args[0]))
flora.treatment.each { treatment ->
  treatment.taxon.each { taxon ->
    taxon.nomenclature.homotypes.nom.each { nom ->
      if (nom.@class.text() == "accepted") {
	nom.name.each { nomname ->
	  println nomname.@class.text() + "\t" + nomname.text()
	}
      }
    }
    taxon.feature.each { feature ->
      if (feature.@class.text() == "description") {
	feature.char.each { character ->
	  def cclass = character.@class.text().toLowerCase()
	  if (cclass.endsWith("s")) {
	    cclass = cclass.substring(0,cclass.length()-1)
	  }

	  def ctext = character.text().toLowerCase()

	  def tokenizedText = tokenizer.tokenize(ctext)
	  def matches = finder.find(tokenizedText)
	  def occurrences = Span.spansToStrings(matches, tokenizedText)
	  print "$cclass ("+name2id[cclass]+")\t$ctext\t"
	  occurrences.each { match ->
	    def matchids = name2id[match]
	    matchids.each { print "$it("+match+")\t" }
	  }
	  println "\n"
	}
      }
    }
  }
}
