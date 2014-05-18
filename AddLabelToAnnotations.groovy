// adds label to FLOPO annotation file

// flopo labels
def id2label = [:]
new File(args[0]).splitEachLine("\t") { line ->
  id2label[line[0]] = line[1]
}

new File(args[1]).splitEachLine("\t") { line ->
  def tax = line[0]
  def str = line[1]
  def id = line[2].replaceAll("<http://phenomebrowser.net/plant-phenotype.owl#","").replaceAll(">","")
  println "$tax\t$str\t"+line[2]+"\t"+id2label[id]
}