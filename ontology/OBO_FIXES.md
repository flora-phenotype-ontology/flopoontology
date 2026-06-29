# FLOPO — OBO Foundry dashboard fixes (2026-06-29)

Applied by `python -m flopo2.owl.obo_fix` to `ontology/flopo.owl` (original backed up as
`ontology/flopo.pre-obofix.owl`). Every existing `FLOPO_*` IRI is preserved — only annotations were
added and dangling axioms removed from already-obsolete classes.

## Dashboard failures → fixes

| Dashboard check | Was | Fix |
|---|---|---|
| **Open: Missing ontology license** | ERROR | Added `dcterms:license` → CC0 (`creativecommons.org/publicdomain/zero/1.0/`) |
| **Versioning: Missing version IRI** | ERROR | Added `owl:versionIRI` → `…/obo/flopo/releases/2026-06-29/flopo.owl` + `owl:versionInfo` |
| **Maintenance: Missing version IRI** | ERROR | (same as above) |
| **ROBOT: missing_ontology_title** | ERROR | Added `dcterms:title` = "Flora Phenotype Ontology" |
| **ROBOT: missing_ontology_description** | ERROR | Added `dcterms:description` |
| **ROBOT: deprecated_boolean_datatype** (56) | ERROR | Normalized all `owl:deprecated` to `"true"^^xsd:boolean` (0 malformed remain) |
| **ROBOT: deprecated_class_reference** (9) | ERROR | Stripped logical axioms (equivalentClass/subClassOf) from obsolete classes; removed live→obsolete references. The 7 obsolete EQ classes (e.g. FLOPO:0002888 "bark direction") and the FLOPO:0900057↔0900058 cycle are resolved |
| **Textual Definitions: 23,221 missing** | WARN | Generated **23,096** `IAO:0000115` definitions for EQ/PHENO classes from their logical pattern (e.g. "A phenotype in which a(n) flower exhibits the quality of being red.") |
| **GitHub #11: root term** | issue | Added `IAO:0000700` (has_ontology_root_term) → `FLOPO_0000000` |

Verified post-fix: 24,200 IRIs intact; 23,113 equivalentClass definitions preserved; `flower red`
keeps its logical + new textual definition; 0 malformed deprecated booleans; obsolete classes carry
no logical axioms.

## Still TODO (cannot be done from this repo)

1. **Plurality of Users: Missing usages** — this lives in the OBO **registry** metadata
   (`OBOFoundry.github.io/ontology/flopo.md`), not in the OWL. Add a PR with, e.g.:

   ```yaml
   usages:
     - user: https://www.kaust.edu.sa/
       description: FLOPO is used to integrate plant trait data extracted from digitized Floras.
       examples:
         - url: http://aber-owl.net/ontology/FLOPO/
           description: Browsing and reasoning over FLOPO via AberOWL.
   ```

2. **Release/deploy** — the dashboard reads the PURL-resolved file. Deploy this updated
   `ontology/flopo.owl` to `http://purl.obolibrary.org/obo/flopo.owl` and **tag the release**
   (`v2026-06-29`) so the version IRI resolves (closes GitHub #7).

## GitHub issue dispositions (draft replies — not yet posted)

- **#11 Annotate root terms with `IAO:0000700`** → **fixed in this release** (added to `FLOPO_0000000`). Close on release.
- **#7 Tagging the published ontology version** → versionIRI + versionInfo added; create git tag `v2026-06-29` and a GitHub Release. Close on release.
- **#10 What is the status of FLOPO?** → reply: FLOPO is actively maintained again; a 2026 rebuild
  (LLM/Graph-RAG re-extraction from the Floras, curated trait database, OBO-compliant release, trait
  website) is in progress. This release fixes the OBO dashboard and adds textual definitions.
- **#3 Add synonyms (esp. Latin) for FLOPO terms** → enhancement; planned via carrying PO/PATO
  synonyms onto FLOPO classes during the Phase 8 rebuild. Latin synonyms need a sourced lexicon —
  tracked, not in this release.
