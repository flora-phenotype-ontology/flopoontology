# 09. Relation to another part

**Intent.** A quality of a part that holds with respect to another part.
**Wording.** comparison: "style shorter than the stamens", "bracts exceeding the flowers";
attachment and position: "stamens adnate to the petals", "inserted at the base of the corolla
tube", "opposite the petals", "alternating with the sepals", "fruit enclosed by the calyx".

## Annotation

```json
{"po_id": "PO_0009029", "pato_id": "PATO_0000642",
 "towards": {"target_term": "PO_0009032", "target_text": "petals", "start": 22, "end": 28,
             "comparison_text": "adnate to"}}
```

| Source words | Quality |
|---|---|
| shorter / longer than, exceeding | decreased length PATO:0000574 / increased length PATO:0000573 |
| narrower / broader, smaller / larger, thinner / thicker than | decreased or increased width, size, thickness |
| adnate to, fused with, united with | fused with PATO:0000642 (adnate FLOPO:0991129 where grounded) |
| inserted at, on, in, near ... | inserted into PATO:0000624 |
| opposite (the) | opposite PATO:0001933 |
| alternating with | alternate placement PATO:0001932 |
| enclosed by, included in, surrounded by | surrounded by PATO:0005016 |
| enclosing, surrounding | surrounding PATO:0001772 |
| attached to, overlapping, parallel to, perpendicular to | PATO:0001667, 0001590, 0002272, 0002434 |

The other part is read from the transcribed quality, else from the source span; it is the
longest phrase after the relation words that grounds to a PO or FLOPO class, is not the bearer,
and stands once in the clause. "not longer than" is not read.

## OWL

`has part some (stamen and has characteristic some ('fused with' and towards some petal))`. The
target is part of the class signature.

## RDF

```turtle
<record> fb:bearer obo:PO_0009029 ; fb:quality obo:PATO_0000642 ;
    fb:towards obo:PO_0009032 ; fb:comparison "adnate to" .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `unknown_relational_target` | data model | the target is a PO or FLOPO class of the catalogues |
| `relational_target_span_not_verbatim` | data model | the target phrase stands at its offsets |
| shape `RelationToAnotherPart` | ShEx | `fb:towards` is a PO or FLOPO class; the relation words are kept |
| `relation_target_is_not_the_bearer` | SPARQL | a part is not related to itself |

## Related work

This is the EQ model's relational quality. Mungall et al. [1]: "For relational qualities we use
the towards relation to connect the quality to the additional entity type on which the quality
depends"; Dahdul et al. [2]: "If two (or more) entities are involved in the phenotype, frequently
a relational quality ... is required". The PATO classes used are in PATO's `relational_slim`.

Balhoff et al. [3] state the limit of the pattern for comparisons: "Relative measurement
phenotypes highlighted an important limitation of OWL class expressions: without the ability to
include variables within the expression, it was impossible to fully represent the intended
meaning". `stamen shorter than some petal` does not say *the petals of the same flower*. They
added SWRL rules; FLOPO keeps the weaker class expression and the source words in RDF.

## Limits

The region of an insertion ("at the base of") is kept in `comparison_text` only. "subtended by",
"free from" and comparisons with a measurement are not read.
