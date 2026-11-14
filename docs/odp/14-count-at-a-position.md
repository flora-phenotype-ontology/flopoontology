# 14. Count at a position

**Intent.** The number of parts at each place of a kind, where the flora does not give the
number for the organ as a whole.
**Wording.** "lateral veins 4-6 on each side of the midrib", "lobes 3-10 on each side", "teeth
30-75 per side", "flowers 1-3 per node", "1-3 fruits per leaf axil".

## Annotation

```json
{"po_id": "PO_0020140", "pato_id": "PATO_0000070", "bearer_container": "PO_0020039",
 "value_low": 4.0, "value_high": 6.0, "unit": "count",
 "count_position": {"kind": "each_side", "landmark_term": "PO_0020139",
                    "position_text": "on each side of the midrib", "start": 20, "end": 46}}
```

A count (pattern 03) with a `count_position`: the kind of place (`each_side`, `per_node`,
`per_axil`, `at_region`), its cue with offsets, and the structure that marks the place when the
source names it (the leaf midvein). The organ that has the parts stays in `bearer_container`.
A place is not a container: the fruits are in the axil, not part of it.

## OWL

None. "4-6 on each side" does not say how many veins the lamina has (8-12 only if both sides
always agree), and a class with the range 4-6 would be false for it. The record carries no
phenotype class and is not compared for conflicts, like a statement about a dried specimen
(pattern 06).

## RDF

```turtle
<record> fb:bearer obo:PO_0020140 ; fb:container obo:PO_0020039 ; fb:quality obo:PATO_0000070 ;
    fb:low 4.0 ; fb:high 6.0 ; fb:unit obo:UO_0000189 ;
    fb:countPosition "each_side" ; fb:countPositionText "on each side of the midrib" ;
    fb:countLandmark obo:PO_0020139 .
```

The atlas does not merge such a count with counts of the same part from other statements.

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `count_position_text_not_verbatim` | data model | the cue stands at its offsets in the source |
| `count_position_without_count` | data model | the record is a count: amount, with a number |
| `count_position_with_phenotype_class` | data model | no phenotype class is linked |
| `count_position_landmark_unknown` | data model | the landmark is a PO or FLOPO class |
| `count_per_position` (annotator) | annotator | the cue is not found once in the statement: the row is held |
| shape `CountAtAPosition` | ShEx | amount, count unit, a kind of place, no phenotype class |
| `count_position_without_phenotype_class`, `count_landmark_is_not_the_bearer` | SPARQL | on the RDF |

## Related work

Leaf architecture manuals count secondary veins per side of the midvein as a character of its
own. In EQ annotation a count is a quality of the whole with PATO *has number of* and the
counted entity [1]; the per-side scope has no slot there. Balhoff et al. [3] note that counts
relative to a position are among the characters their model leaves as free text.

## Limits

Rates ("6-10 teeth per cm") and counts on a named fraction ("on the proximal half") are held.
Open: an OWL reading for `each_side` with a symmetric organ. Found by the second-model review of
2026-11-14 (234 of 800 statements for which no pattern existed; 5,221 held rows in 37 floras).
