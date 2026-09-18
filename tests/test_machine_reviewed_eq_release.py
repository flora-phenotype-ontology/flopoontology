from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from rdflib import DCTERMS, OWL, RDF, Graph, Literal, URIRef

from flopo2.review.io import sha256_file
from flopo2.verify.materialize_eq_gap_class_consensus import (
    ALLOCATION_FIELDS,
    TIEBREAK_ALLOCATION_FIELDS,
    _module_text,
)
from tools.update_flopo_machine_reviewed_eq_release import (
    BEGIN_MARKER,
    update_machine_reviewed_eq_release,
)


OBO = "http://purl.obolibrary.org/obo/"
CAMPAIGN = "campaign_" + "b" * 24


def _allocation(number: int, quality: str, *, tiebreak: bool, curator_override: str = "") -> dict:
    return {
        "proposal_key": f"eqgap_{number:024d}",
        "flopo_id": f"FLOPO_{number:07d}",
        "label": f"test leaf colour {number}",
        "eq_signature": f"EQ|PO_0000001|{quality}",
        "signature_sha256": "a" * 64,
        "campaign_id": CAMPAIGN,
        "item_id": f"cluster_{number:024d}",
        "consensus_signature_sha256": "d" * 64,
        "reviewer_ids": (
            ["reviewer_claude", "reviewer_kimi", "reviewer_qwen"]
            if tiebreak
            else ["reviewer_kimi", "reviewer_qwen"]
        ),
        "adjudicator_id": None if tiebreak else "adversary_gpt",
        "occurrence_count": 2,
        "candidate": {
            "proposal_key": f"eqgap_{number:024d}",
            "signature": {"bearer_id": "PO_0000001", "quality_id": quality},
            "label": f"test leaf colour {number}",
            "definition": "A flora phenotype in which a test leaf has a colour.",
            "parent_ids": ["FLOPO_0000001"],
            "authoritative_evidence_ids": ["evidence_quality"],
            "occurrence_count": 2,
            "source_occurrence_membership_sha256": "0" * 64,
        },
        **({"admission_rule": "two_of_three_exact_agreement"} if tiebreak else {}),
        **({"curator_override": curator_override} if curator_override else {}),
    }


def _write_materialization(
    directory: Path, rows: list[dict], *, prior: Path | None, module_name: str | None = None
) -> tuple:
    directory.mkdir()
    fields = TIEBREAK_ALLOCATION_FIELDS if prior is not None else ALLOCATION_FIELDS
    allocations = directory / "allocations.tsv"
    lines = ["\t".join(fields)]
    for row in rows:
        lines.append(
            "\t".join(
                "|".join(row[field]) if field == "reviewer_ids" else str(row.get(field) or "")
                for field in fields
            )
        )
    allocations.write_text("\n".join(lines) + "\n", encoding="utf-8")
    default_name = "machine-reviewed-eq-tiebreak.ttl" if prior else "machine-reviewed-eq.ttl"
    module = directory / (module_name or default_name)
    module.write_text(
        _module_text(
            rows,
            release_date="2026-09-18",
            evidence_locators={"evidence_quality": "ont/quality.obo"},
        ),
        encoding="utf-8",
    )
    report = {
        "schema_version": "flopo-eq-class-consensus-materialization-v1",
        "campaign_id": CAMPAIGN,
        "accepted_classes": len(rows),
        "accepted_candidate_occurrences": 2 * len(rows),
        "class_conserved": True,
        "occurrence_conserved": True,
        "occurrence_annotations_admitted": 0,
        "review_report": {"ok": True},
        "artifacts": {
            "allocations": sha256_file(allocations).model_dump(mode="json"),
            "module": sha256_file(module).model_dump(mode="json"),
        },
    }
    if prior is not None:
        report["tiebreak"] = {
            "rule": "two_of_three",
            "admission_reason": "two_of_three_exact_agreement",
            "prior_allocations": [sha256_file(prior).model_dump(mode="json")],
        }
    report_path = directory / "report.json"
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    return report_path, allocations, module


def _fixture(tmp_path: Path):
    release = tmp_path / "flopo.owl"
    release.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF
  xmlns:obo="http://purl.obolibrary.org/obo/"
  xmlns:dcterms="http://purl.org/dc/terms/"
  xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
  xmlns:owl="http://www.w3.org/2002/07/owl#"
  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/flopo.owl">
    <owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/flopo/releases/2026-08-04/flopo.owl"/>
    <owl:versionInfo>2026-08-04</owl:versionInfo>
  </owl:Ontology>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0000000">
    <rdfs:label>flora phenotype</rdfs:label>
  </owl:Class>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0000001">
    <rdfs:label>test leaf phenotype</rdfs:label>
  </owl:Class>
