# 03. Count of parts

**Intent.** The number of parts of a kind that an organ has.
**Wording.** "stamens 10", "3 seeds per fruit", and, since 2026-11-13, counts inside a word:
"5-nerved", "3-5-foliolate", "three-flowered", "3-jugate".

## Annotation

```json
{"po_id": "PO_0020049", "pato_id": "PATO_0000070", "bearer_container": "PO_0025034",
 "value_low": 3.0, "value_high": 5.0, "unit": "count"}
```

The bearer is the **counted part** (leaflet), the quality is PATO amount, and the organ that has
the parts is `bearer_container` (leaf). A compound word is split only when (a) it has no term of
its own ("3-lobed" stays the quality trilobed where a rule says so) and (b) its ending is in the
reviewed table `config/flora_counted_parts.tsv` (nerved → vein, foliolate → leaflet, flowered →
flower, jugate → pairs of leaflets, ...). Where PO names the part of that organ ("calyx lobe") it
is the bearer and no container is needed.

## OWL

`has part some ((leaflet and part of some leaf) and has characteristic some (amount and has
measurement value some xsd:decimal[>= 3, <= 5] and has value unit some 'count unit'))`. Pairs
("3-jugate") count collections of two: `object aggregate and has member exactly 2 leaflet`.

## RDF

```turtle
<record> fb:bearer obo:PO_0020049 ; fb:container obo:PO_0025034 ; fb:quality obo:PATO_0000070 ;
    fb:low 3.0 ; fb:high 5.0 ; fb:unit obo:UO_0000189 ; fb:unitSymbol "count" .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `measurement_unit_without_value` (existing) | data model | a count has a number ("few", "many" are held: `measurement_value_not_numeric`) |
| `count_container_not_grounded` (annotator) | annotator | the container must be a PO or FLOPO class |
| shape `CountOfParts` | ShEx | quality amount, unit count, optional container |
| `count_is_a_whole_number` | SPARQL | bounds are whole and not negative |

## Related work

Counts are annotated in the EQ model with PATO's *has number of* (PATO:0001555) and a second
entity (Mungall et al. [1]: relational qualities "have the E2 column filled in"). Balhoff et al.
[3] report one count among their characters and model it with a cardinality. FLOPO uses the
amount of the counted part with a data range instead of a cardinality restriction, because
qualified cardinalities are outside OWL EL and the numbers must stay queryable as literals; the
same decision as for all measurements.

## Limits

"merous", "ranked" and "seriate" are not split: they name no single part. A count at a position
("veins 5-10 on each side of the midrib") is held (`count_per_position`).
