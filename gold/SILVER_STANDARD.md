# FLOPO 2.0 Silver Standard

**`silver_standard.jsonl` is a Claude-generated SILVER standard — NOT an expert-verified gold
standard.** It bootstraps the evaluation harness so the extraction engines (Phase 5) can be
compared and tuned *before* a human-curated gold set exists. Treat it as a strong reference, not as
ground truth.

## What it is
- **400 flora text segments**, stratified across source (Flore du Gabon, Flora Malesiana, Flore
  d'Afrique Centrale, Kew African Flora) × organ group × language (FR/EN) — the same sample as
  `annotation_template.jsonl`.
- **2,501 entity-quality assertions** (~6.3 per segment), each grounded to a Plant Ontology entity
  (`po_id`) and a PATO quality (`pato_id`), with `negated`, optional `value_low/value_high/unit`,
  `modifier`, and a verbatim `source_text` span.

## How it was produced
- A 25-agent fan-out workflow (`flopo-silver-standard`), **model: Claude Sonnet 4.6**, each agent
  grounding 16 segments. Agents looked terms up by `grep` against `config/po_lexicon.tsv` (1,555 PO
  terms) and `config/pato_lexicon.tsv` (1,555 PATO terms), translating French organ/quality words to
  the English ontology labels before matching, and were instructed to **skip** rather than invent a
  term when no good id existed (precision over recall).
- Assembled and validated by `flopo2/eval/silver.py`.

## Validation results (deterministic gates, same as the extraction pipeline)
| Check | Result |
|---|---|
| Segments | 400 |
| Assertions | 2,501 |
| Invalid `po_id` (not in PO lexicon) | **0** |
| Invalid `pato_id` (not in PATO lexicon) | **0** |
| Missing `source_text` | 0 |
| `source_text` not verbatim in segment | 6 (0.24%) — flagged `source_verbatim:false`, kept |
| Assertions with a measurement (value/unit) | 908 |
| Negated assertions | 14 |
| Distinct PO entities used | 132 |
| Distinct PATO qualities used | 227 |

## Intended use & limitations
- **Use:** relative comparison and tuning of the Graph-RAG vs SPIRES+OAK engines and the model panel
  (per-language, per-trait-type) via `flopo2/eval/scoring.py`; prompt/threshold iteration; coverage
  sanity checks. Loadable directly with `flopo2.eval.gold.load_gold`.
- **Do not** treat as the locked, authoritative gold for release claims. It is model-generated, so it
  may share blind spots with the LLM engines under test (a silver standard is not an *independent*
  reference). Engines that merely imitate Sonnet will score deceptively well.
- **Recommended next step:** have a botanist verify/correct a stratified subset (e.g. 80–100
  segments) to create a true `gold_standard.jsonl`; use that as the locked test split and keep the
  silver set for development/iteration only.

## Provenance
Per-batch raw outputs are retained in `gold/silver_batches/out_batch_*.jsonl`; inputs in
`in_batch_*.jsonl`. Regenerate via the `flopo-silver-standard` workflow + `python -m flopo2.eval.silver`.
