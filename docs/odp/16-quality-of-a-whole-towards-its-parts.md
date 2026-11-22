# 16. Quality of a whole towards its parts

**Intent.** The flora names a part, but what it says is true of the structure that carries the
parts, or of the parts taken together. No single leaf is alternate; no single sepal is connate.
**Wording.** arrangement on an axis: "leaves alternate", "leaves opposite and decussate",
"leaflets opposite", "flowers secund", "leaves crowded"; relation among the members of a whorl:
"sepals connate", "petals free", "stamens unequal", "stamens didynamous", "petals imbricate".

## Definition

A *quality of a whole towards its parts* is a quality that inheres in a structure by virtue of
how its parts of one kind are placed on it or stand to one another, and that cannot be stated of
any one of those parts alone. The structure is the bearer; the kind of part is the second entity
of the quality (RO:0002503 *towards*).

Two kinds are used.

* **Arrangement.** The bearer is the axis; the parts are what the axis bears at its nodes.
  Ellis et al. [9], character 2: "Leaf Arrangement - The placement of adjacent leaves on the
  nodes of the axis"; 2.1 "Alternate - ... with one leaf per node"; 2.3 "Opposite - Leaves occur
  in opposed pairs that arise from the same node along the axis"; 2.4 "Whorled - Three or more
  leaves are borne at each node".
* **Set.** The bearer is the whorl (calyx, corolla, perianth, androecium, gynoecium, involucre);
  the parts are its members. The FLOPO value classes already say so in their definitions:
  *unequal* (FLOPO:0991101) is "a size quality inhering in a set of structures of the same kind
  by virtue of its members differing from one another in size"; *connate* (FLOPO:0991067) is
  fusion "with other structures of the same kind".

## Relations

| Relation | Definition | Axioms and use here |
|---|---|---|
| has part BFO:0000051 | a core relation between a whole and its part | the plant has the carrier as a part; transitive |
| has characteristic RO:0000053 | a relation between an independent continuant (the bearer) and a specifically dependent continuant (the characteristic), in which the characteristic inheres in the bearer | the carrier bears the quality; the stated part does not |
| towards RO:0002503 | relation binding a relational quality to the additional entity on which the quality depends [1] | the target is the kind of part the flora names; the phenotype holds of a carrier that has parts of this kind |
| `fb:carrier` (RDF of the atlas index) | A relation between a trait record and the class of structure that bears the stated quality with respect to the stated part: the axis on which the parts are arranged, or the whorl whose members are related to one another. | at most one per record; a PO or FLOPO class; never the record's `fb:bearer`; fixed by the part and the value (`flopo2.owl.carrier.expected`) |
| `fb:carrierKind` (RDF of the atlas index) | The way in which the carrier's quality depends on the stated parts: `arrangement`, the placement of the parts on the axis that bears them, or `set`, a relation among the like members of a whorl. | exactly one where `fb:carrier` is given |

The arrangement values and the counts that define them (*has number of parts per node*
FLOPO:0995001: alternate 1, opposite 2, whorled 3 or more) are in
[pattern 17](17-value-defined-by-a-measure.md). With the axis as bearer these counts are true of
the bearer; with the leaf as bearer they were true of nothing.

## Annotation

```json
{"po_id": "PO_0025034", "pato_id": "PATO_0001932",
 "carrier": {"carrier_term": "PO_0025029", "kind": "arrangement"}}
```

The record keeps the part the flora names (`po_id`, with its offsets): that is what the text
says. The slot `carrier` names the structure that has the quality. It is derived from the part
and the value by two tables (`flopo2.owl.carrier`) and is never read from the source, since
floras do not write "axis" or "calyx" here.

| Part named by the flora | Carrier | Kind |
|---|---|---|
| leaf, vascular leaf, branch | shoot axis PO:0025029 | arrangement |
| leaflet, pinna | leaf rachis PO:0020055 | arrangement |
| flower, bract, spikelet | inflorescence axis PO:0020122 | arrangement |
| sepal | calyx PO:0009060 | set |
| petal | corolla PO:0009059 | set |
| tepal | perianth PO:0009058 | set |
| stamen, filament, anther | androecium PO:0009061 | set |
| carpel, style | gynoecium PO:0009062 | set |
| involucral bract | involucre PO:0009100 | set |

| Kind | Values |
|---|---|
| arrangement | alternate placement PATO:0001932, opposite PATO:0001933, whorled PATO:0001951, distichous PATO:0001952, decussate PATO:0001953, spirally arranged FLOPO:0991114, secund FLOPO:0991146, crowded PATO:0000619, distant FLOPO:0991189, approximate FLOPO:0991190, imbricate FLOPO:0991063 |
| set | connate FLOPO:0991067, free FLOPO:0991068, unequal FLOPO:0991101, equal FLOPO:0991102, didynamous FLOPO:0991167, diadelphous FLOPO:0991259, imbricate FLOPO:0991063, valvate FLOPO:0991083 |

