# Botanical terminology curator handoff

Date: 2026-07-15

This is a review package, not an ontology release. No proposal in this package has been added to
PO, PATO, FLOPO, the released OWL, or the terminology registry. Every `curator_decision` and
`curator_notes` field remains blank, and no curator ORCID has been attached to a machine proposal.

## Quantitative outcome

| Item | Result |
|---|---:|
| Registry rows in `config/botanical_terminology.tsv` | 9,089 |
| Registry rows with a redistributable textual definition | 38 (0.42%) |
| Current longest-match Saudi mentions | 20,409 |
| Current eligible ontology-normalized mentions | 11,750 (57.57%) |
| Current unresolved mentions | 8,659 |
| Current unresolved surfaces reviewed | 393/393 |
| Frozen 2026-07-14 unresolved surfaces reviewed | 436/436 |
| Evidence records and checksum-verified local files | 63/63 (59,481,218 bytes) |
| Concept/mapping/modeling proposals | 230 |
| Proposals with textual definitions | 131 |
| Proposals with definition evidence | 84 |
| Recommended new upstream atomic class proposals | 26 (10 PO, 16 PATO) |
| Recommended upstream atomic classes with a definition and evidence | 26/26 |

The measurement grammar independently recovers 1,841 mentions; terminology-or-measurement
coverage is 66.59% before a contextual PO bearer is bound.

## What causes the unresolved mentions

The original missing fraction should not be interpreted as a count of absent ontology classes.
Grouping the complete current decision table by recommended action gives:

| Cause/action | Mentions | Share of 8,659 |
|---|---:|---:|
| Defensible missing atomic PO/PATO class | 337 | 3.89% |
| Existing ontology term; registry, mapping, or ontology repair needed | 2,236 | 25.82% |
| Contextual composition, local FLOPO extension, or modeling pattern | 3,808 | 43.98% |
| Sense split, definition work, or unresolved revision | 1,649 | 19.04% |
| Context-specific non-phenotype noise | 629 | 7.26% |

Thus, adding all plausible-looking words as classes would address only a small part of the
normalization deficit and would introduce many false mappings. Contextual extraction remains the
main requirement.

## PO class proposals recommended for curator acceptance

| Proposed class | Direct parent | Defining relation or boundary |
|---|---|---|
| orchid labellum | petal (PO:0009032) | part of corolla; Orchidaceae scope; do not merge with non-orchid labella |
| corolla tube | collective organ part structure (PO:0025269) | part of fused corolla; composed of fused petal portions, not entire petals |
| parasitic plant haustorium | plant organ (PO:0009008) | no universal root or stem parent because both developmental origins occur |
| plant structure apex | plant structure (PO:0009011) | distal part of a plant structure; keep distinct from a point-like tip |
| plant structure base | plant structure (PO:0009011) | proximal part of a plant structure |
| trunk | stem (PO:0009047) | main stem of a tree; do not classify buttresses or prop roots as stem parts |
| frond | vascular leaf (PO:0009025) | documented broad use for fern, cycad, and palm leaves; no universal whole-plant parthood |
| pinna | cardinal organ part (PO:0025001) | primary division of a pinnately compound leaf; not always an ultimate leaflet |
| pinnule | cardinal organ part (PO:0025001) | secondary or higher-order division within a pinna and compound leaf |
| cyathium | inflorescence (PO:0009049) | has staminate flowers and an involucre; a pistillate flower is usual, not universal; not a cyme |

## PATO class proposals recommended for curator acceptance

| Proposed class | Direct parent | Recognition boundary |
|---|---|---|
| campanulate | shape (PATO:0000052) | inflated tubular base widening gradually toward distal limb or lobes |
| filiform | shape (PATO:0000052) | long, very slender, and terete, resembling a thread |
| hastate | shape (PATO:0000052) | flat bearer with approximately triangular basal lobes directed outward |
| reflexed | bent (PATO:0000617) | abruptly bent backward or abaxially downward; not smoothly recurved |
| winged | shape (PATO:0000052) | one or more thin flattened projecting extensions; not universally ridged |
| ascending | orientation (PATO:0000133) | directed gradually upward at an oblique angle |
| spreading | orientation (PATO:0000133) | directed outward from a principal axis; whole-plant habit must be composed in FLOPO |
| lanate | hairy (PATO:0000454) | long, somewhat matted and tangled trichomes; `woolly` is related, not unrestricted exact |
| sericeous | hairy (PATO:0000454) | long, soft, slender, appressed trichomes; `silky` is related, not unrestricted exact |
| annual life span | life span (PATO:0000050) | expected natural life span no more than one year |
| perennial life span | life span (PATO:0000050) | expected natural life span at least three years |
| dissected | shape (PATO:0000052) | incisions divide the bearer into visible segments; no invented depth threshold |
| clasping | position (PATO:0000140) | attached structure partially encloses an explicit axis; `amplexicaul` is narrower |
| mealy | texture (PATO:0000150) | coarse flour-like powder on the surface; do not erase the finer farina distinction |
| plicate | folded (PATO:0001910) | folded back and forth longitudinally like a fan; `pleated` is only related |
| floccose | hairy (PATO:0000454) | soft hair tufts that tend to rub off; `cottony` requires context |

## FLOPO-local branches recommended for review

