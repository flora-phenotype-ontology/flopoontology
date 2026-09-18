"""Cross-model ensemble experiment (Phase 5): does a *different* second model beat same-model N=3?

Same-model self-consistency (DeepSeek×3) barely helped because a model's repeated samples make
correlated errors. A heterogeneous vote makes *different* errors, so combining models can recover
misses (union → recall) or filter noise (intersection → precision).

We extract each model ONCE per segment (spires grounding), then score several combination
strategies offline — one set of API calls, many strategies for free. Lenient (hierarchical)
scoring is on, comparable to the DeepSeek grid.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path

from flopo2.eval.hierarchy import build_ancestors
from flopo2.eval.scoring import Assertion, EvalReport, assertion_vote_key, score_segment
from flopo2.extract.engine import EngineConfig, extract_segment
from flopo2.extract.pilot import _gold_assertions
from flopo2.extract.router import OpenRouterClient

# short tag -> OpenRouter slug; DeepSeek first so it's the representative for shared keys
MODELS = {
    "D": "deepseek/deepseek-v3.2",
    "G": "z-ai/glm-4.6",
    "O": "openai/gpt-oss-120b",
}


def _key(a: Assertion) -> tuple:
    """Compatibility wrapper around the shared semantic vote identity."""
    return assertion_vote_key(a)


def main() -> None:
    ap = argparse.ArgumentParser(description="Cross-model ensemble vs same-model voting.")
    ap.add_argument("--silver", type=Path, default=Path("gold/silver_standard.jsonl"))
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--max-seconds", type=float, default=3600.0)
    ap.add_argument("-o", "--out", type=Path, default=Path("gold/ensemble_results.json"))
    args = ap.parse_args()

    segs = [
        json.loads(line)
        for line in args.silver.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.limit:
        segs = segs[: args.limit]
    client = OpenRouterClient(max_connections=max(8, args.concurrency * 2))
    anc = build_ancestors()

    # 1) Extract each model once per segment (spires, N=1), in parallel over (segment, model).
    # work() never raises (failed extraction -> empty list) and a wall-clock cap stops stragglers;
    # any (segment, model) without a result defaults to empty so scoring still proceeds.
    preds: dict[tuple[int, str], list[Assertion]] = {(i, tag): [] for i in range(len(segs)) for tag in MODELS}
    tasks = list(preds)

    def work(t):
        i, tag = t
        cfg = EngineConfig(models=[MODELS[tag]], grounding="spires", samples=1)
        try:
            return t, extract_segment(client, cfg, segs[i])
        except Exception:
            return t, []

    done = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = {pool.submit(work, t): t for t in tasks}
        try:
            for fut in as_completed(futs, timeout=args.max_seconds):
                t, res = fut.result()
                preds[t] = res
                done += 1
                print(f"  {done}/{len(tasks)} extracted  cost=${client.usage.cost_usd:.3f}",
                      end="\r", flush=True)
        except FuturesTimeout:
            for f in futs:
                f.cancel()
            print(f"\n[ensemble] wall-clock cap {args.max_seconds:.0f}s hit; "
                  f"extracted {done}/{len(tasks)} (rest empty)", flush=True)
    print()

    # 2) Combination strategies: name -> rule(sets_by_tag) -> set of keys to keep
    def union(*tags):
        return lambda S: set().union(*(S[t] for t in tags))

    def inter(*tags):
        return lambda S: set.intersection(*(S[t] for t in tags))

    def atleast(n, *tags):
        def rule(S):
            c = defaultdict(int)
            for t in tags:
                for k in S[t]:
                    c[k] += 1
            return {k for k, v in c.items() if v >= n}
        return rule

    strategies = {
        "D (solo)": union("D"),
        "G (solo)": union("G"),
        "O (solo)": union("O"),
        "D∪G": union("D", "G"),
        "D∪O": union("D", "O"),
        "D∪G∪O": union("D", "G", "O"),
        "D∩G": inter("D", "G"),
        "maj2of3(DGO)": atleast(2, "D", "G", "O"),
    }

    # 3) Score every strategy (lenient) using per-segment representative assertions.
    reports = {name: EvalReport() for name in strategies}
    for i, seg in enumerate(segs):
        gold = _gold_assertions(seg)
        text = seg.get("text", "")
        sets = {tag: {_key(a) for a in preds[(i, tag)]} for tag in MODELS}
        # representative Assertion per key (prefer DeepSeek's, then G, then O)
        rep: dict[tuple, Assertion] = {}
        for tag in MODELS:
            for a in preds[(i, tag)]:
                rep.setdefault(_key(a), a)
        for name, rule in strategies.items():
            keep = rule(sets)
            score_segment([rep[k] for k in keep], gold, text, ancestors=anc, report=reports[name])

    out = {
        "models": MODELS,
        "segments": len(segs),
        "usage": {"calls": client.usage.calls, "cost_usd": round(client.usage.cost_usd, 4),
                  "by_model": client.usage.by_model},
        "strategies": {name: r.summary() for name, r in reports.items()},
    }
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print("\n=== ENSEMBLE: combination strategies (lenient, vs silver) ===")
    print(f"{'strategy':14} {'exF1':>6} {'lenF1':>6} {'lenP':>6} {'lenR':>6} {'halluc':>7}")
    rows = []
    for name, r in reports.items():
        s = r.summary()
        ex, ln = s["exact"], s["lenient"]
        hal = s.get("hallucination_rate", s.get("halluc", 0.0))
        rows.append((ln["f1"], name))
        print(f"{name:14} {ex['f1']:>6.3f} {ln['f1']:>6.3f} {ln['precision']:>6.3f} "
              f"{ln['recall']:>6.3f} {hal:>7.4f}")
    print(f"\nbest lenient F1: {max(rows)[1]}")
    print(f"total cost ${client.usage.cost_usd:.3f} over {len(segs)} segments; by_model={client.usage.by_model}")


if __name__ == "__main__":
    main()
