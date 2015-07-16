def patofile = new File("quality.obo")

def id2super = [:]
def id2name = [:]
def id = ""
def values = new TreeSet()
def attributes = new TreeSet()
def obsolete = new TreeSet()
patofile.eachLine { line ->
  if (line.startsWith("id:")) {
    id = line.substring(3).trim()
  }
  if (line.startsWith("name:")) {
    def name = line.substring(5).trim()
    id2name[id] = name
  }
  if (line.startsWith("is_a:") && line.indexOf("!")>-1) {
    def sc = line.substring(5, line.indexOf("!")-1).trim()
    if (id2super[id] == null) {
      id2super[id] = new TreeSet()
    }
    id2super[id].add(sc)
  }
  if (line.indexOf("attribute_slim")>-1) {
    attributes.add(id)
  }
  if (line.indexOf("value_slim")>-1) {
    values.add(id)
  }
  if (line.indexOf("is_obsolete: true")>-1) {
    obsolete.add(id)
  }
}

def quality2trait = [:]

/* now get the trait from PATO and generate a class for the trait */
// do a BFS (maybe change)
def search = new LinkedList()
values.each { q ->
  def found = false
  if (id2super[q]) {
    search.addAll(id2super[q])
    while (!found && search.size()>0) {
      def nq = search.poll()
      if (!(nq in attributes)) { // superclass is not a trait but another value
	if (id2super[nq]) {
	  search.addAll(id2super[nq])
	}
      } else { // found the trait (nq)
	found = true
	quality2trait[q] = nq
      }
    }
  }
}

new File(args[0]).splitEachLine("\t") { line ->
  def name = line[0]
  def e = line[2]
  def q = line[4]
  def trait = q
  if (quality2trait[trait]!=null) {
    trait = quality2trait[trait]
  }
  println "$name\t$name\t$e\tnull\t$q\t$trait\t$q"
}
