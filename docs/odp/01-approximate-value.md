# 01. Approximate value

**Intent.** The flora says a value holds roughly, not exactly.
**Wording.** "± erect", "more or less glabrous", "suborbicular", "greenish".

## Annotation

```json
{"po_id": "PO_0009047", "pato_id": "PATO_0000622",
 "value_qualifier": "approximately", "modality_text": "±", "modality_start": 6, "modality_end": 7}
```

The value is the named value (erect); `value_qualifier` is one of `approximately`, `nearly`,
`almost`, `sub`. The cue is the mark or word of the source: "±", "+/-", "more or less", or the
whole word for "sub-" and for colour words such as "greenish".

## OWL

`has part some (stem and has characteristic some erect)`: the class of the named value. The
annotation is **not** used for a strict taxon axiom (`_strict` in `flopo2/owl/assertions.py`
requires `value_qualifier: exact`): "± erect" does not say that every stem is erect.

## RDF

```turtle
<record> a fb:TraitRecord ; fb:bearer obo:PO_0009047 ; fb:quality obo:PATO_0000622 ;
    fb:qualifier "approximately" .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `modality_cue_not_verbatim` (existing) | data model | the cue stands at its offsets in the source |
| shape `ApproximateValue` | ShEx | `fb:qualifier` is one of the four values |

## Related work

Endara et al. [4] give modifier ontologies for frequency, certainty, degree and coverage;
approximation of a state ("more or less") is not one of their four categories, and they exclude
modifiers that derive a state from a base state. The qualifier here is therefore a small local
vocabulary. No OWL pattern for approximate values was found; keeping the qualifier outside the
class expression follows the general practice of annotating, not axiomatising, modifiers.

## Limits

"± 5 mm" (a tolerance) is not read. A cue is used only when it stands directly before the value.
