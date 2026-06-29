# Planteome Plant Trait Ontology (TO) & Ontology of Biological Attributes (OBA)

SSSOM alignment targets for FLOPO 2.0.

- Planteome (NAR 2018): https://academic.oup.com/nar/article/46/D1/D1168/4653531
- Planteome PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC5753347/
- OBA (Mammalian Genome 2023): https://link.springer.com/article/10.1007/s00335-023-09992-1
- Ontologies for FAIR plant research: https://arxiv.org/pdf/2309.07129

## Summary

**Plant Trait Ontology (TO)** — Planteome reference ontology of phenotypic traits in plants,
species-neutral. Many TO terms follow the **EQ pattern**, drawing entities from PO/GO/ChEBI and
qualities from PATO to give pre-composed trait definitions that logically connect TO to other
ontologies. Example annotation: taxon (maize NCBITaxon:381124), PO structure (leaf PO:0009025),
TO trait (leaf color TO:0000299), PATO quality (green PATO:0000320).

**OBA (Ontology of Biological Attributes)** — computable traits for the life sciences; EQ-precomposed
biological attributes.

## Relevance

TO and OBA are the standard EQ-precomposed trait ontologies. FLOPO 2.0 generates **SSSOM mappings**
to both (Phase 8) so FLOPO traits interoperate with Planteome/TO annotations and OBA attributes. The
LinkML schema includes an optional `trait`→TO slot, so an extracted (PO, PATO) can be linked to the
corresponding TO trait where one exists.
