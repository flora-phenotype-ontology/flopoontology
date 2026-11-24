# 22. Part present at a place

**Intent.** A word or phrase states that a part is present, and where.
**Wording.** "stems rooting at the nodes", "rooting nodally".

## Annotation

```json
{"po_id": "PO_0000042", "pato_id": "PATO_0000467", "bearer_container": "PO_0020141"}
```

A reviewed rule of kind `entity_presence` gives the part (shoot-borne root) and, in its column
`container_id`, the place (stem node). The record is a presence (pattern 15, the positive case)
of the part within the place.

## OWL

The expression below is the defining property of the class; the class itself is its phene,
`'flora phenotype' and 'phenotype of' some (...)` (pattern 00).

`has part some ('shoot-borne root' and part of some 'stem node')`.

## RDF

```turtle
<record> fb:bearer obo:PO_0000042 ; fb:quality obo:PATO_0000467 ; fb:container obo:PO_0020141 .
```

## Rules

The rules of a part within another (pattern 03) and of presence (pattern 15). The place comes
from a reviewed rule only; it is not read from free text.

## Related work

Presence of a part is `has part some E` in the EQ model of Gkoutos et al. [8]; the place is the
`part of` qualification that pattern 03 uses for "seeds per fruit". A root at a node is located
at the node, and PO states shoot-borne roots as parts of the shoot system, so parthood is true
here; for a place that is not a whole of the part, use pattern 14.

## Limits

One rule per wording. "Ribs prolonged into a tooth", "each tooth tipped with an awl-like leaf",
"base covered by old sheaths" have the same construction and are still unresolved: they need a
reader that finds the part and the place in the sentence. Found by the second-model review of
2026-11-23 (31 of 3,114 sampled statements).
