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

* **FLOPO release** (`tools/check_flopo_phene_bearers.py`, a release step): the bearer axiom and
  a probe `probe(P) SubClassOf 'has phenotype' some P` for each of the 25,982 phenotype classes.
  An unsatisfiable probe is a phenotype no plant can have, alone or together with the classes
  asserted above it. The release requires none (2 min 30 s).
* **Annotations of a flora** (`flopo2.verify.annotation_class_check`, run for every flora): the
  bearer axiom of every annotation class, and a class per taxon with `T SubClassOf 'has
  phenotype' some C` for each of its statements, as in the published data. Negation is rewritten:
  an absence class N gets `'has phenotype' some N SubClassOf M(N)`, the marker M(N) is disjoint
  with the presence, and `X SubClassOf 'part of' some X` is stated for each absent part X. An
  unsatisfiable taxon class is a contradiction within the taxon; its statements are set to
  review.

The bearer axioms are part of the check, not of the published data: they are entailed by the
published axioms, and a user of ELK can generate them (`python -m tools.check_flopo_phene_bearers
--out bearers.ttl`, `flopo2.owl.phene.bearer_axioms`).

### HermiT, on the axioms as published

`tools/PheneTaxonConsistency.java` asks the question directly, with a reasoner for all of OWL 2
DL and no rewriting: for one taxon at a time it cuts out the part of FLOPO, PO, PATO and the
flora's definitions that the taxon's classes depend on (a syntactic locality module, type BOT)
and asks HermiT whether one plant can have a phene of every class. For an inconsistent taxon it
reduces the classes to a smallest contradicting set.

    python -m flopo2.verify.annotation_class_check SOURCE --complete

writes `<source>-taxon-consistency.tsv` (the taxa that are not consistent) and marks nothing.

Only one taxon is checked at a time, never the taxa together: taxa do not constrain each other.

## What was measured (2026-11-22, 4 threads)

| Flora | Taxa | Module, axioms (median; max) | Per taxon (median; max) | Whole flora | Result |
|---|---|---|---|---|---|
| NCVC Saudi guide, FLOPO's unused named classes left out | 299 | 1,078; 2,036 | 0.63 s; 4.9 s | 1 min 28 s | all answered |
| the same, everything kept | 299 | 4,502; 7,666 | 2.3 s; 9.7 s | 3 min 52 s | all answered |
| Collenette, Saudi wildflowers | 1,228 | not recorded | 0.39 s; 3.6 s | 2 min 43 s | all answered |
| Moss Flora of China (first 42 taxa) | 42 of 1,652 | 7,700; 8,800 | over 100 s | stopped | 23 of 42 timed out at 120 s |

* On the two seed-plant floras HermiT answers every taxon, in about half a second each.
* Positive control: the ten pairs of statements that the ELK check had reported for the NCVC
  guide ("leafless" beside "leaves strap-shaped") are all found inconsistent by HermiT, each in
  under 0.3 s, and none without the reflexivity of `part of`.
* `tests/test_annotation_class_check.py::test_hermit_on_the_published_axioms_agrees_with_the_elk_check`
  puts five small taxa to both reasoners and requires the same answer.
* Leaving out FLOPO's named phenotype classes that the flora does not use is safe (a name for an
  expression cannot make a taxon inconsistent) and makes the modules four times smaller; with
  everything kept the check is still feasible on these floras.
* The moss flora is different: its taxa have about as many statements (median 16, against 13),
  but the modules are 4,000 to 9,000 axioms, and more than half of the taxa do not finish in two
  minutes. The reason was not established. This is the flora on which the same approach was
  found too slow on 2026-11-13 (`docs/km-classification.md`).
* The phene form is not what makes HermiT fast: the earlier checker
  (`tools/TaxonConsistency.java`, taxon as a conjunction of classes of plants) needs the same
  time on the NCVC guide (0.5 s per taxon, modules of the same size).
* **Classifying** a taxon's module with HermiT, as opposed to testing the taxon, is not reliable:
  on five taxa with everything kept, 11 s, 2 min 34 s and 23 min, and two that did not finish;
  with the unused names left out, 23 s for one module of 952 axioms and no result in 2 minutes
  for one of 1,385.

## What is used

* ELK with the bearer axioms is the check that runs on every flora and in the FLOPO release: it
  takes minutes for a whole flora and covers "absent against described" and unsatisfiable
  classes. It does not read unions, number ranges or negated qualities.
* HermiT per taxon is the independent check on the published axioms. It is practical for a flora
  whose taxa give small modules and is run on request (`--complete`); it is not part of the
  build, because it does not finish on every flora.
