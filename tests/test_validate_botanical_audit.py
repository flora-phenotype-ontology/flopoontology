from __future__ import annotations

import json

from flopo2.terminology.validate_audit import SCHEMAS, existing_exact_forms, validate_run


def _write_minimal_run(run_dir):
    run_dir.mkdir()
    for filename in (
        "00-executive-summary.md",
        "05-mapping-sota.md",
        "07-adversarial-review.md",
    ):
        (run_dir / filename).write_text("# Result\n\n" + "Evidence-based result. " * 8)
    for filename, fields in SCHEMAS.items():
        prefix = "# curie_map:\n#   PATO: http://purl.obolibrary.org/obo/PATO_\n" if "sssom" in filename else ""
        (run_dir / filename).write_text(prefix + "\t".join(fields) + "\n", encoding="utf-8")
    (run_dir / "08-unresolved.tsv").write_text("surface_form\treason\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "model": "claude-sonnet",
                "run_time": "now",
                "inputs": [],
                "outputs": [],
                "agents": [],
            }
        ),
        encoding="utf-8",
    )


def test_validate_minimal_complete_run(tmp_path):
    run_dir = tmp_path / "run"
    _write_minimal_run(run_dir)

    report = validate_run(run_dir, tmp_path)

    assert report.valid, report.errors


def test_validator_rejects_curator_orcid_on_llm_mapping(tmp_path):
    run_dir = tmp_path / "run"
    _write_minimal_run(run_dir)
    mapping = run_dir / "06-mapping-proposals.sssom.tsv"
    mapping.write_text(
        mapping.read_text()
        + "BTERM:x\tsilvery\tskos:exactMatch\tPATO_0000001\tquality\t"
        "semapv:SemanticSimilarityMatching\t2026-07-14\t"
        "orcid:0000-0001-8149-5890\t0.9\tclaude\tregistry\tproposed\n",
        encoding="utf-8",
    )

    report = validate_run(run_dir, tmp_path)

    assert not report.valid
    assert any("curator ORCID" in error for error in report.errors)


def test_validator_allows_additional_sssom_columns(tmp_path):
    run_dir = tmp_path / "run"
    _write_minimal_run(run_dir)
    mapping = run_dir / "06-mapping-proposals.sssom.tsv"
    lines = mapping.read_text().splitlines()
    lines[-1] += "\tobject_source"
    mapping.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = validate_run(run_dir, tmp_path)

    assert report.valid, report.errors


def test_existing_exact_forms_reads_labels_and_exact_synonyms_only(tmp_path):
    ont = tmp_path / "ont"
    ont.mkdir()
    (ont / "plant_ontology.obo").write_text("format-version: 1.2\n", encoding="utf-8")
    (ont / "quality.obo").write_text(
        """format-version: 1.2

[Term]
id: PATO:0001373
name: glistening
synonym: "glossy" EXACT []
synonym: "sparkly" RELATED []
""",
        encoding="utf-8",
    )

    forms = existing_exact_forms(tmp_path)

    assert forms["glistening"] == {"PATO_0001373"}
    assert forms["glossy"] == {"PATO_0001373"}
    assert "sparkly" not in forms


def test_existing_exact_forms_reads_additional_current_ontology(tmp_path):
    current = tmp_path / "pato-current.obo"
    current.write_text(
        """format-version: 1.2

[Term]
id: PATO:0104001
name: creamy
""",
        encoding="utf-8",
    )

    forms = existing_exact_forms(tmp_path, [current])

    assert forms["creamy"] == {"PATO_0104001"}


def test_validator_requires_exact_disjoint_surface_partition(tmp_path):
    run_dir = tmp_path / "run"
    _write_minimal_run(run_dir)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"unresolved": {"missing_surfaces": [["silvery", 3], ["leafy", 2]]}}),
        encoding="utf-8",
    )

    mapping = run_dir / "06-mapping-proposals.sssom.tsv"
    mapping.write_text(
        mapping.read_text()
        + "BTERM:silvery\tsilvery\tskos:exactMatch\tPATO_0000001\tquality\t"
        "semapv:SemanticSimilarityMatching\t2026-07-14\tclaude\t0.9\tclaude\t"
        "registry\tproposed\n"
        + "BTERM:silver\tsilver\tskos:closeMatch\tPATO_0000001\tquality\t"
        "semapv:SemanticSimilarityMatching\t2026-07-14\tclaude\t0.7\tclaude\t"
        "registry\tproposed\n",
        encoding="utf-8",
    )
    classified = run_dir / "06-new-class-or-noise.tsv"
    classified.write_text(
        classified.read_text()
        + "BTERM:silvery\tsilvery\t3\tquality\tuncertain\tPATO\tsilvery\tcontext\t"
        "rationale\tevidence\t0.5\tcaveat\n",
        encoding="utf-8",
    )

    report = validate_run(run_dir, tmp_path, baseline)

    assert not report.valid
    assert any("occur in both" in error for error in report.errors)
    assert any("off-baseline" in error for error in report.errors)
    assert any("1 of 2 missing" in error for error in report.errors)
