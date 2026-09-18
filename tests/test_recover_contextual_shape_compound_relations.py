from __future__ import annotations

import json
from pathlib import Path

from flopo2.verify.recover_contextual_shape_compound_relations import (
    prepare_contextual_shape_compound_review,
)
from flopo2.verify.recover_shape_compound_relations import prepare_shape_compound_review


def _span(text: str, value: str, pato_id: str, *, offset: int = 0) -> dict:
    start = text.index(value, offset)
    return {
        "start": start,
        "end": start + len(value),
        "surface_form": value,
        "reason": "hyphenated_or_slash_compound",
        "candidate_pato_id": pato_id,
        "extractor": "fixture",
    }


def _record(text: str, spans: list[dict]) -> dict:
    return {
        "source": "fixture",
        "source_id": f"{abs(hash(text))}.xml",
        "source_segment_index": 0,
        "taxon": "Planta exemplaris",
        "organ": "leaves",
        "language": "en",
        "char_start": 0,
        "char_end": len(text),
        "text": text,
        "assertions": [],
        "unresolved_spans": spans,
    }


def _catalogs(tmp_path: Path) -> tuple[Path, Path, Path]:
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\tslim\n"
        "PO_0009025\tvascular leaf\tleaves|leaf\tplant_anatomy\n",
        encoding="utf-8",
    )
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tsynonyms\tslim\n"
        "PATO_0000052\tshape\t\tattribute_slim\n"
        "PATO_0000946\toblong\t\tvalue_slim\n"
        "PATO_0000947\telliptic\t\tvalue_slim\n"
        "PATO_0001199\tlinear\t\tvalue_slim\n"
        "PATO_0001877\tlanceolate\t\tvalue_slim\n"
        "PATO_0001891\tovate\t\tvalue_slim\n"
        "PATO_0002228\tacuminate\t\tvalue_slim\n",
        encoding="utf-8",
    )
    combinations = tmp_path / "combinations.tsv"
    combinations.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_0009025\tPATO_0000052\tallowed\tfixture\tleaf shape\n",
        encoding="utf-8",
    )
    return po, pato, combinations


def test_requeues_only_contextual_first_wave_exclusions(tmp_path: Path) -> None:
    isolated = "Leaves oblong-elliptic."
    isolated_spans = [
        _span(isolated, "oblong", "PATO_0000946"),
        _span(isolated, "elliptic", "PATO_0000947"),
    ]
    contextual = "Leaves linear-lanceolate or ovate."
    contextual_spans = [
        _span(contextual, "linear", "PATO_0001199"),
        _span(contextual, "lanceolate", "PATO_0001877"),
    ]
    cross_aspect = "Leaves ovate-acuminate."
    cross_spans = [
        _span(cross_aspect, "ovate", "PATO_0001891"),
        _span(cross_aspect, "acuminate", "PATO_0002228"),
    ]
    stage = tmp_path / "stage.jsonl"
    stage.write_text(
        "".join(
            json.dumps(row) + "\n"
            for row in (
                _record(isolated, isolated_spans),
                _record(contextual, contextual_spans),
                _record(cross_aspect, cross_spans),
            )
        ),
        encoding="utf-8",
    )
    po, pato, combinations = _catalogs(tmp_path)
    first_review = tmp_path / "first-review.jsonl"
    first_candidates = tmp_path / "first-candidates.jsonl"
    first_spans = tmp_path / "first-spans.jsonl"
    prepare_shape_compound_review(
        stage_path=stage,
        review_input_path=first_review,
        candidate_ledger_path=first_candidates,
        span_ledger_path=first_spans,
        report_path=tmp_path / "first-report.json",
        po_lexicon_path=po,
        pato_lexicon_path=pato,
        combinations_path=combinations,
    )

    review = tmp_path / "review.jsonl"
    candidates = tmp_path / "candidates.jsonl"
    spans = tmp_path / "spans.jsonl"
    report = prepare_contextual_shape_compound_review(
        stage_path=stage,
        prior_span_ledger_path=first_spans,
        review_input_path=review,
        candidate_ledger_path=candidates,
        span_ledger_path=spans,
        report_path=tmp_path / "report.json",
        po_lexicon_path=po,
        pato_lexicon_path=pato,
        combinations_path=combinations,
    )

    assert report["target_spans"] == 4
    assert report["counts"]["prior_candidate_spans_skipped"] == 2
    assert report["candidates"] == 1
    assert report["candidate_spans"] == 2
    assert report["exclusions"] == 2
    assert report["conserved"] is True
    review_row = json.loads(review.read_text(encoding="utf-8"))
    candidate = review_row["unresolved_spans"][0]["qualitative_relation_candidate"]
    assert candidate["expression_text"] == "linear-lanceolate"
    assert candidate["signature"]["from_value"] == "PATO_0001199"
    assert candidate["signature"]["to_value"] == "PATO_0001877"
    ledger = json.loads(candidates.read_text(encoding="utf-8"))
    assert "logical_compound_context" in ledger["risk_flags"]
    span_rows = [json.loads(line) for line in spans.read_text().splitlines()]
    assert {row["status"] for row in span_rows} == {"candidate", "excluded"}
    assert {
        row["reason"] for row in span_rows if row["status"] == "excluded"
    } == {"not_two_distinct_gross_outline_values"}
