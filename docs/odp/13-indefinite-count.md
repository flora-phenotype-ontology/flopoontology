# 13. Indefinite count

**Intent.** A count that the flora gives as a word, not as a number.
**Wording.** "seeds numerous", "stamens many", "leaves few", "few-flowered", "many-seeded",
"étamines nombreuses".

## Annotation

```json
{"po_id": "PO_0009046", "pato_id": "PATO_0000467", "bearer_container": "PO_0009049",
 "count_word": {"amount": "few", "count_text": "few-flowered", "start": 15, "end": 27}}
```

The counted part (flower) is stated as **present**, in the organ that has it (inflorescence) as
for any count (pattern 03). The word for how many is kept in `count_word` with its offsets and
one of three amounts: `few`, `several`, `many`. A compound word is split with the same reviewed
table as the numbered compounds (`config/flora_counted_parts.tsv`: flowered → flower, seeded →
seed, ...). The words are listed in `flopo2.ingest.ncvc_annotate.INDEFINITE_AMOUNTS`.

## OWL

`has part some (flower and part of some inflorescence)`: the presence only. "Few" and "many"
have no fixed number, and what counts as many differs from organ to organ and from flora to
flora; the word is not part of the class.

## RDF

```turtle
<record> fb:bearer obo:PO_0009046 ; fb:container obo:PO_0009049 ; fb:quality obo:PATO_0000467 ;
    fb:countWord "few" ; fb:countText "few-flowered" .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `count_word_text_not_verbatim` | data model | the word stands at its offsets in the source |
| `count_word_without_presence` | data model | the quality is present (PATO:0000467), not negated |
| `count_word_with_number` | data model | a record with a count word has no number |
| `count_word_not_in_source_span` (annotator) | annotator | no count word in the statement: the row is held |
| shape `IndefiniteCount` | ShEx | quality present, amount one of few, several, many, no bounds |
| `count_word_states_no_number` | SPARQL | the same on the RDF |

## Related work

PATO has *increased amount* (PATO:0000470) and *decreased amount* (PATO:0001997), which are
relative to a normal amount of the same entity, the reading of the model-organism phenotype
annotations (Mungall et al. [1]). A flora's "numerous" is not a deviation from a norm but a
coarse absolute count, so these classes are not used. Character matrices score such characters
as states of a count character ("stamens: few / many"), with thresholds set per matrix [3].

## Limits

"Several to many" and "few or none" stay with the alternatives. "Numerous" said of something
that is not counted ("numerous hairs" as a density) is not told apart from a count. Found by the
second-model review of 2026-11-14 (182 of 800 statements for which no pattern existed).
