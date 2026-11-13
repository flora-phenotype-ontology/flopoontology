# 10. Equality and ratio to another part

**Intent.** A dimension of a part as a multiple of the same dimension of another part.
**Wording.** "petals as long as the sepals", "equalling the calyx", "filaments 2-3 times as long
as the anthers", "calyx half the length of the corolla", "twice as wide as the lip".

## Annotation

```json
{"po_id": "PO_0009067", "pato_id": "PATO_0000573",
 "towards": {"target_term": "PO_0009066", "target_text": "anthers", "start": 32, "end": 39,
             "comparison_text": "2-3 times as long as", "ratio_low": 2.0, "ratio_high": 3.0}}
```

Pattern 09 with the ratio of the bearer's dimension to the target's. Equality is the ratio 1:
PATO has no "same length as". The quality follows from the ratio:

| Ratio | Quality (length; width, thickness, height alike) |
|---|---|
| above 1 | increased length PATO:0000573 |
| below 1 | decreased length PATO:0000574 |
| 1, or a range spanning 1 | length PATO:0000122 |

"about", "almost", "nearly" before the comparison mark the annotation as approximate (pattern
01). A multiple the reader does not know ("five sevenths as long as") is not read as equality.

## OWL

As pattern 09: `has characteristic some ('increased length' and towards some anther)`. The ratio
is not in OWL.

## RDF

```turtle
<record> fb:quality obo:PATO_0000573 ; fb:towards obo:PO_0009066 ;
    fb:comparison "2-3 times as long as" ; fb:ratioLow 2.0 ; fb:ratioHigh 3.0 .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `invalid_ratio_bounds` | data model | both bounds, positive, low not above high |
| rules of pattern 09 | data model | target known and verbatim |
| shape `RatioToAnotherPart` | ShEx | pattern 09 plus both ratio bounds; the quality is a dimension or its increased or decreased form |
| `ratio_bounds_ordered_and_positive`, `ratio_quality_agrees_with_ratio` | SPARQL | order of the bounds; increased above 1, decreased below 1 |

## Related work

PATO's *ratio* (PATO:0001470, "a quality inhering in a bearer by virtue of the bearer's magnitude
in proportion to the magnitude of another entity") is itself in the relational slim and could
carry the pattern; the increased / decreased classes were preferred so that "2-3 times as long
as" is found with "longer than". The limitation that Balhoff et al. [3] describe for relative
measurements applies (see pattern 09). SDD [5] would express the ratio as a separate
quantitative character defined by the author.

## Limits

Equality as "length towards X" is weak in OWL: it says that the petal has a length relative to
the sepal, not that the lengths are equal. A class "same length as" would make it exact and is a
candidate to propose to PATO.
