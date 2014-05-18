import static groovy.io.FileType.*

def cli = new CliBuilder()
cli.with {
usage: 'foobar'
  h longOpt:'help', 'this information'
  i longOpt:'input-dir', 'input directory with FUNC results',args:1, required:true
  o longOpt:'output-file', 'output file with significant Pathway-to-X associations', args:1
  //  t longOpt:'threads', 'number of threads', args:1
  //  k longOpt:'stepsize', 'steps before splitting jobs', arg:1
}

def opt = cli.parse(args)
if( !opt ) {
  //  cli.usage()
  return
}
if( opt.h ) {
  cli.usage()
    return
}

def id2name = [:]
new File("ont/envo-basic.obo").eachLine { line ->
  if (line.startsWith("id:")) {
    id = line.substring(3).trim()
  }
  if (line.startsWith("name:")) {
    def name = line.substring(5).trim()
    id2name[id] = name
  }
}

def flopo2name = [:]
new File("flopo2label.txt").splitEachLine("\t") { line ->
  def id = line[0]
  def label = line[1]
  flopo2name[id] = label
}

def pw2res = [:]
new File(opt.i).eachDir { f ->
  def pw = f.toString()
  pw = pw.substring(pw.lastIndexOf("/")+1)
  pw2res[pw] = new HashSet()
  try {
    def f2 = new File(f.toString()+"/groups.txt")
    f2.splitEachLine("\t") { line ->
      def id = line[2]
      def sig = line[3]=="+"
      try {
	def over = new Double(line[10])
	def under = new Double(line[9])
	if (over<0.05 || under<0.05) {
	  Expando exp = new Expando()
	  exp.id = id
	  exp.over = new Double(over)
	  exp.under = new Double(under)
	  pw2res[pw].add(exp)
	}
      } catch (Exception E2) {}
    }
  } catch (Exception E) {}
}


def siglevel = 0.05
def over = 0
def under = 0
def fout = new PrintWriter(new BufferedWriter(new FileWriter(opt.o)))
pw2res.each { key, value ->
  value.each { v ->
    def id = v.id
    def name = id2name[id]
    def pwname = flopo2name[key]
    fout.println("$key\t$pwname\t$id\t$name\t"+v.over+"\t"+v.under)
    if (v.over < siglevel) {
      over += 1
    }
    if (v.under < siglevel) {
      under += 1
    }
  }
}
fout.flush()
fout.close()
println "Over-represented entities: $over"
println "Under-represented entities: $under"
