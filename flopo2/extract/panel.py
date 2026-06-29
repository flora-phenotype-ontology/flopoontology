"""Run the Phase 5 model panel over the silver standard and rank candidates.

Runs each candidate workhorse model through the extraction engine on the full silver set, scores
each against silver, and writes a comparison table (overall + per-language exact F1 + cost). This
is the empirical workhorse-selection step before committing to a full-corpus run.

Open-weights candidates (see resources/openrouter-budget.md); French matters (58% of corpus).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flopo2.extract.engine import EngineConfig
from flopo2.extract.pilot import run_pilot

DEFAULT_PANEL = [
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
    "mistralai/mistral-small",
    "deepseek/deepseek-v3.2",
]


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 5 model panel comparison.")
    ap.add_argument("--silver", type=Path, default=Path("gold/silver_standard.jsonl"))
    ap.add_argument("--models", nargs="+", default=DEFAULT_PANEL)
    ap.add_argument("--grounding", choices=["spires", "graphrag"], default="spires")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="cap segments (default: all 400)")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("-o", "--out", type=Path, default=Path("gold/pilot_results.json"))
    args = ap.parse_args()

    results = {}
    for model in args.models:
        print(f"\n=== {model} ({args.grounding}, N={args.samples}) ===")
        cfg = EngineConfig(models=[model], grounding=args.grounding, samples=args.samples)
        try:
            results[model] = run_pilot(args.silver, cfg, args.limit, concurrency=args.concurrency)
        except Exception as e:  # one model failing shouldn't sink the panel
            results[model] = {"error": f"{type(e).__name__}: {e}"}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    # Leaderboard
    print("\n\n=== PANEL LEADERBOARD (exact F1 vs silver) ===")
    print(f"{'model':28} {'F1':>6} {'P':>6} {'R':>6} {'fr-F1':>6} {'en-F1':>6} {'cost$':>7}")
    rows = []
    for model, r in results.items():
        if "error" in r:
            print(f"{model:28} ERROR: {r['error'][:40]}")
            continue
        ex = r["overall"]["exact"]
        fr = r["by_language"].get("fr", {}).get("f1", 0.0)
        en = r["by_language"].get("en", {}).get("f1", 0.0)
        cost = r["usage"]["cost_usd"]
        rows.append((ex["f1"], model, ex, fr, en, cost))
        print(f"{model:28} {ex['f1']:>6.3f} {ex['precision']:>6.3f} {ex['recall']:>6.3f} "
              f"{fr:>6.3f} {en:>6.3f} {cost:>7.4f}")
    if rows:
        best = max(rows)[1]
        print(f"\nwinner (overall exact F1): {best}")
    print(f"results written to {args.out}")


if __name__ == "__main__":
    main()
