# 11. Ratio of two dimensions of the bearer

**Intent.** The proportion of one part: its length to its width.
**Wording.** "leaves 2-3 times as long as wide", "as long as broad", "longer than broad",
"wider than long".

## Annotation

```json
{"po_id": "PO_0025034", "pato_id": "PATO_0001470", "value_low": 2.0, "value_high": 3.0, "unit": "ratio",
 "ratio_numerator": "PATO_0000122", "ratio_denominator": "PATO_0000921"}
```

A measurement of PATO ratio with the dimensionless unit *ratio* (UO:0000190) and the two
dimensions. "as long as broad" is 1; "longer than broad" is above 1 with the bound excluded
(`value_low: 1, value_low_inclusive: false`); "wider than long" is the ratio of width to length
above 1.

## OWL

`has part some (leaf and has characteristic some (ratio and has magnitude some
xsd:decimal[>= 2, <= 3] and has value unit some ratio))`. Which dimensions are compared is not in the
class expression: the two annotations "2-3 times as long as wide" and "2-3 times as wide as
long" share a class and differ in RDF.

## RDF

```turtle
<record> fb:quality obo:PATO_0001470 ; fb:low 2.0 ; fb:high 3.0 ; fb:unit obo:UO_0000190 ;
    fb:ratioNumerator obo:PATO_0000122 ; fb:ratioDenominator obo:PATO_0000921 .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `ratio_needs_both_dimensions`, `ratio_of_one_dimension` | data model | two different dimensions |
| `ratio_dimension_not_attribute` | data model | each is a PATO attribute |
| `ratio_dimensions_without_ratio_quality`, `ratio_without_value` | data model | the quality is PATO ratio and has a value |
| shape `RatioOfTwoDimensions` | ShEx | quality ratio, unit ratio, both dimensions, no `fb:towards` |
| `ratio_of_two_different_dimensions` | SPARQL | numerator and denominator differ |

## Related work

PATO *ratio* gives "height to weight" and "waist-hip ratio" as examples of this use. In SDD [5]
and in DELTA a length/width ratio is a quantitative character of its own. No OWL pattern that
names the two dimensions was found; a class "length to width ratio" under PATO ratio would put
them into the class expression.

## Limits

Because the dimensions are not in the class, the classification cannot tell a length/width ratio
from another ratio of the same bearer; queries must use the RDF. Ratios of other pairs (length
to thickness) are not read.
