from __future__ import annotations

import json

from rdflib import OWL, RDF, RDFS, Graph, URIRef


def test_build_ontology_reuses_registry_iri(tmp_path):
    from flopo2.owl.build import (
        ANNOTATION_PROPERTIES,
        HAS_PART,
        SUPPORTED_BY_ASSERTION,
        build_ontology,
    )

    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000001\t1\tleaf phenotype\tPHENO|PO_leaf\t0\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000002\t2\tleaf green\tEQ|PO_leaf|PATO_green\t0\n"
    )
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\tnamespace\nPO_leaf\tleaf\tleaves\tplant_anatomy\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\tsynonyms\tslim\nPATO_green\tgreen\t\t\n")
    gated = tmp_path / "gated.jsonl"
    gated.write_text(
        json.dumps({
            "text": "leaves green",
            "assertions": [{
                "po_id": "PO_leaf",
                "pato_id": "PATO_green",
                "source_text": "leaves green",
                "gate": {"status": "accepted"},
            }],
        }) + "\n"
    )
    out = tmp_path / "flopo.ttl"
    stats = build_ontology(gated, out, registry, po, pato)
    assert stats["reused_existing_eq"] == 1
    assert stats["minted"] == 0

    g = Graph()
    g.parse(out.as_posix())
    cls = URIRef("http://purl.obolibrary.org/obo/FLOPO_0000002")
    assert (cls, RDFS.label, None) in g
    assert any(True for _ in g.objects(cls, OWL.equivalentClass))
    assert any(True for _ in g.triples((None, OWL.onProperty, HAS_PART)))
    assert any(True for _ in g.objects(cls, SUPPORTED_BY_ASSERTION))
    assert all((prop, RDF.type, OWL.AnnotationProperty) in g for prop in ANNOTATION_PROPERTIES)


def test_build_ontology_mints_after_registry_max(tmp_path):
    from flopo2.owl.build import build_ontology

    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000010\t10\troot\tOTHER\t0\n"
    )
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\tnamespace\nPO_leaf\tleaf\t\tplant_anatomy\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\tsynonyms\tslim\nPATO_blue\tblue\t\t\n")
    gated = tmp_path / "gated.jsonl"
    gated.write_text(
        json.dumps({
            "text": "leaves blue",
            "assertions": [{
                "po_id": "PO_leaf",
                "pato_id": "PATO_blue",
                "source_text": "leaves blue",
                "gate": {"status": "accepted"},
            }],
        }) + "\n"
    )
    stats = build_ontology(gated, tmp_path / "flopo.ttl", registry, po, pato)
    assert stats["minted_iris"]["PHENO|PO_leaf"].endswith("FLOPO_0000011")
    assert stats["minted_iris"]["EQ|PO_leaf|PATO_blue"].endswith("FLOPO_0000012")


def test_build_ontology_reuses_reviewed_id_reservations(tmp_path):
    from flopo2.owl.build import build_ontology

    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000010\t10\troot\tOTHER\t0\n"
    )
    reservations = tmp_path / "reservations.tsv"
    reservations.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000011\t11\tleaf phenotype\tPHENO|PO_leaf\t0\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000012\t12\tleaf blue\tEQ|PO_leaf|PATO_blue\t0\n"
    )
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\tnamespace\nPO_leaf\tleaf\t\tplant_anatomy\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\tsynonyms\tslim\nPATO_blue\tblue\t\t\n")
    gated = tmp_path / "gated.jsonl"
    gated.write_text(
        json.dumps(
            {
                "text": "leaves blue",
                "assertions": [
                    {
                        "po_id": "PO_leaf",
                        "pato_id": "PATO_blue",
                        "source_text": "leaves blue",
                        "gate": {"status": "accepted"},
                    }
                ],
            }
        )
        + "\n"
    )
    output = tmp_path / "flopo.ttl"

    stats = build_ontology(
        gated,
        output,
        registry,
        po,
        pato,
        reservations_tsv=reservations,
    )
    graph = Graph().parse(output)

    assert stats["minted"] == 0
    assert stats["reused_reviewed_reservations"] == 2
    assert (
        URIRef("http://purl.obolibrary.org/obo/FLOPO_0000012"),
        RDF.type,
        OWL.Class,
    ) in graph


