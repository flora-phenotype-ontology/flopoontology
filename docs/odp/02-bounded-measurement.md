# 02. Bounded measurement

**Intent.** The flora gives only one bound of a dimension.
**Wording.** "to 8 m", "up to 35 mm", "to c. 2 m", "less than 1 mm", "<1 mm", "more than 5 cm".

## Annotation

```json
{"po_id": "PO_0009031", "pato_id": "PATO_0000122",
 "value_low": null, "value_high": 1.0, "value_high_inclusive": false, "unit": "mm"}
```

"up to", "to", "at most", "reaching" give an inclusive upper bound; "less than", "under",
"below", "<" a strict one (`value_high_inclusive: false`). "more than", "over", ">" give a strict
lower bound. A negated cue ("rarely less than 7 mm") is not a bound and the row is left
unresolved (`upper_bound_cue_not_supported`).

## OWL

`has part some (sepal and has characteristic some (length and has magnitude some
xsd:decimal[< 1.0] and has value unit some millimeter))`: `xsd:maxExclusive` for a strict bound,
`xsd:maxInclusive` otherwise.

## RDF

```turtle
<record> fb:bearer obo:PO_0009031 ; fb:quality obo:PATO_0000122 ; fb:high 1.0 ;
    fb:highExclusive true ; fb:unit obo:UO_0000016 ; fb:unitSymbol "mm" .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `upper_bound_cue_not_in_source_span` (existing) | gate | an upper bound without a lower one needs a cue in the source span |
| `bound_inclusivity_without_bound` (existing) | gate, data model | a strict flag needs its bound |
| shape `BoundedMeasurement` | ShEx | exactly one of `fb:low`, `fb:high`, with a UO unit |

## Related work

SDD [5] has no open interval as such; a one-sided value is a single statistical measure (for
example only `Max`). The OWL form is the usual data-range restriction.

## Limits

A bound relative to another part ("less than half the width of the seed") is pattern 10.
