/* Parses all the flora files */

import opennlp.tools.sentdetect.*
import opennlp.tools.dictionary.*
import opennlp.tools.tokenize.*
import opennlp.tools.util.*
import opennlp.tools.chunker.*
import opennlp.tools.postag.*
import org.apache.commons.io.IOUtils
import opennlp.tools.namefind.*
import java.util.concurrent.*

def MINLENGTH = 2 // minimum length of a token to recognize

def fout = new PrintWriter(new BufferedWriter(new FileWriter("eq.txt")))
def fout2 = new PrintWriter(new BufferedWriter(new FileWriter("missing-e-or-q.txt")))


def name2id = [:]
new File("ont").eachFile { ontfile ->
  def id = ""
  def fname = ""
  ontfile.eachLine { line ->
    if (line.startsWith("id:")) {
      id = line.substring(3).trim()
    }
    if (line.startsWith("name:")) {
      def name = line.substring(5).trim()
      fname = name
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
    if (line.startsWith("replaced_by:")) {
      def i = line.substring(12).trim()
      name2id[fname].remove(id)
      name2id[fname].add(i)
    }
  }
}

/* Now remove the " to" part in PATO qualities */
def newmap = [:]
name2id.each { name, id ->
  if (name.endsWith(" to")) {
    def newname = name.replaceAll(" to","")
    newmap[newname] = id
  }
}
newmap.each { n, i -> 
  if (!name2id[n]) {
    name2id[n] = i
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
      if (name2id[french]) {
	name2id[french].addAll(name2id[english])
      } else {
	name2id[french] = name2id[english]
      }
    }
    if (frenchpretty?.length()>1) {
      if (name2id[frenchpretty]) {
	name2id[frenchpretty].addAll(name2id[english])
      } else {
	name2id[frenchpretty] = name2id[english]
      }
    }
  }
}

new File("glossary/terms/").eachFile { file ->
  file.splitEachLine("\\|") { line ->
    def name = line[3].trim().toLowerCase()
    def type = line[0].trim().toLowerCase()
    def defi = line[4].trim().toLowerCase()
    def flag = false // false if anatomy, true if quality
    if (type.endsWith("types")) {
      flag = true
    }

    /* now we merge the ids of all the synonyms */
    def splits = name.split(";")
    if (splits.size()>1) {
      def ss = new TreeSet()
      splits.each { s ->
	if (name2id[s]) {
	  ss.addAll(name2id[s])
	}
      }
      splits.each { s ->
	name2id[s] = ss
      }
    }

    name.split(";").each { syn ->
      syn = syn.trim()
      //      if (flag) { // quality
	def flag2 = false // false if no PATO term in name2id[syn]
	name2id[syn]?.each { if (it.startsWith("PATO") || (it.startsWith("PO"))) flag2 = true }
	if (!name2id[syn] || !flag2) {
	  println type+"\t"+syn+"\t"+name2id[syn]+"\t$defi\tMISSING"
	}
	//      }
      /*else { // anatomy
	def flag2 = false // false if no PO term in name2id[syn]
	name2id[syn]?.each { if (it.startsWith("PO")) flag2 = true }
	if (!name2id[syn] || !flag2) {
	  println type+"\t"+syn+"\t"+name2id[syn]+"\t$defi\tMISSING ENTITY"
	}
      }
      */
    }
  }
}

TokenizerModel tokenizerModel = new TokenizerModel(new FileInputStream("en-token.bin"))
Tokenizer tokenizer = new TokenizerME(tokenizerModel)

SentenceModel sentenceModel = new SentenceModel(new FileInputStream("en-sent.bin"))
SentenceDetectorME sentenceDetector = new SentenceDetectorME(sentenceModel)

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
//println name2id["petiole"]

Map taxon2string = [:] // maps taxon node to taxon string
def author = null
def year = null
List<String> rankOrder = ["order", "family", "subfamily", "tribe", "subtribe", "genus", "subgenus", "species", "subspecies", "variety"]
Map<String, Set<EntityQuality>> previousCharacters = [:] // this maps taxonomic rank name to EQs
Map<String, String> previousNames = [:] // this keeps the previously encountered taxon names; ordername -> value
def taxon2eq = [:] // this is the raw EQ data for each taxon
def taxon2classes = [:] // this is the processed phenotype data (PPO identifiers) for each taxon
XmlSlurper slurper = new XmlSlurper(false, false)
slurper.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false)

