"""Phase 5 pilot runner: run an engine/model over the silver standard and score it.

Loads the silver-standard segments (text + gold-ish assertions), runs the extraction engine, and
scores predictions with the Phase-4 harness — reporting exact/lenient P/R/F1, hallucination rate,
negation accuracy, per-organ/per-language breakdown, and **actual OpenRouter spend**. This is the
gate that picks the workhorse model + grounding strategy before any full run.

Hierarchical (lenient) matching uses an optional OAK ancestors function; if OAK/PO/PATO aren't
available it scores exact-only (lenient == exact).

Example::

    python -m flopo2.extract.pilot --models openai/gpt-oss-120b --grounding spires --limit 20
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flopo2.eval.scoring import Assertion, EvalReport, score_segment
from flopo2.extract.engine import EngineConfig, extract_segment
from flopo2.extract.router import OpenRouterClient


def _gold_assertions(seg: dict) -> list[Assertion]:
    out = []
    for a in seg.get("assertions", []):
        out.append(Assertion(
            po_id=a["po_id"], pato_id=a["pato_id"], negated=bool(a.get("negated", False)),
            organ=seg.get("organ", ""), source_text=a.get("source_text", ""),
            value_low=a.get("value_low"), value_high=a.get("value_high"),
            unit=a.get("unit", "") or "", value_text=a.get("value_text", "") or "",
        ))
    return out


def run_pilot(silver: Path, cfg: EngineConfig, limit: int | None, ancestors=None,
              client: OpenRouterClient | None = None, concurrency: int = 8) -> dict:
    segs = [json.loads(l) for l in Path(silver).read_text(encoding="utf-8").splitlines() if l.strip()]
    if limit:
        segs = segs[:limit]
    client = client or OpenRouterClient()
    report = EvalReport()
    by_lang: dict[str, EvalReport] = defaultdict(EvalReport)

    # Parallelize the I/O-bound extraction (API calls); score sequentially so EvalReport stays
    # single-threaded. Results are gathered in input order.
    def work(seg):
        return seg, extract_segment(client, cfg, seg)

    done = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for seg, preds in pool.map(work, segs):
            gold = _gold_assertions(seg)
            score_segment(preds, gold, seg.get("text", ""), ancestors=ancestors, report=report)
            score_segment(preds, gold, seg.get("text", ""), ancestors=ancestors,
                          report=by_lang[seg.get("language", "?")])
            done += 1
            print(f"  {done}/{len(segs)} preds={len(preds)} gold={len(gold)} "
                  f"cost=${client.usage.cost_usd:.3f}", end="\r")
    print()
    return {
        "config": {"models": cfg.models, "grounding": cfg.grounding, "samples": cfg.samples},
        "segments": len(segs),
        "overall": report.summary(),
        "by_language": {k: v.summary()["exact"] for k, v in sorted(by_lang.items())},
        "usage": {
            "calls": client.usage.calls,
            "cost_usd": round(client.usage.cost_usd, 4),
            "escalations": client.usage.escalations,
            "by_model": client.usage.by_model,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 5 extraction pilot (scored vs silver standard).")
    ap.add_argument("--silver", type=Path, default=Path("gold/silver_standard.jsonl"))
    ap.add_argument("--models", nargs="+", default=["openai/gpt-oss-120b"],
                    help="tiered model list (workhorse first, escalation after)")
    ap.add_argument("--grounding", choices=["spires", "graphrag"], default="spires")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args()
    cfg = EngineConfig(models=args.models, grounding=args.grounding,
                       samples=args.samples, temperature=args.temperature)
    result = run_pilot(args.silver, cfg, args.limit)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)


if __name__ == "__main__":
    main()
