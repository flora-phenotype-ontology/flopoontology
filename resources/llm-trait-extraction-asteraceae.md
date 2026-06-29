# LLMs can extract morphological data, but stochasticity makes automation hard (Australian Asteraceae)

The load-bearing reliability evidence. Mandates structured output + self-consistency + grounding
verification + human-in-the-loop.

- PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC12381580/

## Method

GPT-4o (Omni) via API extracted **51 morphological characters** from **1,121 taxonomic descriptions**.
Prompt = description + instruction + character list. Manually cropped descriptions → Tesseract OCR →
cleaned text → ChatGPT. **No RAG, no ontology grounding.** Output as markdown tables; min/max as
separate entries; categorical with examples. Post-hoc harmonization in OpenRefine.

## Accuracy

- **Overall error 5.8%** (2,921 data cells from 109 descriptions).
- Error types: wrong trait 53.5%, missing 16.0%, false 12.5%, partial 9.0%, **hallucinated 3.5%**,
  unit errors 2.0%, OCR 1.0%.
- By organ: **capitulum/bracts 13.6%** (highest — confusing involucral bracts / phyllaries /
  calycular bracts), cypsela/pappus 2.1% (lowest). Indumentum 8.7% (partial trichome lists).
  Numeric 7.2%, shapes 6.5%, colour 5.5%, **binary presence/absence 3.4%** (most reliable).

## Stochasticity (the key finding)

- GPT-4o vs GPT-4o, **identical reruns**: only 78.9% of data cells stable; **16.7% of cells had data
  in only one of two replicates**; 67% exact match.
- GPT-4o vs open-source OpenChat: only **38.4% reproducibility**; OpenChat skipped traits (40/109),
  merged min/max, inconsistent null tokens.
- Root cause: token-level sampling variability is *inherent*; temperature 0 is not bit-reproducible
  across versions/endpoints.

## Failure modes

Confusing anatomically-related parts; inconsistent formatting (HTML/LaTeX instead of markdown,
varying "null" capitalization); partial extraction (indumentum); OCR-propagated errors (± → +).

## Recommendations

Structured/JSON output + **schema validation**; **RAG or fine-tuning** to ground (their own naive
RAG got 2/4 queries wrong despite info being available); visual checking of a random sample;
caution flags for high-error organs; **human-in-the-loop** — "inherently probabilistic," unsuitable
for fully automated pipelines. Open models need even more manual cleaning.

## How this project responds

N=5 self-consistency voting (auto-accept ≥4/5; review 2–3; discard 1) — directly attacks the 16.7%
flip-rate, which we adopt as a **first-class release metric**. Source-span verbatim check kills most
of the 3.5% hallucination. Reverse-definition verifier LLM forced to discriminate confusable PO
siblings attacks the 13.6% bract/phyllary error. PO×PATO validity whitelist blocks nonsensical combos
before class creation. Human curation queue for flagged items.
