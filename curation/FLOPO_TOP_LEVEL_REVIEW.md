# FLOPO top-level and local-extension review

Date: 2026-07-15

This is a design proposal for review. It does **not** change `ontology/flopo.owl`, reserve any
identifier, or assert that FLOPO imports or is explicitly grounded in BFO. The design follows the
continuant/occurrent and quality/disposition distinctions of BFO 2020 and the domain/range guidance
of RO so that FLOPO does not create category-crossing axioms.

The machine-readable companion is
`curation/flopo_top_level_and_local_extension_proposals.tsv`. Its curator fields are blank.

## Recommendation in one sentence

Keep the FLOPO phenotype hierarchy bearer-centric, and expose **quality** and **biological process**
as separate support-vocabulary hierarchies rooted in PATO and GO rather than recreating their
branches as subclasses of `flora phenotype`.

## Ontological commitment

The released EQ pattern makes a FLOPO class apply to a material plant bearer through restrictions
such as `has_part some (leaf and RO:0000053 some red)`. FLOPO phenotype terms therefore must not be
declared subclasses of PATO characteristics, BFO dispositions, GO biological processes, or BFO
processes. The phenotype top level describes the kind of target involved while keeping the
phenotype class itself in the FLOPO hierarchy.

PATO:0000001 is labelled `characteristic` and has exact synonym `quality`. It already contains the
morphology, colour, texture, cardinality, disposition, relational, and process-characteristic
branches needed here. FLOPO should not duplicate them under a vague `phenotypic aspect` class.
Quality-oriented navigation is instead derived by querying the PATO ancestry of the characteristic
filler in each phenotype definition.

This matters most for processes. RO prevents a material entity/process parthood crossing. A plant
cannot `has_part` a process, and a process quality must inhere in a process. The earlier phrase
`plant bearer RO:0000056 some ...` was malformed shorthand: `plant bearer` is not a class IRI, and
there was no complete OWL axiom around the restriction.

The pattern consistent with FLOPO's existing outer `has part` definitions is this complete
Manchester-syntax axiom:

```text
Class: FLOPO:<process-phenotype>
EquivalentTo:
  BFO:0000051 some (
    <PO bearer class>
    and RO:0000056 some (
      <GO biological-process class>
      and RO:0000053 some <PATO process-characteristic class>
    )
  )
```

For example, a leaf phenotype involving increased photosynthetic rate would use:

```text
Class: FLOPO:<leaf-increased-photosynthetic-rate-phenotype>
EquivalentTo:
  BFO:0000051 some (
    PO:0025034
    and RO:0000056 some (
      GO:0015979
      and RO:0000053 some PATO:0000912
    )
  )
```

Read literally: an instance of the FLOPO class has some leaf part; that leaf participates in some
photosynthesis process; and that process has an increased-rate characteristic. RO:0000056 is thus
an object property inside an existential restriction whose subject is the leaf, not a predicate
written after the English words “plant bearer”. A whole-plant process phenotype substitutes its
appropriate PO bearer expression; no one literal `plant bearer` class is assumed.

RO:0000053 is `has characteristic`; unlike the narrower RO:0000086 `has quality`, it can relate a
process to a process characteristic. The former global guard used
`has_part some (owl:Thing and RO:0000053 some PATO:0001236) SubClassOf owl:Nothing`. Because FLOPO
declares `has_part` reflexive, that axiom also made every process with a process characteristic
impossible: the process is its own part. The implemented repair narrows the guard to the actual
plant bearer:

```text
BFO:0000051 some (
  PO:0025131
  and RO:0000053 some PATO:0001236
) SubClassOf owl:Nothing
```

Thus a plant anatomical bearer still cannot directly carry a process characteristic, while a GO
process can carry it inside the participation restriction. GO support is supplied through a pinned
module rather than by assuming that GO is already present in the release.

## Proposed hierarchy

```text
flora phenotype  [FLOPO:0000000]
├── plant continuant-target phenotype                 bearer facet
│   ├── plant anatomical entity phenotype
│   │   ├── whole plant phenotype                     [FLOPO:0000089]
│   │   ├── plant structure phenotype
│   │   ├── portion of plant substance phenotype      [FLOPO:0900047]
│   │   └── plant material aggregate phenotype
│   └── plant anatomical space phenotype
└── plant occurrent-target phenotype                  bearer facet
    └── plant process phenotype
```

The three supporting forests are adjacent to, not beneath, this hierarchy:

