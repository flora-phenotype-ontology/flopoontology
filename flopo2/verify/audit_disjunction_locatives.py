"""Audit disjunction/transition candidates and route French locatives to bearer review.

The deterministic baseline historically treated every adjacent French ``à``/``au`` as a
transition connector.  That is not valid for phrases such as ``acuminé au sommet`` or
``glabre à l'intérieur``.  This module does not promote those qualities to whole-bearer
assertions: the locative phrase changes the anatomical attachment.  Instead it emits a
provenance-complete TSV with the proposed reason ``locative_context`` for bearer review.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from flopo2.extract.baseline import _clause_at, _local_bearer, _organ_to_po


TARGET_REASONS = {
    "explicit_disjunction",
    "unsupported_alternative_or_transition",
}

# Deliberately narrow.  In particular, ``à l'état adulte`` and ``à l'anthèse`` are temporal or
# developmental contexts and must not be folded into this anatomical-locative queue.
LOCATIVE_AFTER_QUALITY = re.compile(
    r"^\s*(?:"
    r"au\s+(?:sommet|bord|fond|milieu|centre|niveau)|"
    r"au-(?:dessus|dessous)|"
    r"à\s+(?:la|sa|leur)\s+"
    r"(?:base|face|surface|marge|partie|extrémité|extremite)|"
    r"à\s+l['’](?:intérieur|interieur|extérieur|exterieur|apex)"
    r")\b",
    re.IGNORECASE,
)

CONNECTOR_BEFORE_QUALITY = re.compile(
    r"\b(?:or|ou|to|through|à|au)\s*$",
    re.IGNORECASE,
)

FIELDS = [
    "source",
    "source_id",
    "source_segment_index",
    "segment_id",
    "taxon",
    "organ",
    "language",
    "clause",
    "clause_start",
    "clause_end",
    "span_start",
    "span_end",
    "source_span_start",
    "source_span_end",
    "verbatim",
    "original_reason",
    "proposed_reason",
    "proposed_pato_id",
    "heading_candidate_bearer",
    "current_candidate_bearer",
    "locative_phrase",
    "extractor",
]


def _locative_match(text: str, start: int, end: int) -> tuple[str, str, int, int] | None:
    """Return the exact locative and containing clause for a narrowly safe routing match."""

    clause, clause_start = _clause_at(text, start)
    local_start = start - clause_start
    local_end = end - clause_start
    before = clause[max(0, local_start - 32) : local_start]
    if CONNECTOR_BEFORE_QUALITY.search(before):
        # ``aigu à obtus à la base`` is a true transition whose right endpoint also has a
        # locative.  It must remain in the logical-expression queue.
        return None
    after = clause[local_end : min(len(clause), local_end + 96)]
    match = LOCATIVE_AFTER_QUALITY.match(after)
    if match is None:
        return None
    return match.group(0).strip(), clause, clause_start, clause_start + len(clause)


def audit_sqlite(database: Path, output_tsv: Path) -> dict[str, object]:
    """Write locative-context evidence and return complete target-family counts."""

    reason_counts: Counter[str] = Counter()
    source_reason_counts: Counter[tuple[str, str]] = Counter()
    routed_counts: Counter[str] = Counter()
    rows: list[dict[str, object]] = []
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        query = """
            SELECT u.unresolved_span_id, u.segment_id, u.char_start AS span_start,
                   u.char_end AS span_end, u.surface_form, u.reason,
                   u.candidate_pato_id, u.extractor,
                   t.source, t.source_id, t.source_segment_index, t.taxon, t.organ,
                   t.language, t.char_start AS segment_source_start, t.text
            FROM unresolved_span AS u
            JOIN text_segment AS t USING(segment_id)
            WHERE u.reason IN ('explicit_disjunction',
                               'unsupported_alternative_or_transition')
            ORDER BY u.unresolved_span_id
        """
        for record in connection.execute(query):
            reason = str(record["reason"])
            source = str(record["source"])
            reason_counts[reason] += 1
            source_reason_counts[(source, reason)] += 1
            if reason != "unsupported_alternative_or_transition":
                continue
            text = str(record["text"])
            start = int(record["span_start"])
            end = int(record["span_end"])
            matched = _locative_match(text, start, end)
            if matched is None:
                continue
            locative, clause, clause_start, clause_end = matched
            verbatim = text[start:end]
            if verbatim != record["surface_form"]:
                raise ValueError(
                    f"unresolved span {record['unresolved_span_id']} is not verbatim"
                )
            heading_bearer = _organ_to_po(str(record["organ"]))
            current_bearer = _local_bearer(
                text,
                start,
                heading_bearer,
                str(record["candidate_pato_id"]),
                end,
            )
            segment_source_start = int(record["segment_source_start"])
            rows.append(
                {
                    "source": source,
                    "source_id": record["source_id"],
                    "source_segment_index": record["source_segment_index"],
                    "segment_id": record["segment_id"],
                    "taxon": record["taxon"],
                    "organ": record["organ"],
                    "language": record["language"],
                    "clause": clause,
                    "clause_start": clause_start,
                    "clause_end": clause_end,
                    "span_start": start,
                    "span_end": end,
                    "source_span_start": segment_source_start + start,
                    "source_span_end": segment_source_start + end,
                    "verbatim": verbatim,
                    "original_reason": reason,
                    "proposed_reason": "locative_context",
                    "proposed_pato_id": record["candidate_pato_id"],
                    "heading_candidate_bearer": heading_bearer,
                    "current_candidate_bearer": current_bearer,
                    "locative_phrase": locative,
                    "extractor": record["extractor"],
                }
            )
            routed_counts[source] += 1
    finally:
        connection.close()

    output_tsv.parent.mkdir(parents=True, exist_ok=True)
    with output_tsv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    return {
        "database": str(database),
        "output": str(output_tsv),
        "target_reason_counts": dict(sorted(reason_counts.items())),
        "source_reason_counts": {
            f"{source}:{reason}": count
            for (source, reason), count in sorted(source_reason_counts.items())
        },
        "locative_context_rows": len(rows),
        "locative_context_by_source": dict(sorted(routed_counts.items())),
        "residual_target_rows": sum(reason_counts.values()) - len(rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = audit_sqlite(args.database, args.output)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
