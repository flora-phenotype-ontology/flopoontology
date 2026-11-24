# 20. Measured extent of a state or relation

**Intent.** The number measures how far a state or a relation reaches, not a dimension of the
part.
**Wording.** "filaments exserted 5.5-6.5 mm", "petals fused for 1.2-1.4 cm", "leaf bases
decurrent 3-20 mm", "apex to 1 cm acuminate", "sepals connate for 2 mm".

## Annotation

```json
{"po_id": "PO_0009067", "pato_id": "PATO_0000623",
 "extent": {"quality": "PATO_0000623", "value_low": 5.5, "value_high": 6.5, "unit": "mm"}}
```

The quality is the state (exserted). The numbers go to `extent`, not to `value_low` and
`value_high`, which are those of a dimension of the bearer. Only the states of
`config/extent_qualities.tsv` take an extent; the table says what the number measures:

| Quality | The number is |
|---|---|
| exserted PATO:0000623, protruding PATO:0001598 | how far the part stands out |
| fused with PATO:0000642, connate FLOPO:0991067, adnate FLOPO:0991129 | the length of the joined portion |
| decurrent PATO:0001984 | how far the base runs down the axis |
| split, cleft, cut, lobed | the depth of the division |
| acuminate, caudate, cuspidate, mucronate, beaked, clawed | the length of the tip, tail, beak or claw |
| distant FLOPO:0991189 | the distance between neighbouring parts |

## OWL

The expression below is the defining property of the class; the class itself is its phene,
`'flora phenotype' and 'phenotype of' some (...)` (pattern 00).

`has part some (filament and has characteristic some exserted)`: the class of the state, the
same as for "filaments exserted". The number is not in the class. It could be written as a
magnitude of the state (`exserted and has magnitude some decimal[5.5, 6.5]`), but the classes of
FLOPO give magnitudes to attributes only (length, width), and the classifier would not relate
"exserted 5 mm" to "exserted"; so the record falls under the class a reader looks for, and the
number stays in RDF.

## RDF

```turtle
<record> fb:bearer obo:PO_0009067 ; fb:quality obo:PATO_0000623 ;
    fb:extentLow 5.5 ; fb:extentHigh 6.5 ; fb:extentUnit obo:UO_0000016 ; fb:extentUnitSymbol "mm" .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `extent_of_another_quality` | data model | the extent is that of the stated quality, and the quality is in the table |
| `extent_without_number`, `extent_with_measurement` | data model | an extent has a number; the record has no other measurement |
| `numeric_quality_not_pato_attribute` (annotator) | annotator | a number beside any other value is held |
| shape `MeasuredExtent` | ShEx | a number, a UO unit, no `fb:low` or `fb:high` |
| `extent_bounds_ordered` | SPARQL | low is not above high |

## Related work

In the EQ model a measurement is a value of an attribute of the entity [1]; PATO's relational
qualities take a second entity (`towards`) and no magnitude. Dahdul et al. [2] record "relative
position" characters as text. The Manual of Leaf Architecture measures the same things as named
characters of their own (length of the drip tip, depth of the sinus).

## Limits

The extent beyond a named part ("exserted 2 mm beyond the calyx") keeps the number and drops the
other part. An open bound on an extent ("exserted to more than 5 mm") is held. Found by the
second-model review of 2026-11-23 (97 of 3,114 sampled statements; 2,146 held rows in the floras
under `numeric_quality_not_pato_attribute`).
