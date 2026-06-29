# OpenRouter budget for FLOPO 2.0 extraction (open-weights first)

Estimated 2026-06-29. Prices are OpenRouter pay-as-you-go for open-weights models; cheaper
providers (DeepInfra etc.) and local hosting on KAUST Ibex (open weights → $0 marginal, GPU only)
can be lower.

## Token model
- Corpus: **116,322 segments** (Phase 1).
- Per extraction call ≈ **1,500 input tokens** (instructions + retrieved PO/PATO candidates +
  segment text, ~70 tok) + **300 output tokens** (JSON assertions) ≈ 1.8k tok/call.
- Graph-RAG retrieval embeddings run **locally/free** (bge-m3 / multilingual-e5, FR+EN) — not billed.
- `cost/call = in_tok/1e6·price_in + out_tok/1e6·price_out`.

## Prices (June 2026) and per-call cost (1.5k in / 0.3k out) + full-run N=3 (349k calls)
| Model | $/M in | $/M out | $/call | Full N=3 | Notes |
|---|---|---|---|---|---|
| gpt-oss-120b | 0.03 | 0.15 | 0.00009 | $31 | cheapest + strong (120B MoE); English-centric, verify FR |
| gpt-oss-20b | 0.03 | 0.14 | 0.00009 | $30 | small; English/ensemble only |
| Phi-4 (14B) | 0.07 | 0.14 | 0.00015 | $51 | English-centric, 16K ctx; weak FR — deprioritize |
| Qwen3-32B | 0.08 | 0.28 | 0.00020 | $71 | best multilingual/$; strong FR |
| Gemma 4 31B | 0.12 | 0.35 | 0.00029 | $99 | good multilingual/FR |
| Mistral Small 4 | 0.15 | 0.60 | 0.00041 | $141 | French-native; ideal for FR floras |
| DeepSeek-V3.2 | 0.23 | 0.34 | 0.00045 | $156 | strong reasoning/grounding |
| Qwen3-235B-A22B | 0.195 | 1.56 | 0.00076 | $265 | heavier workhorse / cheap escalation |
| GLM-4.6 | 0.43 | 1.74 | 0.00117 | $407 | escalation |
| GLM-5.2 | 0.95 | 3.00 | 0.00233 | $811 | escalation (user pick) |

**Corpus is 58% French** (Gabon + fdac) — French grounding quality matters as much as price.
Ranked candidates for this task: (1) gpt-oss-120b [cheapest+strong, test FR], (2) Qwen3-32B
[best multilingual/$], (3) Mistral Small 4 [French-native], (4) DeepSeek-V3.2 [hard cases].
Escalation: GLM-5.2 *or* Qwen3-235B (much cheaper). Skip Phi-4/gpt-oss-20b/Gemma as FR primary.

## Scenarios
| Scenario | Calls | Qwen3-32B | DeepSeek-V3.2 | GLM-5.2 |
|---|---|---|---|---|
| Pilot (400×2 engines×N=5) | 4k | $0.80 | $1.80 | $9.30 |
| Full, 1 engine, N=1 | 116k | $24 | $52 | $270 |
| Full, 1 engine, N=3 | 349k | $71 | $156 | $811 |
| Full, both engines, N=3 | 698k | $142 | $312 | — |

## Recommended tiers (open-weights first)
- **Shoestring ~$30**: gpt-oss-120b sole workhorse, 1 engine, N=3.
- **Balanced ~$70–150 (recommended)**: gpt-oss-120b (or Qwen3-32B) workhorse @ **N=3**, single
  winning engine, **escalate ~15% low-agreement/parse-fail segments**. Escalate to Qwen3-235B → ~$71;
  to GLM-5.2 → ~$153. (= the tiered scheme.)
- **Max quality ~$400–800**: GLM-4.6/GLM-5.2 workhorse, N=3–5, optionally both engines.

Pilot is ~$1–10 in all cases → run a **model panel** (gpt-oss-120b + Qwen3-32B + Mistral Small 4 +
DeepSeek-V3.2) × both engines × N=5 on the 400 silver segments (~$3–6) and let the eval harness pick
the winner **per language and per trait type** before committing to a full-run tier.

Sources: openrouter.ai/deepseek/deepseek-v3.2, openrouter.ai/z-ai/glm-5.2, openrouter.ai/z-ai/glm-4.6,
openrouter.ai/qwen/qwen3-32b, openrouter.ai/qwen/qwen3-235b-a22b.
