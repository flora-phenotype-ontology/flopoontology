from __future__ import annotations

import json
from pathlib import Path

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


def _record(text: str, spans: list[dict], *, organ: str = "leaves") -> dict:
    return {
        "source": "fixture",
        "source_id": f"{abs(hash(text))}.xml",
        "source_segment_index": 0,
        "taxon": "Planta exemplaris",
        "organ": organ,
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


def _run(tmp_path: Path, records: list[dict]):
    stage = tmp_path / "stage.jsonl"
    stage.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    po, pato, combinations = _catalogs(tmp_path)
    review_input = tmp_path / "review.jsonl"
    candidate_ledger = tmp_path / "candidates.jsonl"
    span_ledger = tmp_path / "spans.jsonl"
    report_path = tmp_path / "report.json"
    report = prepare_shape_compound_review(
        stage_path=stage,
        review_input_path=review_input,
        candidate_ledger_path=candidate_ledger,
        span_ledger_path=span_ledger,
        report_path=report_path,
        po_lexicon_path=po,
        pato_lexicon_path=pato,
        combinations_path=combinations,
    )
    return report, review_input, candidate_ledger, span_ledger


def test_prepares_exact_source_bound_shape_continuum(tmp_path: Path) -> None:
    text = "Leaves linear-lanceolate."
    spans = [
        _span(text, "linear", "PATO_0001199"),
        _span(text, "lanceolate", "PATO_0001877"),
    ]
    report, review_input, candidate_ledger, span_ledger = _run(
        tmp_path, [_record(text, spans)]
    )

    assert report["target_spans"] == 2
    assert report["candidates"] == 1
    assert report["candidate_spans"] == 2
    assert report["exclusions"] == 0
    assert report["conserved"] is True
    review = json.loads(review_input.read_text(encoding="utf-8"))
    candidate = review["unresolved_spans"][0]["qualitative_relation_candidate"]
    assert candidate["expression_text"] == "linear-lanceolate"
    assert candidate["connector_text"] == "-"
    assert candidate["signature"] == {
        "bearer_id": "PO_0009025",
        "attribute_id": "PATO_0000052",
        "interpretation": "continuum",
        "from_value": "PATO_0001199",
        "to_value": "PATO_0001877",
    }
    assert candidate["clear_unresolved_spans"] == [
        [spans[0]["start"], spans[0]["end"]],
        [spans[1]["start"], spans[1]["end"]],
    ]
    assert len(candidate_ledger.read_text(encoding="utf-8").splitlines()) == 1
    assert {
        row["status"]
        for row in map(json.loads, span_ledger.read_text(encoding="utf-8").splitlines())
    } == {"candidate"}


def test_excludes_cross_aspect_shape_and_adjacent_operator_but_conserves_spans(
    tmp_path: Path,
) -> None:
    cross = "Leaves ovate-acuminate."
    cross_spans = [
        _span(cross, "ovate", "PATO_0001891"),
        _span(cross, "acuminate", "PATO_0002228"),
    ]
    logical = "Leaves linear-lanceolate or ovate."
    logical_spans = [
        _span(logical, "linear", "PATO_0001199"),
        _span(logical, "lanceolate", "PATO_0001877"),
    ]
    report, review_input, _candidate_ledger, span_ledger = _run(
        tmp_path,
        [_record(cross, cross_spans), _record(logical, logical_spans)],
    )

    assert report["target_spans"] == 4
    assert report["candidates"] == 0
    assert report["exclusions"] == 4
    assert review_input.read_text(encoding="utf-8") == ""
    rows = [json.loads(line) for line in span_ledger.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4
    assert {row["reason"] for row in rows} == {
        "not_two_distinct_gross_outline_values",
        "logical_compound_context",
    }


def test_rejects_existing_assertion_overlap(tmp_path: Path) -> None:
    text = "Leaves oblong-elliptic."
    spans = [
        _span(text, "oblong", "PATO_0000946"),
        _span(text, "elliptic", "PATO_0000947"),
    ]
    record = _record(text, spans)
    record["assertions"] = [
        {
            "po_id": "PO_0009025",
            "pato_id": "PATO_0000946",
            "source_start": spans[0]["start"],
            "source_end": spans[0]["end"],
        }
    ]
    report, _review, _candidates, span_ledger = _run(tmp_path, [record])

    assert report["candidates"] == 0
    rows = [json.loads(line) for line in span_ledger.read_text(encoding="utf-8").splitlines()]
    assert {row["reason"] for row in rows} == {"overlapping_existing_assertion"}
