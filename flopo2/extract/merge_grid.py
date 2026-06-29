"""Merge the DeepSeek grid (grounding × N) pilot results into one exact-vs-lenient table."""

from __future__ import annotations

import glob
import json
from pathlib import Path


def _tag(cfg: dict) -> str:
    return f"{cfg['grounding']:8} N={cfg['samples']}"


def main() -> None:
    files = sorted(glob.glob("gold/ds_*.json"))
    print("\n=== DEEPSEEK GRID: grounding × self-consistency (full 400 segments) ===")
    print(f"{'config':16} {'exF1':>6} {'lenF1':>6} {'lenP':>6} {'lenR':>6} "
          f"{'fr-len':>7} {'en-len':>7} {'halluc':>7} {'cost$':>7} {'calls':>6}")
    rows = []
    for f in files:
        r = json.loads(Path(f).read_text(encoding="utf-8"))
        cfg = r["config"]
        s = r["overall"]
        ex = s["exact"]["f1"]
        ln = s["lenient"]
        # per-language lenient isn't stored separately (by_language is exact); approximate with exact fr/en
        fr = r["by_language"].get("fr", {}).get("f1", 0.0)
        en = r["by_language"].get("en", {}).get("f1", 0.0)
        hal = s.get("hallucination_rate", s.get("halluc", 0.0))
        cost = r["usage"]["cost_usd"]
        calls = r["usage"]["calls"]
        rows.append((ln["f1"], _tag(cfg)))
        print(f"{_tag(cfg):16} {ex:>6.3f} {ln['f1']:>6.3f} {ln['precision']:>6.3f} "
              f"{ln['recall']:>6.3f} {fr:>7.3f} {en:>7.3f} {hal:>7.3f} {cost:>7.3f} {calls:>6}")
    if rows:
        print(f"\nbest lenient F1: {max(rows)[1]}")
    print("(fr-len/en-len shown as exact per-language F1; overall lenient is the headline)")


if __name__ == "__main__":
    main()
