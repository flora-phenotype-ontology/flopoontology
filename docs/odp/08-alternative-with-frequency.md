# 08. Alternative with its own frequency

**Intent.** One of the alternatives is said to be rare, or usual.
**Wording.** "dioecious or rarely monoecious", "curved or occasionally straight".

## Annotation

```json
{"po_id": "PO_0009001", "pato_id": "PATO_0000052", "value_operator": "one_of",
 "value_terms": ["PATO_0000406", "PATO_0002180"],
 "value_operands": [
   {"operand_index": 0, "value": "PATO_0000406", "text": "curved", "start": 6, "end": 12},
   {"operand_index": 1, "value": "PATO_0002180", "text": "rarely straight", "start": 16, "end": 31,
    "frequency_qualifier": "rarely", "qualifier_text": "rarely", "qualifier_start": 16, "qualifier_end": 22}]}
```

The frequency is on the **operand**, not on the assertion: `frequency_qualifier` of the
assertion stays `unspecified`. Works with pattern 07a and 07b.

## OWL

The union of pattern 07: `has characteristic some (curved or straight)`. The annotation is
"qualified" (`operands_make_qualified`), so it gives no strict taxon axiom.

## RDF

```turtle
<record> fb:quality obo:PATO_0000406, obo:PATO_0002180 ; fb:valueOperator "one_of" ;
    fb:alternative <record/alternative/1> .
<record/alternative/1> a fb:Alternative ; fb:quality obo:PATO_0002180 ;
    fb:frequency "rarely" ; fb:text "rarely straight" .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `assertion_and_operand_qualifier_conflict` (existing) | data model | no second, different frequency on the assertion |
| operand span rules (existing, `validate_value_operands`) | gate | each operand text and cue is verbatim at its offsets |
| shape `AlternativeWithFrequency` | ShEx | a union with at least one `fb:Alternative` node; no `fb:frequency` on the record |
| `alternative_is_a_value_of_its_record` | SPARQL | the alternative's value is one of the record's values |

## Related work

Endara et al. [4] provide the frequency vocabulary (their modifier ontology for frequency) but
attach a modifier to a statement, not to one of its alternatives. Reifying the alternative as a
node of its own is the standard n-ary relation approach; no specific pattern was found.

## Limits

Only the second alternative of a pair takes a frequency. "usually X, sometimes Y, rarely Z" is
not read.
