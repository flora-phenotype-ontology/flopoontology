"""Schema extension E2: per-operand and per-endpoint degree/approximation/frequency qualifiers."""

from __future__ import annotations

import copy
import json
import sqlite3

import pytest
from rdflib import Graph, Literal, URIRef

from flopo2.annotation.operands import (
    DEGREE_AXIS,
    make_operand,
    operands_fac_representable,
    parse_qualifier_cue,
    validate_value_operands,
)
from flopo2.annotation.qualitative import is_fac_representable
from flopo2.owl.annotation_class import annotation_class_iri
from flopo2.owl.annotation_extension import build_annotation_extension
from flopo2.owl.assertions import FLOPOANN, _logical_status, _strict, build_assertion_ontology
from flopo2.verify.data_model import validate_jsonl

TEXT = "Petals glabrous or sparsely pubescent."
GLABROUS, PUBESCENT = "PATO_0000454", "PATO_0000604"  # glabrous, hairy/pubescent (test ids)


def _assertion(**overrides) -> dict:
    start = TEXT.index("glabrous")
    end = TEXT.index(".")
    assertion = {
        "po_id": "PO_0009032",
        "pato_id": "PATO_0000454",
        "value_operator": "one_of",
        "value_terms": [GLABROUS, PUBESCENT],
        "source_text": TEXT[0:end],
        "source_start": 0,
        "source_end": end,
        "raw_entity_text": "Petals",
        "bearer_start": 0,
        "bearer_end": 6,
        "raw_quality_text": TEXT[start:end],
        "value_text": TEXT[start:end],
        "negated": False,
        "extractor": "test",
        "composition": {"status": "accept"},
        "gate": {"status": "accepted"},
    }
    assertion.update(overrides)
    return assertion


def _operands() -> list[dict]:
    g = TEXT.index("glabrous")
    s = TEXT.index("sparsely")
    return [
        make_operand(0, GLABROUS, TEXT, g, g + len("glabrous")),
        make_operand(
            1,
            PUBESCENT,
            TEXT,
            s,
            TEXT.index("."),
            qualifier_start=s,
            qualifier_end=s + len("sparsely"),
            degree_qualifier="sparsely",
        ),
    ]


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


def _validate(tmp_path, assertion: dict) -> dict:
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps(_record(assertion)) + "\n", encoding="utf-8")
    return validate_jsonl(
        path, stage="gated", catalog_check=False, strict_source_statements=True
    )


def test_operands_never_change_fac_identity():
    plain = _assertion()
    with_operands = _assertion(value_operands=_operands())
    assert annotation_class_iri(plain) == annotation_class_iri(with_operands)
    assert operands_fac_representable(with_operands)
    assert is_fac_representable(with_operands)


def test_valid_operands_pass_data_model_validation(tmp_path):
    assertion = _assertion(value_operands=_operands())
    assertion["phenotype_class_iri"] = annotation_class_iri(assertion)
    report = _validate(tmp_path, assertion)
    assert report["ok"], report["error_examples"]


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda ops: ops[1].update(text="densely pubescent"), "value_operand_not_verbatim"),
        (lambda ops: ops[1].pop("qualifier_text"), "operand_qualifier_missing_cue"),
        (
            lambda ops: ops[1].update(qualifier_start=0, qualifier_end=6, qualifier_text="Petals"),
            "operand_qualifier_outside_operand",
        ),
        (lambda ops: ops[1].update(value="PATO_0000322"), "value_operands_terms_mismatch"),
        (lambda ops: ops.reverse(), "value_operand_index_mismatch"),
        (lambda ops: ops[1].update(degree_qualifier="thickly"), "invalid_operand_degree_qualifier"),
    ],
)
def test_operand_validator_rules(mutate, code):
    assertion = _assertion(value_operands=_operands())
    mutate(assertion["value_operands"])
    codes = {issue.code for issue in validate_value_operands(assertion, TEXT)}
    assert code in codes


def test_same_axis_conflict_but_orthogonal_axes_combine():
    assertion = _assertion(value_operands=_operands(), degree_qualifier="densely")
    codes = {issue.code for issue in validate_value_operands(assertion, TEXT)}
    assert "assertion_and_operand_qualifier_conflict" in codes
    assertion = _assertion(value_operands=_operands(), degree_qualifier="very")
    codes = {issue.code for issue in validate_value_operands(assertion, TEXT)}
    assert "assertion_and_operand_qualifier_conflict" not in codes


def test_non_entailing_operand_is_not_fac(tmp_path):
    text = "Leaves slightly pubescent or subglabrous."
    start = text.index("subglabrous")
    operands = [
        make_operand(
            0,
            PUBESCENT,
            text,
            text.index("slightly"),
            text.index(" or"),
            qualifier_start=text.index("slightly"),
            qualifier_end=text.index("slightly") + 8,
            degree_qualifier="slightly",
        ),
        make_operand(
            1,
            GLABROUS,
            text,
            start,
            start + len("subglabrous"),
            qualifier_start=start,
            qualifier_end=start + 3,
            value_qualifier="sub",
        ),
    ]
    assertion = _assertion(value_operands=operands)
    assert not operands_fac_representable(assertion)
    assert not is_fac_representable(assertion)
    assertion["phenotype_class_iri"] = annotation_class_iri(assertion)
    codes = {issue.code for issue in validate_value_operands(assertion, text)}
    assert "non_entailing_operand_in_fac" in codes
    assert not _strict(assertion, True)
    assert _logical_status(assertion, False) == "structured_value_operands"


def test_frequency_operand_keeps_fac_but_is_not_strict():
    assertion = _assertion(value_operands=_operands())
    assert _strict(assertion, True)
    assertion["value_operands"][1]["frequency_qualifier"] = "rarely"
    assert operands_fac_representable(assertion)
    assert not _strict(assertion, True)


