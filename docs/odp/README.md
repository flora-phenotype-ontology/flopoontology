# Annotation design patterns of the FLOPO flora annotations

Each file in this directory documents one pattern by which a statement of a flora becomes an
annotation: the wording it covers, the record of the annotation model
(`flopo2/schema/flopo_trait.yaml`), its OWL class expression, its RDF in the atlas index, the
rules that are checked, and what is known about the pattern in the literature.

| # | Pattern | Source wording | Since |
|---|---|---|---|
| 01 | [Approximate value](01-approximate-value.md) | ± erect, suborbicular | 2026-11-13 ("±") |
| 02 | [Bounded measurement](02-bounded-measurement.md) | to 8 m, less than 1 mm | 2026-11-13 (strict bounds) |
| 03 | [Count of parts](03-count-of-parts.md) | 5-nerved, 3-5-foliolate | 2026-11-13 (compound words) |
| 04 | [State of the bearer](04-state-of-the-bearer.md) | young stems, basal leaves | 2026-11-13 (FLOPO positions) |
| 05 | [Range with extremes](05-range-with-extremes.md) | (2-)3-8(-11) cm | 2026-11-13 |
| 06 | [Specimen condition](06-specimen-condition.md) | black when dry | 2026-11-13 |
| 07 | [Alternatives](07-alternatives.md) | white or pink; simple or branched | primary 2026-10; secondary 2026-11-13 |
| 08 | [Alternative with its own frequency](08-alternative-with-frequency.md) | dioecious or rarely monoecious | 2026-11-13 |
| 09 | [Relation to another part](09-relation-to-another-part.md) | shorter than the tube, adnate to the petals | 2026-11-13 |
| 10 | [Equality and ratio to another part](10-ratio-to-another-part.md) | as long as the sepals, 2-3 times as long as | 2026-11-13 |
| 11 | [Ratio of two dimensions](11-ratio-of-two-dimensions.md) | 2-3 times as long as wide | 2026-11-13 |
| 12 | [Part of a qualified whole](12-part-of-qualified-whole.md) | calyx of male flowers | 2026-11-13 |

Earlier patterns (continuum and transition between two values, stage of development, surface or
region of the bearer) are described in `docs/annotation-context-patterns.md`.

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
statements whose class is contradictory to review (`<source>-unsatisfiable.tsv`).

The data-model rules run on every record in the pipeline gate (`validate_jsonl`). The RDF side is
checked on a sample of records per pattern:

    python -m tools.validate_annotation_patterns local-corpora/eflora-fop/derived/eflora-fop-annotated.jsonl

Tests: `tests/test_annotation_patterns.py` (one flora sentence per pattern, end to end, and each
rule with a broken record), `tests/test_annotation_pattern_shapes.py` (each shape and SPARQL rule
with a conforming and a broken record).

## Conventions in the pattern files

* Prefixes: `obo:` `http://purl.obolibrary.org/obo/`, `fb:` `http://phenomebrowser.net/flopo/browse#`.
* OWL is written in Manchester syntax with labels; `has part` is BFO:0000051, `part of`
  BFO:0000050, `has characteristic` RO:0000053, `towards` RO:0002503; `has magnitude` and
  `has value unit` are the FLOPO annotation properties for a numeric value and its UO unit.
* "Cue" means the exact words of the source that justify a slot, stored with their offsets.

## References

1. Mungall CJ, Gkoutos GV, Smith CL, Haendel MA, Lewis SE, Ashburner M. Integrating phenotype
   ontologies across multiple species. *Genome Biology* 2010;11:R2. doi:10.1186/gb-2010-11-1-r2
2. Dahdul WM, Balhoff JP, Engeman J, et al. Evolutionary characters, phenotypes and ontologies:
   curating data from the systematic biology literature. *PLoS ONE* 2010;5(5):e10708.
   doi:10.1371/journal.pone.0010708
3. Balhoff JP, Mikó I, Yoder MJ, Mullins PL, Deans AR. A semantic model for species description
   applied to the ensign wasps (Hymenoptera: Evaniidae) of New Caledonia. *Systematic Biology*
   2013;62(5):639-659. doi:10.1093/sysbio/syt028
4. Endara L, Thessen AE, Cole HA, Walls R, Gkoutos G, Cao Y, Chong SS, Cui H. Modifier ontologies
   for frequency, certainty, degree, and coverage phenotype modifier. *Biodiversity Data Journal*
   2018;6:e29232. doi:10.3897/BDJ.6.e29232
5. TDWG Structured Descriptive Data (SDD) 1.1, 2006. Primer, "SddCharacters"
   (https://sdd.tdwg.org/primer/SddCharacters.html) and the UBIF enumeration of univariate
   statistical measures (https://sdd.tdwg.org/2006/Schema/1.1/documentation/UBIF_EnumData.html).
6. Osumi-Sutherland D, Courtot M, Balhoff JP, Mungall C. Dead simple OWL design patterns.
   *Journal of Biomedical Semantics* 2017;8:18. PMC5460348
7. Cui H. CharaParser for fine-grained semantic annotation of organism morphological
   descriptions. *Journal of the American Society for Information Science and Technology*
   2012;63(4):738-754.

The search of 2026-11-13 was small (seven sources). "Not found" in a pattern file means not found
in these sources, not that no such pattern exists.
