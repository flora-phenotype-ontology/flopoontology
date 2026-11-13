# 07. Alternatives ("or")

**Intent.** The flora gives two or more values, any of which a plant of the taxon may have.
**Wording.** primary: "white or blue"; secondary: "simple or branched", "entire or
toothed".

There are two patterns, and the second is used **only when the first cannot apply**.

## 07a. Alternatives of one attribute (primary)

```json
{"po_id": "PO_0009046", "pato_id": "PATO_0000014", "value_operator": "one_of",
 "value_terms": ["FLOPO_0988009", "FLOPO_0988007"]}
```

All values share an attribute below PATO's most general classes (quality, morphology, physical
object quality); that attribute is `pato_id`. This is a strong check on the grounding: a word
grounded to a class of another attribute does not join the union.

## 07b. Alternatives across attributes (secondary)

```json
{"po_id": "PO_0009047", "pato_id": "PATO_0000001", "value_operator": "one_of",
 "value_union_scope": "across_attributes",
 "value_terms": ["PATO_0001503", "PATO_0000402"],
 "value_operands": [{"operand_index": 0, "value": "PATO_0001503", "text": "simple", "start": 5, "end": 11},
                    {"operand_index": 1, "value": "PATO_0000402", "text": "branched", "start": 15, "end": 23}]}
```

Many true alternatives of a flora sit under different PATO attributes (simple is a complexity,
branched a branchiness; entire and toothed). The union is then stated under the root *quality*
and is allowed only when

1. the values share **no** attribute (else 07a must be used),
2. the connector between them in the source is a plain "or",
3. the **pair of values was reviewed** as alternatives of one trait in
   `config/flora_union_pairs.tsv` (decision `accept`).

A pair that is not in the table leaves the row unresolved with the reason
`alternatives_across_attributes_unreviewed:<value>|<value>`, so that new pairs come up for
review instead of being accepted silently. Rejected pairs record why ("'or not' read as
notched"; "'rust' is the colour of the hairs").

## OWL

`has part some (stem and has characteristic some (simple or branched))` for both patterns. A
union says nothing about either value alone, so ELK, which ignores unions, does not classify the
taxon under "stem simple"; a reasoner for full OWL DL keeps the union as it is (see
`docs/km-classification.md`).

## RDF

```turtle
<record> fb:bearer obo:PO_0009047 ; fb:quality obo:PATO_0001503, obo:PATO_0000402 ;
    fb:valueOperator "one_of" ; fb:attribute obo:PATO_0000001 ; fb:unionScope "across_attributes" .
```

Every alternative is an `fb:quality` of the record, so a search for either value finds it;
`fb:valueOperator "one_of"` says that they are alternatives.

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `logical_value_top_level_not_attribute` (existing) | gate, data model | 07a: `pato_id` is an attribute |
| `union_under_quality_root_without_scope` | data model | a union under the root must declare the secondary pattern |
| `across_attributes_not_a_union`, `across_attributes_top_level_not_quality` | data model | 07b is `one_of` with at least two values under PATO:0000001 |
| `across_attributes_but_values_share_attribute` | data model | 07b only when 07a cannot apply |
| `across_attributes_pair_not_reviewed` | data model | every pair of values is accepted in the pair table |
| `across_attributes_operands_do_not_match_values`, `across_attributes_without_or` | data model | one operand per value, with "or" between them in the source |
| shapes `AlternativesOfOneAttribute`, `AlternativesAcrossAttributes` | ShEx | at least two values; the attribute is below the root (07a) or the root with the scope mark (07b) |

## Related work

Balhoff et al. [3] wrote species descriptions as OWL class expressions and note that some
characters "significantly departed from the basic templates, usually by incorporating more
complicated intersection or union expressions"; they also define a phenotype class "not as
equivalent to the EQ description but rather as a subclass". Character matrices treat the same
situation as a polymorphic taxon (several states scored for one character), which presupposes
that the states belong to one character: the equivalent of 07a. No source was found for unions
across attributes; the reviewed pair table is the safeguard chosen here.

## Limits

07b reads two values only. A list of three or more across attributes, a continuum ("simple to
branched") and a degree cue on a value stay with the relation pattern or unresolved.
