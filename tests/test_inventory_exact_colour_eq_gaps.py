from __future__ import annotations

import json
from pathlib import Path


def _inputs(tmp_path: Path, *, active: bool, allowed: bool = True) -> tuple[Path, ...]:
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0009025\tvascular leaf\tleaves\n", encoding="utf-8")
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tslim\nPATO_0001941\tyellow green\tvalue_slim\n",
        encoding="utf-8",
    )
    obo = tmp_path / "quality.obo"
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
        + (
            "http://purl.obolibrary.org/obo/FLOPO_1\t1\tleaf yellow green\t"
            "EQ|PO_0009025|PATO_0001941\t0\n"
            if active
            else ""
        ),
        encoding="utf-8",
    )
    combinations = tmp_path / "combinations.tsv"
    combinations.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        + (
            "PO_0009025\tPATO_0001941\tallowed\tfixture\tleaf yellow green\n"
            if allowed
            else ""
        ),
        encoding="utf-8",
    )
    return po, pato, obo, registry, combinations


def _stage(tmp_path: Path, text: str) -> Path:
    yellow = text.index("yellow")
    green = text.index("green")
    path = tmp_path / "stage.jsonl"
    path.write_text(
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
    return path


def _run(tmp_path: Path, text: str, *, active: bool, allowed: bool = True):
    from flopo2.verify.inventory_exact_colour_eq_gaps import (
        inventory_exact_colour_eq_gaps,
    )

    po, pato, obo, registry, combinations = _inputs(
        tmp_path, active=active, allowed=allowed
    )
    output = tmp_path / "output"
    report = inventory_exact_colour_eq_gaps(
        stage_path=_stage(tmp_path, text),
        occurrences_path=output / "occurrences.jsonl",
        classes_path=output / "classes.jsonl",
        exclusions_path=output / "exclusions.jsonl",
        report_path=output / "report.json",
        pato_obo=obo,
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
        combinations_path=combinations,
    )
    return report, output


def test_missing_eq_is_conserved_as_occurrence_and_class_candidate(tmp_path: Path) -> None:
    report, output = _run(tmp_path, "Leaves yellow-green.", active=False)

    assert report["conserved"] is True
    assert report["target_compounds"] == 1
    assert report["gap_occurrences"] == 1
    assert report["gap_classes"] == 1
    occurrence = json.loads((output / "occurrences.jsonl").read_text(encoding="utf-8"))
    candidate = json.loads((output / "classes.jsonl").read_text(encoding="utf-8"))
    assert occurrence["po_id"] == "PO_0009025"
    assert occurrence["pato_id"] == "PATO_0001941"
    assert occurrence["clear_unresolved_spans"] == [[7, 13], [14, 19]]
    assert candidate["proposed_signature"] == "EQ|PO_0009025|PATO_0001941"
    assert candidate["review_status"] == "pending_machine_review"
    assert candidate["occurrence_count"] == 1


def test_active_eq_is_terminal_exclusion_not_a_duplicate_class(tmp_path: Path) -> None:
    report, output = _run(tmp_path, "Leaves yellow-green.", active=True)

    assert report["conserved"] is True
    assert report["gap_occurrences"] == 0
    assert report["gap_classes"] == 0
    exclusion = json.loads((output / "exclusions.jsonl").read_text(encoding="utf-8"))
    assert exclusion["reason"] == "active_existing_flopo_eq"
    assert exclusion["po_id"] == "PO_0009025"
    assert exclusion["pato_id"] == "PATO_0001941"


def test_novel_combination_remains_pending_and_explicit(tmp_path: Path) -> None:
    report, output = _run(
        tmp_path, "Leaves yellow-green.", active=False, allowed=False
    )

    assert report["gap_occurrences"] == 1
    occurrence = json.loads((output / "occurrences.jsonl").read_text(encoding="utf-8"))
    candidate = json.loads((output / "classes.jsonl").read_text(encoding="utf-8"))
    assert occurrence["combination_status"] == "novel"
    assert "combination_status:novel" in occurrence["risk_flags"]
    assert candidate["combination_statuses"] == ["novel"]


def test_negated_context_is_conserved_as_exclusion(tmp_path: Path) -> None:
    report, output = _run(tmp_path, "Leaves not yellow-green.", active=False)

    assert report["conserved"] is True
    assert report["gap_occurrences"] == 0
    exclusion = json.loads((output / "exclusions.jsonl").read_text(encoding="utf-8"))
    assert exclusion["reason"] == "negated_context"
