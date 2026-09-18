from __future__ import annotations

import json
import sqlite3

import pytest
from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef


TEXT = "Leaves ovate to lanceolate."


def _relation() -> dict:
    return {
        "interpretation": "continuum",
        "from_value": "PATO_0000947",
        "to_value": "PATO_0001877",
        "from_text": "ovate",
        "from_start": 7,
        "from_end": 12,
        "connector_text": "to",
        "connector_start": 13,
        "connector_end": 15,
        "to_text": "lanceolate",
        "to_start": 16,
        "to_end": 26,
    }


def _assertion() -> dict:
    return {
        "po_id": "PO_0009025",
        "pato_id": "PATO_0000052",
        "source_text": "ovate to lanceolate",
        "source_start": 7,
        "source_end": 26,
        "qualitative_value_relation": _relation(),
        "extractor": "test",
    }


def _record() -> dict:
    return {
        "source": "flora-test",
        "source_id": "qualitative.xml",
        "source_segment_index": 0,
        "taxon": "Planta exemplar",
        "text": TEXT,
        "assertions": [_assertion()],
    }


def _lexicons(tmp_path):
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\nPO_0009025\tvascular leaf\n", encoding="utf-8")
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tslim\n"
        "PATO_0000052\tshape\tattribute_slim\n"
        "PATO_0000947\tovate\tshape_slim\n"
        "PATO_0001877\tlanceolate\tshape_slim\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n",
        encoding="utf-8",
    )
    return po, pato, registry


def test_linkml_model_has_closed_qualitative_relation_enum():
    from flopo2.schema.flopo_trait_models import QualitativeValueRelation, TraitAssertion

    relation = QualitativeValueRelation(**_relation())
    assertion = TraitAssertion(
        anatomical_entity="PO_0009025",
        quality="PATO_0000052",
        source_text="ovate to lanceolate",
        qualitative_value_relation=relation,
    )
    assert assertion.qualitative_value_relation.interpretation == "continuum"
    with pytest.raises(Exception):
        QualitativeValueRelation(**{**_relation(), "interpretation": "one_of"})
    with pytest.raises(Exception):
        QualitativeValueRelation(**{**_relation(), "invented": True})


def test_qualitative_relation_cannot_be_given_a_fac_identity():
    from flopo2.owl.annotation_class import annotation_class_iri

    with pytest.raises(ValueError, match="structured flora annotations, not FAC"):
        annotation_class_iri(_assertion())


def test_data_model_validates_exact_endpoint_evidence_without_requiring_fac(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po, pato, registry = _lexicons(tmp_path)
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(_record()) + "\n", encoding="utf-8")
    report = validate_jsonl(
        source,
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
        require_annotation_class=True,
    )
    assert report["ok"], report

    record = _record()
    record["assertions"][0]["qualitative_value_relation"]["to_start"] = 14
    source.write_text(json.dumps(record) + "\n", encoding="utf-8")
    invalid = validate_jsonl(
        source,
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
    )
    assert invalid["errors_by_code"] == {
        "qualitative_relation_source_order": 1,
        "qualitative_to_not_verbatim": 1,
    }


def test_gate_accepts_relation_as_structured_annotation_only():
    from flopo2.verify.gates import Combination, check_assertion

    assertion = _assertion()
    assertion["composition"] = {"status": "accept"}
    decision = check_assertion(
        TEXT,
        assertion,
        {("PO_0009025", "PATO_0000052"): Combination("allowed", "curator_review_1")},
        attribute_pato_ids={"PATO_0000052"},
        po_catalog_ids={"PO_0009025"},
        pato_catalog_ids={"PATO_0000052", "PATO_0000947", "PATO_0001877"},
    )
    assert decision.status == "accepted"
    assert decision.flopo_status == "structured_annotation_only"
    assert decision.flopo_iri == ""
    assert decision.flopo_signature.startswith("QUALREL|")


def test_annotation_extension_skips_relation_instead_of_minting_broad_class(tmp_path):
    from flopo2.owl.annotation_extension import build_annotation_extension

    source = tmp_path / "source.jsonl"
    annotated = tmp_path / "annotated.jsonl"
    output = tmp_path / "extension.ttl"
    source.write_text(json.dumps(_record()) + "\n", encoding="utf-8")
    stats = build_annotation_extension(
        source,
        output,
        annotated_jsonl=annotated,
        include_imports=False,
        output_format="turtle",
    )
    assert stats["assertions"] == 1
    assert stats["fac_assertions"] == 0
    assert stats["structured_qualitative_relations"] == 1
    assert stats["annotation_classes"] == 0
    assertion = json.loads(annotated.read_text())["assertions"][0]
    assert "phenotype_class_iri" not in assertion


def test_source_owl_reifies_relation_without_union_or_taxon_axiom(tmp_path):
    from flopo2.annotation.provenance import ensure_source_statements
    from flopo2.owl.assertions import FLOPOANN, build_assertion_ontology

    record = ensure_source_statements(_record())
    assertion = record["assertions"][0]
    assertion["gate"] = {"status": "accepted"}
    assertion["composition"] = {"status": "accept"}
    source = tmp_path / "source.jsonl"
    output = tmp_path / "assertions.ttl"
    source.write_text(json.dumps(record) + "\n", encoding="utf-8")
    stats = build_assertion_ontology(
        source,
        output,
        include_imports=False,
        output_format="turtle",
    )
    graph = Graph().parse(output)
    relations = set(graph.subjects(RDF.type, FLOPOANN.QualitativeValueRelation))
    assert len(relations) == 1
    relation = next(iter(relations))
    assert (relation, FLOPOANN.qualitative_from_value, URIRef(
        "http://purl.obolibrary.org/obo/PATO_0000947"
    )) in graph
    assert (relation, FLOPOANN.qualitative_to_value, URIRef(
        "http://purl.obolibrary.org/obo/PATO_0001877"
    )) in graph
    assert (relation, FLOPOANN.qualitative_connector_text, Literal("to")) in graph
    assert not list(graph.subjects(OWL.unionOf, None))
    assert not list(graph.triples((None, RDFS.subClassOf, None)))
    assert not list(graph.triples((None, FLOPOANN.phenotype_class, None)))
    assert stats["structured_qualitative_relations"] == 1
    assert stats["annotation_classes"] == 0
    assert stats.get("strict_axioms", 0) == 0


def test_sqlite_loader_retains_relation_without_annotation_class(tmp_path):
    from flopo2.annotation.provenance import ensure_source_statements
    from flopo2.db.load import load_jsonl

    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(ensure_source_statements(_record())) + "\n", encoding="utf-8")
    db = tmp_path / "traits.sqlite"
    report = load_jsonl(db, source)
    with sqlite3.connect(db) as conn:
        stored, class_iri = conn.execute(
            "SELECT qualitative_value_relation, phenotype_class_iri FROM trait_assertion"
        ).fetchone()
        class_count = conn.execute("SELECT COUNT(*) FROM annotation_class").fetchone()[0]
    assert json.loads(stored) == _relation()
    assert class_iri is None
    assert class_count == 0
    assert report["annotation_classes"] == 0
