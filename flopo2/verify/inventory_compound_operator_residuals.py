"""Freeze and conserve the Stage residual scope for compound/operator recovery."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from flopo2.review.io import atomic_write_text, sha256_file, stable_id
from flopo2.review.models import canonical_json, normalized_text


TARGET_REASONS = frozenset(
    {
        "hyphenated_or_slash_compound",
        "unsupported_alternative_or_transition",
        "explicit_disjunction",
        "same_attribute_composite_or_transition",
        "unsupported_same_attribute_neighbor",
    }
)


def _context(text: str, start: int, end: int, radius: int = 180) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    for boundary in ".;\n":
        found = text.rfind(boundary, left, start)
        if found >= 0:
            left = max(left, found + 1)
    endings = [
        found
        for boundary in ".;\n"
        if (found := text.find(boundary, end, right)) >= 0
    ]
    if endings:
        right = min(endings) + 1
    return f"{text[left:start]}[[{text[start:end]}]]{text[end:right]}".strip()


def _write_immutable(path: Path, payload: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace changed residual inventory: {path}")
    atomic_write_text(path, payload)


def freeze_compound_operator_scope(
    *,
    stage_path: Path,
    inventory_path: Path,
    signatures_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    """Write one immutable row per scoped span and prove exact source accounting."""

    if len(
        {
            stage_path.resolve(),
            inventory_path.resolve(),
            signatures_path.resolve(),
            report_path.resolve(),
        }
    ) != 4:
        raise ValueError("residual inventory inputs and outputs must be distinct")
    rows: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    signature_counts: Counter[tuple[Any, ...]] = Counter()
    duplicate_ordinals: Counter[tuple[Any, ...]] = Counter()
    segments = 0
    with stage_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"{stage_path}:{line_number}: record is not an object")
            segments += 1
            text = str(record.get("text", "") or "")
            segment = (
                str(record.get("source", "") or ""),
                str(record.get("source_id", "") or ""),
                int(record.get("source_segment_index", 0) or 0),
                str(record.get("taxon", "") or ""),
            )
            for span in record.get("unresolved_spans", []) or []:
                if not isinstance(span, dict) or span.get("reason") not in TARGET_REASONS:
                    continue
                try:
                    start, end = int(span["start"]), int(span["end"])
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError(
                        f"{stage_path}:{line_number}: scoped span has invalid offsets"
                    ) from error
                surface = str(span.get("surface_form", "") or "")
                if start < 0 or end <= start or end > len(text) or text[start:end] != surface:
                    raise ValueError(
                        f"{stage_path}:{line_number}: scoped span is not verbatim at {start}:{end}"
                    )
                identity = (
                    *segment,
                    start,
                    end,
                    surface,
                    str(span.get("reason", "") or ""),
                    str(span.get("candidate_pato_id", "") or ""),
                    str(span.get("extractor", "") or ""),
                )
                ordinal = duplicate_ordinals[identity]
                duplicate_ordinals[identity] += 1
                context = _context(text, start, end)
                signature = (
                    normalized_text(surface),
                    identity[-3],
                    identity[-2],
                    str(record.get("language", "") or ""),
                    normalized_text(record.get("organ", "")),
                    normalized_text(span.get("pending_bearer", "")),
                    tuple(sorted(str(value) for value in span.get("promoted_po_ids", []) or [])),
                )
                span_id = stable_id("residual", (*identity, ordinal))
                rows.append(
                    {
                        "span_id": span_id,
                        "source": segment[0],
                        "source_id": segment[1],
                        "source_segment_index": segment[2],
                        "taxon": segment[3],
                        "organ": str(record.get("organ", "") or ""),
                        "language": str(record.get("language", "") or ""),
                        "start": start,
                        "end": end,
                        "surface_form": surface,
                        "reason": identity[-3],
                        "candidate_pato_id": identity[-2],
                        "extractor": identity[-1],
                        "pending_bearer": str(span.get("pending_bearer", "") or ""),
                        "promoted_po_ids": sorted(
                            str(value) for value in span.get("promoted_po_ids", []) or []
                        ),
                        "segment_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "context_sha256": hashlib.sha256(context.encode()).hexdigest(),
                        "routing_signature_sha256": hashlib.sha256(
                            canonical_json(signature).encode()
                        ).hexdigest(),
                    }
                )
                reason_counts[identity[-3]] += 1
                signature_counts[signature] += 1

    identifiers = [row["span_id"] for row in rows]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("residual span identifier collision")
    rows.sort(key=lambda row: row["span_id"])
    signatures = [
        {
            "routing_signature_sha256": hashlib.sha256(
                canonical_json(signature).encode()
            ).hexdigest(),
            "normalized_form": signature[0],
            "reason": signature[1],
            "candidate_pato_id": signature[2],
            "language": signature[3],
            "organ": signature[4],
            "pending_bearer": signature[5],
            "promoted_po_ids": list(signature[6]),
            "occurrence_count": count,
        }
        for signature, count in sorted(
            signature_counts.items(), key=lambda item: (-item[1], canonical_json(item[0]))
        )
    ]
    _write_immutable(
        inventory_path,
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
    )
    _write_immutable(
        signatures_path,
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in signatures
        ),
    )
    report = {
        "schema_version": "flopo-compound-operator-residual-inventory-v1",
        "stage": sha256_file(stage_path).model_dump(mode="json"),
        "segments": segments,
        "target_reasons": sorted(TARGET_REASONS),
        "starting_spans": len(rows),
        "distinct_span_ids": len(set(identifiers)),
        "duplicate_physical_rows": sum(
            count - 1 for count in duplicate_ordinals.values() if count > 1
        ),
        "reason_counts": dict(sorted(reason_counts.items())),
        "routing_signatures": len(signatures),
        "conserved": sum(reason_counts.values()) == len(rows),
        "artifacts": {
            "inventory": sha256_file(inventory_path).model_dump(mode="json"),
            "signatures": sha256_file(signatures_path).model_dump(mode="json"),
        },
    }
    _write_immutable(
        report_path, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--signatures", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = freeze_compound_operator_scope(
        stage_path=args.stage,
        inventory_path=args.inventory,
        signatures_path=args.signatures,
        report_path=args.report,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
