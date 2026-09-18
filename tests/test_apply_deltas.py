"""Tests for the generic, precedence-resolved delta applier."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from flopo2.verify.apply_deltas import (
    DeltaError,
    apply_line,
    load_manifest,
    merge,
    merge_held,
)

TEXT = "Leaves ovate-lanceolate, red-brown, glabrous or hairy."
# offsets: ovate 7-12, lanceolate 13-23, red 25-28, brown 29-34, glabrous 36-44, hairy 48-53
KEY = {
    "source": "kew",
    "source_id": "1",
    "source_segment_index": 0,
    "taxon": "Foo bar",
    "organ": "leaf",
    "char_start": 0,
    "char_end": len(TEXT),
}


def _record(**extra) -> dict:
    record = {
        **KEY,
        "text": TEXT,
        "language": "en",
        "assertions": [
            {
                "po_id": "PO_1",
                "pato_id": "PATO_OLD",
                "source_statement_id": "st-old",
                "source_start": 36,
                "source_end": 44,
                "source_text": TEXT[36:44],
            }
        ],
        "source_statements": [
            {"statement_id": "st-old", "start": 36, "end": 44, "verbatim_text": TEXT[36:44]}
        ],
        "unresolved_spans": [
            {"start": 7, "end": 12, "reason": "hyphenated_or_slash_compound", "surface_form": "ovate"},
            {"start": 13, "end": 23, "reason": "hyphenated_or_slash_compound", "surface_form": "lanceolate"},
            {"start": 25, "end": 28, "reason": "hyphenated_or_slash_compound", "surface_form": "red"},
            {"start": 29, "end": 34, "reason": "hyphenated_or_slash_compound", "surface_form": "brown"},
        ],
    }
    record.update(extra)
    return record


def _statement(start: int, end: int, sid: str) -> dict:
    return {"statement_id": sid, "start": start, "end": end, "verbatim_text": TEXT[start:end]}


def _assertion(start: int, end: int, sid: str, pato: str = "PATO_SHAPE", **extra) -> dict:
    row = {
        "po_id": "PO_1",
        "pato_id": pato,
        "source_statement_id": sid,
        "source_start": start,
        "source_end": end,
        "source_text": TEXT[start:end],
        "value_operator": "atomic",
        "value_terms": [],
        "extractor": "x",
        "gate": {"status": "accepted"},
        "mapping_provenance": [],
    }
    row.update(extra)
    return row


def _span(start: int, end: int, reason: str = "hyphenated_or_slash_compound") -> dict:
    return {"start": start, "end": end, "reason": reason, "surface_form": TEXT[start:end]}


def _delta(assertions=(), statements=(), clears=(), **extra) -> dict:
    return {
        "key": dict(KEY),
        "add_source_statements": list(statements),
        "add_assertions": list(assertions),
        "remove_unresolved": list(clears),
        **extra,
    }


def _shape_delta(sid: str = "st-shape", **assertion_extra) -> dict:
    return _delta(
        [_assertion(7, 23, sid, **assertion_extra)],
        [_statement(7, 23, sid)],
        [_span(7, 12), _span(13, 23)],
    )


def _write(path: Path, rows) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _setup(tmp_path: Path, entries: list[tuple[dict, list[dict]]], records=None) -> Path:
    base = _write(tmp_path / "base.jsonl", records or [_record()])
    manifest_entries = []
    for index, (entry, rows) in enumerate(entries):
        path = _write(tmp_path / f"delta{index}.jsonl", rows)
        manifest_entries.append({**entry, "path": str(path)})
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"base": str(base), "deltas": manifest_entries}), encoding="utf-8")
    return manifest


def _run(tmp_path: Path, manifest: Path) -> tuple[dict, list[dict], dict]:
    base, specs = load_manifest(manifest)
    report = merge(base, specs, tmp_path / "out.jsonl", tmp_path / "conflicts.tsv")
    with (tmp_path / "conflicts.tsv").open(encoding="utf-8") as handle:
        conflicts = list(csv.DictReader(handle, delimiter="\t"))
    record = json.loads((tmp_path / "out.jsonl").read_text(encoding="utf-8"))
    return report, conflicts, record


def _recovery(name: str, correct: int, n: int) -> dict:
    return {"name": name, "kind": "recovery", "audit": {"correct": correct, "n": n}}


# ---------------------------------------------------------------------------------------------
# Record-level application


def test_apply_line_adds_statement_assertion_and_clears_spans():
    out = apply_line(_record(), _shape_delta(), "d")
    assert [row["source_statement_id"] for row in out["assertions"]] == ["st-old", "st-shape"]
    assert {row["statement_id"] for row in out["source_statements"]} == {"st-old", "st-shape"}
    assert [span["surface_form"] for span in out["unresolved_spans"]] == ["red", "brown"]


def test_apply_line_fails_on_absent_span():
    delta = _shape_delta()
    delta["remove_unresolved"].append(_span(36, 45, "explicit_disjunction"))
    with pytest.raises(DeltaError, match="not present"):
        apply_line(_record(), delta, "d")


def test_apply_line_fails_on_absent_assertion():
    delta = _delta(
        remove_assertions=[
            {"source_statement_id": "st-old", "po_id": "PO_1", "pato_id": "PATO_X", "source_start": 36, "source_end": 44}
        ]
    )
    with pytest.raises(DeltaError, match="matched 0"):
        apply_line(_record(), delta, "d")


def test_apply_line_fails_on_unknown_statement():
    delta = _shape_delta()
    delta["add_source_statements"] = []
    with pytest.raises(DeltaError, match="unknown statement"):
        apply_line(_record(), delta, "d")


def test_apply_line_fails_on_statement_id_reused_for_other_text():
    delta = _shape_delta(sid="st-old")
    delta["add_source_statements"] = [_statement(7, 23, "st-old")]
    with pytest.raises(DeltaError, match="reused"):
        apply_line(_record(), delta, "d")


def test_correction_removes_assertion_and_restores_span():
    delta = _delta(
        remove_assertions=[
            {"source_statement_id": "st-old", "po_id": "PO_1", "pato_id": "PATO_OLD", "source_start": 36, "source_end": 44}
        ],
        add_unresolved=[_span(36, 44, "missing_or_unsupported_bearer")],
    )
    out = apply_line(_record(), delta, "c")
    assert out["assertions"] == []
    assert out["unresolved_spans"][-1]["surface_form"] == "glabrous"
    bad = _delta(add_unresolved=[{"start": 36, "end": 44, "reason": "r", "surface_form": "hairy"}])
    with pytest.raises(DeltaError, match="does not match"):
        apply_line(_record(), bad, "c")


# ---------------------------------------------------------------------------------------------
# Manifest, precedence and failures


def test_precedence_corrections_then_tiebreaks_then_wilson_lower_bound(tmp_path):
    manifest = _setup(
        tmp_path,
        [
            (_recovery("low", 173, 174), []),
            (_recovery("high", 166, 166), []),
            ({"name": "tb", "kind": "tiebreak"}, []),
            ({"name": "fix", "kind": "correction"}, []),
            (_recovery("mid", 160, 160), []),
        ],
    )
    _, specs = load_manifest(manifest)
    assert [spec.name for spec in specs] == ["fix", "tb", "high", "mid", "low"]


def test_recovery_without_audit_is_rejected(tmp_path):
    manifest = _setup(tmp_path, [({"name": "r", "kind": "recovery"}, [])])
    with pytest.raises(DeltaError, match="audit"):
        load_manifest(manifest)


def test_unknown_segment_key_fails(tmp_path):
    delta = _shape_delta()
    delta["key"] = {**KEY, "source_id": "missing"}
    manifest = _setup(tmp_path, [(_recovery("r", 10, 10), [delta])])
    with pytest.raises(DeltaError, match="match no segment"):
        _run(tmp_path, manifest)
    assert not (tmp_path / "out.jsonl").exists()


def test_duplicate_key_within_one_delta_fails(tmp_path):
    manifest = _setup(tmp_path, [(_recovery("r", 10, 10), [_shape_delta(), _shape_delta()])])
    with pytest.raises(DeltaError, match="duplicate delta key"):
        _run(tmp_path, manifest)


def test_merge_reports_counts_and_unresolved_by_reason(tmp_path):
    manifest = _setup(tmp_path, [(_recovery("r", 10, 10), [_shape_delta()])])
    report, conflicts, record = _run(tmp_path, manifest)
    assert conflicts == []
    assert report["per_delta"]["r"]["assertions_added"] == 1
    assert report["per_delta"]["r"]["spans_removed"] == 2
    assert report["unresolved_by_reason"]["hyphenated_or_slash_compound"] == {
        "before": 4,
        "after": 2,
        "change": -2,
    }
    assert len(record["assertions"]) == 2


# ---------------------------------------------------------------------------------------------
# Conflicts


def test_identical_assertions_are_reported_as_duplicate_and_kept_once(tmp_path):
    manifest = _setup(
        tmp_path,
        [
            (_recovery("low", 173, 174), [_shape_delta("st-a")]),
            ({"name": "tb", "kind": "tiebreak"}, [_shape_delta("st-b")]),
        ],
    )
    report, conflicts, record = _run(tmp_path, manifest)
    assert [(row["conflict"], row["winner_delta"], row["loser_delta"]) for row in conflicts] == [
        ("duplicate", "tb", "low")
    ]
    assert [row["source_statement_id"] for row in record["assertions"]] == ["st-old", "st-b"]
    assert "st-a" not in {row["statement_id"] for row in record["source_statements"]}
    assert report["per_delta"]["low"]["segments"] == 0


def test_differing_assertions_on_shared_span_resolve_to_higher_precision(tmp_path):
    other = _delta(
        [_assertion(7, 12, "st-ovate", value_terms=["PATO_OVATE"])],
        [_statement(7, 12, "st-ovate")],
        [_span(7, 12)],
    )
    manifest = _setup(
        tmp_path,
        [(_recovery("low", 150, 160), [other]), (_recovery("high", 160, 160), [_shape_delta()])],
    )
    report, conflicts, record = _run(tmp_path, manifest)
    assert conflicts[0]["conflict"] == "conflict_shared_span"
    assert conflicts[0]["resolution"] == "kept:high;dropped:low"
    assert conflicts[0]["contested_spans"].startswith("7-12:")
    assert report["conflicts"]["by_kind"] == {"conflict_shared_span": 1}
    assert [row["source_statement_id"] for row in record["assertions"]] == ["st-old", "st-shape"]


def test_same_attribute_overlap_is_a_conflict_and_loser_keeps_no_orphan_clears(tmp_path):
    # Loser claims a different shape over an overlapping range but clears only "red"/"brown",
    # which its surviving colour assertion still covers.
    loser = _delta(
        [
            _assertion(0, 12, "st-l1", value_terms=["PATO_OTHER"]),
            _assertion(25, 34, "st-l2", pato="PATO_COLOUR"),
        ],
        [_statement(0, 12, "st-l1"), _statement(25, 34, "st-l2")],
        [_span(25, 28), _span(29, 34)],
    )
    manifest = _setup(
        tmp_path,
        [(_recovery("high", 160, 160), [_shape_delta()]), (_recovery("low", 100, 160), [loser])],
    )
    report, conflicts, record = _run(tmp_path, manifest)
    assert [row["conflict"] for row in conflicts] == ["conflict_same_attribute"]
    assert {row["source_statement_id"] for row in record["assertions"]} == {"st-old", "st-shape", "st-l2"}
    assert record["unresolved_spans"] == []
    assert report["per_delta"]["low"]["assertions_added"] == 1


def test_compatible_overlap_on_other_attribute_is_not_a_conflict(tmp_path):
    colour = _delta(
        [_assertion(0, 34, "st-colour", pato="PATO_COLOUR")],
        [_statement(0, 34, "st-colour")],
        [_span(25, 28), _span(29, 34)],
    )
    manifest = _setup(
        tmp_path,
        [(_recovery("a", 160, 160), [_shape_delta()]), (_recovery("b", 150, 160), [colour])],
    )
    _, conflicts, record = _run(tmp_path, manifest)
    assert conflicts == []
    assert len(record["assertions"]) == 3


def test_assertion_over_span_restored_by_correction_is_dropped(tmp_path):
    correction = _delta(
        remove_assertions=[
            {"source_statement_id": "st-old", "po_id": "PO_1", "pato_id": "PATO_OLD", "source_start": 36, "source_end": 44}
        ],
        add_unresolved=[_span(36, 44, "missing_or_unsupported_bearer")],
    )
    recovery = _delta(
        [_assertion(36, 53, "st-pil", pato="PATO_PILOSITY")], [_statement(36, 53, "st-pil")], []
    )
    manifest = _setup(
        tmp_path,
        [(_recovery("r", 160, 160), [recovery]), ({"name": "fix", "kind": "correction"}, [correction])],
    )
    _, conflicts, record = _run(tmp_path, manifest)
    assert [row["conflict"] for row in conflicts] == ["conflict_correction_restored"]
    assert record["assertions"] == []


def test_later_correction_that_clears_a_restored_span_readmits_it(tmp_path):
    """A readmission correction re-bears the restored quality; a recovery overlap is still dropped."""

    correction = _delta(
        remove_assertions=[
            {"source_statement_id": "st-old", "po_id": "PO_1", "pato_id": "PATO_OLD", "source_start": 36, "source_end": 44}
        ],
        add_unresolved=[_span(36, 44, "missing_or_unsupported_bearer")],
    )
    readmit = _delta(
        [_assertion(36, 44, "st-old", pato="PATO_OLD", po_id="FLOPO_2")],
        [],
        [_span(36, 44, "missing_or_unsupported_bearer")],
    )
    recovery = _delta(
        [_assertion(36, 53, "st-pil", pato="PATO_PILOSITY")], [_statement(36, 53, "st-pil")], []
    )
    manifest = _setup(
        tmp_path,
        [
            (_recovery("r", 160, 160), [recovery]),
            ({"name": "fix", "kind": "correction"}, [correction]),
            ({"name": "readmit", "kind": "correction"}, [readmit]),
        ],
    )
    _, conflicts, record = _run(tmp_path, manifest)
    assert [row["conflict"] for row in conflicts] == ["conflict_correction_restored"]
    assert [(row["po_id"], row["pato_id"]) for row in record["assertions"]] == [("FLOPO_2", "PATO_OLD")]
    assert not any(span["start"] == 36 for span in record["unresolved_spans"])


# ---------------------------------------------------------------------------------------------
# Admission provenance and held carry-over


def test_admission_stamps_only_matching_assertions(tmp_path):
    relation = {"interpretation": "continuum", "from_value": "PATO_OVATE", "to_value": "PATO_LANCEOLATE"}
    admitted = _shape_delta(extractor="rule", qualitative_value_relation=relation)
    colour = _delta(
        [_assertion(25, 34, "st-c", pato="PATO_COLOUR", extractor="rule")],
        [_statement(25, 34, "st-c")],
        [_span(25, 28), _span(29, 34)],
    )
    colour["key"] = {**KEY, "source_id": "2"}
    note = "admission:deterministic_audited_rule:rule:wilson_lb_0.977"
    entry = {
        **_recovery("r", 160, 160),
        "admission": {
            "match": {"extractor": "rule", "gate_status": "accepted", "interpretation": "continuum"},
            "provenance": [note],
        },
    }
    manifest = _setup(
        tmp_path, [(entry, [admitted, colour])], records=[_record(), _record(source_id="2")]
    )
    base, specs = load_manifest(manifest)
    report = merge(base, specs, tmp_path / "out.jsonl", tmp_path / "conflicts.tsv")
    rows = [json.loads(line) for line in (tmp_path / "out.jsonl").read_text().splitlines()]
    assert rows[0]["assertions"][-1]["mapping_provenance"] == [note]
    assert rows[1]["assertions"][-1]["mapping_provenance"] == []
    assert report["precedence"][0]["admission_provenance_stamped"] == 1


def test_merge_held_keeps_retained_relations_under_review(tmp_path):
    held_a = _assertion(7, 23, "st-shape", gate={"status": "review"})
    held_b = _assertion(25, 34, "st-c", pato="PATO_COLOUR", gate={"status": "review"})
    held = _delta(
        [held_a, held_b],
        [_statement(7, 23, "st-shape"), _statement(25, 34, "st-c")],
        [_span(7, 12), _span(13, 23), _span(25, 28), _span(29, 34)],
    )
    admitted = _shape_delta()
    counts = merge_held(
        _write(tmp_path / "admitted.jsonl", [admitted]),
        _write(tmp_path / "held.jsonl", [held]),
        tmp_path / "merged.jsonl",
    )
    merged = json.loads((tmp_path / "merged.jsonl").read_text())
    assert counts == {
        "held_spans_carried": 2,
        "held_assertions_carried": 1,
        "admitted_assertions": 1,
        "segments": 1,
    }
    assert [row["gate"]["status"] for row in merged["add_assertions"]] == ["accepted", "review"]
    assert len(merged["remove_unresolved"]) == 4
    assert {row["statement_id"] for row in merged["add_source_statements"]} == {"st-shape", "st-c"}


def test_merge_held_rejects_admitted_relation_missing_from_held(tmp_path):
    with pytest.raises(DeltaError, match="absent from the held delta"):
        merge_held(
            _write(tmp_path / "admitted.jsonl", [_shape_delta()]),
            _write(tmp_path / "held.jsonl", []),
            tmp_path / "merged.jsonl",
        )


def _update(**fields) -> dict:
    return {
        "source_statement_id": "st-old",
        "po_id": "PO_1",
        "pato_id": "PATO_OLD",
        "source_start": 36,
        "source_end": 44,
        **fields,
    }


def test_update_assertions_sets_provenance_fields_in_place():
    operands = [{"operand_index": 0, "value": "PATO_0000453", "text": "glabrous", "start": 36, "end": 44}]
    line = {"key": KEY, "update_assertions": [
        _update(set={"value_operands": operands}, add_mapping_provenance=["operand_qualifiers:E2"])
    ]}
    out = apply_line(_record(), line, "enrich")
    assert out["assertions"][0]["value_operands"] == operands
    assert out["assertions"][0]["mapping_provenance"] == ["operand_qualifiers:E2"]
    assert len(out["assertions"]) == 1


def test_update_assertions_rejects_identity_fields_and_missing_targets():
    with pytest.raises(DeltaError, match="may not set"):
        apply_line(_record(), {"key": KEY, "update_assertions": [_update(set={"po_id": "PO_2"})]}, "x")
    with pytest.raises(DeltaError, match="matched 0"):
        apply_line(
            _record(),
            {"key": KEY, "update_assertions": [_update(pato_id="PATO_OTHER", set={})]},
            "x",
        )


def test_update_assertions_cannot_change_fac_identity():
    from flopo2.owl.annotation_class import annotation_class_iri

    record = _record()
    assertion = record["assertions"][0]
    assertion.update(po_id="PO_0009025", pato_id="PATO_0000453")
    assertion["phenotype_class_iri"] = annotation_class_iri(assertion)
    target = {
        "source_statement_id": "st-old", "po_id": "PO_0009025", "pato_id": "PATO_0000453",
        "source_start": 36, "source_end": 44,
    }
    approximated = [{
        "operand_index": 0, "value": "PATO_0000453", "text": "glabrous", "start": 36, "end": 44,
        "value_qualifier": "nearly", "qualifier_text": "glabrous", "qualifier_start": 36,
        "qualifier_end": 44,
    }]
    with pytest.raises(DeltaError, match="FAC identity"):
        apply_line(record, {"key": KEY, "update_assertions": [
            {**target, "set": {"value_operands": approximated}}
        ]}, "x")
    approximated[0].pop("value_qualifier")
    out = apply_line(record, {"key": KEY, "update_assertions": [
        {**target, "set": {"value_operands": approximated}}
    ]}, "x")
    assert out["assertions"][0]["phenotype_class_iri"] == assertion["phenotype_class_iri"]