@pytest.mark.parametrize(
    ("cue", "degree", "value", "frequency"),
    [
        ("± densely", "densely", "approximately", "unspecified"),
        ("very sparsely", "sparsely", "exact", "unspecified"),
        ("usually densely", "densely", "exact", "usually"),
        ("étroitement", "narrowly", "exact", "unspecified"),
        ("largement", "broadly", "exact", "unspecified"),
        ("densément", "densely", "exact", "unspecified"),
        ("peu", "sparsely", "exact", "unspecified"),
        ("peu profondément", "shallowly", "exact", "unspecified"),
        ("un peu", "slightly", "exact", "unspecified"),
        ("brièvement", "shortly", "exact", "unspecified"),
        ("finement", "finely", "exact", "unspecified"),
        ("profondément", "deeply", "exact", "unspecified"),
        ("plus ou moins densément", "densely", "approximately", "unspecified"),
        ("sub", "unmodified", "sub", "unspecified"),
    ],
)
def test_bilingual_cue_mapping(cue, degree, value, frequency):
    parsed = parse_qualifier_cue(cue)
    assert parsed == {
        "degree_qualifier": degree,
        "value_qualifier": value,
        "frequency_qualifier": frequency,
    }


def test_linkml_enums_and_axis_annotations():
    import yaml

    from flopo2.schema.flopo_trait_models import DegreeQualifier, ValueOperand, ValueQualifier

    for value in DEGREE_AXIS:
        assert DegreeQualifier(value)
    assert ValueQualifier("sub")
    schema = yaml.safe_load(open("flopo2/schema/flopo_trait.yaml", encoding="utf-8"))
    degree_values = schema["enums"]["DegreeQualifier"]["permissible_values"]
    for value, axis in DEGREE_AXIS.items():
        assert degree_values[value]["annotations"]["axis"] == axis
    operand = ValueOperand(operand_index=0, value=GLABROUS, text="glabrous", start=0, end=8)
    assert operand.degree_qualifier == "unmodified"


def test_relation_endpoint_operand_rules():
    text = "Leaves narrowly elliptic to broadly elliptic."
    relation_text = "narrowly elliptic"
    start = text.index(relation_text)
    relation = {
        "interpretation": "continuum",
        "from_value": "PATO_0001872",
        "to_value": "PATO_0001873",
        "from_text": relation_text,
        "from_start": start,
        "from_end": start + len(relation_text),
        "connector_text": "to",
        "connector_start": text.index(" to ") + 1,
        "connector_end": text.index(" to ") + 3,
        "to_text": "broadly elliptic",
        "to_start": text.index("broadly"),
        "to_end": text.index("."),
        "from_operand": make_operand(
            0,
            "PATO_0001872",
            text,
            start,
            start + len(relation_text),
            qualifier_start=start,
            qualifier_end=start + 8,
            degree_qualifier="narrowly",
        ),
    }
    assertion = {"po_id": "PO_0025034", "pato_id": "PATO_0000052", "qualitative_value_relation": relation}
    assert not validate_value_operands(assertion, text)
    bad = copy.deepcopy(assertion)
    bad["qualitative_value_relation"]["from_operand"]["value"] = "PATO_0001873"
    codes = {issue.code for issue in validate_value_operands(bad, text)}
    assert "qualitative_endpoint_operand_mismatch" in codes


def test_owl_serialization_emits_operands_and_skips_non_fac(tmp_path):
    fac = _assertion(value_operands=_operands())
    fac["phenotype_class_iri"] = annotation_class_iri(fac)
    non_fac = copy.deepcopy(fac)
    non_fac.pop("phenotype_class_iri")
    non_fac["value_operands"][1]["value_qualifier"] = "nearly"
    non_fac["value_operands"][1]["qualifier_text"] = "sparsely"
    record = _record(fac)
    record["assertions"].append({**non_fac, "source_statement_id": "s1"})
    source = tmp_path / "gated.jsonl"
    source.write_text(json.dumps(record) + "\n", encoding="utf-8")

    stats = build_annotation_extension(
        source, tmp_path / "ext.ttl", include_imports=False, output_format="turtle"
    )
    assert stats["fac_assertions"] == 1
    assert stats["structured_value_operand_lists"] == 1

    module_stats = build_assertion_ontology(
        source, tmp_path / "module.ttl", include_imports=False
    )
    assert module_stats["assertions_with_value_operands"] == 2
    assert module_stats["structured_value_operand_lists"] == 1
    graph = Graph().parse(tmp_path / "module.ttl")
    operands = set(graph.subjects(None, FLOPOANN.ValueOperand))
    assert len(operands) == 4
    assert (None, FLOPOANN.operand_degree_qualifier, FLOPOANN.sparsely) in graph
    assert (None, FLOPOANN.operand_qualifier_text, Literal("sparsely")) in graph
    assert (
        None,
        FLOPOANN.operand_value,
        URIRef("http://purl.obolibrary.org/obo/" + GLABROUS),
    ) in graph


def test_database_stores_value_operands(tmp_path):
    from flopo2.db.load import load_jsonl

    assertion = _assertion(value_operands=_operands())
    source = tmp_path / "gated.jsonl"
    source.write_text(json.dumps(_record(assertion)) + "\n", encoding="utf-8")
    db = tmp_path / "t.sqlite"
    load_jsonl(db, source)
    with sqlite3.connect(db) as conn:
        stored = conn.execute("SELECT value_operands FROM trait_assertion").fetchone()[0]
    assert json.loads(stored)[1]["degree_qualifier"] == "sparsely"
