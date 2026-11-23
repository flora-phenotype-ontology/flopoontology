# Annotation design patterns of the FLOPO flora annotations

Each file in this directory documents one pattern by which a statement of a flora becomes an
annotation: the wording it covers, the record of the annotation model
(`flopo2/schema/flopo_trait.yaml`), its OWL class expression, its RDF in the atlas index, the
rules that are checked, and what is known about the pattern in the literature.

| # | Pattern | Source wording | Since |
|---|---|---|---|
| 00 | [Part and quality](00-part-and-quality.md) | leaves glabrous, petals white | the basic pattern |
| 01 | [Approximate value](01-approximate-value.md) | ± erect, suborbicular | 2026-11-13 ("±") |
| 02 | [Bounded measurement](02-bounded-measurement.md) | to 8 m, less than 1 mm | 2026-11-13 (strict bounds) |
| 03 | [Count of parts](03-count-of-parts.md) | 5-nerved, 3-5-foliolate | 2026-11-13 (compound words) |
| 04 | [State of the bearer](04-state-of-the-bearer.md) | young stems, male flowers, sterile fronds | 2026-11-13 |
| 05 | [Range with extremes](05-range-with-extremes.md) | (2-)3-8(-11) cm | 2026-11-13 |
| 06 | [Specimen condition](06-specimen-condition.md) | black when dry | 2026-11-13 |
| 07 | [Alternatives](07-alternatives.md) | white or pink; simple or branched | primary 2026-10; secondary 2026-11-13 |
| 08 | [Alternative with its own frequency](08-alternative-with-frequency.md) | dioecious or rarely monoecious | 2026-11-13 |
| 09 | [Relation to another part](09-relation-to-another-part.md) | shorter than the tube, adnate to the petals | 2026-11-13 |
| 10 | [Equality and ratio to another part](10-ratio-to-another-part.md) | as long as the sepals, 2-3 times as long as | 2026-11-13 |
| 11 | [Ratio of two dimensions](11-ratio-of-two-dimensions.md) | 2-3 times as long as wide | 2026-11-13 |
| 12 | [Part of a qualified whole](12-part-of-qualified-whole.md) | calyx of male flowers | 2026-11-13 |
| 13 | [Indefinite count](13-indefinite-count.md) | seeds numerous, few-flowered | 2026-11-14 |
| 14 | [Count at a position](14-count-at-a-position.md) | veins 4-6 on each side of the midrib | 2026-11-14 |
| 15 | [Absence of a part](15-absence-of-a-part.md) | petals absent, no stipules, leafless | 2026-10; form of [8] 2026-11-20 |
| 16 | [Quality of a whole towards its parts](16-quality-of-a-whole-towards-its-parts.md) | leaves alternate, sepals connate | 2026-11-21 |
| 17 | [Value defined by a measure](17-value-defined-by-a-measure.md) (defines value classes; no record carries it) | lanceolate, acute, opposite | 2026-11-21 |
| 18 | [Position of the bearer](18-position-of-the-bearer.md) | basal leaves, lateral umbels, outer bracts | 2026-11-23 ('has position') |

Earlier patterns (continuum and transition between two values, stage of development, surface or
region of the bearer) are described in `docs/annotation-context-patterns.md`.

## The model in one page

A flora says "basal leaves spatulate, glabrous; petals 5, white". The atlas turns each such
statement into one **annotation**, and each annotation has two sides: a class in OWL, which says
what the plant is like, and a record in RDF, which says where the statement comes from and how
it was said.

### The ontologies

