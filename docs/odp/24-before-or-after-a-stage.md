# 24. Before or after a stage

**Intent.** The statement holds before, or after, a stage of development, not during it.
**Wording.** "pedicels nodding after anthesis", "leaves withering before flowering", "basal
leaves withered by flowering".

## Annotation

```json
{"po_id": "PO_0030112", "pato_id": "PATO_0002165",
 "developmental_stage_contexts": [{"stage_term": "PO_0007616", "temporal_relation": "present_after",
                                   "stage_text": "after anthesis", "start": 17, "end": 31}]}
```

The stage is read as in the stage pattern ("at anthesis", `docs/annotation-context-patterns.md`);
the word before it gives the relation: "after", "following" `present_after`; "before", "prior
to", "until" `present_before`. "By flowering" says that the state is reached no later than the
stage, so it holds during it: `present_during`.

## OWL

The expression below is the defining property of the class; the class itself is its phene,
`'flora phenotype' and 'phenotype of' some (...)` (pattern 00).

`has part some (pedicel and has characteristic some drooping) and 'present after developmental
stage' some 'flowering stage'`. The two relations are in the annotation vocabulary beside
`present during developmental stage`
(`http://phenomebrowser.net/flopo/annotation/present_after_developmental_stage`,
`..._before_...`). The relation is part of the class signature: "nodding after anthesis" and
"nodding at anthesis" are different classes, and neither is under the other.

## RDF

```turtle
<record> fb:bearer obo:PO_0030112 ; fb:quality obo:PATO_0002165 ;
    fb:stage obo:PO_0007616 ; fb:stageRelation "after" ; fb:stageText "after anthesis" .
```

`fb:stageRelation` is written only for "before" and "after".

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `developmental_stage_text_not_verbatim` (existing) | data model | the phrase stands at its offsets |
| `invalid_developmental_stage_context` (existing) | gate | the stage is a PO stage class |
| shape `BeforeOrAfterAStage` | ShEx | a stage, "before" or "after", the phrase |

## Related work

Endara et al. [4] list temporal modifiers among the modifiers of a character statement and keep
them outside their ontologies. PO's stage classes are processes; "before" and "after" are
Allen's interval relations between the time the state holds and the stage, which OWL class
expressions state with a property per relation, as here.

## Limits

A stage that PO does not have ("after dehiscence", "at maturity" of an organ) stays unresolved
(`developmental_stage_context`). "Flowers appearing before the leaves" relates two parts in
time and is not read. Found by the second-model review of 2026-11-23 (24 of 3,114 sampled
statements).
