from __future__ import annotations

import json
from pathlib import Path


def _files(tmp_path: Path):
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\n"
        "PO_0009025\tleaf\tleaves\n"
        "PO_0020039\tleaf lamina\tblade\n"
        "PO_0020137\tleaf apex\tapex|tip\n",
        encoding="utf-8",
    )
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tslim\n"
        "PATO_0002228\tacuminate\tshape_slim\n"
        "PATO_0001982\tattenuate\tshape_slim\n"
        "PATO_0001935\tobtuse\tshape_slim\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_1\t1\tleaf apex acuminate\t"
        "EQ|PO_0020137|PATO_0002228\t0\n"
        "http://purl.obolibrary.org/obo/FLOPO_2\t2\tleaf apex attenuate\t"
        "EQ|PO_0020137|PATO_0001982\t0\n",
        encoding="utf-8",
    )
    combinations = tmp_path / "combinations.tsv"
    combinations.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_0020137\tPATO_0002228\tallowed\tfixture\tleaf apex acuminate\n"
        "PO_0020137\tPATO_0001982\tallowed\tfixture\tleaf apex attenuate\n",
        encoding="utf-8",
    )
    return po, pato, registry, combinations


def _span(text: str, surface: str, pato_id: str) -> dict:
    start = text.index(surface)
    return {
        "start": start,
        "end": start + len(surface),
        "surface_form": surface,
        "reason": "same_attribute_composite_or_transition",
        "candidate_pato_id": pato_id,
        "extractor": "fixture",
    }


def test_explicit_leaf_apex_candidate_reuses_existing_flopo_eq(tmp_path: Path):
    from flopo2.review.inventory import build_inventory, model_spec
    from flopo2.review.io import read_jsonl
    from flopo2.review.models import Occurrence
    from flopo2.verify.recover_leaf_apex_expressions import prepare_leaf_apex_review_input

    text = "Leaves elliptic, acuminate at apex."
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
                "char_start": 0,
                "char_end": len(text),
                "text": text,
                "assertions": [],
                "unresolved_spans": [_span(text, "acuminate", "PATO_0002228")],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    po, pato, registry, combinations = _files(tmp_path)
    output = tmp_path / "output"
    report = prepare_leaf_apex_review_input(
        stage_path=stage,
        review_input_path=output / "review.jsonl",
        candidate_ledger_path=output / "ledger.jsonl",
        exclusions_path=output / "excluded.jsonl",
        report_path=output / "report.json",
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
        combinations_path=combinations,
    )
    assert report["candidates"] == 1
    assert report["exclusions"] == 0
    ledger = json.loads((output / "ledger.jsonl").read_text(encoding="utf-8"))
    candidate = ledger["candidate"]
    assert candidate["signature"]["bearer_id"] == "PO_0020137"
    assert candidate["signature"]["quality_id"] == "PATO_0002228"
    assert candidate["signature"]["value_operator"] == "atomic"
    assert candidate["bearer_text"] == "apex"
    assert candidate["clear_unresolved_spans"] == [[17, 26]]
    assert candidate["expression_text"] == "acuminate at apex"

    prompt = tmp_path / "prompt.md"
    prompt.write_text("Review leaf-apex candidates.\n", encoding="utf-8")
    build_inventory(
        stage13_path=output / "review.jsonl",
        occurrence_path=output / "occurrences.jsonl",
        cluster_path=output / "clusters.jsonl",
        evidence_path=output / "evidence.jsonl",
        manifest_path=output / "manifest.json",
        ontology_paths=[po, pato, registry, combinations],
        prompt_paths={"reviewer": prompt},
        models=[
            model_spec(
                reviewer_id="claude",
                provider="anthropic",
                model="claude-opus-4-8",
                model_family="claude-opus",
                role="reviewer",
            )
        ],
    )
    occurrence = next(read_jsonl(output / "occurrences.jsonl", Occurrence))
    assert occurrence.phenotype_expression_candidate is not None


def test_explicit_base_scope_is_conserved_as_exclusion(tmp_path: Path):
    from flopo2.verify.recover_leaf_apex_expressions import prepare_leaf_apex_review_input

    text = "Leaves elliptic, attenuate at base."
    stage = tmp_path / "stage.jsonl"
    stage.write_text(
        json.dumps(
            {
                "source": "fixture",
                "source_id": "flora.xml",
                "source_segment_index": 0,
                "organ": "leaves",
                "language": "en",
                "text": text,
                "assertions": [],
                "unresolved_spans": [_span(text, "attenuate", "PATO_0001982")],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    po, pato, registry, combinations = _files(tmp_path)
    output = tmp_path / "output"
    report = prepare_leaf_apex_review_input(
        stage_path=stage,
        review_input_path=output / "review.jsonl",
        candidate_ledger_path=output / "ledger.jsonl",
        exclusions_path=output / "excluded.jsonl",
        report_path=output / "report.json",
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
        combinations_path=combinations,
    )
    assert report["conserved"] is True
    assert report["candidates"] == 0
    assert report["exclusions"] == 1
    exclusion = json.loads((output / "excluded.jsonl").read_text(encoding="utf-8"))
    assert exclusion["reason"] == "explicit_base_scope"