| Ontology | What it gives | Example |
|---|---|---|
| Plant Ontology (PO) [12] | the parts of a plant | leaf PO:0025034, petal PO:0009032 |
| PATO [13] | qualities: shape, colour, texture, size, position | glabrous PATO:0000453, spatulate PATO:0001937 |
| FLOPO [14] | phenotype classes built from a part and a quality; values and parts that PO and PATO lack | 'leaf glabrous'; frutescent habit FLOPO:0987002; 'basal leaf' FLOPO:0996000 |
| Unit Ontology (UO) | units of measurements | millimetre UO:0000016 |
| Relation Ontology (RO), BFO | the relations between them | 'has part', 'has characteristic', 'has phenotype' |
| Evidence Ontology (ECO) | the kind of evidence of a record | author statement used in automatic assertion ECO:0007319 |
| PROV-O, Dublin Core | where a record comes from | the flora, the page, the sentence |

FLOPO is built on PO and PATO and classified with them (ELK [15]), so that 'leaf glabrous' is found
under 'leaf pilosity' and under 'vascular leaf phenotype' without anyone stating it.

### A phenotype class

A phenotype is a quality of the plant, not a kind of plant (Gkoutos et al. [8]; Hoehndorf et
al. [11]). Every class has the same form:

    'flora phenotype' and 'phenotype of' some <defining property>

The **defining property** is what the patterns differ in. In the basic pattern it names a part
(the *entity*) and a quality (Mungall et al. [1]):

    'has part' some (leaf and 'has characteristic' some glabrous)

The `## OWL` section of each pattern gives its defining property. `'phenotype of'` is functional and the
inverse of `'has phenotype'`, by which a taxon is linked to its classes. (Since 2026-11-22;
before, the defining property was itself the class.)

A class that many floras use has a name and an identifier in FLOPO. Any other combination is
written with the same form as an **annotation class** (`.../flopo/annotation-class/FAC_...`), and
the reasoner places it among the FLOPO classes.

### Relations

| Relation | Identifier | Used for |
|---|---|---|
| has phenotype | RO:0002200 | taxon to phenotype class: `Taxon SubClassOf 'has phenotype' some C` |
| phenotype of | RO:0002201 | inverse of 'has phenotype'; functional (a phenotype has one bearer) |
| has part | BFO:0000051 | plant to its part |
| part of | BFO:0000050 | a part within another ("seeds per fruit"); absence (pattern 15) |
| has characteristic | RO:0000053 | part to its quality |
| has position | FLOPO:0995004 | part to its position among the parts of its kind (pattern 18); a sub-relation of 'has characteristic' |
| towards | RO:0002503 | a quality that relates two parts ("adnate to the petals", pattern 09; "leaves alternate", pattern 16) |
| has magnitude, has value unit | FLOPO annotation vocabulary | the number of a measurement and its unit |
| has member | RO:0002351 | a group of parts ("pairs of leaflets") |

### A taxon

A taxon is a class of plants. For each of its statements it gets one axiom,
`Taxon SubClassOf 'has phenotype' some C`. Because 'phenotype of' is functional, the phenotypes
of one taxon are those of one plant, and "petals absent" beside "petals white" is a
contradiction that a reasoner finds (`docs/phene-consistency.md`). Taxon names are matched to the
World Checklist of Vascular Plants; the identifier of a taxon is that of its accepted name.

### An annotation record

The record (`fb:TraitRecord`) is what the website and SPARQL queries read:

| Part of the record | Properties | Says |
|---|---|---|
| what | `fb:taxon`, `fb:bearer`, `fb:quality`, `fb:phenotypeClass`, `fb:flopoClass` | the taxon, the part, the quality, the annotation class, the FLOPO class it falls under |
| numbers | `fb:low`, `fb:high`, `fb:unit` | the range of a measurement or count |
| how it was said | `fb:qualifier`, `fb:frequency`, `fb:negated`, `fb:bearerState` | "usually", "about", "not"; the state or position of the part |
| where from | `fb:source`, `fb:text`; the source statement, `prov:wasDerivedFrom` its document | the flora and the words, with their offsets |
| evidence and status | `fb:evidence` ECO:0007319, 'has evidence' (RO:0002558) to the source statement; `fb:status` | every record is an automatic assertion from an author statement; `accepted` or `review` |

