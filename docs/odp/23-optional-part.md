# 23. Optional part

**Intent.** The part is present in some plants of the taxon and absent in others.
**Wording.** "with or without stipules", "stipules present or absent", "branches lenticellate
or not", "pedicels absent or to 0.5 mm", "stem leaves few or absent".

## Annotation

```json
{"po_id": "PO_0020041", "pato_id": "PATO_0000467", "negated": false,
 "presence_variable": {"cue_text": "with or without", "start": 7, "end": 22}}
```

The quality is *present* and the record is not negated; `presence_variable` keeps the words.
The "or" is the statement itself and is not an alternative of values (pattern 07). A measurement
in the same phrase ("or to 0.5 mm") is a statement of its own, about the plants that have the
part.

## OWL

The expression below is the defining property of the class; the class itself is its phene,
`'flora phenotype' and 'phenotype of' some (...)` (pattern 00).

None. `has part some stipule` holds of some plants of the taxon and its complement of the
others; their union holds of every plant and says nothing. The record carries no phenotype
class, so a taxon with "stipules present or absent" does not contradict a flora that says
"stipules absent" (the per-taxon check of `docs/phene-consistency.md`).

## RDF

```turtle
<record> fb:bearer obo:PO_0020041 ; fb:quality obo:PATO_0000467 ; fb:negated false ;
    fb:presence "variable" ; fb:presenceText "with or without" .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `presence_variable_cue_not_verbatim` | data model | the cue stands at its offsets in the source |
| `presence_variable_without_presence` | data model | the quality is present, and the record is not negated |
| `presence_variable_with_phenotype_class` | data model | no phenotype class is linked |
| shape `OptionalPart` | ShEx | present, "variable", no phenotype class |
| `variable_presence_without_phenotype_class` | SPARQL | on the RDF |

## Related work

Polymorphic characters are states of their own in character matrices ("0/1") and in SDD [5]
(several states scored, with a frequency modifier). Dahdul et al. [2] annotate a polymorphic
taxon with each state. FLOPO records one statement, because the flora makes one.

## Limits

A quality that is optional ("with or without long hairs", where the part is the corolla lobe
and hairy the value) is not read: only parts. Absence in one sex or stage ("absent in female
flowers") is pattern 12 or stays unresolved (`absence_in_some_members`). Found by the
second-model review of 2026-11-23 (14 of 3,114 sampled statements).
