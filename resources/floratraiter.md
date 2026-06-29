# FloraTraiter — rule-based NLP trait parsing

High-precision oracle for cross-checking LLM extractions.

- Wiley (Applications in Plant Sciences): https://bsapubs.onlinelibrary.wiley.com/doi/10.1002/aps3.11563
- bioRxiv: https://www.biorxiv.org/content/10.1101/2023.06.06.543883v1.full
- PubMed: https://pubmed.ncbi.nlm.nih.gov/38369975/

## Summary

Rule-based NLP to parse computable trait data from descriptive biodiversity literature, built by
programmers + botanists, customized for online floras and scanned literature. Uses rule-based
parsing over preexisting language models to break descriptions into parts of speech with an extended
botanical vocabulary, then processes biodiversity-specific structure: recognize taxon → identify
partial traits → map to taxa.

**Type I error rate <1%** (similar to prior NLP efforts) — high precision.

## Relevance

Used as a **high-precision oracle** in `verify/gates.py`: on traits both methods can extract, an LLM
assertion contradicting FloraTraiter is auto-flagged to the curation queue. Complements the
high-recall-but-stochastic LLM. Also prior art for taxon-then-trait mapping.
