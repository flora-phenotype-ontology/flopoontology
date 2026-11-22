# Phenotypes as phenes, and how their consistency is checked

Since the release of 2026-11-22 every phenotype class, in FLOPO and in the annotations of the
floras, is a *phene*: a quality of the plant, defined by a property of the plant.

    'leaf glabrous'  EquivalentTo:
        'flora phenotype' and 'phenotype of' some
            ('has part' some (leaf and 'has characteristic' some glabrous))

    Taxon  SubClassOf:  'has phenotype' some 'leaf glabrous'

The inner expression is the **defining property**. The form is that of Hoehndorf, Oellrich and
Rebholz-Schuhmann, Interoperability between phenotype and anatomy ontologies, *Bioinformatics*
2010;26(24):3112-3118, doi:10.1093/bioinformatics/btq578 (`Phene and phene-of some Y`), and it is
the second of the two readings of a phenotype class in Gkoutos, Schofield and Hoehndorf, The
anatomy of phenotype ontologies, *Briefings in Bioinformatics* 2018;19(5):1008-1021,
doi:10.1093/bib/bbx035: a class of qualities of organisms, not a class of organisms. Before, a
FLOPO class was its defining property (a class of plants), and an annotation class mixed the two.

Code: `flopo2/owl/phene.py` (the form, the view that gives back the defining properties, the
bearer axioms), `tools/update_flopo_phene_form.py` (the release pass),
`flopo2/owl/assertions.py` (`defining_property`, `_phenotype_expression`).

## The axioms

| Axiom | Where | Why |
|---|---|---|
| `'phenotype of'` (RO:0002201) is functional | FLOPO, the assertion modules, RO | a phene has one bearer |
| `'has phenotype'` (RO:0002200) is the inverse of `'phenotype of'` | the same | the taxon is linked from the plant's side |
| `part of` is reflexive | stated by the checks | a petal is part of itself: "no part of a petal" means "no petal" |

Two things follow.

1. *One phene in two classes.* If p is the phene of a plant that has no part of a petal and the
   phene of a plant that has a white petal, the two plants are one plant, which is impossible:
   `'petals absent' and 'petals white'` is empty. This needs the functional property only.
2. *One plant with two phenes.* A plant o with a phene p1 of "petals absent" and another phene
   p2 of "petals white": by the inverse, p1 and p2 are phenotypes of o; by functionality the
   plants named in their definitions are o. So o has no part of a petal and has a white petal: a
   taxon with both statements is empty. This needs the inverse as well.

Subsumption between phenes is subsumption between defining properties (`'phenotype of' some X` is
under `'phenotype of' some Y` when X is under Y). That is in OWL 2 EL, and the ELK classification
of FLOPO is the same as before the change: 35,462 subclass links between named classes on
2026-11-21 and on 2026-11-22, none added or lost (`tests/test_flopo_phene_form.py` guards the
form; the comparison was made when the release was built).

## Two reasoners

Functional properties, inverses and negation are outside OWL 2 EL. ELK passes over them without
an error, so with ELK alone the two consequences above are lost.

### ELK, with the bearer axiom

Both axioms together entail, for every class C with defining property Y,

    'has phenotype' some C  SubClassOf  Y

(a plant that has the phene of Y is a Y). This is in OWL 2 EL. Stated once per class it gives ELK
the step from the phenes of a plant to the plant.

* **FLOPO release** (`tools/check_flopo_phene_bearers.py`, a release step): the published file
  of bearer axioms (next section) and a probe `probe(P) SubClassOf 'has phenotype' some P` for
  each of the 25,982 phenotype classes.
  An unsatisfiable probe is a phenotype no plant can have, alone or together with the classes
  asserted above it. The release requires none (3 min 30 s).
* **Annotations of a flora** (`flopo2.verify.annotation_class_check`, run for every flora): the
  bearer axiom of every annotation class, and a class per taxon with `T SubClassOf 'has
  phenotype' some C` for each of its statements, as in the published data. Negation is rewritten:
  an absence class N gets `'has phenotype' some N SubClassOf M(N)`, the marker M(N) is disjoint
  with the presence, and `X SubClassOf 'part of' some X` is stated for each absent part X. An
  unsatisfiable taxon class is a contradiction within the taxon; its statements are set to
  review.

The bearer axioms of FLOPO are published with every release as a file of their own, see the next
section. Those of the annotation classes of a flora are written by the check for its own run
(`flopo2.owl.phene.bearer_axioms` gives them for any graph of phene classes).

## The bearer axioms as a release file

`ontology/flopo-bearer-axioms.ofn` holds the bearer axiom of every FLOPO phenotype class, 25,989
axioms in the release of 2026-11-22, and nothing else. It is for anyone who reasons with ELK, or
another OWL 2 EL reasoner, over data that links taxa or specimens to FLOPO classes.

