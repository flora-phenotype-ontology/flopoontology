# Phase 5 — model & strategy selection (pilot results)

All numbers are scored against the **Claude-generated silver standard** (`gold/silver_standard.jsonl`),
not human gold, so absolute values are a *floor*. Lenient = hierarchical PO/PATO ancestor-distance
matching (`flopo2/eval/hierarchy.py` over `ont/plant_ontology.obo` + `ont/quality.obo`).

## 1. Model panel — 100-segment slice (spires grounding, N=1, exact F1)

| Model | F1 | Prec | Rec | fr-F1 | en-F1 | Cost/100 |
|---|---|---|---|---|---|---|
| deepseek/deepseek-v3.2 | **0.450** | 0.605 | 0.358 | 0.497 | 0.372 | $0.033 |
| z-ai/glm-4.6 | 0.433 | 0.535 | 0.363 | 0.470 | 0.372 | $0.532 |
| openai/gpt-oss-120b | 0.337 | 0.450 | 0.270 | 0.368 | 0.283 | $0.039 |
| qwen/qwen3-32b | 0.322 | 0.419 | 0.261 | 0.339 | 0.293 | $0.035 |
| mistralai/mistral-small-3.2-24b-instruct | 0.307 | 0.386 | 0.254 | 0.313 | 0.296 | $0.015 |

DeepSeek-V3.2 wins on quality and is near-cheapest. French > English for every model. Note:
`mistralai/mistral-small` (no version) is **not a valid OpenRouter slug** — use
`mistralai/mistral-small-3.2-24b-instruct`.

## 2. DeepSeek grid — full 400 segments (grounding × self-consistency, lenient on)

| config | exF1 | lenF1 | lenP | lenR | halluc | cost |
|---|---|---|---|---|---|---|
| spires N=1 | 0.455 | **0.566** | 0.759 | 0.452 | 0.7% | $0.14 |
| spires N=3 | 0.460 | 0.563 | 0.772 | 0.443 | 0.6% | $0.41 |
| graphrag N=1 | 0.285 | 0.372 | 0.302 | 0.483 | 1.5% | $0.43 |

- **Deterministic (spires) grounding beats model-pick (graphrag) decisively** — graphrag over-grounds,
  wrecking precision (0.30 vs 0.76) and doubling hallucination, at 21× the calls.
- **Same-model N=3 self-consistency is a wash** (correlated errors); not worth 3× cost for bulk.

## 3. Cross-model ensemble — 150 segments (spires, lenient, one call/model/segment)

| strategy | exF1 | lenF1 | lenP | lenR | halluc |
|---|---|---|---|---|---|
| D solo | 0.464 | 0.577 | 0.779 | 0.458 | 0.6% |
| G solo | 0.479 | 0.597 | 0.725 | 0.508 | 0.3% |
| O solo | 0.377 | 0.555 | 0.771 | 0.434 | 1.4% |
| **D∪G** | **0.491** | 0.618 | 0.672 | 0.572 | 0.4% |
| D∪O | 0.461 | 0.612 | 0.685 | 0.554 | 1.3% |
| D∪G∪O | 0.477 | **0.627** | 0.628 | 0.626 | 1.0% |
| D∩G | 0.444 | 0.514 | **0.844** | 0.370 | 0.5% |
| maj2of3 | 0.463 | 0.579 | 0.809 | 0.451 | 0.4% |

(D = DeepSeek-V3.2, G = GLM-4.6, O = gpt-oss-120b.)

- **A *different* second model (union) beats same-model N=3**: D∪G lenient 0.618 vs N=3's 0.563.
  Mechanism is recall (D 0.458 → D∪G 0.572); models miss different things.
- **GLM is the right union partner** (low hallucination, higher precision than gpt-oss).
- **D∩G intersection → precision 0.844**: a high-precision auto-accept gate.

## Decision

- **Workhorse:** DeepSeek-V3.2, **spires** grounding, **N=1** (≈ $40 for the full 116k-segment corpus).
- **Recall lever:** add a **GLM-4.6 union pass selectively** (recall-critical material) rather than
  unioning everything (GLM on the whole corpus ≈ $500).
- **Auto-accept gate:** **D∩GLM** (intersection, precision 0.84) for high-confidence rows.
- **Drop/redesign graphrag**; reserve N=3 voting for the curation-sensitive tail.

These are silver-standard numbers — re-run against the **human gold set** (Phase 4) before locking.
Reproduce: `flopo2/extract/panel.py`, `flopo2/extract/ensemble.py` (+ `merge_slices.py`,
`merge_grid.py`).
