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
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path

from flopo2.eval.scoring import Assertion, EvalReport, score_segment
from flopo2.extract.engine import EngineConfig, extract_segment
from flopo2.extract.router import OpenRouterClient


def _gold_assertions(seg: dict) -> list[Assertion]:
    out = []
    for a in seg.get("assertions", []):
        out.append(Assertion(
            po_id=a["po_id"], pato_id=a["pato_id"], negated=bool(a.get("negated", False)),
            negation_scope=a.get("negation_scope", "") or "",
            organ=seg.get("organ", ""), source_text=a.get("source_text", ""),
            value_low=a.get("value_low"), value_high=a.get("value_high"),
            value_low_inclusive=a.get("value_low_inclusive", True),
            value_high_inclusive=a.get("value_high_inclusive", True),
            unit=a.get("unit", "") or "", value_text=a.get("value_text", "") or "",
            value_operator=a.get("value_operator", "atomic") or "atomic",
            value_term_ids=tuple(a.get("value_terms", []) or a.get("value_term_ids", []) or []),
            bearer_context_qualities=tuple(a.get("bearer_context_qualities", []) or []),
            developmental_stage_contexts=tuple(
                a.get("developmental_stage_contexts", []) or []
            ),
            developmental_stage_operator=(
                a.get("developmental_stage_operator", "atomic") or "atomic"
            ),
        ))
    return out


def run_pilot(silver: Path, cfg: EngineConfig, limit: int | None, ancestors=None,
              client: OpenRouterClient | None = None, concurrency: int = 8,
              max_seconds: float = 3600.0) -> dict:
    segs = [
        json.loads(line)
        for line in Path(silver).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if limit:
        segs = segs[:limit]
    client = client or OpenRouterClient(max_connections=max(8, concurrency * 2))
    report = EvalReport()
    by_lang: dict[str, EvalReport] = defaultdict(EvalReport)

    # Parallelize the I/O-bound extraction (API calls); score as results complete so EvalReport
    # stays single-threaded. work() never raises — a failed segment yields no predictions — and a
    # global wall-clock cap means one stuck segment can't block the whole run.
    def work(seg):
        try:
            return seg, extract_segment(client, cfg, seg)
        except Exception:  # defensive: extraction must never crash the pool
            return seg, []

    done = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {pool.submit(work, s): s for s in segs}
        try:
            for fut in as_completed(futs, timeout=max_seconds):
                seg, preds = fut.result()
                gold = _gold_assertions(seg)
                score_segment(preds, gold, seg.get("text", ""), ancestors=ancestors, report=report)
                score_segment(preds, gold, seg.get("text", ""), ancestors=ancestors,
                              report=by_lang[seg.get("language", "?")])
                done += 1
                print(f"  {done}/{len(segs)} preds={len(preds)} gold={len(gold)} "
                      f"cost=${client.usage.cost_usd:.3f}", end="\r", flush=True)
        except FuturesTimeout:
            for f in futs:
                f.cancel()
            print(f"\n[run_pilot] wall-clock cap {max_seconds:.0f}s hit; scored {done}/{len(segs)} "
                  f"segments (rest skipped)", flush=True)
    print()
    return {
        "config": {
            "models": cfg.models,
            "grounding": cfg.grounding,
            "samples": cfg.samples,
            "use_terminology": cfg.use_terminology,
            "terminology_mode": cfg.terminology_mode,
            "terminology_registry": cfg.terminology_registry,
        },
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
    ap.add_argument("--no-terminology", action="store_true")
    ap.add_argument(
        "--terminology-mode",
        choices=["off", "ontology", "registry", "full"],
        default="full",
    )
    ap.add_argument("--terminology-registry", default="config/botanical_terminology.tsv")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--lenient", action="store_true",
                    help="enable hierarchical (PO/PATO ancestor-distance) scoring via ont/*.obo")
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args()
    cfg = EngineConfig(models=args.models, grounding=args.grounding,
                       samples=args.samples, temperature=args.temperature,
                       use_terminology=not args.no_terminology,
                       terminology_mode="off" if args.no_terminology else args.terminology_mode,
                       terminology_registry=args.terminology_registry)
    ancestors = None
    if args.lenient:
        from flopo2.eval.hierarchy import build_ancestors
        ancestors = build_ancestors()
    result = run_pilot(args.silver, cfg, args.limit, ancestors=ancestors,
                       concurrency=args.concurrency)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)


if __name__ == "__main__":
    main()
