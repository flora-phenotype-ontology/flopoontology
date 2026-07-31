from __future__ import annotations

import json

import pytest

from flopo2.terminology.compare_audits import compare_runs, load_run_decisions
from flopo2.terminology.validate_audit import SCHEMAS


def _write_run(run_dir, mapping_rows=(), gap_rows=()):
    run_dir.mkdir()
    mapping = run_dir / "06-mapping-proposals.sssom.tsv"
    mapping.write_text(
        "# sssom_version: 1.0\n"
        + "\t".join(SCHEMAS[mapping.name])
        + "\n"
        + "\n".join(mapping_rows)
        + ("\n" if mapping_rows else ""),
        encoding="utf-8",
    )
    gap = run_dir / "06-new-class-or-noise.tsv"
    gap.write_text(
        "\t".join(SCHEMAS[gap.name])
        + "\n"
        + "\n".join(gap_rows)
        + ("\n" if gap_rows else ""),
        encoding="utf-8",
    )


def _mapping(surface, target="PATO:0000001", confidence="0.9"):
    return "\t".join(
        (
            f"BTERM:{surface}", surface, "skos:exactMatch", target, "quality",
            "semapv:LexicalMatching", "2026-07-14", "claude", confidence, "tool", "source",
            "proposed mapping",
        )
    )


def _gap(surface, decision="new_class", confidence="0.4"):
    return "\t".join(
        (
            f"BTERM:{surface}", surface, "1", "quality", decision, "PATO", surface,
            "context", "rationale", "evidence", confidence, "caveat",
        )
    )


def test_compare_runs_marks_agreement_and_disagreement(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"unresolved": {"missing_surfaces": [["silvery", 3], ["leafy", 2]]}}),
        encoding="utf-8",
    )
    run_dirs = [tmp_path / f"run-{index}" for index in range(3)]
    _write_run(run_dirs[0], [_mapping("silvery")], [_gap("leafy")])
    _write_run(run_dirs[1], [_mapping("silvery")], [_gap("leafy")])
    _write_run(run_dirs[2], [_mapping("silvery", "PATO:0000002")], [_gap("leafy")])

    rows, summary = compare_runs(run_dirs, baseline)

    by_surface = {row["surface_form"]: row for row in rows}
    assert by_surface["silvery"]["agreement"] == "disagreement"
    assert by_surface["leafy"]["agreement"] == "unanimous"
    assert summary == {"unanimous": 1, "disagreement": 1, "incomplete": 0, "total": 2}


def test_compare_runs_canonicalizes_obo_curie_syntax(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"unresolved": {"missing_surfaces": [["wide", 1]]}}),
        encoding="utf-8",
    )
    run_dirs = [tmp_path / "run-1", tmp_path / "run-2"]
    _write_run(run_dirs[0], [_mapping("wide", "PATO_0000600")])
    _write_run(run_dirs[1], [_mapping("wide", "PATO:0000600")])

    rows, summary = compare_runs(run_dirs, baseline)

    assert rows[0]["agreement"] == "unanimous"
    assert summary["unanimous"] == 1


def test_load_run_decisions_rejects_overlap(tmp_path):
    run_dir = tmp_path / "run"
    _write_run(run_dir, [_mapping("silvery")], [_gap("silvery")])

    with pytest.raises(ValueError, match="duplicate decision"):
        load_run_decisions(run_dir)
