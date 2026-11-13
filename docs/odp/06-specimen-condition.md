# 06. Specimen condition

**Intent.** The statement holds of the specimen in a condition of preservation or treatment, not
of the living plant as such.
**Wording.** "black when dry", "drying brown", "in sicco", "red when fresh", "mucilaginous on
wetting".

## Annotation

```json
{"po_id": "PO_0025034", "pato_id": "PATO_0000014", "value_terms": ["FLOPO_0988011"],
 "specimen_condition": {"condition": "dried", "condition_text": "when dry", "start": 13, "end": 21}}
```

`condition` is `dried`, `fresh`, `moistened` or `preserved`. The cue words are in
`config/flora_context_words.tsv` (kind `specimen_condition`); "drying ..." in the source span is
read as `dried` even when the transcriber gave no qualifier.

## OWL

**None.** The annotation has no `phenotype_class_iri`, is not compiled into a taxon axiom and is
not compared for conflicts with other sources: "black when dry" must not classify the taxon
under "leaf black", nor contradict "leaves green".

## RDF

```turtle
<record> fb:bearer obo:PO_0025034 ; fb:quality obo:FLOPO_0988011 ;
    fb:specimenCondition "dried" ; fb:conditionText "when dry" .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `specimen_condition_text_not_verbatim` | data model | the cue stands at its offsets in the source |
| `specimen_condition_with_phenotype_class` | data model | no phenotype class is linked |
| shape `SpecimenCondition` | ShEx | the condition is one of four values; no `fb:phenotypeClass` |
| `specimen_condition_without_phenotype_class` | SPARQL | the same on the RDF |

## Related work

Not found as a pattern. Endara et al. [4] name temporal modifiers ("when old") as a modifier
type but do not model them, and do not treat conditions of the specimen. Darwin Core records the
preparation of a specimen (`dwc:preparations`), but as a property of a specimen record, not as
the scope of a character statement. The pattern here is local: an annotation-level qualifier
that removes the statement from classification.

## Limits

Measurements "when dry" are kept as records but left out of the merged range of the taxon. The
four conditions are a closed list; "when flattened" and "in the dry season" are not conditions of
the specimen and are not read.
