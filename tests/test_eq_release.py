import pytest
from rdflib import Graph, URIRef, RDF, OWL
from flopo2.verify.eq_release import (
    OBO,
    deterministic_checks,
    neighbourhood,
    request_payload,
    validate_answer,
    eq_axioms,
)


def test_neighbourhood_uses_depth_and_does_not_loop():
    edges = {"C": {"D"}, "D": {"E", "C"}, "E": {"F"}, "F": {"G"}}
    assert neighbourhood("C", edges, 3) == {"D": 1, "E": 2, "F": 3}


@pytest.mark.parametrize(
    "answer,count",
    [
        ({"answers": []}, 0),
        ({"inheres": "maybe", "answers": []}, 0),
        ({"inheres": "yes", "answers": []}, 1),
        (
            {
                "inheres": "yes",
                "answers": [{"id": "0", "answer": "yes"}, {"id": "0", "answer": "yes"}],
            },
            2,
        ),
        ({"inheres": "yes", "answers": [{"id": "0", "answer": "probably"}]}, 1),
        ({"inheres": "yes", "answers": [{"id": 0, "answer": "yes"}]}, 1),
    ],
)
def test_incomplete_or_nonbinary_review_fails_closed(answer, count):
    with pytest.raises(ValueError):
        validate_answer(answer, count)


def test_both_inherence_and_every_hierarchy_answer_must_pass():
    assert validate_answer({"inheres": "yes", "answers": [{"id": "0", "answer": "yes"}]}, 1)
    assert not validate_answer({"inheres": "no", "answers": [{"id": "0", "answer": "yes"}]}, 1)
    assert not validate_answer({"inheres": "yes", "answers": [{"id": "0", "answer": "no"}]}, 1)


def test_subclass_question_is_reversed():
    import json

    c = {
        "class": {"label": "C", "id": "C"},
        "entity_info": {},
        "quality_info": {},
        "entity_ancestors": [],
        "quality_ancestors": [],
    }
    payload = request_payload(
        c,
        [
            {"id": "D", "label": "D", "direction": "superclass", "depth": 1},
            {"id": "S", "label": "S", "direction": "subclass", "depth": 2},
        ],
        "qwen",
    )
    q = json.loads(payload["messages"][1]["content"])["questions"]
    assert q[0]["question"] == "Is C a kind of D? Answer yes or no."
    assert q[1]["question"] == "Is S a kind of C? Answer yes or no."


def test_process_quality_is_rejected_even_if_owl_class_is_satisfiable():
    e, q = OBO + "PO_0009046", OBO + "PATO_0000389"
    c = {"entity": e, "quality": q, "id": "C"}
    parents = {q: {OBO + "PATO_0001236"}, OBO + "PATO_0001236": {OBO + "PATO_0000001"}}
    reasons = deterministic_checks(c, Graph(), parents, set(), {e, q}, {}, [])
    assert "process_quality_on_anatomical_entity" in reasons
    assert "pato_acute_process_duration_manual_review" in reasons


def test_bearer_constraints_use_ancestry_not_exact_label():
    e, q = OBO + "PO_leaflet", OBO + "FLOPO_leaf_quality"
    c = {"entity": e, "quality": q, "id": "C"}
    parents = {e: {OBO + "PO_leaf"}, q: {OBO + "PATO_0000001"}}
    rule = {"quality_id": "FLOPO_leaf_quality", "allowed_bearer_ancestors": "PO_leaf"}
    assert not deterministic_checks(c, Graph(), parents, set(), {e, q}, {}, [rule])
    rule["allowed_bearer_ancestors"] = "PO_flower"
    assert deterministic_checks(c, Graph(), parents, set(), {e, q}, {}, [rule]) == [
        "bearer_scope:FLOPO_leaf_quality"
    ]


def test_eq_definition_round_trips_to_registry_signature():
    from flopo2.ids.registry import _signature_of

    g = Graph()
    cls = eq_axioms(
        g, OBO + "FLOPO_9999999", OBO + "PO_0025034", OBO + "PATO_0000322", "leaf red", ""
    )
    assert _signature_of(g, cls) == "EQ|PO_0025034|PATO_0000322"


