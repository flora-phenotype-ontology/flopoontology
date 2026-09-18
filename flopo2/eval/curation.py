"""Curation exports for turning the Phase 4/5 sample into human gold.

The review sheet is deliberately TSV, not XLSX, so it can be opened in Excel/LibreOffice/Sheets
without adding another dependency to the core package. Each row is one text segment with the
Claude-generated silver assertions included as editable JSON. The curator fills or edits the
``gold_assertions_json`` cell; that column can then be converted back to JSONL for scoring.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


KEEP_ASSERTION_FIELDS = (
    "po_id",
    "po_label",
    "pato_id",
    "pato_label",
    "negated",
    "negation_scope",
    "value_low",
    "value_high",
    "value_low_inclusive",
    "value_high_inclusive",
    "unit",
    "value_text",
    "value_operator",
    "value_terms",
    "bearer_context_qualities",
    "developmental_stage_contexts",
    "developmental_stage_operator",
    "raw_entity_text",
    "raw_quality_text",
    "normalization_status",
    "mapping_provenance",
    "modifier",
    "source_text",
)


def _compact_assertions(assertions: list[dict]) -> list[dict]:
    out = []
    for a in assertions:
        out.append({k: a.get(k, "") for k in KEEP_ASSERTION_FIELDS if k in a})
    return out


def write_review_tsv(
    silver_path: Path,
    out_path: Path,
    limit: int = 100,
    start: int = 0,
) -> int:
    """Write a curator-friendly TSV review sheet from a silver/gold JSONL file."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with Path(silver_path).open(encoding="utf-8") as inp, out_path.open(
        "w", encoding="utf-8", newline=""
    ) as out:
        fields = [
            "review_id",
            "source",
            "source_id",
            "taxon",
            "organ",
            "language",
            "text",
            "silver_assertions_json",
            "gold_assertions_json",
            "curator_notes",
        ]
        writer = csv.DictWriter(out, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for idx, line in enumerate(inp):
            if idx < start:
                continue
            if n >= limit:
                break
            if not line.strip():
                continue
            obj = json.loads(line)
            assertions = _compact_assertions(obj.get("assertions", []) or [])
            writer.writerow({
                "review_id": f"paul-{n + 1:03d}",
                "source": obj.get("source", ""),
                "source_id": obj.get("source_id", ""),
                "taxon": obj.get("taxon", ""),
                "organ": obj.get("organ", ""),
                "language": obj.get("language", ""),
                "text": obj.get("text", ""),
                "silver_assertions_json": json.dumps(assertions, ensure_ascii=False),
                "gold_assertions_json": json.dumps(assertions, ensure_ascii=False),
                "curator_notes": "",
            })
            n += 1
    return n


def review_tsv_to_gold_jsonl(review_path: Path, out_path: Path) -> int:
    """Convert a completed review TSV into the JSONL format consumed by ``load_gold``."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with Path(review_path).open(encoding="utf-8", newline="") as inp, out_path.open(
        "w", encoding="utf-8"
    ) as out:
        reader = csv.DictReader(inp, delimiter="\t")
        for row in reader:
            raw = (row.get("gold_assertions_json") or "").strip()
            assertions = json.loads(raw) if raw else []
            obj = {
                "source": row.get("source", ""),
                "source_id": row.get("source_id", ""),
                "taxon": row.get("taxon", ""),
                "organ": row.get("organ", ""),
                "language": row.get("language", ""),
                "text": row.get("text", ""),
                "assertions": assertions,
            }
            out.write(json.dumps(obj, ensure_ascii=False) + "\n")
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description="Export a 100-segment TSV for curator review.")
    ap.add_argument("--to-jsonl", action="store_true",
                    help="convert a completed review TSV to gold-standard JSONL")
    ap.add_argument("--silver", type=Path, default=Path("gold/silver_standard.jsonl"))
    ap.add_argument("-o", "--out", type=Path, default=Path("gold/paul_gold_review_100.tsv"))
    ap.add_argument("--review", type=Path, default=Path("gold/paul_gold_review_100.tsv"))
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--start", type=int, default=0)
    args = ap.parse_args()
    if args.to_jsonl:
        n = review_tsv_to_gold_jsonl(args.review, args.out)
        print(f"wrote {n} rows to {args.out}")
        return
    n = write_review_tsv(args.silver, args.out, limit=args.limit, start=args.start)
    print(f"wrote {n} rows to {args.out}")


if __name__ == "__main__":
    main()
