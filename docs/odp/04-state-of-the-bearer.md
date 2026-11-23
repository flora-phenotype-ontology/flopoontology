# 04. State of the bearer

**Intent.** The statement holds of those bearers that are in a stated state.
**Wording.** "leaves pubescent when young", "male flowers", "sterile fronds". The position of a
bearer ("basal leaves", "terminal leaflet") is recorded in the same slot and is pattern 18.

## Annotation

```json
{"po_id": "PO_0009047", "pato_id": "PATO_0000455", "bearer_context_qualities": ["PATO_0000309"]}
```

The context quality inheres in the **same bearer**. It is a PATO quality (young PATO:0000309, mature, old,
male, female, fertile, sterile). The readings are in `config/flora_context_words.tsv` (kind `bearer_quality`),
each with the bearers it may be said of.

## OWL

The expression below is the defining property of the class; the class itself is its phene,
`'flora phenotype' and 'phenotype of' some (...)` (pattern 00).

`has part some (stem and has characteristic some young and has characteristic some pubescent)`.
The context quality is part of the class signature. A value that is a position is written with
`has position` instead ([pattern 18](18-position-of-the-bearer.md)).

## RDF

```turtle
<record> fb:bearer obo:PO_0009047 ; fb:quality obo:PATO_0000455 ; fb:bearerState obo:PATO_0000309 .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `invalid_bearer_context_quality`, `unknown_bearer_context_quality` | data model | a PATO class of the catalogue or a FLOPO class of the registry |
| `bearer_context_duplicates_primary_quality` (existing) | data model | not the stated quality itself |
| shape `BearerState` | ShEx | `fb:bearerState` is a PATO or FLOPO class |

## Related work

Dahdul et al. [2] describe post-composition for such cases: terms "can be joined by a relation
... to create a post-composed term". Endara et al. [4] list temporal modifiers ("when old")
among modifier types but leave them out of their ontologies. Stating the state as a second
quality of the bearer keeps it inside the EQ class expression.

## Limits

Where the state has no class or is not listed for the bearer, the record is set to review
(`bearer_position_not_modelled`, shared with pattern 18). Where the member is a part of another
organ in that state ("calyx of male flowers") use pattern 12.