Only what holds of the plant goes into the OWL class. What is said *about* the statement (how
often, how exactly, under which condition of the specimen) stays in the record (see "What goes into OWL and what stays in RDF" below).

### From text to annotation

1. A language model transcribes each statement of a description: part, quality, value, and the
   exact words.
2. The words are grounded to PO and PATO classes by reviewed lexicons, never by the model's own
   choice of identifier.
3. The patterns below turn the grounded statement into a record and a class.
4. Checks (data-model rules, ShEx shapes, SPARQL rules, ELK on the classes) set doubtful records
   to `review`; they stay visible but are not counted as accepted.

## What goes into OWL and what stays in RDF

An annotation is always an RDF record. Its firm content is also an OWL class expression, from
which the taxon is classified under FLOPO classes.

* **OWL** states what the plant is like: the part, the quality, the part of the part, the other
  part of a relation, the whole it belongs to, and alternatives (as a union).
* **RDF only** states what is said about that statement: how often, how exactly, the rare
  extremes of a range, the condition of the specimen, a ratio, and the words of the source. OWL
  has no "rarely" and no "about"; written as class axioms these would be claims about every plant
  of the taxon.

Numbers of the usual range are in both: as data ranges in the class expression and as literals in
the index, where they are queried.

## Three layers of checking

| Layer | What it checks | Where |
|---|---|---|
| Data-model rules | every annotation record, against the source text | `flopo2.verify.data_model.pattern_issues`; rule codes in each pattern file |
| ShEx shapes | the triples of a record of each pattern | `shapes/flopo-annotation-patterns.shex` |
| SPARQL rules | comparisons between two values of one record | `shapes/rules.rq` |

A fourth check works on the OWL side: `flopo2.verify.annotation_class_check` classifies the
annotation classes of each flora with ELK, together with FLOPO, PO and PATO, and sets
statements whose class is contradictory to review (`<source>-unsatisfiable.tsv`), and statements
that contradict each other within a taxon (`<source>-taxon-contradictions.tsv`). The second
question rests on the functional `'phenotype of'`, which ELK does not read; the check states its
consequence per class (the bearer axiom), and `tools/PheneTaxonConsistency.java` asks the same
question of the published axioms with HermiT (`docs/phene-consistency.md`).

The data-model rules run on every record in the pipeline gate (`validate_jsonl`). The RDF side is
checked on a sample of records per pattern:

    python -m tools.validate_annotation_patterns local-corpora/eflora-fop/derived/eflora-fop-annotated.jsonl

Tests: `tests/test_annotation_patterns.py` (one flora sentence per pattern, end to end, and each
rule with a broken record), `tests/test_annotation_pattern_shapes.py` (each shape and SPARQL rule
with a conforming and a broken record).

## Conventions in the pattern files

* Prefixes: `obo:` `http://purl.obolibrary.org/obo/`, `fb:` `http://phenomebrowser.net/flopo/browse#`.
* OWL is written in Manchester syntax with labels; `has part` is BFO:0000051, `part of`
  BFO:0000050, `has characteristic` RO:0000053, `has position` FLOPO:0995004, `towards` RO:0002503, `phenotype of`
  RO:0002201, `has phenotype` RO:0002200, `flora phenotype` FLOPO:0000000; `has magnitude` and
  `has value unit` are the FLOPO annotation properties for a numeric value and its UO unit.
* "Cue" means the exact words of the source that justify a slot, stored with their offsets.

## References

1. Mungall CJ, Gkoutos GV, Smith CL, Haendel MA, Lewis SE, Ashburner M. Integrating phenotype
   ontologies across multiple species. *Genome Biology* 2010;11:R2.
   https://doi.org/10.1186/gb-2010-11-1-r2
2. Dahdul WM, Balhoff JP, Engeman J, et al. Evolutionary characters, phenotypes and ontologies:
   curating data from the systematic biology literature. *PLoS ONE* 2010;5(5):e10708.
   https://doi.org/10.1371/journal.pone.0010708
