from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef


ROBOT_AVAILABLE = Path("tools/robot.jar").exists() and shutil.which("java") is not None


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="ROBOT/OWLAPI is not available")
def test_functional_syntax_round_trip_preserves_owl_axioms(tmp_path):
    from flopo2.owl.io import parse_ontology, serialize_ontology

    cls = URIRef("http://purl.obolibrary.org/obo/FLOPO_0000001")
    graph = Graph()
    graph.add((URIRef("http://purl.obolibrary.org/obo/flopo-test.owl"), RDF.type, OWL.Ontology))
    graph.add((cls, RDF.type, OWL.Class))
    graph.add((cls, RDFS.label, Literal("leaf green", lang="en")))

    output = tmp_path / "flopo.ofn"
    serialize_ontology(graph, output, "ofn")
    reparsed = parse_ontology(output)

    assert output.read_text().lstrip().startswith("Prefix(")
    assert (cls, RDF.type, OWL.Class) in reparsed
    assert (cls, RDFS.label, Literal("leaf green", lang="en")) in reparsed


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="ROBOT/OWLAPI is not available")
def test_builder_and_qc_accept_functional_syntax(tmp_path):
    import json

    from flopo2.owl.build import build_ontology
    from flopo2.owl.qc import qc

    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000001\t1\tleaf phenotype\t"
        "PHENO|PO_leaf\t0\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000002\t2\tleaf green\t"
        "EQ|PO_leaf|PATO_green\t0\n"
    )
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\nPO_leaf\tleaf\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\nPATO_green\tgreen\n")
    gated = tmp_path / "gated.jsonl"
    gated.write_text(
        json.dumps(
            {
                "text": "leaves green",
                "assertions": [
                    {
                        "po_id": "PO_leaf",
                        "pato_id": "PATO_green",
                        "source_text": "leaves green",
                        "gate": {"status": "accepted"},
                    }
                ],
            }
        )
        + "\n"
    )

    output = tmp_path / "flopo.ofn"
    build_ontology(gated, output, registry, po, pato, output_format="ofn")
    result = qc(output, gated)

    assert result["ok"]
    assert result["expected_eq_from_gated"] == 1
