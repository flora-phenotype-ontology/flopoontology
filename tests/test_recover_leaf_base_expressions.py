from __future__ import annotations

import json
from pathlib import Path


def _files(tmp_path: Path):
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\n"
        "PO_0009025\tleaf\tleaves\n"
        "PO_0020039\tleaf lamina\tblade\n"
        "PO_0020040\tleaf base\tbase\n",
        encoding="utf-8",
    )
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tslim\n"
        "PATO_0001982\tattenuate\tshape_slim\n"
        "PATO_0001935\tobtuse\tshape_slim\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_1\t1\tleaf base attenuate\t"
        "EQ|PO_0020040|PATO_0001982\t0\n",
        encoding="utf-8",
    )
    combinations = tmp_path / "combinations.tsv"
    combinations.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_0020040\tPATO_0001982\tallowed\tfixture\tleaf base attenuate\n",
        encoding="utf-8",
    )
    return po, pato, registry, combinations


def _stage(tmp_path: Path, text: str, surface: str, pato_id: str) -> Path:
    start = text.index(surface)
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
                        "start": start,
                        "end": start + len(surface),
                        "surface_form": surface,
                        "reason": "same_attribute_composite_or_transition",
                        "candidate_pato_id": pato_id,
                        "extractor": "fixture",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return stage


def _prepare(tmp_path: Path, text: str):
    from flopo2.verify.recover_leaf_base_expressions import prepare_leaf_base_review_input

    po, pato, registry, combinations = _files(tmp_path)
    output = tmp_path / "output"
    report = prepare_leaf_base_review_input(
        stage_path=_stage(tmp_path, text, "attenuate", "PATO_0001982"),
        review_input_path=output / "review.jsonl",
        candidate_ledger_path=output / "ledger.jsonl",
        exclusions_path=output / "excluded.jsonl",
        report_path=output / "report.json",
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
        combinations_path=combinations,
    )
    return report, output


def test_explicit_leaf_base_candidate_reuses_existing_flopo_eq(tmp_path: Path):
    report, output = _prepare(tmp_path, "Leaves elliptic, attenuate at base.")
    assert report["conserved"] is True
    assert report["candidates"] == 1
    candidate = json.loads((output / "ledger.jsonl").read_text(encoding="utf-8"))["candidate"]
    assert candidate["signature"]["bearer_id"] == "PO_0020040"
    assert candidate["signature"]["quality_id"] == "PATO_0001982"
    assert candidate["signature"]["value_operator"] == "atomic"
    assert candidate["bearer_text"] == "base"
    assert candidate["expression_text"] == "attenuate at base"
    assert candidate["clear_unresolved_spans"] == [[17, 26]]


def test_explicit_apex_scope_is_conserved_as_exclusion(tmp_path: Path):
    report, output = _prepare(tmp_path, "Leaves elliptic, attenuate at apex.")
    assert report["conserved"] is True
    assert report["candidates"] == 0
    exclusion = json.loads((output / "excluded.jsonl").read_text(encoding="utf-8"))
    assert exclusion["reason"] == "no_nearest_explicit_base_scope"