3. Balhoff JP, Mikó I, Yoder MJ, Mullins PL, Deans AR. A semantic model for species description
   applied to the ensign wasps (Hymenoptera: Evaniidae) of New Caledonia. *Systematic Biology*
   2013;62(5):639-659. https://doi.org/10.1093/sysbio/syt028
4. Endara L, Thessen AE, Cole HA, Walls R, Gkoutos G, Cao Y, Chong SS, Cui H. Modifier ontologies
   for frequency, certainty, degree, and coverage phenotype modifier. *Biodiversity Data Journal*
   2018;6:e29232. https://doi.org/10.3897/BDJ.6.e29232
5. TDWG Structured Descriptive Data (SDD) 1.1, 2006. Primer, "SddCharacters", and the UBIF
   enumeration of univariate statistical measures. https://sdd.tdwg.org/primer/SddCharacters.html
6. Osumi-Sutherland D, Courtot M, Balhoff JP, Mungall C. Dead simple OWL design patterns.
   *Journal of Biomedical Semantics* 2017;8:18. https://doi.org/10.1186/s13326-017-0126-0
7. Cui H. CharaParser for fine-grained semantic annotation of organism morphological
   descriptions. *Journal of the American Society for Information Science and Technology*
   2012;63(4):738-754. https://doi.org/10.1002/asi.22618
8. Gkoutos GV, Schofield PN, Hoehndorf R. The anatomy of phenotype ontologies: principles,
   properties and applications. *Briefings in Bioinformatics* 2018;19(5):1008-1021.
   https://doi.org/10.1093/bib/bbx035
9. Ellis B, Daly DC, Hickey LJ, Johnson KR, Mitchell JD, Wilf P, Wing SL. *Manual of Leaf
   Architecture*. Cornell University Press, Ithaca, 2009. Characters are cited by their number
   in the manual (2 leaf arrangement, 9 laminar L:W ratio, 10 laminar shape, 16 apex angle,
   18 base angle).
   https://www.cornellpress.cornell.edu/book/9780801475184/manual-of-leaf-architecture/
10. Systematics Association Committee for Descriptive Biological Terminology. II. Terminology of
   simple symmetrical plane shapes (Chart 1). *Taxon* 1962;11(5):145-148.
   https://doi.org/10.2307/1216718
11. Hoehndorf R, Oellrich A, Rebholz-Schuhmann D. Interoperability between phenotype and anatomy
   ontologies. *Bioinformatics* 2010;26(24):3112-3118.
   https://doi.org/10.1093/bioinformatics/btq578
12. Cooper L, Walls RL, Elser J, et al. The Plant Ontology as a tool for comparative plant
   anatomy and genomic analyses. *Plant and Cell Physiology* 2013;54(2):e1.
   https://doi.org/10.1093/pcp/pcs163
13. Gkoutos GV, Green ECJ, Mallon AM, Hancock JM, Davidson D. Using ontologies to describe mouse
   phenotypes. *Genome Biology* 2005;6:R8. https://doi.org/10.1186/gb-2004-6-1-r8
14. Hoehndorf R, Alshahrani M, Gkoutos GV, et al. The flora phenotype ontology (FLOPO): tool for
   integrating morphological traits and phenotypes of vascular plants. *Journal of Biomedical
   Semantics* 2016;7:65. https://doi.org/10.1186/s13326-016-0107-8
15. Kazakov Y, Krötzsch M, Simančík F. The incredible ELK: from polynomial procedures to
   efficient reasoning with EL ontologies. *Journal of Automated Reasoning* 2014;53:1-61.
   https://doi.org/10.1007/s10817-013-9296-3

The search for earlier descriptions of each pattern (2026-11-13) was small: references 1 to 7.
"Not found" in a pattern file means not found in these sources, not that no such pattern exists.
