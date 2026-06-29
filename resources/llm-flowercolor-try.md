# Expanding plant trait databases using an LLM: flower-color extraction → TRY

Scale precedent for the modern-sources phase (Flora of China at scale).

- bioRxiv: https://www.biorxiv.org/content/10.1101/2025.02.11.637746v1.full
  (PDF 403'd on automated fetch; summary below from the search abstract.)

## Summary

Large-scale text-extraction workflow using an LLM to transform Flora descriptions into structured
trait data. Applied to extract **flower color** from the **Flora of China**, normalizing free-text
color descriptions to a controlled vocabulary, and integrating the result into the **TRY Plant Trait
Database** — expanding it to **27,252 species**.

## Relevance

Demonstrates LLM trait extraction works at the tens-of-thousands-of-species scale and that
free-text trait values can be normalized to a controlled vocabulary and merged into an established
trait database (TRY). Directly supports Phase 10 (expand to WFO / Flora of China / FNA) and the
value-normalization design in the LinkML schema. FLOPO 2.0's EQ classes + curated DB are a
generalization of this single-trait case to the full PO×PATO space with provenance.