def test_builder_uses_a_reviewed_flopo_local_anatomy_bearer(tmp_path):
    from flopo2.owl.build import build_ontology

    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000010\t10\torchid labellum\tOTHER\t0\n"
    )
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\tnamespace\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\tsynonyms\tslim\nPATO_white\twhite\t\t\n")
    gated = tmp_path / "gated.jsonl"
    gated.write_text(
        json.dumps(
            {
                "text": "Labellum white.",
                "assertions": [
                    {
                        "po_id": "FLOPO_0000010",
                        "pato_id": "PATO_white",
                        "source_text": "white",
                        "gate": {"status": "accepted"},
                    }
                ],
            }
        )
        + "\n"
    )

    output = tmp_path / "flopo.ttl"
    stats = build_ontology(gated, output, registry, po, pato)
    graph = Graph().parse(output)
    bearer = URIRef("http://purl.obolibrary.org/obo/FLOPO_0000010")

    assert stats["minted_iris"]["PHENO|FLOPO_0000010"].endswith("FLOPO_0000011")
    assert (bearer, RDFS.label, None) in graph
    assert any(str(label) == "orchid labellum" for label in graph.objects(bearer, RDFS.label))


def test_build_ontology_keeps_one_of_union_out_of_reusable_vocabulary(tmp_path):
    from flopo2.owl.build import build_ontology

    registry = tmp_path / "registry.tsv"
    registry.write_text("flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n")
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\tnamespace\nPO_flower\tflower\tflowers\tplant_anatomy\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tsynonyms\tslim\n"
        "PATO_color\tcolor\t\tattribute_slim\n"
        "PATO_red\tred\t\tvalue_slim\n"
        "PATO_yellow\tyellow\t\tvalue_slim\n"
    )
    gated = tmp_path / "gated.jsonl"
    gated.write_text(
        json.dumps(
            {
                "text": "red or yellow flowers",
                "assertions": [
                    {
                        "po_id": "PO_flower",
                        "pato_id": "PATO_color",
                        "value_operator": "one_of",
                        "value_terms": ["PATO_red", "PATO_yellow"],
                        "source_text": "red or yellow flowers",
                        "gate": {"status": "accepted"},
                    }
                ],
            }
        )
        + "\n"
    )
    out = tmp_path / "flopo.ttl"
    stats = build_ontology(gated, out, registry, po, pato)
    signature = "EQ|PO_flower|PATO_color"
    trait_iri = URIRef(stats["minted_iris"][signature])
    graph = Graph().parse(out.as_posix())
    assert not list(graph.subjects(OWL.unionOf, None))
    assert (trait_iri, RDF.type, OWL.Class) in graph
    assert any(
        "quality color" in str(value)
        for value in graph.objects(
            trait_iri, URIRef("http://purl.obolibrary.org/obo/IAO_0000115")
        )
    )


def test_builder_emits_reusable_attribute_for_numeric_source_phenotype(tmp_path):
    from flopo2.owl.build import load_candidates

    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\nPO_leaf\tleaf\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\nPATO_length\tlength\n")
    registry = tmp_path / "registry.tsv"
    registry.write_text("flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n")
    gated = tmp_path / "gated.jsonl"
    gated.write_text(json.dumps({
        "text": "leaves 3 cm long",
        "assertions": [{
            "po_id": "PO_leaf",
            "pato_id": "PATO_length",
            "source_text": "3 cm long",
            "value_low": 3,
            "value_high": 3,
            "unit": "cm",
            "gate": {"status": "accepted"},
        }],
    }) + "\n")
    candidates = load_candidates(gated, po, pato, registry)
    assert len(candidates) == 1
    assert candidates[0].eq_signature == "EQ|PO_leaf|PATO_length"


def test_builder_keeps_distinct_attributes_when_source_disjunctions_differ(tmp_path):
    from flopo2.owl.build import load_candidates

    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\nPO_flower\tflower\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\nPATO_color\tcolor\nPATO_shape\tshape\nPATO_red\tred\nPATO_yellow\tyellow\n"
    )
    registry = tmp_path / "registry.tsv"
    registry.write_text("flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n")
    gated = tmp_path / "gated.jsonl"
    assertions = [
        {
            "po_id": "PO_flower",
            "pato_id": attribute,
            "value_operator": "one_of",
            "value_terms": ["PATO_red", "PATO_yellow"],
            "source_text": "red or yellow",
            "gate": {"status": "accepted"},
        }
        for attribute in ("PATO_color", "PATO_shape")
    ]
    gated.write_text(json.dumps({"text": "red or yellow", "assertions": assertions}) + "\n")
    candidates = load_candidates(gated, po, pato, registry)
    assert {candidate.eq_signature for candidate in candidates} == {
        "EQ|PO_flower|PATO_color",
        "EQ|PO_flower|PATO_shape",
    }


