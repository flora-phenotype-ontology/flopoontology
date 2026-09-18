# DRAFT issue: Issue 6, PO: modelling questions that block further anatomy (rows 11, 12, 13, 18, 64, 133)

- Target repository: `Planteome/plant-ontology`
- Status: opened 2026-09-18 as https://github.com/Planteome/plant-ontology/issues/733 (curator decision D2). The submitted text was revised from the draft below; see SUBMITTED.md.
- Source: `scratchpad/qwen-concept-proposal-review-20260917/CURATOR_PACKET.md`; decisions recorded in `curation/botanical_concept_proposals.tsv` and `curation/curator_approvals.tsv`.

## Rows

| packet row | proposal | decision | label | parent | provisional FLOPO bridge |
|---|---|---|---|---|---|
| 11 | `PO-CAND:corolla_throat` | defer | corolla throat |  |  |
| 12 | `PO-CAND:pseudobulb` | defer | orchid pseudobulb |  |  |
| 13 | `PO-CAND:storage_shoot_tunic` | defer | storage shoot tunic |  |  |
| 18 | `PO-CAND:gynostegial_corona` | defer | gynostegial corona |  |  |
| 64 | `PO-CAND:plant_organ_lamina_lobe` | defer | plant organ lamina lobe |  |  |
| 133 | `SURFACE-CAND:plant_structure_surface` | defer | plant structure surface |  |  |

## Body

Six decisions are needed before FLOPO can propose more classes. (a) Corolla throat: is it the opening (an anatomical space) or the surrounding distal tube tissue? Flora descriptions use both. (b) Pseudobulb is a NARROW synonym of corm (PO:0025355), but corm is defined as a whole shoot system, whereas orchid pseudobulbs are swollen stem portions of one or more internodes. The synonym should go, and a parent should be chosen. (c) Bulb and corm tunics: should they be separate classes, and should each be a leaf base, a scale leaf or a collective phyllome structure? (d) Gynostegium, which is needed before a gynostegial corona can be defined. (e) Generic lamina lobe: the glossary rounded-lobe criterion conflicts with the one-quarter sinus threshold of phyllome lamina lobe (PO:0025514). (f) A generic anatomical *surface*, which is an immaterial boundary and therefore neither a plant structure (PO:0009011) nor a plant anatomical space (PO:0025117).
