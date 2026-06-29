# ODK / ROBOT — OBO release tooling

Replaces the legacy Groovy + hand-run ELK scripts (`MakePlantPhenotypeOntology.groovy`,
`DeprecateDumbClasses.groovy`).

- ROBOT (BMC Bioinformatics 2019): https://link.springer.com/article/10.1186/s12859-019-3002-3
- ROBOT PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC6664714/
- ODK (arXiv): https://arxiv.org/pdf/2207.02056
- ROBOT tutorial (reason/report): https://oboacademy.github.io/obook/tutorial/robot-tutorial-2/

## Summary

**ODK (Ontology Development Kit)** — standardized, customizable, executable workflows packaged in a
Docker image. Release prep: artifact production (OWL/OBO/JSON/TTL) by merging source + imports +
templates, logical classification, version-IRI assignment, multiple serializations (base/full/
simplified), QC. Semantic versioning enforced.

**ROBOT** — automates ontology workflows. `robot reason` runs a reasoner (ELK) to ensure logical
coherency (no unsatisfiable classes) and absence of unintended equivalencies. `robot report` +
SPARQL anti-pattern queries + `robot verify` for QC (missing labels, license, IRI scheme).
`robot template` builds classes from TSV templates.

## Relevance / mapping to FLOPO 2.0

- `robot template` from DB rows → EQ-pattern classes (replaces `MakePlantPhenotypeOntology.groovy`).
- `robot reason --reasoner ELK` → unsatisfiable detection; any `owl:Nothing` subclass triggers
  obsolete-in-place + auto-blocklist (replaces `DeprecateDumbClasses.groovy`, but proactive).
- `robot report` + custom SPARQL anti-patterns in CI.
- ODK Makefile for dated versionIRIs, serializations, OBO Foundry conventions, CC0.
- ROBOT also produces SSSOM-adjacent mapping artifacts; SSSOM toolkit for TO/OBA alignment.
