# DRAFT pull request: PR 5, PO: 14 anatomy classes for flora description, plus synonym-scope corrections (rows 8, 9, 10, 14, 15, 16, 17, 62, 63, 66, 67, 68, 69, 70)

- Target repository: `Planteome/plant-ontology`
- Status: opened 2026-09-18 as https://github.com/Planteome/plant-ontology/pull/734 (curator decision D2). The submitted text was revised from the draft below; see SUBMITTED.md.
- Source: `scratchpad/qwen-concept-proposal-review-20260917/CURATOR_PACKET.md`; decisions recorded in `curation/botanical_concept_proposals.tsv` and `curation/curator_approvals.tsv`.

## Rows

| packet row | proposal | decision | label | parent | provisional FLOPO bridge |
|---|---|---|---|---|---|
| 8 | `PO-CAND:orchid_labellum` | accept | orchid labellum | PO:0009032 | FLOPO:0980978 (existing) |
| 9 | `PO-CAND:corolla_lip` | accept | corolla lip | PO:0025269 | FLOPO:0985017 |
| 10 | `PO-CAND:corolla_tube` | accept | corolla tube | PO:0025269 | FLOPO:0985018 |
| 14 | `PO-CAND:parasitic_plant_haustorium` | accept | parasitic plant haustorium | PO:0009008 | FLOPO:0985019 |
| 15 | `SURFACE-CAND:corona` | accept_with_revision | floral corona | PO:0025269 | FLOPO:0985020 |
| 16 | `PO-CAND:corolline_corona` | accept_with_revision | corolline corona | SURFACE-CAND:corona | FLOPO:0985021 |
| 17 | `PO-CAND:staminal_corona` | accept_with_revision | staminal corona | SURFACE-CAND:corona | FLOPO:0985022 |
| 62 | `PO-CAND:plant_structure_apex` | accept_with_revision | plant organ apex | PO:0025001 | FLOPO:0985023 |
| 63 | `PO-CAND:plant_structure_base` | accept_with_revision | plant organ base | PO:0025001 | FLOPO:0985024 |
| 66 | `PO-CAND:trunk` | accept_with_revision | trunk | PO:0009047 | FLOPO:0985025 |
| 67 | `PO-CAND:frond` | accept | frond | PO:0009025 | FLOPO:0985026 |
| 68 | `PO-CAND:pinna` | accept | pinna | PO:0025001 | FLOPO:0985027 |
| 69 | `PO-CAND:pinnule` | accept_with_revision | pinnule | PO:0025001 | FLOPO:0985028 |
| 70 | `PO-CAND:cyathium` | accept | cyathium | PO:0009049 | FLOPO:0985029 |
| 113 (optional) | `PO-CAND:tree_crown` | accept_with_revision | tree crown | PO:0009006 | FLOPO:0985030 |
| 59 (optional) | `MAP-CAND:whole_plant_words` | accept | whole plant (synonyms plant/plants) | PO:0000003 |  |

## Body

This PR adds classes for structures that flora treatments name routinely and that PO covers only through NARROW synonyms or not at all. Floral structures: orchid labellum (is_a petal PO:0009032, part_of corolla PO:0009059; Orchidaceae scope in the definition); corolla lip and corolla tube (is_a collective organ part structure PO:0025269, part_of fused corolla PO:0025581); an origin-neutral floral corona (is_a PO:0025269, part_of flower PO:0009046) with corolline and staminal subtypes whose corolla or androecium parthood holds only for that origin. Other organs: parasitic plant haustorium (is_a plant organ PO:0009008, replacing the obsolete haustorial root PO:0003004 without a root/stem restriction). Organ regions: generic plant organ apex and plant organ base (is_a cardinal organ part PO:0025001, as parents for phyllome apex/base and stem base). Stems and leaves: trunk (is_a stem PO:0009047); frond (is_a vascular leaf PO:0009025, covering fern, cycad and palm leaves); pinna and pinnule (is_a PO:0025001, part_of compound leaf PO:0020043; not under leaflet, which requires ultimate segments). Inflorescences: cyathium (is_a inflorescence PO:0009049, has_part staminate flower PO:0025600 and involucre PO:0009100). The synonym changes remove cyathium/cyathia from cyme inflorescence (PO:0030126), whose definition requires pedicellate flowers on paired axes. They also move pinna/pinnae/pinnule off leaflet (PO:0020049), and promote the NARROW synonyms trunk (on stem) and frond (on vascular leaf) to their new classes. Every class has a genus-differentia definition and cited glossary evidence. Parthood is asserted only where it holds universally, and the counterexamples considered are listed in the PR. Optional, lower-priority additions: tree crown (is_a shoot system PO:0009006, row 113) and the exact synonyms plant/plants on whole plant (PO:0000003, row 59).

## Migration note

FLOPO carries the provisional bridge classes listed above in `ontology/flopo-botanical-extension-2.ttl` (identifier block FLOPO:0985000-0985999). When the upstream ontology assigns identifiers, obsolete each bridge with `IAO:0100001` (term replaced by) pointing to the new PO/PATO term and update mappings; no PO or PATO identifier is minted locally.
