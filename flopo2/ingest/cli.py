"""Ingestion CLI: turn the flora corpus into a JSONL stream of TextSegments, or print stats.

Examples::

    python -m flopo2.ingest.cli stats          # corpus-wide segment/taxon counts
    python -m flopo2.ingest.cli dump -o segments.jsonl
    python -m flopo2.ingest.cli dump flora-gabon/fdgvol1_final.xml
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from flopo2.ingest import collenette, fdac, florml, kew
from flopo2.ingest.models import TextSegment

# The in-repo corpus. FlorML directories + the fdac CSV + the Kew Access export. Modern sources
# (WFO/FoC/FNA) join here in Phase 10 via flopo2/ingest/external.py.
FLORML_DIRS = ["flora-gabon", "flora-malesiana"]
FDAC_CSV = "flora-central-africa/fdacDescriptions.csv"
KEW_XML = "floras-other/Kew African Flora Species.xml"


def iter_corpus(root: Path) -> Iterator[TextSegment]:
    for d in FLORML_DIRS:
        if (root / d).is_dir():
            yield from florml.iter_segments_dir(root / d)
    csv_path = root / FDAC_CSV
    if csv_path.is_file():
        yield from fdac.iter_segments(csv_path)
    kew_path = root / KEW_XML
    if kew_path.is_file():
        yield from kew.iter_segments(kew_path)


def _is_kew(path: Path) -> bool:
    """Detect the Kew Access export by sniffing the first KB for its root tag."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        head = fh.read(1024)
    return "<dataroot" in head or "<Specieslist" in head


def iter_path(target: Path) -> Iterator[TextSegment]:
    if target.is_dir():
        yield from florml.iter_segments_dir(target)
    elif "collenette" in target.name.lower() and target.suffix.lower() in {".pdf", ".txt"}:
        yield from collenette.iter_segments(target)
    elif target.suffix.lower() == ".csv":
        yield from fdac.iter_segments(target)
    elif _is_kew(target):
        yield from kew.iter_segments(target)
    else:
        yield from florml.iter_segments(target)


def cmd_stats(root: Path) -> None:
    n = 0
    taxa: set[str] = set()
    organs: Counter[str] = Counter()
    langs: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    chars = 0
    for s in iter_corpus(root):
        n += 1
        taxa.add(f"{s.source}:{s.taxon.name_string}")
        organs[s.organ] += 1
        langs[s.language] += 1
        sources[s.source] += 1
        chars += len(s.text)
    print(f"segments:        {n:,}")
    print(f"distinct taxa:   {len(taxa):,}")
    print(f"text chars:      {chars:,}")
    print(f"by source:       {dict(sources)}")
    print(f"by language:     {dict(langs)}")
    print(f"top 15 organs:   {organs.most_common(15)}")


def cmd_dump(target: Path | None, root: Path, out: Path | None) -> None:
    segs = iter_path(target) if target else iter_corpus(root)
    fh = out.open("w") if out else None
    n = 0
    source_positions: Counter[tuple[str, str]] = Counter()
    try:
        for s in segs:
            row = s.to_row()
            source_key = (s.source, s.source_id)
            row["source_segment_index"] = source_positions[source_key]
            source_positions[source_key] += 1
            line = json.dumps(row, ensure_ascii=False)
            if fh:
                fh.write(line + "\n")
            elif n < 5:
                print(line)
            n += 1
    finally:
        if fh:
            fh.close()
    print(f"wrote {n:,} segments" + (f" to {out}" if out else " (showed first 5)"))


def main() -> None:
    ap = argparse.ArgumentParser(description="FLOPO 2.0 flora ingestion")
    ap.add_argument("--root", type=Path, default=Path("."), help="repo root (default: .)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats", help="print corpus segment/taxon/organ statistics")
    d = sub.add_parser("dump", help="dump segments as JSONL")
    d.add_argument("target", type=Path, nargs="?", help="file/dir (default: whole corpus)")
    d.add_argument("-o", "--out", type=Path, help="output JSONL path")
    args = ap.parse_args()
    if args.cmd == "stats":
        cmd_stats(args.root)
    else:
        cmd_dump(args.target, args.root, args.out)


if __name__ == "__main__":
    main()
