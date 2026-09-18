"""Schema extension E3: bearer scope, nested part restrictions and pinned BSPO fillers."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from rdflib import OWL, Graph, URIRef
from rdflib.collection import Collection

from flopo2.annotation.positional import (
    find_surface_cues,
    load_bspo_ids,
    po_scope_within,
    surface_scope,
    validate_positional,
)
from flopo2.owl.annotation_class import annotation_class_iri, annotation_class_signature
from flopo2.owl.annotation_extension import BSPO_IMPORT, build_annotation_extension
from flopo2.verify.data_model import validate_jsonl
from flopo2.verify.gates import assertion_signature

ROOT = Path(__file__).resolve().parents[1]
OBO = "http://purl.obolibrary.org/obo/"
TEXT = "Leaves stellate-pubescent beneath; ovary glabrous or hairy at the apex."


def _stellate_beneath() -> dict:
    cue = TEXT.index("beneath")
    stellate = TEXT.index("stellate")
    return {
        "po_id": "PO_0000049",
        "pato_id": "PATO_0001320",
        "raw_entity_text": "Leaves",
        "bearer_start": 0,
        "bearer_end": 6,
        "source_text": TEXT[: cue + len("beneath")],
        "source_start": 0,
        "source_end": cue + len("beneath"),
        "negated": False,
        "extractor": "test",
        "composition": {"status": "accept"},
        "gate": {"status": "accepted"},
        "part_restrictions": [
            {
                "property": "BFO_0000051",
                "filler_class": "PO_0000282",
                "qualities": ["PATO_0002065"],
                "part_text": "stellate",
                "part_start": stellate,
                "part_end": stellate + len("stellate"),
            }
        ],
        "bearer_scope": {
            "outer_bearer": "PO_0025034",
            "scope_class": "PO_0000049",
            "mode": "substituted_bearer",
            "scope_text": "beneath",
            "scope_start": cue,
            "scope_end": cue + len("beneath"),
        },
    }


def _record(assertion: dict) -> dict:
    return {
        "source": "flora-test",
        "source_id": "x.xml",
        "taxon": "Planta exemplar",
        "text": TEXT,
        "source_statements": [
            {"statement_id": "s1", "verbatim_text": TEXT, "start": 0, "end": len(TEXT)}
        ],
        "assertions": [{**assertion, "source_statement_id": "s1"}],
    }


def test_depth_one_identity_ignores_evidence_and_scope():
    assertion = _stellate_beneath()
    plain = copy.deepcopy(assertion)
    plain.pop("bearer_scope")
    for key in ("part_text", "part_start", "part_end"):
        plain["part_restrictions"][0].pop(key)
    assert annotation_class_iri(assertion) == annotation_class_iri(plain)
    assert "part_restrictions" not in annotation_class_signature(plain)["part_restrictions"][0]


def test_nested_parts_are_additive_and_depth_limited():
    assertion = {
        "po_id": "PO_0020049",
        "pato_id": "PATO_0001320",
        "part_restrictions": [
            {
                "property": "BFO_0000051",
                "filler_class": "PO_0006019",
                "qualities": [],
                "part_restrictions": [
                    {"property": "BFO_0000051", "filler_class": "PO_0000282",
                     "qualities": ["PATO_0002065"]}
                ],
            }
        ],
    }
    signature = annotation_class_signature(assertion)
    nested = signature["part_restrictions"][0]["part_restrictions"]
    assert nested[0]["filler_class"] == OBO + "PO_0000282"
    flat = copy.deepcopy(assertion)
    flat["part_restrictions"][0]["qualities"] = ["PATO_0002065"]
    flat["part_restrictions"][0].pop("part_restrictions")
    assert annotation_class_iri(flat) != annotation_class_iri(assertion)
    assert assertion_signature(assertion).startswith("EQRN|")
    too_deep = copy.deepcopy(assertion)
    too_deep["part_restrictions"][0]["part_restrictions"][0]["part_restrictions"] = [
        {"property": "BFO_0000051", "filler_class": "PO_0000282", "qualities": ["PATO_0000320"]}
    ]
    with pytest.raises(ValueError, match="depth exceeds"):
        annotation_class_signature(too_deep)


def test_bspo_filler_is_a_region_of_the_bearer():
    assertion = {
        "po_id": "PO_0009072",
        "pato_id": "PATO_0000454",
        "part_restrictions": [
            {"property": "BFO_0000051", "filler_class": "BSPO:0000073", "qualities": ["PATO_0000454"]}
        ],
    }
    signature = annotation_class_signature(assertion)
    assert signature["part_restrictions"][0]["filler_class"] == OBO + "BSPO_0000073"
    assert "BSPO_0000073" in load_bspo_ids()
    bad = copy.deepcopy(assertion)
    bad["part_restrictions"][0]["filler_class"] = "BSPO_0000999"
    codes = {code for code, _ in validate_positional(bad, "")}
    assert "unknown_part_restriction_bspo_filler" in codes


def test_bearer_scope_rules():
    assertion = _stellate_beneath()
    assert validate_positional(assertion, TEXT) == []
    wrong_mode = copy.deepcopy(assertion)
    wrong_mode["po_id"] = "PO_0025034"
    assert "bearer_scope_mode_mismatch" in {c for c, _ in validate_positional(wrong_mode, TEXT)}
    not_verbatim = copy.deepcopy(assertion)
    not_verbatim["bearer_scope"]["scope_start"] += 1
    assert "bearer_scope_not_verbatim" in {c for c, _ in validate_positional(not_verbatim, TEXT)}
    unrelated = copy.deepcopy(assertion)
    unrelated["bearer_scope"]["outer_bearer"] = "PO_0009032"
    assert "bearer_scope_outer_not_ancestor" in {
        c for c, _ in validate_positional(unrelated, TEXT)
    }
    assert po_scope_within("PO_0000049", "PO_0025034")
    assert po_scope_within("PO_0000049", "PO_0009025")  # vascular leaf is a leaf
    assert not po_scope_within("PO_0006052", "PO_0025034")


def test_data_model_accepts_scoped_nested_assertion(tmp_path):
    assertion = _stellate_beneath()
    assertion["phenotype_class_iri"] = annotation_class_iri(assertion)
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps(_record(assertion)) + "\n", encoding="utf-8")
    report = validate_jsonl(path, stage="gated", catalog_check=False, strict_source_statements=True)
    assert report["ok"], report["error_examples"]
    broken = copy.deepcopy(assertion)
    broken["part_restrictions"][0]["part_text"] = "hairs"
    path.write_text(json.dumps(_record(broken)) + "\n", encoding="utf-8")
    report = validate_jsonl(path, stage="gated", catalog_check=False, strict_source_statements=True)
    assert "part_text_not_verbatim" in report["errors_by_code"]


@pytest.mark.parametrize(
    ("text", "side"),
    [
        ("glabrous above", "adaxial"),
        ("pubescent beneath", "abaxial"),
        ("pubescentes à la face inférieure", "abaxial"),
        ("glabre en dessus", "adaxial"),
        ("vert dessous", "abaxial"),
        ("hairy outside", "outside"),
        ("glabrous on the lower surface", "abaxial"),
    ],
)
def test_surface_cue_lexicon(text, side):
    cues = find_surface_cues(text, 0, len(text))
    assert cues and cues[0][0] == side


def test_surface_cue_guards_and_scope_table():
    assert not find_surface_cues("hairy below the middle", 0, 22)
    assert surface_scope("PO_0020039", "abaxial", 0, 1).scope_class == "PO_0000049"
    leaflet = surface_scope("PO_0020049", "adaxial", 0, 1)
    assert (leaflet.scope_class, leaflet.mode) == ("PO_0006018", "substituted_bearer")
    assert surface_scope("PO_0020039", "outside", 0, 1) is None  # only perianth members/bracts
    assert surface_scope("PO_0009031", "outside", 0, 1).scope_class == "PO_0006054"
    assert surface_scope("PO_0009047", "abaxial", 0, 1) is None  # stems are not laminar


def _members(graph: Graph, expression) -> list:
    head = next(graph.objects(expression, OWL.intersectionOf), None)
    return list(Collection(graph, head)) if head is not None else []


def test_nested_owl_compilation_and_bspo_import(tmp_path):
    assertion = {
        "po_id": "PO_0020049",
        "pato_id": "PATO_0001320",
        "source_text": TEXT,
        "part_restrictions": [
            {
                "property": "BFO_0000051",
                "filler_class": "PO_0006019",
                "qualities": [],
                "part_restrictions": [
                    {"property": "BFO_0000051", "filler_class": "PO_0000282",
                     "qualities": ["PATO_0002065"]}
                ],
            }
        ],
    }
    source = tmp_path / "rows.jsonl"
    source.write_text(json.dumps({"source": "t", "source_id": "t", "text": TEXT,
                                  "assertions": [assertion]}) + "\n", encoding="utf-8")
    output = tmp_path / "ext.ttl"
    build_annotation_extension(source, output, include_imports=True, output_format="turtle")
    graph = Graph().parse(output)
    assert (None, OWL.imports, BSPO_IMPORT) in graph
    epidermis = URIRef(OBO + "PO_0006019")
    trichome = URIRef(OBO + "PO_0000282")
    epidermis_expression = next(
        node for node in graph.subjects(None, None) if epidermis in _members(graph, node)
    )
    nested = [m for m in _members(graph, epidermis_expression) if (m, OWL.someValuesFrom, None) in graph]
    fillers = {next(graph.objects(m, OWL.someValuesFrom)) for m in nested}
    assert any(trichome in _members(graph, filler) for filler in fillers)


def test_bspo_module_is_pinned_and_cataloged():
    module = ROOT / "ontology" / "imports" / "bspo_import.owl"
    pins = (ROOT / "ontology" / "imports" / "bspo_import.sha256").read_text(encoding="utf-8")
    assert hashlib.sha256(module.read_bytes()).hexdigest() in pins
    text = module.read_text(encoding="utf-8")
    for term in ("BSPO_0000073", "BSPO_0000074", "BSPO_0000006", "BSPO_0000001", "BSPO_0000002"):
        assert f"obo/{term}\"" in text
    assert "bspo/releases/2023-05-27/bspo.owl" in text
    for catalog, uri in (
        (ROOT / "ontology" / "catalog-v001.xml", "imports/bspo_import.owl"),
        (ROOT / "catalog-v001.xml", "ontology/imports/bspo_import.owl"),
    ):
        entries = {
            node.get("name"): node.get("uri") for node in ET.parse(catalog).getroot().iter()
            if node.get("name")
        }
        assert entries[str(BSPO_IMPORT)] == uri


def test_database_stores_bearer_scope(tmp_path):
    from flopo2.db.load import load_jsonl

    source = tmp_path / "rows.jsonl"
    source.write_text(json.dumps(_record(_stellate_beneath())) + "\n", encoding="utf-8")
    db = tmp_path / "t.sqlite"
    load_jsonl(db, source)
    with sqlite3.connect(db) as conn:
        stored = conn.execute("SELECT bearer_scope, part_restrictions FROM trait_assertion").fetchone()
    assert json.loads(stored[0])["scope_class"] == "PO_0000049"
    assert json.loads(stored[1])[0]["filler_class"] == "PO_0000282"
