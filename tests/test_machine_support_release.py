from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, Graph, URIRef

from flopo2.review.io import sha256_file
from tools.update_flopo_machine_support_release import (
    BEGIN_MARKER,
    update_machine_support_release,
)


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
    <owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/flopo/releases/2026-08-03/flopo.owl"/>
    <owl:versionInfo>2026-08-03</owl:versionInfo>
  </owl:Ontology>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0000000">
    <rdfs:label>flora phenotype</rdfs:label>
  </owl:Class>
</rdf:RDF>
""",
        encoding="utf-8",
    )
    allocation = tmp_path / "allocations.tsv"
    allocation.write_text(
        "proposal_key\tflopo_id\tlabel\tsignature_sha256\tcampaign_id\titem_id\t"
        "consensus_signature_sha256\treviewer_ids\tadjudicator_id\toccurrence_count\n"
        "FLOPO_LOCAL:orchid_labellum\tFLOPO_0000001\torchid labellum\t"
        f"{'a' * 64}\tcampaign_{'b' * 24}\tcluster_{'c' * 24}\t{'d' * 64}\t"
        "claude|gpt\tadversary\t153\n",
        encoding="utf-8",
    )
    module = tmp_path / "support.ttl"
    module.write_text(
        f"""@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix flopoann: <https://w3id.org/flopo/annotation/> .

<http://purl.obolibrary.org/obo/flopo-machine-reviewed-support.owl> a owl:Ontology .
obo:FLOPO_0000001 a owl:Class ;
    rdfs:label "orchid labellum"@en ;
    rdfs:subClassOf obo:PO_0009032 ;
    dcterms:source <https://example.org/orchid-source> ;
    obo:IAO_0000116 "Provisional bridge; not human reviewed."@en ;
    flopoann:machine_review_campaign "campaign_{'b' * 24}" ;
    flopoann:machine_review_item "cluster_{'c' * 24}" ;
    flopoann:machine_review_signature "{'d' * 64}" ;
    flopoann:machine_review_status "llm_consensus" ;
    flopoann:machine_reviewer "claude", "gpt" ;
    flopoann:machine_adjudicator "adversary" .
""",
        encoding="utf-8",
    )
    report = tmp_path / "materialization.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": "flopo-support-consensus-materialization-v1",
                "campaign_id": f"campaign_{'b' * 24}",
                "accepted_classes": 1,
                "accepted_occurrences": 153,
                "class_conserved": True,
                "occurrence_conserved": True,
                "review_report": {"ok": True},
                "artifacts": {
                    "allocations": sha256_file(allocation).model_dump(mode="json"),
                    "module": sha256_file(module).model_dump(mode="json"),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    registry = tmp_path / "flopo_id_registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000000\t0\tflora phenotype\tOTHER\t0\n",
        encoding="utf-8",
    )
    return release, allocation, module, report, registry


def test_machine_support_publisher_keeps_machine_provenance_distinct(tmp_path):
    release, allocation, module, report, registry = _fixture(tmp_path)
    machine_registry = tmp_path / "machine-support.tsv"
    result = update_machine_support_release(
        release_path=release,
        module_path=module,
        materialization_report_path=report,
        allocation_path=allocation,
        machine_registry_path=machine_registry,
        flopo_registry_path=registry,
        release_date="2026-08-04",
    )
    assert result["classes"] == 1
    assert result["human_reviewed"] is False
    text = release.read_text(encoding="utf-8")
    assert text.count(BEGIN_MARKER) == 1
    graph = Graph().parse(release.as_posix())
    support = URIRef("http://purl.obolibrary.org/obo/FLOPO_0000001")
    assert (support, RDF.type, OWL.Class) in graph
    assert not list(graph.objects(support, DCTERMS.contributor))
    with registry.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    support_row = next(row for row in rows if row["flopo_num"] == "1")
    assert support_row["label"] == "orchid labellum"
    assert support_row["signature"] == "OTHER"
    first_hash = hashlib.sha256(release.read_bytes()).hexdigest()
    update_machine_support_release(
        release_path=release,
        module_path=module,
        materialization_report_path=report,
        allocation_path=allocation,
        machine_registry_path=machine_registry,
        flopo_registry_path=registry,
        release_date="2026-08-04",
    )
    assert hashlib.sha256(release.read_bytes()).hexdigest() == first_hash
