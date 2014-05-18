// arg 0: phenotype file; arg 1: environment file; arg 2: output dir

def pmap = [:].withDefault { new TreeSet() }
new File(args[0]).splitEachLine("\t") { line -> // the phenotypes
  def taxon = line[1]
  def anno = line[2]
  pmap[anno].add(taxon)
}

def emap = [:].withDefault { new TreeSet() }
new File(args[1]).splitEachLine("\t") { line -> // environment
  def taxon = line[0]
  def anno = line[2]
  emap[taxon].add(anno)
}

def taxon2count = [:]
def count = 0
emap.keySet().each { taxon ->
  taxon2count[taxon] = count
  count += 1
}

pmap.each { ppo, tset ->
  def cppo = ppo.replaceAll("<http://phenomebrowser.net/plant-phenotype.owl#","").replaceAll(">","")
  def fout = new PrintWriter(new BufferedWriter(new FileWriter(args[2]+"/"+cppo)))
  emap.each { taxon, envo ->
    if (taxon in tset) {
      envo.each { env ->
	fout.println("TAXON"+taxon2count[taxon]+"\t$env\t1")
      }
    } else {
      envo.each { env ->
	fout.println("TAXON"+taxon2count[taxon]+"\t$env\t0")
      }
    }
  }
  fout.flush()
  fout.close()
}