- Repair `FLOPO:0900067 leaf trifoliolate` in place as a compound-leaf phenotype with exactly
  three ultimate leaflets; create the bifoliolate analogue with exactly two. Their supporting
  relational cardinality qualities are FLOPO-local subclasses of PATO:0001555. These combinations
  are not PO anatomy classes.
- Model stinging trichome beneath `FLOPO:0000355 trichome phenotype`, using PO:0000282 as bearer
  and a FLOPO-local stinging disposition beneath PATO:0001727. Do not universally classify the
  bearer as glandular or hollow.
- Create a FLOPO-local foliage entity beneath PO:0025131 and a foliage phenotype branch. Do not use
  PO:0025497, whose definition requires adjacent plant organs. The proposed membership pattern is
  BFO:0000115 `has member part some leaf` plus `has member part only leaf`, subject to review.
- Create a FLOPO-local plant-latex entity beneath PO:0025161 and develop the existing
  `FLOPO:0900048--0900051` branch. Literature defines latex as laticifer cytoplasmic fluid; it is
  distinct from PO:0025538 plant sap and is not universally milky or white.
- Develop whole-plant growth forms beneath `FLOPO:0900032`, including climbing, bushy, spreading,
  and related architectures. These are contextual phenotypes rather than new PO anatomical kinds
  or an unrestricted multiplication of atomic PATO values.

These proposals depend on the accompanying top-level design review. The revised design keeps
phenotype classes bearer-centric and separates continuant-target from process-target phenotypes.
It does not duplicate morphology, appearance, cardinality, disposition, or relational branches as
a `phenotypic aspect` facet: those are taken from the PATO characteristic hierarchy and used as
logical fillers. A separate pinned GO biological-process module supplies process targets. A plant
bearer participates in such a process; it does not have the process as a material part. Neither
PATO nor GO support classes become subclasses of `flora phenotype`.

## Proposals deliberately not ready for acceptance

- `nodding` has useful contrast evidence but not yet a sufficiently complete, source-backed
  recognition definition.
- Historical botanical prototypes or explicit no-single-prototype findings are now documented for
  `cream`, `crimson`, `scarlet`, `golden`, `lemon`, `mahogany`, `salmon`, `chestnut`, `chocolate`,
  `olive`, `rose`, and `straw`. The review proposal places unqualified true-colour names under open
  lexical umbrellas and preserves Saccardo, Ridgway, RHS, Wilson, and TCCA recognition rules in
  separate `sensu` subclasses. For example, unqualified `scarlet` maps to the umbrella while three
  source-specific scarlets retain their own prototypes. The generic umbrella is not closed to the
  currently known children; an optional separately named reviewed-set union is provided. `silvery`
  and much of `golden` remain appearance compositions rather than pure colour values.
- Compound colours remain compositional FLOPO phenotypes. Alternative colours use a genuine union;
  mixtures are linked to component colours and are not made subclasses of every component colour.

## Existing ontology/release repairs exposed by the audit

- 154 released FLOPO classes use puberty PATO:0000455 for botanical `pubescent`; the correct
  pilosity term is PATO:0001320. Because the formal referent changes materially, the proposed
  migration obsoletes each old class and creates an exact replacement instead of silently editing
  its logical definition. The review report has 154 provisional, unreserved replacement IDs; the
  release is unchanged.
- FLOPO:0980163 `three-angled` is incorrectly parented under `bent`; its intended meaning is a
  triangular transverse section.
- FLOPO:0980174 `golden` and FLOPO:0980342 `cottony` have label-paraphrase definitions.
- FLOPO:0980131 `rose-pink`, FLOPO:0980205 `pale rose-pink`, and FLOPO:0980366
  `purple-magenta` need explicit colour-composition semantics rather than conjunctive
  component-colour subsumption.
- PATO:0005010 `plumose` already has exact synonym `feathery`; a duplicate temporary FLOPO class
  should be migrated rather than retained.

## Review files

- `botanical_concept_proposals.tsv` contains all 230 evidence, mapping, modeling, and rejection
  proposals.
- `FLOPO_TOP_LEVEL_REVIEW.md` and `flopo_top_level_and_local_extension_proposals.tsv` contain the
  review-only top-level, local support-class, growth-form, foliage, latex, and obsoletion design.
- `botanical_colour_prototypes.tsv` records source-qualified recognition criteria and cautions for
  the botanical colour vocabulary.
- `BOTANICAL_COLOUR_SENSU_REVIEW.md` and `botanical_colour_sensu_proposals.tsv` separate generic
  annotation umbrellas from operational source-specific colour subclasses without minting IDs.
- `../scratchpad/botanical-terminology-current-2026-07-15-curator-decision-table.tsv` is the
  complete current 393-surface review table.
- `../scratchpad/botanical-terminology-baseline-2026-07-14/curator-decision-table.tsv` replays the
  same proposals against the frozen 436-surface baseline.
- `botanical_evidence.tsv` is the checksum-pinned evidence manifest.

The next authorized step is review of the top-level and local-extension design, followed by human
adjudication in the blank decision columns. Accepted rows can then receive ORCID
`0000-0001-8149-5890`, be materialized in a FLOPO extension for testing, and be separated into
focused PO and PATO pull requests. Compound and alternative colour phenotypes stay in FLOPO.