def test_real_elk_report_detects_equivalence_and_direct_hierarchy(tmp_path):
    from pathlib import Path
    from rdflib import RDFS
    from flopo2.verify.eq_release import reasoner_report, taxonomy

    root = Path(__file__).resolve().parents[1]
    if not (root / "tools/robot.jar").exists():
        pytest.skip("ROBOT jar not installed")
    import shutil

    if not shutil.which("javac"):
        pytest.skip("JDK not installed")
    g = Graph()
    e = URIRef(OBO + "PO_0025034")
    q = URIRef(OBO + "PATO_0000322")
    a = URIRef(OBO + "PATO_0000014")
    for n in [e, q, a]:
        g.add((n, RDF.type, OWL.Class))
    g.add((q, RDFS.subClassOf, a))
    eq_axioms(g, OBO + "FLOPO_A", str(e), str(q), "leaf red", "")
    eq_axioms(g, OBO + "FLOPO_B", str(e), str(q), "red leaf", "")
    eq_axioms(g, OBO + "FLOPO_T", str(e), str(a), "leaf colour", "")
    source = tmp_path / "mini.owl"
    g.serialize(source, format="xml")
    report = reasoner_report(source, tmp_path)
    parents, children, eq, unsat, classes = taxonomy(report)
    assert OBO + "FLOPO_B" in eq[OBO + "FLOPO_A"]
    assert OBO + "FLOPO_T" in parents[OBO + "FLOPO_A"]
    assert not unsat


def test_coarse_eq_signature_is_not_a_substitute_for_reasoner_equivalence(tmp_path):
    from pathlib import Path
    import shutil
    from flopo2.ids.registry import _signature_of
    from flopo2.owl.build import HAS_PART, HAS_QUALITY, _intersection, _restriction
    from flopo2.verify.eq_release import reasoner_report, taxonomy

    root = Path(__file__).resolve().parents[1]
    if not (root / "tools/robot.jar").exists() or not shutil.which("javac"):
        pytest.skip("ROBOT/JDK not installed")
    g = Graph()
    e, q, container = [URIRef(OBO + x) for x in ["PO_E", "PATO_Q", "PO_container"]]
    for node in [e, q, container]:
        g.add((node, RDF.type, OWL.Class))
    plain = eq_axioms(g, OBO + "FLOPO_plain", str(e), str(q), "plain", "")
    narrow = URIRef(OBO + "FLOPO_narrow")
    g.add((narrow, RDF.type, OWL.Class))
    filler = _intersection(
        g,
        [
            e,
            _restriction(g, HAS_QUALITY, q),
            _restriction(g, URIRef(OBO + "BFO_0000050"), container),
        ],
    )
    g.add((narrow, OWL.equivalentClass, _restriction(g, HAS_PART, filler)))
    assert _signature_of(g, plain) == _signature_of(g, narrow)
    source = tmp_path / "extra-restriction.owl"
    g.serialize(source, format="xml")
    _, _, equivalents, unsat, _ = taxonomy(reasoner_report(source, tmp_path))
    assert not unsat
    assert str(narrow) not in equivalents[str(plain)]


def test_duplicate_json_keys_cannot_replace_a_negative_answer():
    from flopo2.verify.eq_release import strict_json

    with pytest.raises(ValueError, match="Duplicate JSON key"):
        strict_json('{"inheres":"yes","answers":{"0":"no","0":"yes"}}')


def test_reextraction_requires_explicit_source_approval():
    answer = {"inheres": "yes", "answers": []}
    with pytest.raises(ValueError, match="grounding"):
        validate_answer(answer, 0, require_grounding=True)
    assert not validate_answer({**answer, "grounded": "no"}, 0, require_grounding=True)
    assert validate_answer({**answer, "grounded": "yes"}, 0, require_grounding=True)


def test_solid_ovoid_on_leaf_is_rejected():
    e, q = OBO + "PO_0025034", OBO + "PATO_0001891"
    reasons = deterministic_checks(
        {"entity": e, "quality": q, "id": "C"},
        Graph(),
        {q: {OBO + "PATO_0000001"}},
        set(),
        {e, q},
        {},
        [],
    )
    assert "solid_ovoid_on_flat_bearer" in reasons


def test_formal_eq_and_anatomical_part_context_are_supplied():
    from rdflib import RDFS
    from flopo2.verify.eq_release import node_data, anatomy_context
    from flopo2.owl.build import _restriction

    g = Graph()
    leaf, apex = OBO + "PO_0025034", OBO + "PO_leaf_apex"
    g.add(
        (URIRef(apex), RDFS.subClassOf, _restriction(g, URIRef(OBO + "BFO_0000050"), URIRef(leaf)))
    )
    c = eq_axioms(g, OBO + "FLOPO_test", apex, OBO + "PATO_red", "apex red", "")
    assert node_data(g, str(c))["formal_EQ"]["entity"]["id"] == apex
    assert anatomy_context(g, apex)[0]["relation"] == "part_of"