new File("floras").eachFile { florafile ->
  def flora = slurper.parse(florafile)
  flora.treatment.each { treatment ->
    treatment.taxon.each { taxon ->
      def name = null
      taxon.nomenclature.homotypes.nom.each { nom ->
	if (nom.@class.text() == "accepted") {
	  taxon2eq[nom] = new LinkedHashSet()
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
	      previousCharacters[cname] = taxon2eq[nom]
	      previousNames[cname] = cvalue
	      rankOrder[0..rankOrder.indexOf(cname)].each { if (previousCharacters[it]) {taxon2eq[nom].addAll(previousCharacters[it]) } }
	    }
	  }
	  def taxonString = ""
	  rankOrder[0..rankOrder.indexOf(lastOrderRank)].each {
	    if (previousNames[it] != null) {
	      taxonString += "$it: "+previousNames[it]+"; "
	    }
	  }
	  taxonString += "$author; $year"
	  taxon2string[nom] = taxonString
	}
      }
      if (name) {
	taxon.feature.each { feature ->
	  if (feature.@class.text() == "description") {
	    feature.char.each { character ->
	      def cclass = character.@class.text().toLowerCase()
	      cclass = cclass.replaceAll("leaves","leaf")
	      if (cclass.endsWith("s")) {
		cclass = cclass.substring(0,cclass.length()-1)
	      }

	      EntityQuality eq = new EntityQuality()
	      taxon2eq[name].add(eq)
	      eq.entity = new LinkedHashSet()
	      eq.entityName = new LinkedHashSet()
	      eq.quality = new LinkedHashSet()
	      eq.qualityName = new LinkedHashSet()

	      def tokenizedCClass = tokenizer.tokenize(cclass)
	      def classMatches = finder.find(tokenizedCClass)
	      def classOccurrences = Span.spansToStrings(classMatches, tokenizedCClass)
	      classOccurrences.each { match ->
		def matchids = name2id[match]
		eq.entityName.add(match)
		matchids.each {
		  eq.entity.add(it)
		}
	      }

	      def ctext = character.text()
	      def sentences = sentenceDetector.sentDetect(ctext)

	      sentences.each { sentence ->
		sentence = sentence.toLowerCase()
		def mainStructure = sentence.split(";")[0]
		def tokenizedText = tokenizer.tokenize(mainStructure)
		def matches = finder.find(tokenizedText)
		def occurrences = Span.spansToStrings(matches, tokenizedText)
		//	      print "$cclass ("+name2id[cclass]+")\t$ctext\t"
		occurrences.each { match ->
		  def matchids = name2id[match]
		  eq.qualityName.add(match)
		  matchids.each { 
		    //		  print "$it("+match+")\t" 
		    eq.quality.add(it)
		  }
		}
	      }

	      /*
	      def pattern = ~/\d+(\.|\,)*\d*\s*(\-|x)\s*\d+(\.\d+|\,\d+)*\s*[a-z]+/
	      (ctext =~ pattern).each { println it[0] }
	      */
	      ctext = ctext.toLowerCase()
	      def tokenizedText = tokenizer.tokenize(ctext)
	      def matches = finder.find(tokenizedText)
	      def occurrences = Span.spansToStrings(matches, tokenizedText)
	      //	      print "$cclass ("+name2id[cclass]+")\t$ctext\t"
	      occurrences.each { match ->
		def matchids = name2id[match]
		eq.qualityName.add(match)
		matchids.each { 
		  //		  print "$it("+match+")\t" 
		  eq.quality.add(it)
		}
	      }
	      //	      println "\n"
	    }
	  }
	}
      }
    }
  }
}

taxon2eq.each { taxon, eqset ->
  def taxonstring = taxon2string[taxon]
  eqset.each { eq ->
    eq?.entity.each { ent ->
      if (ent.indexOf("PO")>-1) {
	eq?.quality.each { qual ->
	  if (qual.indexOf("PATO")>-1) {
	    fout.println("$taxonstring\t$ent\t$qual")
	  }
	}
      }
    }
  }
}
fout.flush()
fout.close()

taxon2eq.each { taxon, eqset ->
  eqset.each { eq ->
    def checked = new TreeSet()
    eq?.entity.each { ent ->
      if (ent.indexOf("PO:")>-1) {
	checked.add(ent)
      }
    }
    if (checked.size() == 0) {
      fout2.println (eq.entityName+"\t"+"ENTITY-MISMATCH") 
    }


    checked = new TreeSet()
    eq?.qualityName.each { ent ->
      name2id[ent]?.each { e ->
	if (e.indexOf("PATO:")>-1) {
	  checked.add(ent)
	}
	if (e.indexOf("PO:")>-1) {
	  checked.add(ent)
	}
      }
    }
    eq?.qualityName.removeAll { it in checked }
    eq?.qualityName.each { fout2.println (it+"\t"+name2id[it]+"\tQUALITY") }

  }
}
fout2.flush()
fout2.close()
