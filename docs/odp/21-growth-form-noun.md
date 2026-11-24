# 21. Growth-form noun

**Intent.** The description names the plant by its growth form; the noun states the habit.
**Wording.** "Lianas to 12 m", "Vines woody", "Twining shrubs", "Bejucos", "Lianes".

## Annotation

```json
{"po_id": "PO_0000003", "pato_id": "PATO_0000140", "value_terms": ["FLOPO_0991412"]}
```

The bearer is the whole plant and the value is the habit: climbing FLOPO:0991108 ("climber",
"vine", "climbing shrub"), twining FLOPO:0991411, lianescent FLOPO:0991412 ("liana"), beside the
habits that were there (arborescent, frutescent, suffrutescent habit; "tree", "shrub",
"subshrub"). The readings are rules of `flopo2/ingest/ncvc_normalization.tsv` (Q04-Q14). A
measurement in the same phrase ("to 12 m") is a statement of its own.

## OWL

The expression below is the defining property of the class; the class itself is its phene,
`'flora phenotype' and 'phenotype of' some (...)` (pattern 00).

`has part some ('whole plant' and has characteristic some lianescent)`, the basic pattern.
Twining and lianescent are subclasses of climbing, so a liana is found among the climbers.

## RDF

```turtle
<record> fb:bearer obo:PO_0000003 ; fb:quality obo:FLOPO_0991412 .
```

## Rules

The rules of pattern 00. Until 2026-11-24 these nouns were held
(`flopo_phenotype_class_without_eq_signature`): they were mapped to classes of FLOPO that have
a label and no definition by part and quality ('whole plant climbing phenotype' FLOPO:0985031).

## Related work

Growth form is a character of the whole plant in every descriptive standard (SDD [5]; the
Raunkiaer life forms). The Plant Trait Ontology has "whole plant growth form" as an attribute
without values; PATO has no habit values, which is why they are FLOPO classes.

## Limits

'whole plant climbing phenotype' FLOPO:0985031 and its two subclasses keep their identifiers and
have no logical definition yet; the records are under the annotation class of the habit value.
"Vine" is read as climbing: floras use it for woody and herbaceous climbers alike. Found by the
second-model review of 2026-11-23 (43 of 3,114 sampled statements; 9,986 held rows).
