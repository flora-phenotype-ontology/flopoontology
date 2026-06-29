# LLMs4OL / LLMs4Life — LLM ontology learning

Context for using LLMs to build/extend ontologies.

- LLMs4OL 2024 overview (arXiv): https://arxiv.org/pdf/2409.10146
- LLMs4OL 2025 overview: https://www.tib-op.org/ojs/index.php/ocp/article/view/2913
- LLMs4OL repo: https://github.com/HamedBabaei/LLMs4OL
- LLMs4Life (life sciences): https://arxiv.org/pdf/2412.02035
- LLM-driven ontology construction for enterprise KGs: https://arxiv.org/pdf/2602.01276

## Summary

**LLMs4OL** — Large Language Models for Ontology Learning challenge (1st at ISWC 2024, 2nd in 2025).
Four subtasks: Text2Onto (extract terms + types), Term Typing, Taxonomy Discovery (is-a),
Non-Taxonomic Relation Extraction. Fully automated via prompt engineering, no fine-tuning needed.
Ontology-learning primitives: corpus prep → terminology extraction → term typing → taxonomy
construction. **LLMs4Life** applies these to life-sciences ontology learning.

## Relevance

Background/justification for LLM-driven ontology extension. FLOPO 2.0 differs in that it does NOT
let the LLM freely invent taxonomy — classes are EQ-composed from grounded PO/PATO terms and the
hierarchy is computed by the ELK reasoner (deterministic). The LLM's job is term recognition +
grounding + relation (E,Q) extraction, not is-a invention. This keeps the ontology logically
coherent and the IRIs stable, while still benefiting from LLM recall.
