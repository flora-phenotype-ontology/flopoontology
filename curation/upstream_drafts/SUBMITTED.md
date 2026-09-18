# Upstream submissions

Curator decision 2026-09-18 (Robert Hoehndorf): D2 "open them", and B2 withdraw the pending PATO vernacular colour terms.

| title | repo | URL | date | status |
|---|---|---|---|---|
| Add 17 botanical morphology, indumentum and life span qualities (PATO:0104350-0104366; draft PR 1) | pato-ontology/pato | https://github.com/pato-ontology/pato/pull/618 | 2026-09-18 | open |
| Fix malformed definition of drooping (PATO:0002165) | pato-ontology/pato | https://github.com/pato-ontology/pato/pull/619 | 2026-09-18 | open |
| Fix sessile (sensu botany) definition and botanical synonym scopes (draft PR 2, without drooping) | pato-ontology/pato | https://github.com/pato-ontology/pato/pull/620 | 2026-09-18 | open |
| herbaceous (PATO:0002352) conflates die-back with non-woodiness (draft issue 3) | pato-ontology/pato | https://github.com/pato-ontology/pato/issues/621 | 2026-09-18 | open |
| Persistent organs vs non-deciduous (any body part) (PATO:0001732); fringed and falciform definitions (draft issue 4) | pato-ontology/pato | https://github.com/pato-ontology/pato/issues/622 | 2026-09-18 | open |
| Modelling questions: corolla throat, pseudobulb, tunics, gynostegium, lamina lobe, anatomical surface (draft issue 6) | Planteome/plant-ontology | https://github.com/Planteome/plant-ontology/issues/733 | 2026-09-18 | open |
| Add 14 anatomy classes used in flora descriptions, plus synonym-scope corrections (draft PR 5; provisional IDs PO:0026001-0026015, pending an ID range from PO) | Planteome/plant-ontology | https://github.com/Planteome/plant-ontology/pull/734 | 2026-09-18 | open |
| Add generic botanical colour terms (9 vernacular colours PATO:0104314-0104343, rose PATO:0001425 and cream PATO:0104031 changes) | pato-ontology/pato | https://github.com/pato-ontology/pato/pull/617 | 2026-07-15 opened; 2026-09-18 closed | withdrawn (B2): closed with a comment explaining the move to the ISCC-NBS backbone |

Notes:
- PR branches are on the fork: leechuck/pato (flopo-botanical-qualities, fix-drooping-definition, botanical-definition-synonym-fixes) and leechuck/plant-ontology (flora-anatomy-classes). Working clones are in scratchpad/upstream-20260918/.
- The PO PR has two commits. The second commit (tree crown, plus plant/plants synonyms on whole plant) is optional.
- Local files still carry the withdrawn colour IDs: config/botanical_colour_id_registry.tsv (status new_pato_generic, read by tools/build_botanical_colour_terms.py and tests) and curation/pato_botanical_colour_terms.obo. They were left unchanged for the ISCC-NBS backbone migration.
