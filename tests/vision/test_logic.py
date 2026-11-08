import itertools

import pyoxigraph as ox
import pytest

from flopo2.vision.logic import Compiler, Expr, HAS_PART, HAS_QUALITY, Scene, UnsupportedExpression, combine, probability


def phenotype(organ="leaf", colour="yellow"):
    return Expr("some", HAS_PART, (Expr("and", children=(Expr("atom", organ),
        Expr("some", HAS_QUALITY, (Expr("atom", colour),)))),))


def scene():
    return Scene(
        nodes={"plant": {}, "a": {"types": ["leaf"]}, "b": {"types": ["petal"]},
               "qa": {"choice": "a.colour"}, "qb": {"choice": "b.colour"}},
        edges=[("plant", HAS_PART, "a", True), ("plant", HAS_PART, "b", True),
               ("a", HAS_QUALITY, "qa", ("eq", "a.visible", 1)), ("b", HAS_QUALITY, "qb", True)],
        domains={"a.colour": (("green",), ("yellow",), ()), "b.colour": (("green",), ("yellow",), ()),
                 "a.visible": ((), ())},
        ancestors={"pale-yellow": ["pale-yellow", "yellow"]})


def test_yellow_petal_cannot_satisfy_yellow_leaf():
    s = scene()
    probabilities = {"a.colour": [1, 0, 0], "b.colour": [0, 1, 0], "a.visible": [0, 1]}
    assert probability(s.ground(phenotype(), "plant"), probabilities) == 0
    assert probability(s.ground(phenotype("petal"), "plant"), probabilities) == 1


def test_unassessable_and_unknown_are_not_observed_support():
    s = scene(); f = s.ground(phenotype(), "plant")
    assert probability(f, {"a.colour": [0, 1, 0], "a.visible": [1, 0]}) == 0
    assert probability(f, {"a.colour": [0, 0, 1], "a.visible": [0, 1]}) == 0


def test_ancestry_preserves_bearer():
    s = scene(); s.domains["b.colour"] = (("pale-yellow",), ())
    p = {"a.colour": [1, 0, 0], "a.visible": [0, 1], "b.colour": [1, 0]}
    assert probability(s.ground(phenotype("petal"), "plant"), p) == 1
    assert probability(s.ground(phenotype("flower"), "plant"), p) == 0


def test_duplicate_proofs_and_edges_share_probability():
    s = scene(); s.edges.append(s.edges[0])
    f = s.ground(phenotype(), "plant")
    assert probability(combine("or", [f, f]), {"a.colour": [.4, .6, 0], "a.visible": [.2, .8]}) == pytest.approx(.48)


def test_exact_probability_matches_enumeration_with_shared_choices():
    f = combine("or", [combine("and", [("eq", "a", 0), ("eq", "b", 1)]),
                        combine("and", [("eq", "a", 1), ("eq", "b", 1)]), ("eq", "a", 0)])
    p = {"a": [.2, .3, .5], "b": [.7, .3]}
    expected = sum(p["a"][a] * p["b"][b] for a, b in itertools.product(range(3), range(2))
                   if (a == 0 and b == 1) or (a == 1 and b == 1) or a == 0)
    assert probability(f, p) == pytest.approx(expected)


def test_gradient_matches_finite_difference():
    import torch
    logits = torch.tensor([.2, -.4, .9], dtype=torch.float64, requires_grad=True)
    f = combine("or", [("eq", "x", 0), ("eq", "x", 1)])
    result = probability(f, {"x": logits.softmax(0)})
    result.backward()
    for i in range(3):
        plus, minus = logits.detach().clone(), logits.detach().clone()
        plus[i] += 1e-5; minus[i] -= 1e-5
        difference = (probability(f, {"x": plus.softmax(0)}) - probability(f, {"x": minus.softmax(0)})) / 2e-5
        assert logits.grad[i].item() == pytest.approx(difference.item(), abs=1e-8)


def test_invalid_probabilities_fail_loudly():
    with pytest.raises(ValueError):
        probability(("eq", "x", 0), {"x": [.9, .9]})


def test_owl_compiler_binds_nested_existentials_and_rejects_complement():
    store = ox.Store()
    store.load(input=f'''@prefix owl: <http://www.w3.org/2002/07/owl#> .
      <http://test/C> owl:equivalentClass [owl:onProperty <{HAS_PART}>;
        owl:someValuesFrom [owl:intersectionOf (<http://test/Leaf>
          [owl:onProperty <{HAS_QUALITY}>; owl:someValuesFrom <http://test/Yellow>])]] .
      <http://test/NotC> owl:equivalentClass [owl:complementOf <http://test/C>] .''', format=ox.RdfFormat.TURTLE)
    c = Compiler(store)
    expr = c.compile("http://test/C")
    assert expr == phenotype("http://test/Leaf", "http://test/Yellow")
    assert Expr.from_json(expr.json()) == expr
    with pytest.raises(UnsupportedExpression, match="complementOf"):
        c.compile("http://test/NotC")


def test_compiler_rejects_role_and_rdf_list_cycles():
    store = ox.Store()
    store.load(input='''@prefix owl: <http://www.w3.org/2002/07/owl#> .
      @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
      <http://test/Role> owl:equivalentClass [owl:onProperty <http://test/arbitrary>; owl:someValuesFrom <http://test/X>] .
      <http://test/List> owl:equivalentClass [owl:intersectionOf _:x] .
      _:x rdf:first <http://test/A>; rdf:rest _:x .''', format=ox.RdfFormat.TURTLE)
    for iri in ("http://test/Role", "http://test/List"):
        with pytest.raises(UnsupportedExpression):
            Compiler(store).compile(iri)