```text
entity vocabulary                      quality vocabulary
PO plant anatomical entity             PATO:0000001 characteristic (quality)
└── FLOPO-local entity extension       ├── PATO:0001241 physical object characteristic
                                        │   └── FLOPO-local quality extension
                                        └── PATO:0001236 process characteristic

process vocabulary
GO:0008150 biological_process
└── selected GO descendants
    └── FLOPO-local provisional process extension, only when GO lacks the concept
```

For example, `trifoliolate leaf phenotype` remains below the leaf-phenotype branch; its exact-three
cardinality quality is a PATO-descended filler. `stinging trichome phenotype` remains below the
trichome-phenotype branch; its stinging disposition is a PATO-descended filler. A UI can derive
“composition/cardinality” or “disposition” views from those fillers without asserting duplicate
phenotype parents. This also handles a climbing phenotype whose definition combines an
architectural characteristic with a relation to external support.

No new cross-vocabulary disjointness is proposed. Existing PATO disjointness between physical
object characteristics and process characteristics remains applicable and should be tested.

## Biological-process support

Add process support, but do not make GO a branch of FLOPO phenotypes. Build a pinned extracted GO
module containing every referenced `biological_process` term and the ancestors required to reach
GO:0008150. This keeps release inputs reviewable and avoids importing the whole of GO merely to
support a small process vocabulary.

The canonical process-phenotype pattern is:

```text
FLOPO:<process-phenotype> EquivalentTo
  BFO:0000051 some (
    <PO bearer>
    and RO:0000056 some (
      <GO:0008150 descendant>
      and RO:0000053 some <PATO:0001236 descendant>
    )
  )
```

The GO class says **which process** is involved; the PATO process characteristic says **how that
process differs**, for example increased rate, duration, or timing. A process alone may also be
sufficient when the annotation means presence/participation rather than an altered process
characteristic.

When GO lacks a required reusable process, a provisional class may use a FLOPO IRI while being
asserted under the closest GO process class. It must live in the support module, not under `flora
phenotype`; it needs a cited genus-differentia definition and explicit local/provisional metadata.
Broadly reusable processes should be requested upstream from GO. The terminology registry and
extractor will also need explicit `process` semantic-role and `GO` target-namespace support before
such terms can be normalized; the current registry has neither.

## Local support classes

FLOPO sometimes needs an anatomical entity or quality that upstream PO/PATO appropriately does not
coin. These support classes should be biologically parented directly under the closest imported
class and marked as FLOPO-local with editorial metadata. There should be no asserted biological
class named “FLOPO extension”: provenance is not an `is_a` differentia.

The first local set is:

| Local support class | Imported parent | Purpose |
|---|---|---|
| trifoliolate | PATO:0001555 `has number of` | supports an exact three-leaflet phenotype |
| bifoliolate | PATO:0001555 `has number of` | supports an exact two-leaflet phenotype |
| stinging | PATO:0001727 `disposition` | capacity to deliver an irritant on contact/breakage |
| foliage | PO:0025131 `plant anatomical entity` | distributed/time-indexed leaf collection |
| plant latex | PO:0025161 `portion of plant substance` | laticifer cytoplasmic fluid/exudate |

`foliage` is deliberately not a `PO:0025497 collective plant structure`, because that PO class
requires adjacent organs. Use BFO:0000115 `has member part`, whose inverse defines membership in a
material aggregate, rather than ordinary structural parthood. The proposed necessary conditions
are `has member part some leaf` and `has member part only leaf`; the existential avoids the
vacuously true empty case and the universal restriction prevents non-leaf members.

## Specific curator-directed repairs

### Trifoliolate and bifoliolate leaves

`FLOPO:0900067 leaf trifoliolate` already exists, but its sole parent is `leaf shape`. The intended
referent is correct; its placement and definition are not. Repair it in place by:

- removing the leaf-shape parent;
- placing it under `FLOPO:0000004 leaf phenotype`;
- defining it as a compound-leaf phenotype with exactly three ultimate leaflets;
- adding a qualified cardinality restriction and a local `trifoliolate` relational quality.

Create bifoliolate analogously with exactly two ultimate leaflets. These combinations belong in
FLOPO; PO need not multiply anatomical kinds for every leaflet count.

### Stinging trichome

Create a local `stinging` disposition and compose it with `PO:0000282 trichome` under
`FLOPO:0000355 trichome phenotype`. Do not make every stinging trichome a glandular trichome: the
glossary supports a hollow hair associated with a secreting gland, not PO's universal anatomical
differentia for a glandular trichome.

