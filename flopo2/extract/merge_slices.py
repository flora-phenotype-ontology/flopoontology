"""Merge per-model slice result files into one leaderboard.

Each slice_<tag>.json is the dict that panel.py writes ({model: pilot_result}). This reads all of
them, prints a combined leaderboard (exact F1 / P / R, per-language F1, cost), and writes the merged
dict to gold/slice_results.json.
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path


def main() -> None:
    pattern = sys.argv[1] if len(sys.argv) > 1 else "gold/slice_*.json"
    merged: dict = {}
    for f in sorted(glob.glob(pattern)):
        if Path(f).name == "slice_results.json":
            continue
        try:
            merged.update(json.loads(Path(f).read_text(encoding="utf-8")))
        except Exception as e:
            print(f"skip {f}: {e}")

    Path("gold/slice_results.json").write_text(json.dumps(merged, indent=2, ensure_ascii=False))

    print("\n=== QUICK SLICE LEADERBOARD (100 segments, exact F1 vs silver) ===")
    print(f"{'model':28} {'F1':>6} {'P':>6} {'R':>6} {'fr-F1':>6} {'en-F1':>6} {'cost$':>8} {'calls':>6}")
    rows = []
    for model, r in merged.items():
        if not isinstance(r, dict) or "error" in r:
            print(f"{model:28} ERROR: {str(r.get('error', r))[:40]}")
            continue
        ex = r["overall"]["exact"]
        fr = r["by_language"].get("fr", {}).get("f1", 0.0)
        en = r["by_language"].get("en", {}).get("f1", 0.0)
        cost = r["usage"]["cost_usd"]
        calls = r["usage"]["calls"]
        rows.append((ex["f1"], model))
        print(f"{model:28} {ex['f1']:>6.3f} {ex['precision']:>6.3f} {ex['recall']:>6.3f} "
              f"{fr:>6.3f} {en:>6.3f} {cost:>8.4f} {calls:>6}")
    if rows:
        print(f"\nwinner (exact F1): {max(rows)[1]}")
    print("merged -> gold/slice_results.json")


if __name__ == "__main__":
    main()
