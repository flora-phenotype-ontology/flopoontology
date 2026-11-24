# 25. Comparison with an implied counterpart

**Intent.** A comparison whose second term the flora leaves out, because it is the same part at
the opposite place.
**Wording.** "leaf blades paler beneath", "lower surface paler", "the inner smaller", "the
lower glume narrower than the upper", "stem leaves smaller".

## Annotation

A side of the part, where PO has a class for each side:

```json
{"po_id": "PO_0000049", "pato_id": "PATO_0000328",
 "towards": {"target_term": "PO_0000050", "target_text": "beneath", "start": 18, "end": 25,
             "comparison_text": "paler", "implied": true}}
```

A member of a series, where the opposite member has no class of its own:

```json
{"po_id": "PO_0009066", "pato_id": "PATO_0000587", "bearer_context_qualities": ["FLOPO_0991378"],
 "towards": {"target_term": "PO_0009066", "target_text": "inner", "start": 15, "end": 20,
             "comparison_text": "smaller", "implied": true, "counterpart_position": "FLOPO_0991379"}}
```

The record is a relation to another part (pattern 09) with `implied: true`; `target_text` is the
place word, since the other part is not named. The opposite places are abaxial and adaxial;
inner and outer; upper and lower; basal and cauline. The part compared has its own position
(pattern 18). Where FLOPO names both positioned parts ('inner sepal', 'outer sepal'), they are
the bearer and the target, and `counterpart_position` is not needed.

| Source word | Quality |
|---|---|
| shorter, longer, narrower, broader, smaller, larger, thinner, thicker | as in pattern 09 |
| paler | low saturation PATO:0000328 |
| lighter, darker | high, low brightness PATO:0000665, PATO:0000327 |

## OWL

The expression below is the defining property of the class; the class itself is its phene,
`'flora phenotype' and 'phenotype of' some (...)` (pattern 00).

`has part some ('leaf lamina abaxial epidermis' and has characteristic some ('low saturation'
and towards some 'leaf lamina adaxial epidermis'))`;
`has part some (anther and has position some inner and has characteristic some ('decreased
size' and towards some anther))`. The position of the second term is not in the class
expression: `towards some (anther and has position some outer)` would be exact, and the classes
of FLOPO take a named class as the second term. The record has it (`fb:towardsPosition`).

## RDF

```turtle
<record> fb:bearer obo:PO_0009066 ; fb:bearerState obo:FLOPO_0991378 ; fb:quality obo:PATO_0000587 ;
    fb:towards obo:PO_0009066 ; fb:comparison "smaller" ;
    fb:towardsImplied true ; fb:towardsPosition obo:FLOPO_0991379 .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `counterpart_position_unknown` | data model | the position is a value of `config/bearer_positions.tsv`, and the target is implied |
| `counterpart_is_another_part` | data model | with a counterpart position, the target is the class of the bearer |
| shape `ImpliedCounterpart` | ShEx | a relation to another part, marked implied |
| `relation_target_is_not_the_bearer` (changed) | SPARQL | bearer and target may be the same class only with a counterpart position |
| `counterpart_position_differs_from_own` | SPARQL | the two positions differ |

## Related work

Gkoutos et al. [8]: floras give direct statements, and comparative ones are derived from them
(the same entity with values of the same attribute). Here the flora itself states the
comparison, between two parts of one plant, which is a relational quality in the EQ model [1].
The limit Balhoff et al. [3] name for pattern 09 holds here too: the class does not say that
both anthers are of the same flower. PATO has no relational class for colour comparisons;
"paler" is written with the value it compares by.

## Limits

Comparisons with a part named elsewhere in the description ("anthers shorter", meaning than the
filaments of the sentence before) stay unresolved, as do superlatives over three or more members
("the median longest"). Found by the second-model review of 2026-11-23 (94 of 3,114 sampled
statements; 16,213 held rows in the floras).
