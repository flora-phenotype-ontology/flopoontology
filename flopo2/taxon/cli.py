"""Phase 2 CLI: resolve the corpus taxa to WFO/IPNI/GBIF and write the taxon table.

Connects ingestion (Phase 1) to normalization: collect the distinct taxon name strings across the
flora corpus, resolve them in cached batches via the Global Names APIs, and write
``config/taxon_table.tsv`` (one row per distinct input name, with backbone IDs and segment counts).

Examples::

    python -m flopo2.taxon.cli --limit 50          # sample (validate end-to-end)
    python -m flopo2.taxon.cli                      # full corpus (batched, cached; network)
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from flopo2.ingest.cli import iter_corpus
from flopo2.taxon.normalize import TaxonNormalizer


def collect_names(root: Path, limit: int | None = None) -> Counter[str]:
    """Distinct taxon name strings across the corpus, with how many segments each carries."""
    counts: Counter[str] = Counter()
    for seg in iter_corpus(root):
        name = seg.taxon.name_string
        if name:
            counts[name] += 1
    if limit:
        return Counter(dict(counts.most_common(limit)))
    return counts


def run(root: Path, out: Path, cache: Path, batch: int, limit: int | None) -> None:
    counts = collect_names(root, limit)
    names = list(counts)
    print(f"resolving {len(names):,} distinct taxon names (batch={batch}) ...")
    tn = TaxonNormalizer(cache_path=cache)
    resolved = []
    try:
        for i in range(0, len(names), batch):
            chunk = names[i : i + batch]
            resolved.extend(tn.resolve_many(chunk))
            print(f"  {min(i + batch, len(names)):,}/{len(names):,}", end="\r")
    finally:
        tn.close()
    print()

    out.parent.mkdir(parents=True, exist_ok=True)
    n_wfo = n_ipni = n_match = 0
    with out.open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(
            ["input_name", "canonical", "matched_name", "match_type",
             "wfo_id", "ipni_id", "gbif_id", "accepted_canonical", "n_segments"]
        )
        for rt in resolved:
            w.writerow([
                rt.input_name, rt.canonical, rt.matched_name, rt.match_type,
                rt.wfo_id, rt.ipni_id, rt.gbif_id, rt.accepted_canonical, counts[rt.input_name],
            ])
            n_match += rt.resolved
            n_wfo += bool(rt.wfo_id)
            n_ipni += bool(rt.ipni_id)
    print(f"wrote {out}: {len(resolved):,} taxa | matched {n_match:,} | WFO {n_wfo:,} | IPNI {n_ipni:,}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Resolve corpus taxa to WFO/IPNI/GBIF (Phase 2).")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("-o", "--out", type=Path, default=Path("config/taxon_table.tsv"))
    ap.add_argument("--cache", type=Path, default=Path("config/taxon_cache.sqlite"))
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--limit", type=int, default=None, help="cap to the N most frequent taxa (sampling)")
    args = ap.parse_args()
    run(args.root, args.out, args.cache, args.batch, args.limit)


if __name__ == "__main__":
    main()
