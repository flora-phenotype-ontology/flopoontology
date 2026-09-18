from __future__ import annotations

import copy
import json

import pytest
from rdflib import OWL, URIRef, Graph
from rdflib.collection import Collection

from flopo2.owl.annotation_class import annotation_class_iri, annotation_class_signature
from flopo2.owl.annotation_extension import build_annotation_extension


OBO = "http://purl.obolibrary.org/obo/"
HAS_PART = URIRef(OBO + "BFO_0000051")
HAS_QUALITY = URIRef(OBO + "RO_0000053")
LEAF = URIRef(OBO + "PO_0025034")
TRICHOME = URIRef(OBO + "PO_0000282")
GREEN = URIRef(OBO + "PATO_0000320")
RED = URIRef(OBO + "PATO_0000322")


def _assertion() -> dict:
    return {
        "po_id": "PO_0025034",
        "pato_id": "PATO_0000320",
        "part_restrictions": [
            {
                "property": "BFO_0000051",
                "filler_class": "PO_0000282",
                "qualities": ["PATO_0000322"],
            }
        ],
        "source_text": "leaves with red trichomes are green",
    }


def _members(graph: Graph, expression) -> list:
    head = next(graph.objects(expression, OWL.intersectionOf), None)
    return list(Collection(graph, head)) if head is not None else []


def test_part_restrictions_are_sorted_and_empty_preserves_fac_identity():
    baseline = {"po_id": "PO_0025034", "pato_id": "PATO_0000320"}
    assert annotation_class_iri(baseline) == annotation_class_iri(
        {**baseline, "part_restrictions": []}
    )

    assertion = _assertion()
    reordered = copy.deepcopy(assertion)
    reordered["part_restrictions"] = [
        {
            "property": "BFO:0000051",
            "filler_class": "PO:0000282",
            "qualities": ["PATO:0000322", "PATO_0000322"],
        },
        copy.deepcopy(assertion["part_restrictions"][0]),
    ]
    assert annotation_class_iri(assertion) == annotation_class_iri(reordered)
    assert annotation_class_iri(assertion) != annotation_class_iri(baseline)
    signature = annotation_class_signature(assertion)
    assert signature["part_restrictions"] == [
        {
            "property": OBO + "BFO_0000051",
            "filler_class": OBO + "PO_0000282",
            "qualities": [OBO + "PATO_0000322"],
        }
    ]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("property", "RO_0000053", "property must be BFO"),
        ("filler_class", "PATO_0000322", "filler must be a PO"),
        ("qualities", [], "at least one quality"),
        ("qualities", ["PO_0000282"], "must be PATO or FLOPO"),
    ],
)
def test_part_restriction_validation(field, value, message):
    assertion = _assertion()
    assertion["part_restrictions"][0][field] = value
    with pytest.raises(ValueError, match=message):
        annotation_class_signature(assertion)


def test_part_quality_compiles_on_nested_part_and_is_not_flattened(tmp_path):
    assertion = _assertion()
    source = tmp_path / "source.jsonl"
    source.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "relational.xml",
                "taxon": "Planta exemplar",
                "text": assertion["source_text"],
                "assertions": [assertion],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "extension.ttl"
    build_annotation_extension(source, output, include_imports=False, output_format="turtle")
    graph = Graph().parse(output)

    outer_restriction = next(
        restriction
        for restriction in graph.subjects(OWL.onProperty, HAS_PART)
        if LEAF
        in _members(graph, next(graph.objects(restriction, OWL.someValuesFrom), None))
    )
    outer_filler = next(graph.objects(outer_restriction, OWL.someValuesFrom))
    outer_members = _members(graph, outer_filler)
    outer_quality_fillers = {
        next(graph.objects(member, OWL.someValuesFrom), None)
        for member in outer_members
        if (member, OWL.onProperty, HAS_QUALITY) in graph
    }
    assert GREEN in outer_quality_fillers
    assert RED not in outer_quality_fillers

    nested_restriction = next(
        member for member in outer_members if (member, OWL.onProperty, HAS_PART) in graph
    )
    nested_filler = next(graph.objects(nested_restriction, OWL.someValuesFrom))
    nested_members = _members(graph, nested_filler)
    assert TRICHOME in nested_members
    assert any(
        (member, OWL.onProperty, HAS_QUALITY) in graph
        and (member, OWL.someValuesFrom, RED) in graph
        for member in nested_members
    )


def test_part_restriction_linkml_model_requires_supported_property_and_quality():
    from flopo2.schema.flopo_trait_models import PartRestriction, TraitAssertion

    assertion = TraitAssertion(
        anatomical_entity="PO_0025034",
        quality="PATO_0000320",
        part_restrictions=[
            PartRestriction(
                property="BFO_0000051",
                filler_class="PO_0000282",
                qualities=["PATO_0000322"],
            )
        ],
        source_text="leaves with red trichomes are green",
    )
    assert assertion.part_restrictions[0].qualities == ["PATO_0000322"]
    with pytest.raises(Exception):
        PartRestriction(
            property="RO_0000053",
            filler_class="PO_0000282",
            qualities=["PATO_0000322"],
        )
    # E3: qualities may be empty at schema level (nested parts carry them); the canonical
    # grammar still rejects a part with neither qualities nor nested parts.
    empty = PartRestriction(property="BFO_0000051", filler_class="PO_0000282", qualities=[])
    with pytest.raises(ValueError, match="at least one quality or a nested"):
        annotation_class_signature(
            {
                "po_id": "PO_0025034",
                "pato_id": "PATO_0000320",
                "part_restrictions": [empty.model_dump(exclude_none=True)],
            }
        )


def test_part_restriction_data_model_adapter_validates_catalog_ids(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\nPO_0025034\tleaf\nPO_0000282\ttrichome\n",
        encoding="utf-8",
    )
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\nPATO_0000320\tgreen\nPATO_0000322\tred\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n",
        encoding="utf-8",
    )
    record = {
        "source": "flora-test",
        "source_id": "one.xml",
        "text": "leaves with red trichomes are green",
        "assertions": [_assertion()],
    }
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(record) + "\n", encoding="utf-8")
    report = validate_jsonl(
        source,
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
    )
    assert report["ok"], report

    record["assertions"][0]["part_restrictions"][0].update(
        {"filler_class": "PATO_0000322", "qualities": ["PO_0000282"]}
    )
    source.write_text(json.dumps(record) + "\n", encoding="utf-8")
    invalid = validate_jsonl(
        source,
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
    )
    assert invalid["errors_by_code"] == {
        "invalid_part_restriction_filler": 1,
        "invalid_part_restriction_quality": 1,
    }


def test_part_restrictions_round_trip_through_sqlite_loader(tmp_path):
    import sqlite3

    from flopo2.db.load import load_jsonl

    assertion = _assertion()
    source = tmp_path / "source.jsonl"
    source.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "one.xml",
                "text": assertion["source_text"],
                "assertions": [assertion],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    database = tmp_path / "traits.sqlite"
    load_jsonl(database, source)
    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT part_restrictions FROM trait_assertion"
        ).fetchone()[0]
    assert json.loads(stored) == assertion["part_restrictions"]
