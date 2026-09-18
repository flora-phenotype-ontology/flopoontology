from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from flopo2.review.models import PhenotypeExpression, PhenotypeExpressionCandidate
from flopo2.verify.recover_llm_one_of_expressions import prepare_one_of_review


def _catalogs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\tslim\nPO_0020041\tstipule\tstipules\tplant_anatomy\n",
        encoding="utf-8",
    )
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tsynonyms\tslim\n"
        "PATO_0000052\tshape\t\tattribute_slim\n"
        "PATO_0001891\tovate\t\tvalue_slim\n"
        "PATO_0001877\tlanceolate\t\tvalue_slim\n",
        encoding="utf-8",
    )
    flopo = tmp_path / "flopo.tsv"
    flopo.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n", encoding="utf-8"
    )
    combinations = tmp_path / "combinations.tsv"
    combinations.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_0020041\tPATO_0000052\tallowed\tfixture\tstipule shape\n",
        encoding="utf-8",
    )
    return po, pato, flopo, combinations


def _decision(text: str) -> dict[str, str]:
    source = "fixture"
    source_id = "flora.xml"
    segment = "0"
    digest_seed = f"{source}|{source_id}|{segment}|0|{len(text)}|{text}"
    return {
        "expression_uid": f"{source}|{source_id}|{segment}|0|{len(text)}",
        "expression_digest": hashlib.sha256(digest_seed.encode()).hexdigest()[:16],
        "source": source,
        "source_id": source_id,
        "source_segment_index": segment,
        "expression_start": "0",
        "expression_end": str(len(text)),
        "expression_text": text,
        "operator": "one_of",
        "operator_interpretation": "explicit_finite_disjunction",
        "bearer_po_id": "PO_0020041",
        "bearer_method": "expression_head_noun",
        "bearer_surface": "stipules",
        "attribute_pato_id": "PATO_0000052",
        "family": "shape",
        "operand_surfaces": "stipules ovate|lanceolate",
        "operand_term_ids": "PATO_0001891|PATO_0001877",
        "modifiers": "",
        "modality_text": "",
        "frequency_qualifier": "",
        "epistemic_modality": "",
        "negation_guard": "",
        "decision": "recover_one_of",
    }


def test_prepares_exact_one_of_candidate(tmp_path: Path) -> None:
    text = "stipules ovate or lanceolate"
    ovate = text.index("ovate")
    lanceolate = text.index("lanceolate")
    stage_record = {
        "source": "fixture",
        "source_id": "flora.xml",
        "source_segment_index": 0,
        "taxon": "Planta exemplaris",
        "organ": "stipules",
        "language": "en",
        "char_start": 0,
        "char_end": len(text),
        "text": text,
        "assertions": [],
        "unresolved_spans": [
            {
                "start": ovate,
                "end": ovate + len("ovate"),
                "surface_form": "ovate",
                "reason": "explicit_disjunction",
                "candidate_pato_id": "PATO_0001891",
                "extractor": "fixture",
            },
            {
                "start": lanceolate,
                "end": lanceolate + len("lanceolate"),
                "surface_form": "lanceolate",
                "reason": "explicit_disjunction",
                "candidate_pato_id": "PATO_0001877",
                "extractor": "fixture",
            },
        ],
    }
    stage = tmp_path / "stage.jsonl"
    stage.write_text(json.dumps(stage_record) + "\n", encoding="utf-8")
    decision = _decision(text)
    decisions = tmp_path / "decisions.tsv"
    with decisions.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(decision), delimiter="\t")
        writer.writeheader()
        writer.writerow(decision)
    po, pato, flopo, combinations = _catalogs(tmp_path)
    review_input = tmp_path / "review.jsonl"
    ledger = tmp_path / "ledger.jsonl"
    exclusions = tmp_path / "exclusions.jsonl"
    report_path = tmp_path / "report.json"
    report = prepare_one_of_review(
        stage_path=stage,
        decisions_path=decisions,
        review_input_path=review_input,
        candidate_ledger_path=ledger,
        exclusions_path=exclusions,
        report_path=report_path,
        po_lexicon_path=po,
        pato_lexicon_path=pato,
        flopo_registry_path=flopo,
        combinations_path=combinations,
    )

    assert report["candidates"] == 1
    assert report["exclusions"] == 0
    row = json.loads(review_input.read_text())
    candidate = row["unresolved_spans"][0]["phenotype_expression_candidate"]
    assert candidate["signature"]["value_operator"] == "one_of"
    assert candidate["signature"]["value_terms"] == [
        "PATO_0001891",
        "PATO_0001877",
    ]
    assert candidate["support_proposal_key"] is None
    assert candidate["clear_unresolved_spans"] == [
        [ovate, ovate + len("ovate")],
        [lanceolate, lanceolate + len("lanceolate")],
    ]


def test_logical_expression_values_must_be_distinct_and_support_binding_is_all_or_none() -> None:
    try:
        PhenotypeExpression(
            bearer_id="PO_0020041",
            quality_id="PATO_0000052",
            value_operator="one_of",
            value_terms=("PATO_0001891", "PATO_0001891"),
        )
    except ValueError as error:
        assert "distinct" in str(error)
    else:
        raise AssertionError("duplicate logical values were accepted")

    try:
        PhenotypeExpressionCandidate(
            signature=PhenotypeExpression(
                bearer_id="PO_0020041",
                quality_id="PATO_0000052",
                value_operator="one_of",
                value_terms=("PATO_0001891", "PATO_0001877"),
            ),
            bearer_method="fixture",
            expression_start=0,
            expression_end=10,
            expression_text="x" * 10,
            clear_unresolved_spans=((0, 1),),
            support_proposal_key="FLOPO_LOCAL:fixture",
        )
    except ValueError as error:
        assert "supplied together" in str(error)
    else:
        raise AssertionError("partial support-class provenance was accepted")
