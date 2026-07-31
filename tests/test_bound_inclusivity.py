"""Regression tests for explicit numeric-bound inclusivity.

An inclusive upper bound must render ``xsd:maxInclusive`` (the historical behaviour, byte-stable
FAC identity); a strict upper bound (``value_high_inclusive=False``) must render
``xsd:maxExclusive`` and mint a *distinct* FAC identity.  The strict French participial
``n'atteignant pas 0,5 mm`` ("reaching less than 0.5 mm") is the motivating case.
"""

from __future__ import annotations

import sqlite3

from rdflib import OWL, RDF, XSD, Graph

from flopo2.owl import assertions as A
from flopo2.owl.annotation_class import annotation_class_iri
from flopo2.owl.assertions import formal_assertion_iri
from flopo2.extract import compose, run
from flopo2.verify import data_model, gates


ATTR = {"PATO_0000122"}  # length, attribute_slim


def _numeric_assertion(**extra) -> dict:
    base = {
        "po_id": "PO_0009073",
        "pato_id": "PATO_0000122",
        "value_low": None,
        "value_high": 0.5,
        "unit": "mm",
        "value_operator": "atomic",
        "negated": False,
        "source_text": "n'atteignant pas 0,5 mm",
        "source_start": 0,
        "source_end": 23,
    }
    base.update(extra)
    return base


def _facets(assertion: dict) -> set:
    """Return the set of facet predicates emitted for the assertion's numeric datatype."""
    graph = Graph()
    nodes = A._Nodes()
    A._quality_restrictions(graph, nodes, assertion, ATTR)
    datatype = next(graph.subjects(OWL.onDatatype, XSD.decimal))
    restr = next(graph.objects(datatype, OWL.withRestrictions))
    facet_predicates = set()
    for facet in graph.items(restr):
        for pred, _obj in graph.predicate_objects(facet):
            if pred != RDF.type:
                facet_predicates.add(pred)
    return facet_predicates


def test_inclusive_upper_bound_renders_max_inclusive():
    assert XSD.maxInclusive in _facets(_numeric_assertion())
    assert XSD.maxExclusive not in _facets(_numeric_assertion())


def test_strict_upper_bound_renders_max_exclusive():
    facets = _facets(_numeric_assertion(value_high_inclusive=False))
    assert XSD.maxExclusive in facets
    assert XSD.maxInclusive not in facets


def test_strict_lower_bound_renders_min_exclusive():
    assertion = _numeric_assertion(
        value_low=1.0,
        value_high=None,
        value_low_inclusive=False,
        source_text="more than 1 mm",
        source_end=14,
    )
    facets = _facets(assertion)
    assert XSD.minExclusive in facets
    assert XSD.minInclusive not in facets


def test_default_is_inclusive_and_identity_stable():
    """Omitting the flag must be byte-for-byte identical to an explicit inclusive bound."""
    without_flag = _numeric_assertion()
    with_flag = _numeric_assertion(value_high_inclusive=True)
    assert annotation_class_iri(without_flag) == annotation_class_iri(with_flag)
    assert formal_assertion_iri("s", 0, without_flag) == formal_assertion_iri("s", 0, with_flag)


def test_fac_identity_changes_with_inclusivity():
    inclusive = annotation_class_iri(_numeric_assertion(value_high_inclusive=True))
    strict = annotation_class_iri(_numeric_assertion(value_high_inclusive=False))
    assert inclusive != strict


def test_formal_assertion_iri_changes_with_inclusivity():
    inclusive = formal_assertion_iri("s", 0, _numeric_assertion(value_high_inclusive=True))
    strict = formal_assertion_iri("s", 0, _numeric_assertion(value_high_inclusive=False))
    assert inclusive != strict


