import csv
import json
from pathlib import Path

from flopo2.verify.classify_unresolved import (
    Classification,
    HyphenForm,
    ReferenceDecision,
    classify_explicit_disjunction,
    classify_file,
    classify_hyphen,
    classify_missing_bearer,
    classify_residual_logic,
    classify_stage,
    compound_bounds,
    normalise_compound,
)


def test_compound_bounds_reconstructs_spaced_hyphen_token():
    text = "leaves oblong- elliptic and green"
    start = text.index("elliptic")
    left, right = compound_bounds(text, start, start + len("elliptic"))
    assert text[left:right] == "oblong- elliptic"
    assert normalise_compound(text[left:right]) == "oblong elliptic"


def test_explicit_disjunction_uses_audited_ungrounded_operand_route():
    classification = classify_explicit_disjunction(
        {"candidate_pato_id": "PATO_0001935"},
        [ReferenceDecision("routed", "", "ungrounded_operand")],
    )
    assert classification.initiative == "lexicon_or_ontology_term"
    assert classification.subtype == "disjunction_operand_not_normalized"


def test_numeric_disjunction_is_a_class_expression_model_task():
    classification = classify_explicit_disjunction(
        {"candidate_pato_id": "PATO_0000122"},
        [ReferenceDecision("routed", "", "ungrounded_operand")],
    )
    assert classification.subtype == "numeric_trait_disjunction"
    assert classification.priority == "3_model_extension"


def test_residual_range_with_ungrounded_endpoint_routes_to_vocabulary():
    classification = classify_residual_logic(
        "unsupported_alternative_or_transition",
        [
            ReferenceDecision(
                "retained",
                "qualitative_range_or_transition",
                "range_endpoint_not_fully_grounded",
            )
        ],
    )
    assert classification.initiative == "lexicon_or_ontology_term"
    assert classification.subtype == "qualitative_range_endpoint_not_normalized"


def test_hyphen_existing_pato_is_quick_lexing_work():
    classification = classify_hyphen(
        HyphenForm("F1_atomic_pato", "atomic_colour", "promote_atomic_guarded", ""),
        "yellow-green",
    )
    assert classification.subtype == "existing_atomic_pato_whole_token"
    assert classification.priority == "1_quick_win"


def test_leading_dash_singleton_is_logical_ellipsis_not_ocr():
    classification = classify_hyphen(
        HyphenForm(
            "F11_singleton",
            "reconstruction_singleton",
            "residual",
            "prefix inherited from prior coordinated form",
        ),
        "-elliptic",
    )

    assert classification.initiative == "logical_expression_parser"
    assert classification.subtype == "elliptical_compound_shorthand"
    assert classification.priority == "3_model_extension"


def test_stage_no_bearer_routes_to_bearer_work():
    classification = classify_stage("retained_no_bearer")
    assert classification.initiative == "bearer_ontology_and_attachment"
    assert classification.subtype == "stage_expression_missing_bearer"


def test_missing_bearer_detects_local_subregion():
    text = "corolla red at the throat"
    record = {"text": text, "organ": "corolla"}
    span = {
        "start": text.index("red"),
        "end": text.index("red") + 3,
        "candidate_pato_id": "PATO_0000322",
    }
    classification = classify_missing_bearer(record, span)
    assert classification.initiative == "bearer_ontology_and_attachment"
    assert classification.subtype == "local_subregion_bearer_or_parthood"


def test_generic_description_heading_requires_local_parser_not_new_po_term():
    text = "ray 10 mm long"
    record = {"text": text, "organ": "description"}
    span = {
        "start": text.index("10 mm long"),
        "end": len(text),
        "candidate_pato_id": "PATO_0000122",
    }
    classification = classify_missing_bearer(record, span)
    assert classification.subtype == "free_text_description_requires_local_bearer"
    assert classification.priority == "3_model_extension"


def test_sex_qualified_heading_routes_to_context_model():
    text = "red and glabrous"
    record = {"text": text, "organ": "male flowers"}
    span = {
        "start": 0,
        "end": 3,
        "candidate_pato_id": "PATO_0000322",
    }
    classification = classify_missing_bearer(record, span)
    assert classification.initiative == "context_annotation_model"
    assert classification.subtype == "sex_or_state_qualified_bearer_heading"


def _write_tsv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def test_classify_file_preserves_one_output_row_per_span(tmp_path):
    text = "leaves red or green when young; corolla red at throat"
    record = {
        "source": "fixture",
        "source_id": "1",
        "source_segment_index": 0,
        "taxon": "Quercus example",
        "organ": "leaves",
        "language": "en",
        "text": text,
        "unresolved_spans": [
            {
                "start": text.index("red"),
                "end": text.index("red") + 3,
                "surface_form": "red",
                "candidate_pato_id": "PATO_0000322",
                "reason": "explicit_disjunction",
                "extractor": "fixture",
            },
            {
                "start": text.index("green"),
                "end": text.index("green") + 5,
                "surface_form": "green",
                "candidate_pato_id": "PATO_0000320",
                "reason": "developmental_stage_context",
                "extractor": "fixture",
            },
            {
                "start": text.rindex("red"),
                "end": text.rindex("red") + 3,
                "surface_form": "red",
                "candidate_pato_id": "PATO_0000322",
                "reason": "missing_or_unsupported_bearer",
                "extractor": "fixture",
            },
        ],
    }
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    explicit_path = tmp_path / "explicit.tsv"
    _write_tsv(
        explicit_path,
        [
            "status",
            "route",
            "reason",
            "source",
            "source_id",
            "source_segment_index",
            "expression_start",
            "expression_end",
        ],
        [
            {
                "status": "routed",
                "route": "",
                "reason": "ungrounded_operand",
                "source": "fixture",
                "source_id": "1",
                "source_segment_index": 0,
                "expression_start": text.index("red"),
                "expression_end": text.index("red") + 3,
            }
        ],
    )
    stage_path = tmp_path / "stage.tsv"
    _write_tsv(
        stage_path,
        [
            "source",
            "source_id",
            "source_segment_index",
            "organ",
            "surface_form",
            "candidate_pato_id",
            "disposition",
        ],
        [
            {
                "source": "fixture",
                "source_id": "1",
                "source_segment_index": 0,
                "organ": "leaves",
                "surface_form": "green",
                "candidate_pato_id": "PATO_0000320",
                "disposition": "r2_not_atomic_safe",
            }
        ],
    )
    output_path = tmp_path / "classified.tsv"
    summary_path = tmp_path / "summary.json"
    markdown_path = tmp_path / "report.md"
    summary = classify_file(
        input_path,
        output_path,
        summary_path,
        explicit_decisions_path=explicit_path,
        stage_audit_path=stage_path,
        markdown_path=markdown_path,
        expected_total=3,
    )
    assert summary["total_spans"] == 3
    assert sum(summary["by_initiative"].values()) == 3
    with output_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == 3
    assert rows[0]["classification_basis"] == "explicit_disjunction_audit"
    assert rows[1]["subtype"] == "complex_stage_scoped_expression"
    assert rows[2]["subtype"] == "local_subregion_bearer_or_parthood"
    assert json.loads(summary_path.read_text())["accounting_ok"] is True
    assert "Total classified spans" in markdown_path.read_text()


def test_classification_dataclass_is_stable():
    value = Classification("initiative", "subtype", "action", "priority", "basis")
    assert value.detail == ""
