# 05. Range with extremes

**Intent.** A usual range with rarely reached values beyond one or both ends.
**Wording.** "(2-)3-8(-11) cm", "3-6(-13) cm", "up to 35(-45) mm", "5(-6)".

## Annotation

```json
{"po_id": "PO_0025034", "pato_id": "PATO_0000122", "unit": "cm",
 "value_low": 3.0, "value_high": 8.0, "value_min_extreme": 2.0, "value_max_extreme": 11.0}
```

`range_extremes` (in `flopo2/ingest/ncvc_annotate.py`) reads the printed range: the numbers
outside the parentheses are the usual range, those inside the extremes. It replaces the
transcribed bounds, because the transcriber often folds an extreme into the range ("3-6(-13)"
as 6-13). In "(6-)12(-26) x (19-)21-24(-42) mm" the transcribed numbers decide which of the two
ranges the row is about; if that is not decidable the row keeps its transcribed values and gets
no extremes.

## OWL

Only the usual range enters the class expression (`xsd:decimal[>= 3, <= 8]`). The extremes are
not in the class signature: "3-8(-11)" and "3-8" annotate the same class.

## RDF

```turtle
<record> fb:low 3.0 ; fb:high 8.0 ; fb:minExtreme 2.0 ; fb:maxExtreme 11.0 ; fb:unit obo:UO_0000015 .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `extreme_without_usual_bound` | data model | a lower extreme needs `value_low`, an upper one `value_high` |
| `extreme_not_outside_usual_range` | data model | min extreme < `value_low`; max extreme > `value_high` |
| `extreme_not_in_parentheses_in_source` | data model | the number is printed in parentheses in the source span |
| shape `RangeWithExtremes` | ShEx | usual upper bound, unit, at least one extreme |
| `extreme_outside_usual_range`, `range_low_not_above_high` | SPARQL | the same order on the RDF values |

## Related work

This is a known pattern of descriptive data. The SDD primer [5] supports "extended ranges (e.g.
wing length (5-)10-40(-50) mm, interpreted as wings usually between 10 and 40mm but occasionally
down to 5mm or up to 50mm)". SDD encodes the four numbers as statistical measures of one
quantitative character: `Min` and `Max` ("absolute smallest/largest value") for the outer values
and, for legacy ranges of unknown method, `UMethLower` and `UMethUpper` for the usual range. The
four FLOPO fields correspond one to one: `value_min_extreme` = Min, `value_low` = UMethLower,
`value_high` = UMethUpper, `value_max_extreme` = Max. No OWL pattern was found; keeping the
extremes as annotations is the choice made here.

## Limits

An extreme inside a count word ("7-9(-11)-nerved") is not yet read. A reversed extreme
("2(-1)-seriate") is ignored.
