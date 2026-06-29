# ETC / CharaParser / OTO

Prior art for semantic markup of taxonomic descriptions + expert term curation UX.

- ETC (BMC Bioinformatics 2016): https://bmcbioinformatics.biomedcentral.com/articles/10.1186/s12859-016-1352-7
- ETC PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC5114841/
- OTO (Ontology Term Organizer): https://pmc.ncbi.nlm.nih.gov/articles/PMC4339750/
- Biosemantic Research Group: https://infosci.arizona.edu/biosemantic-research-group

## Summary

**CharaParser** semi-automatically extracts character information from taxonomic descriptions,
involving biologists in categorizing domain terms; produces machine-readable XML markup organized
by an input term ontology. Named in the 2016 FLOPO paper as future work.

**Explorer of Taxon Concepts (ETC)** toolkit: Text Capture (CharaParser), Ontology Building, Matrix
Generation, Key Generation, Taxonomy Comparison — usable as a pipeline.

**OTO (Ontology Term Organizer)**: CharaParser extracts domain terms → uploaded to OTO where experts
review and categorize them.

## Relevance

Validates the design of: (1) producing a character matrix from descriptions (our
`mv_species_trait_matrix`), and (2) a human term-organization/curation step (our curation queue,
possibly CurateGPT). CharaParser's grammar could be an additional rule-based cross-check alongside
FloraTraiter.
