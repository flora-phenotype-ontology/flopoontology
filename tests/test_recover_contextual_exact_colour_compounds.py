from __future__ import annotations

import json
from pathlib import Path


def _files(tmp_path: Path):
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0009025\tleaf\tleaves\n", encoding="utf-8")
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tslim\n"
        "PATO_0001941\tyellow green\tvalue_slim\n",
        encoding="utf-8",
    )
    obo = tmp_path / "pato.obo"
    obo.write_text(
        "format-version: 1.2\n\n"
        "[Term]\n"
        "id: PATO:0000014\n"
        "name: color\n\n"
        "[Term]\n"
        "id: PATO:0001941\n"
        "name: yellow green\n"
        "is_a: PATO:0000014 ! color\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_1\t1\tleaf yellow green\t"
        "EQ|PO_0009025|PATO_0001941\t0\n",
        encoding="utf-8",
    )
    combinations = tmp_path / "combinations.tsv"
    combinations.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_0009025\tPATO_0001941\tallowed\tfixture\tleaf yellow green\n",
        encoding="utf-8",
    )
    return po, pato, obo, registry, combinations


def _stage(tmp_path: Path, text: str) -> Path:
    yellow = text.index("yellow")
    green = text.index("green")
    stage = tmp_path / "stage.jsonl"
    stage.write_text(
        json.dumps(
            {
                "source": "fixture",
                "source_id": "flora.xml",
                "source_segment_index": 0,
                "taxon": "Planta exemplaris",
                "organ": "leaves",
                "language": "en",
                "text": text,
                "assertions": [],
                "unresolved_spans": [
                    {
                        "start": yellow,
                        "end": yellow + 6,
                        "surface_form": "yellow",
                        "reason": "hyphenated_or_slash_compound",
                        "candidate_pato_id": "PATO_0000324",
                    },
                    {
                        "start": green,
                        "end": green + 5,
                        "surface_form": "green",
                        "reason": "hyphenated_or_slash_compound",
                        "candidate_pato_id": "PATO_0000320",
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return stage


def _prepare(tmp_path: Path, text: str):
    from flopo2.verify.recover_contextual_exact_colour_compounds import (
        prepare_contextual_exact_colour_review,
    )

    po, pato, obo, registry, combinations = _files(tmp_path)
    output = tmp_path / "output"
    report = prepare_contextual_exact_colour_review(
        stage_path=_stage(tmp_path, text),
        review_input_path=output / "review.jsonl",
        candidate_ledger_path=output / "ledger.jsonl",
        exclusions_path=output / "excluded.jsonl",
        report_path=output / "report.json",
        pato_obo=obo,
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
        combinations_path=combinations,
    )
    return report, output


def test_exact_compound_candidate_reuses_atomic_pato_and_flopo_eq(tmp_path: Path):
    report, output = _prepare(tmp_path, "Leaves yellow-green.")
    assert report["conserved"] is True
    assert report["candidates"] == 1
    candidate = json.loads((output / "ledger.jsonl").read_text(encoding="utf-8"))["candidate"]
    assert candidate["signature"]["bearer_id"] == "PO_0009025"
    assert candidate["signature"]["quality_id"] == "PATO_0001941"
    assert candidate["signature"]["value_operator"] == "atomic"
    assert candidate["expression_text"] == "yellow-green"
    assert candidate["clear_unresolved_spans"] == [[7, 13], [14, 19]]


def test_unrepresented_colour_modifier_is_conserved_as_exclusion(tmp_path: Path):
    report, output = _prepare(tmp_path, "Leaves pale yellow-green.")
    assert report["conserved"] is True
    assert report["candidates"] == 0
    exclusion = json.loads((output / "excluded.jsonl").read_text(encoding="utf-8"))
    assert exclusion["reason"] == "unmodeled_colour_modifier"