| | |
|---|---|
| In the repository | `ontology/flopo-bearer-axioms.ofn` (OWL functional syntax, 11 MB) |
| With each release | asset `flopo-bearer-axioms.ofn` of the GitHub release, from 2026-11-22 on |
| Address of a version | `http://purl.obolibrary.org/obo/flopo/releases/<date>/flopo-bearer-axioms.ofn` |
| Ontology IRI | `http://purl.obolibrary.org/obo/flopo/flopo-bearer-axioms.owl` |
| Imports | `flopo.owl` of the same version |
| Licence | CC0, as FLOPO |
| Built by | `python -m tools.build_flopo_phene_bearers` (after the final passes of a release) |
| Checked by | `python -m tools.check_flopo_phene_bearers`: the file is what the release gives, and with it ELK finds no phenotype that no plant can have |

**What it does.** Without the file ELK knows that 'petal linear' is a kind of 'petal phenotype',
but nothing about the plant. With it, a taxon that has the phenotype 'petal linear' is a plant
with a linear petal, and so a plant with petals:

```turtle
ex:TaxonA rdfs:subClassOf [ a owl:Restriction ; owl:onProperty obo:RO_0002200 ;   # has phenotype
                            owl:someValuesFrom obo:FLOPO_0000014 ] .              # petal linear
ex:PlantWithPetals owl:equivalentClass [ a owl:Restriction ; owl:onProperty obo:BFO_0000051 ;
                            owl:someValuesFrom obo:PO_0009032 ] .                 # has part some petal
```

```bash
robot merge --input flopo.owl --input flopo-bearer-axioms.ofn \
            --input docs/examples/flopo-bearer-axioms-taxon.ttl \
      reason --reasoner ELK --output classified.ofn
grep TaxonA classified.ofn      # SubClassOf(ex:TaxonA ex:PlantWithPetals)
```

Without `flopo-bearer-axioms.ofn` the same command does not give that line. The second example,
`docs/examples/flopo-bearer-axioms-contradiction.ttl`, is a taxon said to have linear petals and
to be a plant without petals; ELK reports it unsatisfiable only with the file.
(`flopo.owl` imports PO and PATO; with ROBOT offline use the catalog in `ontology/`.) Both
examples are tests (`tests/test_flopo_phene_form.py`).

**What it does not do.** OWL 2 EL has no negation, so "petals absent" has to be given to ELK as a
class declared disjoint with "has part some petal", as in the second example and in the flora
check. The file does not state that `part of` is reflexive. The axioms are in OWL 2 EL wherever
the defining property is; a few FLOPO classes use a number restriction, which ELK passes over.

**Do not use it instead of the definitions.** The file is a consequence of `flopo.owl`, not a
replacement; a reasoner for all of OWL 2 DL (HermiT) needs only `flopo.owl`.

### HermiT, on the axioms as published

`tools/PheneTaxonConsistency.java` asks the question directly, with a reasoner for all of OWL 2
DL and no rewriting: for one taxon at a time it cuts out the part of FLOPO, PO and PATO that the
definitions of the taxon's own classes depend on (a syntactic locality module, type BOT), adds
those definitions, and asks HermiT whether one plant can have a phene of every class. For an
inconsistent taxon it reduces the classes to a smallest contradicting set.

    python -m flopo2.verify.annotation_class_check SOURCE --complete

writes `<source>-taxon-consistency.tsv` (the taxa that are not consistent) and marks nothing.

Only one taxon is checked at a time, never the taxa together: taxa do not constrain each other.

## What was measured (2026-11-22, 4 threads)

| Flora | Taxa | Module, axioms (median; max) | Per taxon (median; max) | Whole flora |
|---|---|---|---|---|
| Moss Flora of China | 1,652 | 299; 636 | 0.03 s; 0.5 s | 28 s |
| NCVC Saudi guide | 299 | 268; 395 | 0.03 s; 0.4 s | 12 s |

Every taxon is answered. Variants, on the first 200 taxa (60 for the last row) of each flora:

| Variant | Moss Flora of China | NCVC |
|---|---|---|
| FLOPO's named phenotype classes that the flora does not use are kept | modules 1,164 (max 6,101); 0.47 s (max 3.8 s) | modules 1,249 (max 2,781); 0.46 s (max 1.4 s) |
| the taxon's module is also **classified** (whole class hierarchy) | 0.07 s (max 1.8 s) | 0.05 s (max 0.4 s) |
| classified with FLOPO's named classes kept | 3.2 s (90% under 16 s, max 106 s) | 2.2 s (90% under 5 s, max 14 s) |

* Positive control: the ten pairs of statements that the ELK check had reported for the NCVC
  guide ("leafless" beside "leaves strap-shaped") are all found inconsistent, and none without
  the reflexivity of `part of`.
* `tests/test_annotation_class_check.py::test_hermit_on_the_published_axioms_agrees_with_the_elk_check`
  puts five small taxa to both reasoners and requires the same answer.
