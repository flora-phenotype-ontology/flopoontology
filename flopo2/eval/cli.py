"""Phase 4 CLI: build the gold-standard annotation template from the corpus.

``sample`` draws a stratified, reproducible set of segments (balanced across source × organ ×
language) and writes a blank annotation template for botanist curators. After annotation, the same
files load via ``flopo2.eval.gold.load_gold`` for scoring in Phase 5.

Example::

    python -m flopo2.eval.cli sample --n 400 -o gold/annotation_template.jsonl
    python -m flopo2.eval.cli sample --n 400 --stats   # just show the strata balance
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from flopo2.eval.gold import organ_group, stratified_sample, write_annotation_template
from flopo2.ingest.cli import iter_corpus


def cmd_sample(root: Path, n: int, out: Path | None, stats_only: bool) -> None:
    chosen = stratified_sample(iter_corpus(root), n=n)
    strata = Counter((s.source, organ_group(s.organ), s.language) for s in chosen)
    print(f"sampled {len(chosen)} segments across {len(strata)} strata")
    for key, c in sorted(strata.items()):
        print(f"  {key[0]:16} {key[1]:14} {key[2]:3} : {c}")
    if stats_only:
        return
    out = out or Path("gold/annotation_template.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    written = write_annotation_template(chosen, out)
    print(f"wrote {written} blank annotation segments to {out}")
    print("Curators: fill each segment's `assertions` with {po_id, pato_id, negated, "
          "value_low, value_high, unit, value_text, source_text}.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Gold-standard sampling (Phase 4).")
    ap.add_argument("--root", type=Path, default=Path("."))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="stratified-sample segments into an annotation template")
    s.add_argument("--n", type=int, default=400)
    s.add_argument("-o", "--out", type=Path)
    s.add_argument("--stats", action="store_true", help="only print strata balance, don't write")
    args = ap.parse_args()
    if args.cmd == "sample":
        cmd_sample(args.root, args.n, args.out, args.stats)


if __name__ == "__main__":
    main()
