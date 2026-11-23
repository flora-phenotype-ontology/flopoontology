# 18. Position of the bearer

**Intent.** The statement holds of those parts that are in a stated position among the parts of
their kind: the basal leaves, the lateral umbels, the outer bracts.
**Wording.** "basal leaves spatulate", "cauline leaves linear", "the lateral umbels usually
sterile", "outer bracts ovate", "terminal leaflet larger".

## Annotation

```json
{"po_id": "PO_0025034", "pato_id": "PATO_0001937", "bearer_context_qualities": ["FLOPO_0991002"]}
```

The record is that of pattern 04: the position is one of the `bearer_context_qualities`. What
makes it a position is the value: one of the nine classes of `config/bearer_positions.tsv`.

| Position | Class | Words |
|---|---|---|
| basal | FLOPO:0991002 | basal, radical |
| cauline | FLOPO:0991117 | cauline |
| upper | FLOPO:0991376 | upper, uppermost |
| lower | FLOPO:0991377 | lower, lowermost, lowest |
| inner | FLOPO:0991378 | inner, innermost |
| outer | FLOPO:0991379 | outer, outermost |
| lateral | FLOPO:0991380 | lateral |
| median | FLOPO:0991381 | median, central, middle |
| terminal | PATO:0002476 | terminal |

The words and the bearers each may be said of are in `config/flora_context_words.tsv` (kind
`bearer_quality`).

## OWL

The expression below is the defining property of the class; the class itself is its phene,
`'flora phenotype' and 'phenotype of' some (...)` (pattern 00).

The position has a relation of its own, a sub-relation of `has characteristic`:

    'has position' SubPropertyOf 'has characteristic'          (FLOPO:0995004)

    'has part' some (leaf and 'has position' some basal and 'has characteristic' some spatulate)

`leaf and 'has position' some basal` is the part the statement is about; `'has characteristic'
some spatulate` is what is said of it. Before 2026-11-23 both were written with `has
characteristic`, and the class did not show which quality selects the part and which is
asserted.

**Named positioned parts.** FLOPO names the positioned parts that many taxa use:

    'basal leaf' EquivalentTo leaf and 'has position' some basal      (FLOPO:0996000)

43 classes in the release of 2026-11-23, those used by 100 taxa or more
(`config/flopo_positioned_parts.tsv`, identifiers FLOPO:0996000 to FLOPO:0996999): basal leaf,
upper leaf, lower leaf, lateral sepal, outer sepal, inner petal, terminal leaflet, outer
involucral bract, and so on. Where the Plant Ontology has the part, no class is added and the
release states the equivalence for the Plant Ontology class: cauline leaf (PO:0000013), lower
glume (PO:0006002), upper glume (PO:0006004), terminal bud (PO:0004713), lateral root
(PO:0020121).

The label of a named class is built from the labels of the ontologies ('lateral vascular bundle').
The words botanists use are its synonyms ("lateral vein", "lateral nerve"; "radical leaf" for
'basal leaf'; "outer phyllary" for 'outer involucral bract'), in the column `synonyms` of the
table, exact or related.

Because the names are equivalences, a reasoner treats an annotation written with the expression
and one written with the name as the same class. The 280 rarer combinations ("lowest bract",
"median pinna") stay expressions in the annotation class and need no name. Naming all of them
would mean nine positions for each of several hundred parts.

Since `has position` is a sub-relation of `has characteristic`, every such class is still found
under the FLOPO classes written with `has characteristic` ('leaf basal', FLOPO:0992663: a plant
that has basal leaves).

## RDF

```turtle
<record> fb:bearer obo:PO_0025034 ; fb:quality obo:PATO_0001937 ; fb:bearerState obo:FLOPO_0991002 .
```

The index does not distinguish position from state; the class of the value does. Where the
positioned part has a name, the record also carries it:

```turtle
<record> fb:positionedPart obo:FLOPO_0996000 .     # basal leaf
```

The website's trait search finds such records by the label and the synonyms of the named class.

## Rules

| Rule | Layer | Statement |
|---|---|---|
| rules of pattern 04 | data model, ShEx | the value is a PATO or FLOPO class and not the stated quality itself |
| `bearer_position_not_modelled` | review | the position word has no class ("axillary"), is not listed for the bearer, or two positions are joined ("the terminal and uppermost umbels") |
| `tests/test_position_pattern.py` | OWL | the named class and the expression are equivalent (ELK); a positioned part is found under the plain part |

`python -m flopo2.verify.apply_bearer_position` gives older records the position named before
the bearer in the source text. On 2026-11-23 it restored 32,760 positions and states in 3.7
million statements and set 6,819 to review.

## Related work

Post-composition of an anatomy term with a spatial modifier is the practice of Dahdul et al. [2]
and of the Phenoscape annotations, there with BSPO ("anterior region of"). The entity of an
entity-quality statement may itself be a class expression (Mungall et al. [1]). A relation that
separates the selecting quality from the asserted one was not found in the sources read.

## Limits

The class says that the taxon has **some** basal leaf that is spatulate, not that all its basal
leaves are; this is the reading of every pattern. A position is relative to the other parts of
the same plant ("upper" leaves), which OWL does not express: the value classes are defined in
words. "Axillary" has no value class. Positions on a part (its base, its apex, its margin) are
regions, not positions of the bearer: `docs/annotation-context-patterns.md`.