A part that is in neither table keeps the plain pattern 00. So does a record with a number, a
negation, alternatives, a named other part ("stamens opposite the petals" is pattern 09), a
region, a container or a qualified whole.

## OWL

The expression below is the defining property of the class; the class itself is its phene,
`'flora phenotype' and 'phenotype of' some (...)` (pattern 00).

`'has part' some ('shoot axis' and 'has characteristic' some ('alternate placement' and towards
some leaf))`

`'has part' some (calyx and 'has characteristic' some (connate and towards some sepal))`

This is the relational quality of the EQ model [1] with the roles of pattern 09 turned round:
there the stated part bears the quality and another part is the target; here the whole bears it
and the stated part is the target. A state of the stated part stays with the part: "young leaves
opposite" is `... towards some (leaf and 'has characteristic' some young)`. The carrier is part
of the class signature, so the class of "leaves alternate" changes when the slot is added.

The form follows the review [8]: the phenotype is `has part some (E and has characteristic some
Q)` with E the entity in which the quality inheres, and a second entity enters through a
relational quality. With the leaf as E, "leaf alternate" was classified under "leaf phenotype"
beside "leaf lanceolate", and a plant with leaves in whorls of three had three "whorled" leaves.

## RDF

```turtle
<record> fb:bearer obo:PO_0025034 ; fb:quality obo:PATO_0001932 ;
    fb:carrier obo:PO_0025029 ; fb:carrierKind "arrangement" ; fb:text "Leaves alternate" .
```

`fb:bearer` stays the stated part, so that a search for leaf traits still finds the record.

## Named FLOPO classes

The 50 named FLOPO classes of a part and a value of the two tables ("leaf alternate placement"
FLOPO:0001032, "leaflet opposite", "sepal connate" ...) are defined in the same form
(`tools/update_flopo_carrier_release.py`, module `ontology/flopo-carrier-migration.ttl`). Each
keeps its identifier and label, gets a text definition that names the carrier ("A flora
phenotype in which a shoot axis bears its leaves in an alternate arrangement.") and is placed
under the phenotype class of the carrier ("shoot axis phenotype"), no longer under "leaf
phenotype". The identifier registry still files the class under the part the flora names and
the value (`EQ|PO_0025034|PATO_0001932`), so an annotation of "leaves alternate" finds it as
before. An annotation class of the new form is equivalent to the named class; one of the old
form (a record that was not converted, see Limits) is not.

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `carrier_does_not_follow_from_part_and_value` | data model | the carrier and its kind are those of the two tables |
| `carrier_is_the_part` | data model | the carrier is not the stated part |
| `carrier_with_number_negation_or_relation` | data model | no number, no negation, no other target |
| `unknown_carrier_kind` | data model | arrangement or set |
| shape `QualityOfWholeTowardsParts` | ShEx | a carrier of PO or FLOPO, a kind, not negated, no `fb:towards`, no number |
| `carrier_is_not_the_bearer` | SPARQL | on the RDF |

Existing records get the slot from `python -m flopo2.verify.apply_carrier` (counts only unless
`--write-suffix` is given); new records get it in the annotator.

## Related work

Ellis et al. [9] place leaf arrangement on the nodes of the axis and score it once per shoot.
PATO files *alternate placement* and *whorled* under spatial pattern but *opposite* and
*distichous* under position, and none of the four definitions names the bearer. The Plant Trait
Ontology has *phyllotaxy* (TO:0006014) as a trait of the shoot system. Mungall et al. [1] and
Dahdul et al. [2] give the relational quality with *towards*; a quality of a whole *towards its
own parts* was not found in the sources read (the search of 2026-11-20, 38 papers, is in
`local-corpora/trait-vision-lit/9-arrangement-bearer/`). Collections as bearers are discussed by
Rector et al. (Granularity, scale and collectivity, *Artificial Intelligence in Medicine* 2006;
38:171-190) and for phenotypes by Alghamdi et al. (2023, cardinality phenotypes); they fit
"leaves in a rosette" and are not used here.

## Limits

* Alternatives ("leaves opposite or alternate") keep pattern 00/07 until the union is written
  inside the relational quality.
* "Stamens free" without a named other part is read as free from one another. Where the flora
  means free from the corolla, the reading is wrong; such records are not told apart.
* Rosulate, tufted and fascicled parts (a group at one place) are not moved: their bearer is the
  group (PO:0025022 collective leaf structure), which is a separate change.
* Rows (uniseriate, biseriate) are left: the FLOPO classes are already defined on the whole
  ("the bearer's members ... arranged in two rows").
* Dimorphic leaves, heterostyly and the sexual system are traits of the plant, not of a whorl.