### Foliage

Create a local foliage entity plus a new foliage phenotype branch beneath material-aggregate
phenotype. The entity is the leaves borne by one plant or shoot system at a specified time,
considered collectively. The time qualification belongs in the definition because a deciduous
plant's foliage membership changes. Model its members with BFO:0000115 `has member part`, using
both existential and universal leaf restrictions; do not use adjacency or connectedness as a
differentia.

### Plant latex

Develop the existing `FLOPO:0900048--0900051` branch. Add a FLOPO-local `plant latex` entity under
`PO:0025161`; define it from laticifer literature and the field-recognition glossary. Do not place
it under plant sap, whose PO comment explicitly distinguishes latex, and do not require it to be
milky, white, or currently inside a laticifer after it has exuded.

### Whole-plant growth forms

Develop `FLOPO:0900032 whole plant growth form` rather than creating PO entities or a combinatorial
set of atomic PATO values. Existing arborescent, frutescent, lianescent, and herbaceous classes need
definitions and sense separation. In particular, climber is broader than woody liana, and bushy is
an architectural phenotype rather than an exact synonym of shrub.

## Obsoletion policy

The decision depends on referent stability, not edit size:

| Change | Action |
|---|---|
| spelling, grammar, citation, or clearer wording with the same referent | edit in place |
| wrong parent/axiom but the intended referent is unchanged | repair in place and document the change |
| existing IRI's text or logic denotes a materially different referent | obsolete and replace |
| exact replacement exists | add IRI-valued IAO:0100001 `term replaced by` |
| only an inexact alternative exists | add IRI-valued `oboInOwl:consider` |

For every obsolete term: prefix the label exactly with `obsolete `, add boolean
`owl:deprecated true`, retain the textual definition, remove every logical axiom and logical use,
and add replacement guidance. `IAO:0000231 has obsolescence reason` may point only to an OMO reason
individual; free-text diagnostics belong in an editor note.

The 154 botanical-pubescence classes are the first required obsolete-and-replace migration. Their
logical definitions currently use `PATO:0000455`, a puberty maturity quality, so the released IRI's
formal referent is not the intended botanical pilosity phenotype. New replacement classes use
`PATO:0001320`; the old classes become annotation-only obsolete terms with exact IRI-valued
replacement links. By contrast, fixing `leaf trifoliolate` from shape to cardinality preserves its
intended referent and does not require obsoletion.

## Migration and validation gates

Before any released OWL change:

1. Review and accept/reject each row in the companion TSV; mint IDs only after acceptance.
2. Classify every existing direct child of `flora phenotype` by imported PO/BFO target ancestry;
   leave genuinely ambiguous rows at the root for manual review.
3. Add the top-level parents without removing existing EQ equivalences; run ELK and a DL reasoner
   for the cardinality/union patterns that ELK cannot fully check.
4. Require no new unsatisfiable active class, no continuant/process parthood crossing, and no
   obsolete class with a logical axiom or logical incoming reference.
5. Verify exact-cardinality examples and counterexamples for bifoliolate/trifoliolate leaves.
6. Verify every process phenotype links its bearer with RO:0000056 to a GO process, uses
   RO:0000053 for any PATO process characteristic, and contains no material/process parthood.
7. Verify the pinned GO module contains every referenced process and an ancestry path to
   GO:0008150, while no GO or PATO support class is asserted below a FLOPO phenotype class.
8. Verify alternative-colour classes use `owl:unionOf`, while mixtures use an explicit component
   relation and are not subclasses of every component colour.
9. Verify every new definition has a resolvable source and every local support class has an
   imported biological parent plus explicit local provenance.
10. Regenerate `flopo.owl`, inferred and OBO artifacts from one source, then verify version IRI,
   version information, release date, catalog resolution, and byte-level reproducibility.

## Sources governing the design

- BFO 2020 official repository and hierarchy: https://github.com/BFO-ontology/BFO-2020
- RO process and participation relations: https://oborel.github.io/obo-relations/process-relations/
- RO/BFO relation alignment: https://oborel.github.io/obo-relations/ro-and-bfo/
- Gene Ontology structure and `biological_process`: https://www.geneontology.org/docs/ontology-documentation/
- OBO Foundry Principle 19, term stability: https://obofoundry.org/principles/fp-019-term-stability.html