def test_strict_bound_gate_not_blocked_and_no_defect_reasons():
    """A strict upper bound with the comparator in source_text must not be *blocked*; a novel
    numeric trait may still route to curator review, but never for being strict or for a missing
    cue."""
    decision = gates.check_assertion(
        "n'atteignant pas 0,5 mm",
        _numeric_assertion(value_high_inclusive=False),
        combos={("PO_0009073", "PATO_0000122"): gates.Combination(status="allowed")},
        attribute_pato_ids=ATTR,
    )
    assert decision.status != "blocked", decision.reasons
    for defect in (
        "invalid_bound_inclusivity",
        "bound_inclusivity_without_bound",
        "upper_bound_cue_not_in_source_span",
    ):
        assert defect not in decision.reasons


def test_exclusive_flag_without_bound_is_flagged():
    decision = gates.check_assertion(
        "leaves green",
        {
            "po_id": "PO_0009025",
            "pato_id": "PATO_0000320",
            "value_operator": "atomic",
            "value_high_inclusive": False,
            "source_text": "green",
            "source_start": 7,
            "source_end": 12,
        },
        combos={("PO_0009025", "PATO_0000320"): gates.Combination(status="allowed")},
        attribute_pato_ids=ATTR,
    )
    assert "bound_inclusivity_without_bound" in decision.reasons


def test_data_model_flags_exclusive_flag_without_bound():
    issues: list = []
    data_model._validate_assertion(
        {
            "po_id": "PO_0009025",
            "pato_id": "PATO_0000320",
            "source_text": "green",
            "source_start": 0,
            "source_end": 5,
            "value_high_inclusive": False,
            "source_statement_id": "statement-x",
            "composition": {"status": "accept"},
            "gate": {"status": "accepted"},
        },
        text="green leaves",
        line_number=1,
        assertion_number=0,
        mention_ids=set(),
        statement_ids={"statement-x"},
        source_statements_present=True,
        po_ids=set(),
        flopo_bearer_ids=set(),
        pato_ids=set(),
        attribute_pato_ids=ATTR,
        stage="gated",
        require_annotation_class=False,
        issues=issues,
    )
    assert any(issue.code == "bound_inclusivity_without_bound" for issue in issues)


def test_data_model_accepts_strict_bound_with_comparator():
    issues: list = []
    data_model._validate_assertion(
        _numeric_assertion(
            value_high_inclusive=False,
            source_statement_id="statement-y",
            composition={"status": "accept"},
            gate={"status": "accepted"},
        ),
        text="n'atteignant pas 0,5 mm",
        line_number=1,
        assertion_number=0,
        mention_ids=set(),
        statement_ids={"statement-y"},
        source_statements_present=True,
        po_ids={"PO_0009073"},
        flopo_bearer_ids=set(),
        pato_ids={"PATO_0000122"},
        attribute_pato_ids=ATTR,
        stage="gated",
        require_annotation_class=False,
        issues=issues,
    )
    codes = {issue.code for issue in issues}
    assert "bound_inclusivity_without_bound" not in codes
    assert "upper_bound_cue_not_in_source_span" not in codes


def test_sqlite_roundtrips_inclusivity_column():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE t(value_high REAL, value_high_inclusive INTEGER NOT NULL DEFAULT 1);"
    )
    conn.execute(
        "INSERT INTO t(value_high, value_high_inclusive) VALUES (0.5, ?)",
        (1 if _numeric_assertion(value_high_inclusive=False).get("value_high_inclusive") else 0,),
    )
    row = conn.execute("SELECT value_high_inclusive FROM t").fetchone()
    assert row[0] == 0


def test_compose_and_extraction_serializers_preserve_strict_bound():
    record = {
        "text": "stigmas n'atteignant pas 0,5 mm",
        "assertions": [_numeric_assertion(value_high_inclusive=False)],
    }
    assertion = compose._assertions_from_json(record)[0]
    assert assertion.value_low_inclusive is True
    assert assertion.value_high_inclusive is False

    composed = compose._assertion_to_json(assertion)
    extracted = run._assertion_to_json(assertion, {}, {})
    assert composed["value_high_inclusive"] is False
    assert extracted["value_high_inclusive"] is False
