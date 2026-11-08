"""Positive OWL query compilation and exact categorical weighted model counting.

This evaluates observed support, not absence in an incompletely photographed specimen.
No taxon axioms or source descriptions are used as facts about an image.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

OBO = "http://purl.obolibrary.org/obo/"
OWL = "http://www.w3.org/2002/07/owl#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
HAS_PART = OBO + "BFO_0000051"
HAS_QUALITY = OBO + "RO_0000053"


class UnsupportedExpression(ValueError):
    pass


@dataclass(frozen=True)
class Expr:
    op: str
    value: str = ""
    children: tuple["Expr", ...] = ()

    def json(self):
        return {"op": self.op, "value": self.value, "children": [c.json() for c in self.children]}

    @classmethod
    def from_json(cls, row):
        return cls(row["op"], row.get("value", ""), tuple(cls.from_json(c) for c in row.get("children", [])))


class Compiler:
    """Compile a named phenotype definition from a pinned RDF store; reject unsupported OWL."""

    def __init__(self, store):
        self.store = store

    def objects(self, subject, predicate):
        import pyoxigraph as ox
        return sorted({q.object for q in self.store.quads_for_pattern(subject, ox.NamedNode(predicate), None, None)}, key=str)

    def compile(self, iri: str) -> Expr:
        import pyoxigraph as ox
        definitions = self.objects(ox.NamedNode(iri), OWL + "equivalentClass")
        if not definitions:
            raise UnsupportedExpression(f"No equivalent-class definition for {iri}")
        # Each equivalence is sufficient for membership; shared proofs are not independent.
        expressions = tuple(dict.fromkeys(self._expr(d, frozenset()) for d in definitions))
        return expressions[0] if len(expressions) == 1 else Expr("or", children=expressions)

    def _expr(self, node, seen) -> Expr:
        import pyoxigraph as ox
        if isinstance(node, ox.NamedNode):
            return Expr("atom", node.value)
        if not isinstance(node, ox.BlankNode) or node in seen:
            raise UnsupportedExpression(f"Malformed/cyclic expression: {node}")
        seen = seen | {node}
        for unsupported in ("complementOf", "allValuesFrom", "hasValue", "onClass", "onDataRange",
                            "cardinality", "minCardinality", "maxCardinality", "qualifiedCardinality",
                            "minQualifiedCardinality", "maxQualifiedCardinality", "oneOf", "withRestrictions"):
            if self.objects(node, OWL + unsupported):
                raise UnsupportedExpression(unsupported)
        alternatives = []
        for predicate, operation in (("intersectionOf", "and"), ("unionOf", "or")):
            heads = self.objects(node, OWL + predicate)
            if heads:
                if len(heads) != 1:
                    raise UnsupportedExpression("Multiple RDF list heads")
                items, visited, head = [], set(), heads[0]
                while head != ox.NamedNode(RDF + "nil"):
                    if head in visited:
                        raise UnsupportedExpression("Cyclic RDF list")
                    visited.add(head)
                    first, rest = self.objects(head, RDF + "first"), self.objects(head, RDF + "rest")
                    if len(first) != 1 or len(rest) != 1:
                        raise UnsupportedExpression("Malformed RDF list")
                    items.append(self._expr(first[0], seen)); head = rest[0]
                if not items:
                    raise UnsupportedExpression("Empty class expression")
                alternatives.append(Expr(operation, children=tuple(items)))
        roles, fillers = self.objects(node, OWL + "onProperty"), self.objects(node, OWL + "someValuesFrom")
        if roles or fillers:
            if len(roles) != 1 or len(fillers) != 1 or roles[0].value not in (HAS_PART, HAS_QUALITY):
                raise UnsupportedExpression("Unsupported existential role or malformed restriction")
            alternatives.append(Expr("some", roles[0].value, (self._expr(fillers[0], seen),)))
        if len(alternatives) != 1:
            raise UnsupportedExpression("Unknown or mixed class-expression syntax")
        return alternatives[0]

    def ancestors(self, classes: set[str]) -> dict[str, list[str]]:
        import pyoxigraph as ox
        result = {}
        for iri in sorted(classes):
            seen, pending = {iri}, [iri]
            while pending:
                for parent in self.objects(ox.NamedNode(pending.pop()), RDFS + "subClassOf"):
                    if isinstance(parent, ox.NamedNode) and parent.value not in seen:
                        seen.add(parent.value); pending.append(parent.value)
            result[iri] = sorted(seen)
        return result


# A Boolean formula over finite categorical choices. Repeated atoms share the same variable.
Formula = bool | tuple


def combine(op: str, children) -> Formula:
    identity, annihilator = (True, False) if op == "and" else (False, True)
    flattened = []
    for child in children:
        if child is annihilator:
            return annihilator
        if child is identity:
            continue
        flattened.extend(child[1:] if isinstance(child, tuple) and child[0] == op else [child])
    unique = sorted(set(flattened), key=repr)
    return identity if not unique else unique[0] if len(unique) == 1 else (op, *unique)


@dataclass
class Scene:
    # node -> fixed types and/or categorical variable whose states contain class IRIs
    nodes: dict[str, dict]
    # source, role, target, Boolean existence/assessability condition
    edges: list[tuple[str, str, str, Formula]]
    domains: dict[str, tuple[tuple[str, ...], ...]]
    ancestors: dict[str, list[str]]

    def ground(self, expr: Expr, node: str) -> Formula:
        if node not in self.nodes:
            raise ValueError(f"Unknown scene node {node}")
        if expr.op == "atom":
            if expr.value == OWL + "Thing":
                return True
            if expr.value == OWL + "Nothing":
                return False
            def entails(types):
                return any(expr.value in self.ancestors.get(t, [t]) for t in types)
            spec = self.nodes[node]
            if entails(spec.get("types", [])):
                return True
            var = spec.get("choice")
            if not var:
                return False  # no observed proof; not an OWL negative
            # Several typed nodes may be projections of one joint categorical choice.
            states = spec.get("state_types", self.domains[var])
            if len(states) != len(self.domains[var]):
                raise ValueError(f"Invalid state projection for {node}")
            return combine("or", (("eq", var, i) for i, types in enumerate(states) if entails(types)))
        if expr.op in ("and", "or"):
            return combine(expr.op, (self.ground(c, node) for c in expr.children))
        if expr.op == "some":
            return combine("or", (combine("and", [condition, self.ground(expr.children[0], target)])
                for source, role, target, condition in self.edges if source == node and role == expr.value))
        raise UnsupportedExpression(expr.op)


def probability(formula: Formula, probabilities: dict[str, Any]):
    """Exact Shannon expansion; accepts floats or differentiable torch state vectors.

    Inputs describe mutually exclusive categorical choices, independent across variables.
    Use joint state domains to represent dependence; do not multiply correlated marginals.
    """
    @lru_cache(None)
    def variables(f):
        if isinstance(f, bool):
            return frozenset()
        return frozenset([f[1]]) if f[0] == "eq" else frozenset().union(*(variables(c) for c in f[1:]))

    @lru_cache(None)
    def substitute(f, variable, state):
        if isinstance(f, bool):
            return f
        if f[0] == "eq":
            return f[2] == state if f[1] == variable else f
        return combine(f[0], (substitute(c, variable, state) for c in f[1:]))

    @lru_cache(None)
    def evaluate(f):
        if isinstance(f, bool):
            return float(f)
        variable = min(variables(f))
        ps = probabilities[variable]
        return sum(ps[i] * evaluate(substitute(f, variable, i)) for i in range(len(ps)))

    for variable in variables(formula):
        values = probabilities[variable]
        # Validate without changing autograd; caller supplies normalized categorical scores.
        checked = values.detach().cpu().tolist() if hasattr(values, "detach") else list(values)
        if not checked or any(not 0 <= p <= 1 for p in checked) or abs(sum(checked) - 1) > 1e-5:
            raise ValueError(f"Invalid categorical probabilities for {variable}")
    def validate(f):
        if isinstance(f, bool):
            return
        if f[0] == "eq":
            if not isinstance(f[2], int) or not 0 <= f[2] < len(probabilities[f[1]]):
                raise ValueError(f"Invalid categorical state: {f}")
        elif f[0] in ("and", "or"):
            for child in f[1:]:
                validate(child)
        else:
            raise ValueError(f"Invalid formula operator: {f[0]}")
    validate(formula)
    return evaluate(formula)
