from __future__ import annotations

import json
from pathlib import Path

from flopo2.verify.recover_bilingual_shape_compound_relations import (
    prepare_bilingual_shape_compound_review,
)


def _record(text: str) -> dict:
    surface = "lancéolées"
    start = text.index(surface)
    return {
        "source": "fixture",
        "source_id": f"{abs(hash(text))}.xml",
        "source_segment_index": 0,
        "taxon": "Planta exemplaris",
        "organ": "feuilles",
        "language": "fr",
        "char_start": 0,
        "char_end": len(text),
        "text": text,
        "assertions": [],
        "unresolved_spans": [
            {
                "start": start,
                "end": start + len(surface),
                "surface_form": surface,
                "reason": "hyphenated_or_slash_compound",
                "candidate_pato_id": "PATO_0001877",
                "extractor": "fixture",
            }
        ],
    }


def _catalogs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\tslim\n"
        "PO_0009025\tvascular leaf\tleaves|leaf|feuilles\tplant_anatomy\n",
        encoding="utf-8",
    )
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tsynonyms\tslim\n"
        "PATO_0000052\tshape\t\tattribute_slim\n"
        "PATO_0000946\toblong\t\tvalue_slim\n"
        "PATO_0000947\telliptic\telliptical\tvalue_slim\n"
        "PATO_0001199\tlinear\t\tvalue_slim\n"
        "PATO_0001877\tlanceolate\t\tvalue_slim\n"
        "PATO_0001891\tovate\t\tvalue_slim\n",
        encoding="utf-8",
    )
    combinations = tmp_path / "combinations.tsv"
    combinations.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_0009025\tPATO_0000052\tallowed\tfixture\tleaf shape\n",
        encoding="utf-8",
    )
    terminology = tmp_path / "terminology.tsv"
    terminology.write_text(
        "term_id\tnormalized_form\tlanguage\tsource_id\ttarget_id\t"
        "mapping_relation\tmapping_confidence\n"
        "t1\toblong\tfr\tenglish_french_lexicon\tPATO_0000946\t"
        "skos:exactMatch\t0.99\n"
        "t2\telliptique\tfr\tenglish_french_lexicon\tPATO_0000947\t"
        "skos:closeMatch\t0.92\n"
        "t3\tlineaire\tfr\tenglish_french_lexicon\tPATO_0001199\t"
        "skos:closeMatch\t0.92\n"
        "t4\tlanceole\tfr\tenglish_french_lexicon\tPATO_0001877\t"
        "skos:closeMatch\t0.92\n"
        "t5\tovale\tfr\tenglish_french_lexicon\tPATO_0001891\t"
        "skos:closeMatch\t0.92\n",
        encoding="utf-8",
    )
    return po, pato, combinations, terminology


def test_recovers_one_missing_french_shape_endpoint_under_strict_guards(
    tmp_path: Path,
) -> None:
    clean = "Feuilles ovales-lancéolées."
    logical = "Feuilles ovales-lancéolées ou oblongues."
    stage = tmp_path / "stage.jsonl"
    stage.write_text(
        json.dumps(_record(clean)) + "\n" + json.dumps(_record(logical)) + "\n",
        encoding="utf-8",
    )
    po, pato, combinations, terminology = _catalogs(tmp_path)
    review = tmp_path / "review.jsonl"
    candidates = tmp_path / "candidates.jsonl"
    spans = tmp_path / "spans.jsonl"
    report = prepare_bilingual_shape_compound_review(
        stage_path=stage,
        review_input_path=review,
        candidate_ledger_path=candidates,
        span_ledger_path=spans,
        report_path=tmp_path / "report.json",
        terminology_path=terminology,
        po_lexicon_path=po,
        pato_lexicon_path=pato,
        combinations_path=combinations,
    )

    assert report["target_spans"] == 2
    assert report["candidates"] == 1
    assert report["candidate_spans"] == 1
    assert report["exclusions"] == 1
    assert report["conserved"] is True
    row = json.loads(review.read_text(encoding="utf-8"))
    candidate = row["unresolved_spans"][0]["qualitative_relation_candidate"]
    assert candidate["expression_text"] == "ovales-lancéolées"
    assert candidate["from_text"] == "ovales"
    assert candidate["to_text"] == "lancéolées"
    assert candidate["signature"]["from_value"] == "PATO_0001891"
    assert candidate["signature"]["to_value"] == "PATO_0001877"
    assert candidate["clear_unresolved_spans"] == [
        [clean.index("lancéolées"), clean.index("lancéolées") + len("lancéolées")]
    ]
    ledger = json.loads(candidates.read_text(encoding="utf-8"))
    assert any(
        value.startswith("botanical_terminology:")
        for value in ledger["component_mapping_evidence"]
    )
    span_rows = [json.loads(line) for line in spans.read_text().splitlines()]
    assert {row["status"] for row in span_rows} == {"candidate", "excluded"}
    assert {
        row["reason"] for row in span_rows if row["status"] == "excluded"
    } == {"logical_compound_context"}
