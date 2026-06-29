# OntoGPT / SPIRES + OAK

Schema-driven, ontology-grounded LLM extraction. Basis of the **two-step extraction engine (B)**.

- OntoGPT repo: https://github.com/monarch-initiative/ontogpt
- SPIRES paper (Bioinformatics 2024): https://academic.oup.com/bioinformatics/article/40/3/btae104/7612230
- SPIRES PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC10924283/
- OAK + LLMs how-to: https://incatools.github.io/ontology-access-kit/howtos/use-llms.html
- PyPI: https://pypi.org/project/ontogpt/
- CurateGPT (companion biocuration tool): https://arxiv.org/pdf/2411.00046

## Summary

**OntoGPT** is a Python package extracting structured information from text via LLMs, instruction
prompts, and **ontology-based grounding**. CLI + simple web app.

**SPIRES** (Structured Prompt Interrogation and Recursive Extraction of Semantics): zero-shot
extraction that returns data conforming to a **LinkML schema**, recursively interrogating the LLM
to match the schema. Uses LinkML static + dynamic value sets. Grounding/normalization via the
**Ontology Access Kit (OAK/oaklib)**, working over OBO-format ontologies.

Relevance: OAK ships adapters (`sqlite:obo:po`, `sqlite:obo:pato`, `sqlite:obo:uo`, TO) with synonym
+ embedding search — directly addresses the old shallow exact-match dictionary problem. SPIRES gives
schema-validated structured output with retry/repair and multi-model backends. Part of the Monarch
Initiative ecosystem. **CurateGPT** is the companion human-in-the-loop curation tool.

For this project: engine B = SPIRES extract → OAK ground (two steps). Compared on the gold set
against engine A (Graph-RAG). The same LinkML schema (`schema/flopo_trait.yaml`) drives both
extraction and the DB DDL.
