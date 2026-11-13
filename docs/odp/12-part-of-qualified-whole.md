# 12. Part of a qualified whole

**Intent.** The statement holds of a part when the organ it belongs to is in a stated state.
**Wording.** "calyx hairy in male flowers", "petioles of basal leaves to 2.5 cm", "leaves on
sterile shoots", "roots of young plants".

## Annotation

```json
{"po_id": "PO_0009060", "pato_id": "PATO_0000454",
 "bearer_whole": {"whole_term": "PO_0009046", "qualities": ["PATO_0000384"],
                  "whole_text": "in male flowers", "start": 12, "end": 27}}
```

The sex, age or position is a quality of the **whole** (the flower), not of the bearer (the
calyx): pattern 04 would be wrong here. The phrase is read when its quality word has a reviewed
reading for that whole (`config/flora_context_words.tsv`), the whole grounds to a PO or FLOPO
class other than the bearer, and the phrase stands once in the clause.

## OWL

`has part some ((calyx and part of some (flower and has characteristic some male)) and has
characteristic some hairy)`. The whole and its qualities are part of the class signature.

## RDF

```turtle
<record> fb:bearer obo:PO_0009060 ; fb:quality obo:PATO_0000454 ;
    fb:whole obo:PO_0009046 ; fb:wholeQuality obo:PATO_0000384 ; fb:wholeText "in male flowers" .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `unknown_whole_term`, `unknown_whole_quality` | data model | PO/FLOPO whole; PATO/FLOPO qualities |
| `whole_is_the_bearer` | data model | a part is not its own whole (use pattern 04) |
| `whole_text_not_verbatim` | data model | the phrase stands at its offsets |
| `whole_with_bearer_container` | data model | not together with the container of a count |
| shape `PartOfQualifiedWhole` | ShEx | whole, at least one quality, the phrase; no `fb:container` |
| `whole_is_not_the_bearer` | SPARQL | the same on the RDF |

## Related work

This is entity post-composition of the EQ model: Dahdul et al. [2] join terms "by a relation
(part_of) to create a post-composed term (the anterior margin that is part_of the frontal
bone)"; Mungall et al. [1] use the same construct in the logical definitions of pre-composed
phenotype classes. The addition here is that the whole carries its own quality.

## Limits

Parthood is not checked against PO (a calyx is part of a flower; "stamens of female plants" is
accepted as stated). One quality of the whole is read; "in young male flowers" is not.
