# Graph-RAG / Ontology-grounded RAG / KARMA

Combining recognition + normalization in one retrieval-augmented LLM step. Basis of the
**combined extraction engine (A)**.

- OG-RAG (EMNLP 2025): https://aclanthology.org/2025.emnlp-main.1674/
- OntologyRAG overview: https://www.emergentmind.com/topics/ontologyrag
- Ontology-driven KG for GraphRAG: https://deepsense.ai/resource/ontology-driven-knowledge-graph-for-graphrag/
- LLM-empowered KG construction survey: https://arxiv.org/html/2510.20345v1
- KG-guided RAG: https://arxiv.org/pdf/2502.06864
- Ontology learning vs KG construction & RAG impact: https://arxiv.org/pdf/2511.05991

## Summary

**GraphRAG** builds a graph index with an LLM from source documents and pre-generates community
summaries; queries retrieve related subgraphs to ground generation.

**OG-RAG (Ontology-Grounded RAG)** integrates structured ontological knowledge (entities, relations,
constraints) into every stage of retrieval+generation for fact-centric output; strong in
biomedicine. **OntologyRAG** retrieves over ontology-guided KGs/entities rather than plain dense
embeddings, and "can nearly eliminate hallucinations" while supporting verifiable multi-hop
reasoning.

**Entity linking**: maps NL mentions to graph entities; LLM-assisted linkers (e.g. KG-Linker) work
without task-specific training. **KARMA**: multi-agent, schema-guided extraction with accurate
entity normalization and relation classification **within a fixed ontological boundary**.

For this project: engine A loads PO/PATO/TO (labels, synonyms, definitions, parthood/subclass edges)
into a graph + vector store; **one retrieval-augmented LLM pass both recognizes and grounds** the
(entity, quality, value) — fusing the two steps the user wanted combined. Caveat from the Asteraceae
study: *naive* RAG can answer wrong even when the info is retrievable, so retrieval quality and the
verification gates matter. Compared against engine B on the gold set.