def test_builder_canonicalizes_direct_and_attribute_plus_atomic_value(tmp_path):
    from flopo2.owl.build import load_candidates

    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\nPO_stem\tstem\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\nPATO_shape\tshape\nPATO_cyl\tcylindrical\n")
    registry = tmp_path / "registry.tsv"
    registry.write_text("flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n")
    assertions = [
        {
            "po_id": "PO_stem",
            "pato_id": pato_id,
            "value_operator": "atomic",
            "value_terms": ["PATO_cyl"],
            "source_text": source,
            "gate": {"status": "accepted"},
        }
        for pato_id, source in (("PATO_shape", "cylindrical"), ("PATO_cyl", "cyl"))
    ]
    gated = tmp_path / "gated.jsonl"
    gated.write_text(json.dumps({"text": "cylindrical; cyl", "assertions": assertions}) + "\n")
    candidates = load_candidates(gated, po, pato, registry)
    assert len(candidates) == 1
    assert candidates[0].pato_id == "PATO_cyl"
    assert candidates[0].support == 2


def test_qc_checks_labels(tmp_path):
    from flopo2.owl.build import build_ontology
    from flopo2.owl.qc import qc

    registry = tmp_path / "registry.tsv"
    registry.write_text("flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n")
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\tnamespace\nPO_leaf\tleaf\t\tplant_anatomy\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\tsynonyms\tslim\nPATO_blue\tblue\t\t\n")
    gated = tmp_path / "gated.jsonl"
    gated.write_text(
        json.dumps({
            "text": "leaves blue",
            "assertions": [{"po_id": "PO_leaf", "pato_id": "PATO_blue", "gate": {"status": "accepted"}}],
        }) + "\n"
    )
    out = tmp_path / "flopo.ttl"
    build_ontology(gated, out, registry, po, pato)
    assert qc(out, gated)["ok"]


def test_build_ontology_obsoletes_unsupported_existing_in_release_mode(tmp_path):
    from flopo2.owl.build import IAO_0000116, build_ontology

    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000001\t1\tleaf green\tEQ|PO_leaf|PATO_green\t0\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000002\t2\tstem blue\tEQ|PO_stem|PATO_blue\t0\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000003\t3\tlegacy manual class\tOTHER\t0\n"
    )
    combos = tmp_path / "valid.tsv"
    combos.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_leaf\tPATO_green\tallowed\ttest\tleaf green\n"
        "PO_stem\tPATO_blue\tblocked\ttest\tstem blue\n"
    )
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\tnamespace\n"
        "PO_leaf\tleaf\t\tplant_anatomy\n"
        "PO_stem\tstem\t\tplant_anatomy\n"
    )
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tsynonyms\tslim\n"
        "PATO_green\tgreen\t\t\n"
        "PATO_blue\tblue\t\t\n"
    )
    gated = tmp_path / "gated.jsonl"
    gated.write_text(
        json.dumps({
            "text": "leaves green",
            "assertions": [{
                "po_id": "PO_leaf",
                "pato_id": "PATO_green",
                "source_text": "leaves green",
                "gate": {"status": "accepted"},
            }],
        }) + "\n"
    )
    out = tmp_path / "flopo.ttl"
    stats = build_ontology(
        gated,
        out,
        registry,
        po,
        pato,
        combinations_tsv=combos,
        obsolete_unsupported_existing=True,
    )
    assert stats["obsoleted_existing"] == 2

    g = Graph()
    g.parse(out.as_posix())
    unsupported = URIRef("http://purl.obolibrary.org/obo/FLOPO_0000002")
    legacy_other = URIRef("http://purl.obolibrary.org/obo/FLOPO_0000003")
    assert (unsupported, OWL.deprecated, None) in g
    assert any("validity gate" in str(o) for o in g.objects(unsupported, IAO_0000116))
    assert (legacy_other, OWL.deprecated, None) in g
    assert any("no recoverable" in str(o) for o in g.objects(legacy_other, IAO_0000116))
    assert not list(
        g.objects(unsupported, URIRef("http://purl.obolibrary.org/obo/IAO_0000231"))
    )


def test_sssom_generates_exact_label_mapping(tmp_path):
    from flopo2.owl.build import build_ontology
    from flopo2.owl.sssom import generate_mappings

    registry = tmp_path / "registry.tsv"
    registry.write_text("flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n")
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\tnamespace\nPO_leaf\tleaf\t\tplant_anatomy\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\tsynonyms\tslim\nPATO_green\tgreen\t\t\n")
    gated = tmp_path / "gated.jsonl"
    gated.write_text(
        json.dumps({
            "text": "leaves green",
            "assertions": [{"po_id": "PO_leaf", "pato_id": "PATO_green", "gate": {"status": "accepted"}}],
        }) + "\n"
    )
    owl = tmp_path / "flopo.ttl"
    build_ontology(gated, owl, registry, po, pato)
    to = tmp_path / "trait.obo"
    to.write_text("[Term]\nid: TO:0000001\nname: leaf green\n")
    out = tmp_path / "mappings.sssom.tsv"
    stats = generate_mappings(owl, {"TO": to}, out)

    assert stats["mappings"] == 1
    text = out.read_text()
    assert "FLOPO_0000002" in text
    assert "TO:0000001" in text
