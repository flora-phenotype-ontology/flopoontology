# Taxon recognition & normalization — GNparser, GNV, GBIF, WFO, IPNI, TNRS

The species side of the knowledge base. **Chosen stack: GNparser → World Flora Online + IPNI.**

- GNparser (BMC Bioinformatics 2017): https://bmcbioinformatics.biomedcentral.com/articles/10.1186/s12859-017-1663-3
- GNparser repo: https://github.com/gnames/gnparser
- GBIF species matching: https://www.gbif.org/tools/species-lookup ; https://training.gbif.org/en/data-use/species-matching
- WorldFlora R package (WFO backbone): https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7526431/
- Taxonomic Name Resolution Service (TNRS): https://www.academia.edu/2462667/
- pytaxon (Python over GNV): see GNV API

## Tools

- **GNparser** — parses a name-string (e.g. `Drosophila (Sophophora) melanogaster Meigen, 1830`)
  into semantic elements (genus, epithet, rank, authorship, year, annotations) and canonical forms.
  ~99% accuracy, ~30M names/hour/thread, handles hybrids/nested structures. MIT. CLI + web + REST API
  + library (Scala/Java/R/etc.). **Use for parsing/canonicalizing names before matching.**
- **Global Names Verifier (GNV) / gnverifier** — matches names against many data sources; `pytaxon`
  wraps the GNV API with fuzzy matching.
- **GBIF backbone** — species-match API → taxonKeys; broadest cross-domain interop (occurrence data).
- **World Flora Online (WFO)** — actively curated vascular-plant backbone; WorldFlora R package does
  exact + fuzzy matching. **Authoritative plant taxonomy.**
- **IPNI** — International Plant Names Index; nomenclatural IDs (the 2016 paper's stated linking
  target). Provides LSID URNs.
- **TNRS** — online standardization of plant names.

## Decision for FLOPO 2.0

`taxon/normalize.py`: recognize taxon mentions (FlorML nomenclature blocks give genus/species/author
directly; NER for free text) → **GNparser** parse/canonicalize → match to **WFO + IPNI** (exact +
fuzzy) → persist `taxon(wfo_id, ipni_id, accepted_name, authorship, rank, parent)`. Every
`trait_assertion` links to a normalized taxon, forming the species↔phenotype knowledge base. WFO+IPNI
chosen over GBIF for plant-native taxonomic fidelity; gnverifier remains an option for multi-source
cross-links later.
