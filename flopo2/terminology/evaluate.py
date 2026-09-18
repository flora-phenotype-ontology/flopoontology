"""Quantitative evaluation for botanical terminology normalization."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from flopo2.terminology.model import RegistryEntry
from flopo2.terminology.normalize import fold
from flopo2.terminology.registry import read_registry


def _truth(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def _integer(value: str) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def _frequency_slice(value: int) -> str:
    if value <= 0:
        return "zero"
    if value < 10:
        return "1-9"
    if value < 100:
        return "10-99"
    return "100+"


def _prediction_correct(entry: RegistryEntry, gold_ids: set[str], gold_nil: bool) -> bool:
    predicted_nil = not entry.target_id and not entry.components
    if gold_nil:
        return predicted_nil
    if predicted_nil:
        return False
    if entry.target_id and entry.target_id in gold_ids:
        return True
    return bool(entry.components) and set(entry.components) == gold_ids


def _candidate_recalled(candidates: tuple[str, ...], gold_ids: set[str], k: int) -> bool:
    available = set(candidates[:k])
    if len(gold_ids) > 1:
        return gold_ids.issubset(available)
    return bool(gold_ids & available)


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _relation_metrics(records: list[dict]) -> dict:
    annotated = [record for record in records if record["gold_relation"]]
    if not annotated:
        return {"evaluated": 0, "accuracy": 0.0, "macro_f1": 0.0, "by_relation": {}}
    labels = sorted(
        {record["gold_relation"] for record in annotated}
        | {record["predicted_relation"] for record in annotated}
    )
    by_relation = {}
    for label in labels:
        tp = sum(
            record["gold_relation"] == label and record["predicted_relation"] == label
            for record in annotated
        )
        fp = sum(
            record["gold_relation"] != label and record["predicted_relation"] == label
            for record in annotated
        )
        fn = sum(
            record["gold_relation"] == label and record["predicted_relation"] != label
            for record in annotated
        )
        by_relation[label] = _prf(tp, fp, fn)
    correct = sum(
        record["gold_relation"] == record["predicted_relation"] for record in annotated
    )
    return {
        "evaluated": len(annotated),
        "accuracy": round(correct / len(annotated), 4),
        "macro_f1": round(
            sum(metric["f1"] for metric in by_relation.values()) / len(by_relation), 4
        ),
        "by_relation": by_relation,
    }


def _calibration(records: list[dict], bins: int = 10) -> dict:
    if not records:
        return {"brier_score": 0.0, "expected_calibration_error": 0.0, "bins": []}
    brier = sum(
        (record["confidence"] - float(record["correct"])) ** 2 for record in records
    ) / len(records)
    rendered = []
    ece = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        selected = [
            record
            for record in records
            if lower <= record["confidence"] < upper
            or (index == bins - 1 and record["confidence"] == 1.0)
        ]
        if not selected:
            continue
        confidence = sum(record["confidence"] for record in selected) / len(selected)
        accuracy = sum(record["correct"] for record in selected) / len(selected)
        ece += len(selected) / len(records) * abs(confidence - accuracy)
        rendered.append(
            {
                "lower": round(lower, 2),
                "upper": round(upper, 2),
                "count": len(selected),
                "mean_confidence": round(confidence, 4),
                "accuracy": round(accuracy, 4),
            }
        )
    return {
        "brier_score": round(brier, 4),
        "expected_calibration_error": round(ece, 4),
        "bins": rendered,
    }


def _selective_accuracy(records: list[dict]) -> dict[str, dict[str, float | int]]:
    report = {}
    for threshold in (0.5, 0.7, 0.8, 0.9, 0.95):
        selected = [record for record in records if record["confidence"] >= threshold]
        report[f"{threshold:.2f}"] = {
            "selected": len(selected),
            "coverage": round(len(selected) / len(records), 4) if records else 0.0,
            "accuracy": (
                round(sum(record["correct"] for record in selected) / len(selected), 4)
                if selected
                else 0.0
            ),
        }
    return report


def _summary(records: list[dict]) -> dict[str, float | int]:
    mapped = [record for record in records if not record["gold_nil"]]
    nil_tp = sum(record["gold_nil"] and record["predicted_nil"] for record in records)
    nil_fp = sum(not record["gold_nil"] and record["predicted_nil"] for record in records)
    nil_fn = sum(record["gold_nil"] and not record["predicted_nil"] for record in records)
    nil_scores = _prf(nil_tp, nil_fp, nil_fn)
    return {
        "evaluated": len(records),
        "accuracy": (
            round(sum(record["correct"] for record in records) / len(records), 4)
            if records
            else 0.0
        ),
        "mapped_gold": len(mapped),
        "candidate_recall_at_10": (
            round(sum(record["candidate_hits"][10] for record in mapped) / len(mapped), 4)
            if mapped
            else 0.0
        ),
        "nil_f1": nil_scores["f1"],
    }


def _slice_report(records: list[dict]) -> dict[str, dict[str, dict[str, float | int]]]:
    dimensions = ("language", "source", "semantic_role", "frequency", "composition", "split")
    report = {}
    for dimension in dimensions:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for record in records:
            grouped[record[dimension] or "(blank)"].append(record)
        report[dimension] = {
            value: _summary(group) for value, group in sorted(grouped.items())
        }
    return report


def validate_alignment_splits(gold_path: Path) -> dict:
    """Detect synonym, translation, surface, and curated-target leakage across splits."""
    groups: dict[str, set[str]] = defaultdict(set)
    rows_with_split = 0
    with Path(gold_path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            split = (row.get("split") or "").strip()
            if not split:
                continue
            if split not in {"train", "dev", "test"}:
                raise ValueError(f"invalid alignment split {split!r} for {row.get('term_id', '')}")
            rows_with_split += 1
            split_group = (row.get("split_group") or "").strip()
            if split_group:
                groups[f"declared:{split_group}"].add(split)
            translation = (row.get("translation_group") or "").strip()
            if translation:
                groups[f"translation:{translation}"].add(split)
            surface = fold(row.get("surface_form") or "")
            language = (row.get("language") or "").strip()
            if surface:
                groups[f"surface:{language}:{surface}"].add(split)
            for target_id in (row.get("gold_target_ids") or "").split("|"):
                if target_id:
                    groups[f"gold_target:{target_id}"].add(split)
    leaks = {
        group: sorted(splits) for group, splits in sorted(groups.items()) if len(splits) > 1
    }
    return {
        "rows_with_split": rows_with_split,
        "groups_checked": len(groups),
        "leaking_groups": len(leaks),
        "leaks": leaks,
    }


def evaluate_alignment(
    gold_path: Path,
    registry_path: Path = Path("config/botanical_terminology.tsv"),
    k: int = 10,
    auto_threshold: float = 0.95,
    split: str | None = None,
) -> dict:
    """Evaluate retrieval, committed mappings, NIL handling, relations, and calibration."""
    split_validation = validate_alignment_splits(gold_path)
    if split_validation["leaking_groups"]:
        examples = list(split_validation["leaks"])[:5]
        raise ValueError(f"alignment split leakage detected: {examples}")
    registry = {entry.term_id: entry for entry in read_registry(registry_path)}
    records = []
    skipped_unannotated = skipped_unknown = skipped_split = 0
    cutoffs = sorted({1, 5, 10, k})

    with Path(gold_path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            row_split = (row.get("split") or "").strip()
            if split and row_split != split:
                skipped_split += 1
                continue
            gold_ids = {part for part in (row.get("gold_target_ids") or "").split("|") if part}
            gold_nil_text = row.get("gold_is_nil", "")
            if not gold_ids and not gold_nil_text:
                skipped_unannotated += 1
                continue
            gold_nil = _truth(gold_nil_text)
            entry = registry.get(row["term_id"])
            if entry is None:
                skipped_unknown += 1
                continue
            candidates = entry.candidate_id_list
            predicted_nil = not entry.target_id and not entry.components
            predicted_relation = entry.mapping_relation or (
                "flopo:unmapped" if predicted_nil else ""
            )
            records.append(
                {
                    "term_id": entry.term_id,
                    "gold_nil": gold_nil,
                    "predicted_nil": predicted_nil,
                    "correct": _prediction_correct(entry, gold_ids, gold_nil),
                    "candidate_hits": {
                        cutoff: _candidate_recalled(candidates, gold_ids, cutoff)
                        for cutoff in cutoffs
                    },
                    "candidate_top1": _candidate_recalled(candidates, gold_ids, 1),
                    "gold_relation": (row.get("gold_relation") or "").strip(),
                    "predicted_relation": predicted_relation,
                    "confidence": max(0.0, min(1.0, entry.mapping_confidence)),
                    "auto_eligible": entry.mapping_confidence >= auto_threshold
                    and entry.review_status in {"auto", "reviewed", "accepted"},
                    "gold_semantic_role": (row.get("gold_semantic_role") or "").strip(),
                    "predicted_semantic_role": entry.semantic_role,
                    "language": row.get("language") or entry.language,
                    "source": row.get("source_id") or entry.source_id,
                    "semantic_role": row.get("gold_semantic_role")
                    or row.get("semantic_role")
                    or entry.semantic_role,
                    "frequency": _frequency_slice(
                        _integer(row.get("corpus_frequency", ""))
                        if row.get("corpus_frequency", "")
                        else entry.corpus_frequency
                    ),
                    "composition": (
                        "compositional"
                        if entry.components
                        or row.get("gold_logical_operator") in {"all_of", "one_of"}
                        else "atomic"
                    ),
                    "split": row_split,
                }
            )

    mapped = [record for record in records if not record["gold_nil"]]
    nil_tp = sum(record["gold_nil"] and record["predicted_nil"] for record in records)
    nil_fp = sum(not record["gold_nil"] and record["predicted_nil"] for record in records)
    nil_fn = sum(record["gold_nil"] and not record["predicted_nil"] for record in records)
    nil_scores = _prf(nil_tp, nil_fp, nil_fn)
    relation = _relation_metrics(records)
    auto = [record for record in records if record["auto_eligible"]]
    role_records = [record for record in records if record["gold_semantic_role"]]
    candidate_recalls = {
        f"candidate_recall_at_{cutoff}": (
            round(
                sum(record["candidate_hits"][cutoff] for record in mapped) / len(mapped), 4
            )
            if mapped
            else 0.0
        )
        for cutoff in cutoffs
    }
    report = {
        "evaluated": len(records),
        "split_filter": split or "all",
        "split_validation": split_validation,
        "skipped_unannotated": skipped_unannotated,
        "skipped_unknown_term": skipped_unknown,
        "skipped_other_split": skipped_split,
        "mapped_gold": len(mapped),
        "top1_accuracy": (
            round(sum(record["correct"] for record in mapped) / len(mapped), 4)
            if mapped
            else 0.0
        ),
        "candidate_top1_accuracy": (
            round(sum(record["candidate_top1"] for record in mapped) / len(mapped), 4)
            if mapped
            else 0.0
        ),
        **candidate_recalls,
        "relation_accuracy": relation["accuracy"],
        "relation_macro_f1": relation["macro_f1"],
        "relation_metrics": relation,
        "semantic_role_accuracy": (
            round(
                sum(
                    record["gold_semantic_role"] == record["predicted_semantic_role"]
                    for record in role_records
                )
                / len(role_records),
                4,
            )
            if role_records
            else 0.0
        ),
        "nil_precision": nil_scores["precision"],
        "nil_recall": nil_scores["recall"],
        "nil_f1": nil_scores["f1"],
        "nil_counts": {key: nil_scores[key] for key in ("tp", "fp", "fn")},
        "auto_accept_total": len(auto),
        "auto_accept_coverage": round(len(auto) / len(records), 4) if records else 0.0,
        "auto_accept_precision": (
            round(sum(record["correct"] for record in auto) / len(auto), 4) if auto else 0.0
        ),
        "calibration": _calibration(records),
        "selective_accuracy": _selective_accuracy(records),
        "slices": _slice_report(records),
        "acceptance_targets": {
            "candidate_recall_at_10": 0.95,
            "auto_accept_precision": 0.95,
        },
    }
    return report