</rdf:RDF>
""",
        encoding="utf-8",
    )
    registry = tmp_path / "flopo_id_registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        f"{OBO}FLOPO_0000000\t0\tflora phenotype\tOTHER\t0\n",
        encoding="utf-8",
    )
    base = _write_materialization(
        tmp_path / "base", [_allocation(2, "PATO_0000002", tiebreak=False)], prior=None
    )
    tiebreak = _write_materialization(
        tmp_path / "tiebreak", [_allocation(3, "PATO_0000003", tiebreak=True)], prior=base[1]
    )
    return release, registry, base, tiebreak


def _publish(tmp_path, release, registry, materializations):
    return update_machine_reviewed_eq_release(
        release_path=release,
        materializations=materializations,
        machine_registry_path=tmp_path / "machine-eq.tsv",
        flopo_registry_path=registry,
        retained_module_dir=tmp_path / "retained",
        release_date="2026-09-18",
    )


def test_publishes_adversarial_and_tiebreak_classes_with_machine_provenance(tmp_path):
    release, registry, base, tiebreak = _fixture(tmp_path)
    result = _publish(tmp_path, release, registry, [base, tiebreak])
    assert result["classes"] == 2
    assert result["human_reviewed"] is False
    assert result["flopo_id_range"] == ["FLOPO_0000002", "FLOPO_0000003"]
    assert result["classes_by_admission_rule"] == {
        "two_family_exact_agreement_adversarial_no_blocker": 1,
        "two_of_three_exact_agreement": 1,
    }
    text = release.read_text(encoding="utf-8")
    assert text.count(BEGIN_MARKER) == 1
    assert "<owl:versionInfo>2026-09-18</owl:versionInfo>" in text
    graph = Graph().parse(release.as_posix())
    for number in (2, 3):
        cls = URIRef(f"{OBO}FLOPO_{number:07d}")
        assert (cls, RDF.type, OWL.Class) in graph
        assert len(list(graph.objects(cls, OWL.equivalentClass))) == 1
        assert not list(graph.objects(cls, DCTERMS.contributor))
    tie = URIRef(f"{OBO}FLOPO_0000003")
    reviewers = {
        str(value)
        for value in graph.objects(tie, URIRef("https://w3id.org/flopo/annotation/machine_reviewer"))
    }
    assert reviewers == {"reviewer_claude", "reviewer_kimi", "reviewer_qwen"}
    with registry.open(encoding="utf-8", newline="") as handle:
        rows = {row["flopo_num"]: row for row in csv.DictReader(handle, delimiter="\t")}
    assert rows["2"]["signature"] == "EQ|PO_0000001|PATO_0000002"
    assert rows["3"]["signature"] == "EQ|PO_0000001|PATO_0000003"
    with (tmp_path / "machine-eq.tsv").open(encoding="utf-8", newline="") as handle:
        machine = list(csv.DictReader(handle, delimiter="\t"))
    assert [row["admission_rule"] for row in machine] == [
        "two_family_exact_agreement_adversarial_no_blocker",
        "two_of_three_exact_agreement",
    ]
    assert sorted(path.name for path in (tmp_path / "retained").iterdir()) == [
        "flopo-machine-reviewed-eq-tiebreak.ttl",
        "flopo-machine-reviewed-eq.ttl",
    ]
    first = hashlib.sha256(release.read_bytes()).hexdigest()
    _publish(tmp_path, release, registry, [base, tiebreak])
    assert hashlib.sha256(release.read_bytes()).hexdigest() == first


def test_tiebreak_must_follow_its_prior_ledger(tmp_path):
    release, registry, _base, tiebreak = _fixture(tmp_path)
    before = release.read_bytes()
    with pytest.raises(ValueError, match="prior allocations"):
        _publish(tmp_path, release, registry, [tiebreak])
    assert release.read_bytes() == before


def test_publishes_curator_override_class_with_provenance(tmp_path):
    release, registry, base, tiebreak = _fixture(tmp_path)
    override = _write_materialization(
        tmp_path / "curator-override",
        [_allocation(4, "PATO_0000004", tiebreak=True, curator_override="curator 2026-09-18")],
        prior=base[1],
        module_name="machine-reviewed-eq-curator-override.ttl",
    )
    result = _publish(tmp_path, release, registry, [base, tiebreak, override])
    assert result["classes"] == 3
    assert result["flopo_id_range"] == ["FLOPO_0000002", "FLOPO_0000004"]
    graph = Graph().parse(release.as_posix())
    cls = URIRef(f"{OBO}FLOPO_0000004")
    assert (
        cls,
        URIRef("https://w3id.org/flopo/annotation/curator_override"),
        Literal("curator 2026-09-18"),
    ) in graph
    note = str(next(graph.objects(cls, URIRef(f"{OBO}IAO_0000116"))))
    assert "overridden by" in note.casefold()
    with (tmp_path / "machine-eq.tsv").open(encoding="utf-8", newline="") as handle:
        machine = {row["flopo_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    assert machine["FLOPO_0000004"]["curator_override"] == "curator 2026-09-18"
    assert machine["FLOPO_0000002"]["curator_override"] == ""


def test_curator_override_claim_without_allocation_field_is_rejected(tmp_path):
    release, registry, base, tiebreak = _fixture(tmp_path)
    override = _write_materialization(
        tmp_path / "bad-override",
        [_allocation(4, "PATO_0000004", tiebreak=True)],
        prior=base[1],
        module_name="machine-reviewed-eq-bad-override.ttl",
    )
    module_path = override[2]
    text = module_path.read_text(encoding="utf-8")
    text = text.replace(
        'flopoann:machine_review_rule "two_of_three_exact_agreement" ;',
        'flopoann:machine_review_rule "two_of_three_exact_agreement" ;\n'
        '    flopoann:curator_override "curator 2026-09-18" ;',
    )
    module_path.write_text(text, encoding="utf-8")
    report_path = override[0]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["artifacts"]["module"] = sha256_file(module_path).model_dump(mode="json")
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="claims a curator override"):
        _publish(tmp_path, release, registry, [base, tiebreak, override])


def test_tampered_module_is_rejected(tmp_path):
    release, registry, base, tiebreak = _fixture(tmp_path)
    module = tiebreak[2]
    module.write_text(module.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        _publish(tmp_path, release, registry, [base, tiebreak])
