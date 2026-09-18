from __future__ import annotations

import json

from rdflib import OWL, RDF, Graph, URIRef

from flopo2.ids.registry import (
    build_registry,
    parse_relational_signature,
    relational_signature,
)
from flopo2.owl.build import build_ontology


def test_eqr_signature_is_canonical_collision_safe_and_round_trips():
    first = relational_signature(
        "PO_0025034",
        "PATO_0000320",
        [
            ("BFO_0000051", "PO_0000282", ("PATO_0000322", "FLOPO_1234567")),
            ("BFO:0000051", "PO:0000282", ("PATO:0000322",)),
        ],
    )
    bearer, quality, parts = parse_relational_signature(first)
    assert bearer == "PO_0025034"
    assert quality == "PATO_0000320"
    assert relational_signature(bearer, quality, parts) == first
    assert first.startswith("EQR|{")


def test_relational_class_builds_nested_owl_and_registry_recovers_eqr(tmp_path):
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n",
        encoding="utf-8",
    )
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\nPO_0025034\tleaf\nPO_0000282\ttrichome\n",
        encoding="utf-8",
    )
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tslim\n"
        "PATO_0000001\tquality\t\n"
        "PATO_0000320\tgreen\t\n"
        "PATO_0000322\tred\t\n",
        encoding="utf-8",
    )
    source = tmp_path / "accepted.jsonl"
    assertion = {
        "po_id": "PO_0025034",
        "pato_id": "PATO_0000320",
        "part_restrictions": [
            {
                "property": "BFO_0000051",
                "filler_class": "PO_0000282",
                "qualities": ["PATO_0000322"],
            }
        ],
        "source_text": "leaves green with red trichomes",
        "source_start": 0,
        "source_end": 31,
        "gate": {"status": "accepted", "flopo_status": "new_class_candidate"},
    }
    source.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "one.xml",
                "taxon": "Planta exemplar",
                "text": assertion["source_text"],
                "assertions": [assertion],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "candidate.ttl"
    build_ontology(
        source,
        output,
        registry_tsv=registry,
        po_lex=po,
        pato_lex=pato,
        output_format="turtle",
    )

    entries = build_registry(output)
    relational = [entry for entry in entries if entry.signature.startswith("EQR|")]
    assert len(relational) == 1
    bearer, quality, parts = parse_relational_signature(relational[0].signature)
    assert (bearer, quality) == ("PO_0025034", "PATO_0000320")
    assert parts == (("BFO_0000051", "PO_0000282", ("PATO_0000322",)),)

    graph = Graph().parse(output)
    relational_class = URIRef(relational[0].iri)
    assert (relational_class, RDF.type, OWL.Class) in graph
