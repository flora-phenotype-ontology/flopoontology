"""Correction delta: remove one-surface values asserted for a whole laminar organ.

``limbe … glabre en dessus, pubescent en dessous`` was asserted as ``leaf lamina glabrous`` (and
``pubescent``) by the deterministic baseline.  Each accepted colour/pilosity/texture assertion on a
whole laminar bearer (:data:`flopo2.extract.surface_context.LAMINAR_BEARERS`) whose own comma
member restricts it to one surface is removed, and its value span is restored as unresolved
(``missing_or_unsupported_bearer``, ``pending_bearer`` "upper surface"/"lower surface"/"other
surface").  Values stated for both surfaces are kept.  Assertions an earlier correction already
removed are skipped.  Leaf/leaf-lamina values whose side maps to an approved PO_0000050/PO_0000049
pair are listed as re-bearing candidates only.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from flopo2.extract import baseline
from flopo2.extract.surface_context import LAMINAR_BEARERS, single_side_restriction
from flopo2.verify.apply_deltas import DELTA_KEY_FIELDS, REMOVE_FIELDS
from flopo2.verify.gates import load_combinations

EXTRACTOR = "surface_restriction_correction_v1"
_PILOSITY = re.compile(
    r"glabr|pubesc|tomentose|tomentell|hairy|pilose|villous|hirsute|sericeous|velutinous|puberul|"
    r"strigose|hispid|ciliat|scabr|lanate|woolly|arachnoid|floccose|setose|stellate|lepidote|"
    r"scaly|glandular",
    re.I,
)
_TEXTURE = re.compile(
    r"smooth|rough|glossy|shiny|shining|dull|glaucous|papillose|punctate|rugose|verrucose|"
    r"reticulate|wrinkled|glistening|coriaceous|lustrous|waxy|pruinose",
    re.I,
)
SURFACE_BEARER = {"upper": "PO_0000050", "lower": "PO_0000049"}
LEAF_BEARERS = frozenset({"PO_0009025", "PO_0020039", "PO_0025034"})


def value_family(assertion: dict[str, Any], labels: dict[str, str]) -> str:
    ids = [assertion.get("pato_id", ""), *(assertion.get("value_terms") or [])]
    relation = assertion.get("qualitative_value_relation") or {}
    ids += [relation.get("from_value", ""), relation.get("to_value", "")]
    if any(i in baseline.COLOR_PATO_IDS or i == "PATO_0000014" for i in ids):
        return "colour"
    if any(_PILOSITY.search(labels.get(i, "")) or i == "PATO_0000066" for i in ids):
        return "pilosity"
    if any(_TEXTURE.search(labels.get(i, "")) or i == "PATO_0000150" for i in ids):
        return "texture"
    return ""


def value_span(assertion: dict[str, Any]) -> tuple[int, int]:
    start, end = int(assertion["source_start"]), int(assertion["source_end"])
    source = assertion.get("source_text") or ""
    value = assertion.get("value_text") or assertion.get("raw_quality_text") or ""
    if value and value in source and len(source) > len(value):
        start += source.index(value)
        end = start + len(value)
    return start, end


def correct_record(
    record: dict[str, Any],
    labels: dict[str, str],
    skip: set[tuple[Any, ...]] = frozenset(),
    counts: Counter[str] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    counts = counts if counts is not None else Counter()
    text = str(record.get("text", "") or "")
    present = {
        (int(u["start"]), int(u["end"]), u.get("reason"))
        for u in record.get("unresolved_spans", []) or []
    }
    removals, restored, sides = [], [], []
    for assertion in record.get("assertions", []) or []:
        if assertion.get("po_id") not in LAMINAR_BEARERS:
            continue
        if (assertion.get("gate") or {}).get("status") != "accepted":
            continue
        family = value_family(assertion, labels)
        if not family:
            continue
        start, end = value_span(assertion)
        side = single_side_restriction(text, start, end)
        if not side:
            continue
        identity = tuple(assertion.get(name) for name in REMOVE_FIELDS)
        if identity in skip:
            counts["skipped_already_corrected"] += 1
            continue
        if (start, end, "missing_or_unsupported_bearer") in present:
            counts["skipped_span_already_unresolved"] += 1
            continue
        present.add((start, end, "missing_or_unsupported_bearer"))
        removals.append(dict(zip(REMOVE_FIELDS, identity)))
        restored.append(
            {
                "start": start,
                "end": end,
                "surface_form": text[start:end],
                "reason": "missing_or_unsupported_bearer",
                "candidate_pato_id": assertion.get("pato_id", ""),
                "extractor": EXTRACTOR,
                "pending_bearer": f"{side} surface",
            }
        )
        sides.append((assertion, side, start, end))
        counts["removed"] += 1
        counts[f"removed:{assertion['po_id']}:{family}:{side}"] += 1
        counts[f"extractor:{assertion.get('extractor', '')}"] += 1
    if not removals:
        return None, []
    line = {
        "key": {name: record.get(name) for name in DELTA_KEY_FIELDS},
        "add_source_statements": [],
        "add_assertions": [],
        "remove_unresolved": [],
        "remove_assertions": removals,
        "add_unresolved": restored,
    }
    return line, sides


def build(stage: Path, out_dir: Path, skip_corrections: list[Path]) -> dict[str, Any]:
    with Path("config/pato_lexicon.tsv").open(encoding="utf-8", newline="") as handle:
        labels = {row["id"]: row.get("label", "") for row in csv.DictReader(handle, delimiter="\t")}
    skip: set[tuple[Any, ...]] = set()
    for path in skip_corrections:
        for raw in path.open(encoding="utf-8"):
            if raw.strip():
                for removal in json.loads(raw).get("remove_assertions", []) or []:
                    skip.add(tuple(removal.get(name) for name in REMOVE_FIELDS))
    combos = load_combinations()
    counts: Counter[str] = Counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    rebear = []
    lines = 0
    with (out_dir / "surface-correction-delta.jsonl").open("w", encoding="utf-8") as handle:
        for raw in stage.open(encoding="utf-8"):
            record = json.loads(raw)
            line, sides = correct_record(record, labels, skip, counts)
            if line is None:
                continue
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
            lines += 1
            text = record.get("text", "")
            for assertion, side, start, end in sides:
                target = SURFACE_BEARER.get(side)
                combo = combos.get((target, assertion.get("pato_id", ""))) if target else None
                if (
                    assertion["po_id"] in LEAF_BEARERS
                    and (assertion.get("value_operator") or "atomic") == "atomic"
                    and combo is not None
                    and combo.status == "allowed"
                ):
                    rebear.append(
                        {
                            "source": record.get("source"),
                            "source_id": record.get("source_id"),
                            "source_segment_index": record.get("source_segment_index"),
                            "po_from": assertion["po_id"],
                            "po_to": target,
                            "pato_id": assertion.get("pato_id"),
                            "value": text[start:end],
                            "window": text[max(0, start - 80) : end + 40].replace("\t", " "),
                        }
                    )
    if rebear:
        with (out_dir / "surface-rebear-candidates.tsv").open("w", encoding="utf-8", newline="") as h:
            writer = csv.DictWriter(h, fieldnames=list(rebear[0]), delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rebear)
    report = {"lines": lines, "rebear_candidates_allowed_pair": len(rebear), **dict(sorted(counts.items()))}
    (out_dir / "surface-correction-report.json").write_text(
        json.dumps(report, indent=1) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("stage", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--skip-correction", type=Path, action="append", default=[])
    args = parser.parse_args()
    report = build(args.stage, args.out_dir, args.skip_correction)
    print(json.dumps({k: v for k, v in report.items() if not k.startswith("removed:")}, indent=1))


if __name__ == "__main__":
    main()
