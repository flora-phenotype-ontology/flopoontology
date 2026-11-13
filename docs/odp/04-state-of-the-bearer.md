# 04. State or series position of the bearer

**Intent.** The statement holds of those bearers that are in a stated state, or of one member of
a series.
**Wording.** "leaves pubescent when young", "male flowers", "sterile fronds"; since 2026-11-13
"basal leaves", "cauline leaves", "terminal leaflet".

## Annotation

```json
{"po_id": "PO_0025034", "pato_id": "PATO_0000453", "bearer_context_qualities": ["FLOPO_0991002"]}
```

The context quality inheres in the **same bearer**. It is a PATO quality (young, mature, old,
male, female, fertile, sterile, terminal) or a reviewed FLOPO value (basal FLOPO:0991002, cauline
FLOPO:0991117). The readings are in `config/flora_context_words.tsv` (kind `bearer_quality`),
each with the bearers it may be said of.

## OWL

`has part some (leaf and has characteristic some basal and has characteristic some glabrous)`.
The context quality is part of the class signature.

## RDF

```turtle
<record> fb:bearer obo:PO_0025034 ; fb:quality obo:PATO_0000453 ; fb:bearerState obo:FLOPO_0991002 .
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

upper, lower, inner, outer and lateral members have no value class yet (five FLOPO position
values are proposed for the next release); their rows stay unresolved. Where the member is a
part of another organ in that state ("calyx of male flowers") use pattern 12.