* Leaving out FLOPO's named phenotype classes that the flora does not use is safe: a name for an
  expression cannot make a taxon inconsistent.
* The phene form is not what makes HermiT fast or slow: the earlier checker
  (`tools/TaxonConsistency.java`, taxon as a conjunction of classes of plants) behaves the same.

### Every flora, every taxon (2026-11-22)

`--complete` was run on all 40 floras of the atlas: 108,510 taxa in 77 minutes on 4 threads
(the largest, Flora of China with 33,463 taxa, in 22 minutes). No taxon timed out and none gave
an error; the slowest single taxon took 2.7 s.

HermiT found **109 inconsistent taxa** (1 in 1,000) in 13 floras, none of which the ELK check
had reported. The 35 of them that were read (six floras) are all of one kind: a part is said
to be absent, and the same taxon has a measurement of that part.

| Absent | Beside | Taxa (of 35) |
|---|---|---|
| a part | a length of that part or of a part of it | 23 |
| a part | a count of it or of a part of it (never 0) | 9 |
| a part | a width of it | 3 |

Example (Lamarckia aurea, Kew grass descriptions): "lemma awns absent" and a lemma awn with a
length in millimetres. ELK misses these because a class with a number range is outside OWL 2 EL
and ELK passes over its whole definition, so for ELK the taxon has no awn. This is the limit
named under "What is used", now with a size: about 1 taxon in 1,000. Whether each is an error
of the annotation or two forms described in one paragraph (fertile and sterile florets, say)
was not judged; they need a reader, as the other marked statements do.

The reports are `<source>-taxon-consistency.tsv`, one line per inconsistent taxon with the
smallest set of classes that contradict each other.

### Why the Moss Flora of China did not finish at first

The first version of the check, and the trial of 2026-11-13 (`docs/km-classification.md`), cut
each taxon's module out of the ontologies **together with the definitions of all annotation
classes of the flora**. On the Moss Flora of China the modules then had 4,000 to 9,000 axioms and
23 of the first 42 taxa did not finish in two minutes; on the two Saudi floras the same program
took half a second per taxon. The number of statements per taxon is about the same (median 16
against 13), and no single term is to blame: the module of every Plant Ontology, PATO or FLOPO
term that the moss flora uses has at most 108 axioms.

The cause is how a locality module treats a definition `C EquivalentTo: D` of a class C that the
taxon does not have. Such an axiom is left out only if D is certain to be empty when the terms
outside the module are taken to be empty. That fails in three cases:

1. **All terms of D are already in the module.** A flora describes the same organs with the same
   qualities in every taxon, so most other classes qualify as soon as the module holds "leaf",
   "costa", "shape" and their superclasses.
2. **D is a negation.** "Costa absent" is `not ('has part' some ('part of' some costa))`. A
   negation is never certain to be empty, so every absence class of the flora enters every
   module, and brings the absent part and everything above it.
3. **D is an alternative.** "Ovate or lanceolate" is not empty as soon as one of the two is in
   the module, and brings the other.

The second and third feed the first. The moss flora has 230 classes with a negation and 599 with
an alternative among 8,875; the module of one typical class ("peristome tooth: recurved") held
2,212 axioms, of which 1,600 were definitions of other annotation classes (161 of them
negations, 373 alternatives). The NCVC guide has 6 negations and 88 alternatives among 1,623
classes; the module of a typical class held 158 axioms and 38 other definitions.

None of these definitions can change whether the taxon is consistent: they define names the
taxon does not use. The check now keeps the flora's definitions apart and gives each taxon the
module of the ontologies for the terms of **its own** definitions, plus those definitions. This
is the same locality module, of a smaller ontology (ontologies and the taxon's definitions). The
moss modules fell from about 7,700 axioms to about 300 and the time per taxon from over 100 s to
0.03 s; the Saudi floras became 7 times faster as well (NCVC: 88 s before, 12 s now).

The lesson for anyone modularising annotation data: extract the module from the ontologies and
the entity's own axioms, not from the whole dataset; negated and disjunctive class definitions
are non-local and pull a dataset together.

## What is used

* ELK with the bearer axioms is the check that marks statements, on every flora and in the FLOPO
  release. It covers "absent against described" and unsatisfiable classes; it does not read
  unions, number ranges or negated qualities.
* HermiT per taxon is the independent check on the published axioms. It reads everything, and
  with the module cut correctly it takes seconds to minutes for a whole flora (77 minutes for
  all 108,510 taxa). It reports (`--complete`) and marks nothing yet.
* Open: the 109 taxa that only HermiT finds are not marked for review in the atlas. Two ways to
  close this: let the HermiT report mark statements, or give ELK the bearer axiom of a numeric
  class without its number (`'has part' some (E and 'has characteristic' some Q)`), which is in
  OWL 2 EL and enough for "absent against measured".
