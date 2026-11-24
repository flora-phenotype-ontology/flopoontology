# 19. Lower bound on the maximum

**Intent.** The flora says that the largest plants exceed a number, and not by how much.
**Wording.** "subshrubs to more than 1.5 m high", "tuber to at least 6 cm diam.", "petioles up
to 4 cm long or longer", "to over 2 m".

## Annotation

```json
{"po_id": "PO_0000003", "pato_id": "PATO_0000119",
 "maximum_at_least": {"value": 1.5, "unit": "m", "inclusive": false,
                      "cue_text": "to more than", "start": 10, "end": 22}}
```

"to" (or "up to", "reaching") followed by "more than", "over", "above" gives a strict bound, "at
least" an inclusive one; so does "or more", "or longer" after a number. The record has no value
range: `value_low` and `value_high` stay empty. A length in feet or inches is converted as in
pattern 02.

## OWL

The expression below is the defining property of the class; the class itself is its phene,
`'flora phenotype' and 'phenotype of' some (...)` (pattern 00).

None. "To more than 1.5 m" is not an upper bound (pattern 02) and not a lower bound on every
plant: a seedling of the taxon is smaller. It says that the tallest plants pass 1.5 m. A class
`height > 1.5 m` would be false of most plants of the taxon, and a class without a number would
say nothing. The record carries no phenotype class.

## RDF

```turtle
<record> fb:bearer obo:PO_0000003 ; fb:quality obo:PATO_0000119 ;
    fb:maxAtLeast 1.5 ; fb:maxAtLeastExclusive true ; fb:unit obo:UO_0000008 ; fb:unitSymbol "m" .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `maximum_at_least_cue_not_verbatim` | data model | the cue stands at its offsets in the source |
| `maximum_at_least_with_range` | data model | the record has no `value_low` or `value_high` |
| `maximum_at_least_with_phenotype_class` | data model | no phenotype class is linked |
| shape `LowerBoundOnTheMaximum` | ShEx | the bound, a UO unit, no range, no phenotype class |
| `maximum_at_least_has_no_range` | SPARQL | on the RDF |

## Related work

SDD [5] gives a measurement as statistical measures (`Min`, `Max`, `UMethLower`); a bound on
`Max` alone has no element there. Balhoff et al. [3] leave open-ended sizes as free text.

## Limits

"Rarely more than 3 feet" and "rarely less than 10 cm" give the usual bound with a rare
exception and stay unresolved (`upper_bound_cue_not_supported`). Found by the second-model
review of 2026-11-23 (41 of 3,114 sampled statements).
