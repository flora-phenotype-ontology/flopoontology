# Replacing the provisional PATO bridges by released PATO terms

FLOPO requested 18 botanical qualities from PATO in 2026 (pato-ontology/pato#618, revised on
2026-10-01). While the request was open, FLOPO used provisional bridge classes beneath the
closest PATO parent: FLOPO:0985000–0985016 (`tools/build_flopo_botanical_extension_2.py`) and
FLOPO:0987000 biennial life span (`tools/build_flopo_growth_form_extension.py`). PATO released the
terms as PATO:0104350–0104367 in its 2026-10-01 release.

Since 2026-11-08 FLOPO pins that PATO release (`ont/quality.obo`, `config/pato_lexicon.tsv`) and:

- `config/flopo_pato_bridge_migration.tsv` records bridge → PATO identifier, release and provenance;
- `tools/migrate_pato_bridges.py` re-points every reference (the `rdf:resource` attributes of
  `ontology/flopo.owl`, the generated modules that use a bridge as a quality filler, and the
  combination, disjointness, normalization and rule tables); it never touches declarations;
- the two module builders read the same table and emit each migrated bridge as an obsolete shell:
  `owl:deprecated true`, label `obsolete …`, `IAO:0100001` → the PATO term, definition kept;
- the identifier registry re-derives the EQ signatures with the PATO qualities; class IRIs are
  unchanged (the same mechanism as the 2026-07 replacement of FLOPO:0980xxx values by PATO terms).

The PO bridges FLOPO:0985017–0985030 (corolla lip, corolla tube, haustorium, pinna, …) are not
affected: Planteome/plant-ontology#734 is still open. When PO assigns identifiers, add them to the
table (column `pato_id` holds any OBO identifier) and run the same steps:

```bash
.venv/bin/python tools/migrate_pato_bridges.py
.venv/bin/python tools/build_flopo_botanical_extension_2.py --date 2026-09-18
.venv/bin/python tools/update_flopo_botanical_extension_2_release.py --date <release>
.venv/bin/python tools/build_flopo_growth_form_extension.py --date 2026-09-18
.venv/bin/python tools/update_flopo_growth_form_release.py --date <release>
.venv/bin/python -m tools.build_flopo_flora_value_extension   # rules follow the mapping
# then the README release passes
```
