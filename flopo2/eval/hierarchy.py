"""Build an ``ancestors`` function from PO/PATO OBO files for lenient (hierarchical) scoring.

The eval harness credits a prediction whose PO/PATO term is an ancestor/descendant of the gold term
(right region, wrong granularity). That needs a function CURIE -> {ancestor CURIEs, incl. self}.

OBO files use colon CURIEs (``PO:0009052``); the silver standard and lexicons use underscores
(``PO_0009052``). We parse the OBO ``is_a`` edges and normalize everything to the underscore form so
ids line up with the assertions being scored. Only ``is_a`` (subclass) edges count — not
``relationship: part_of`` etc. — since subsumption is what "wrong granularity" means.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

DEFAULT_OBO = [Path("ont/plant_ontology.obo"), Path("ont/quality.obo")]


def _norm(curie: str) -> str:
    # PO:0009052 -> PO_0009052 ; leave already-underscored ids untouched.
    return curie.replace(":", "_", 1).strip()


def _parse_parents(paths: list[Path]) -> dict[str, set[str]]:
    """Direct is_a parents per term (normalized to underscore CURIEs)."""
    parents: dict[str, set[str]] = {}
    for p in paths:
        if not p.exists():
            continue
        cur: str | None = None
        in_term = False
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line in ("[Term]", "[Typedef]", "[Instance]"):
                in_term = line == "[Term]"
                cur = None
            elif in_term and line.startswith("id:"):
                cur = _norm(line[3:].strip())
                parents.setdefault(cur, set())
            elif in_term and cur and line.startswith("is_a:"):
                # "is_a: PO:0025099 ! embryo plant structure"
                target = line[5:].split("!")[0].strip()
                if target:
                    parents[cur].add(_norm(target))
    return parents


def build_ancestors(paths: list[Path] | None = None):
    """Return ``ancestors(curie) -> frozenset`` (transitive is_a closure, including the term)."""
    parents = _parse_parents(paths or DEFAULT_OBO)

    @lru_cache(maxsize=None)
    def ancestors(curie: str) -> frozenset[str]:
        seen = {curie}
        stack = list(parents.get(curie, ()))
        while stack:
            n = stack.pop()
            if n not in seen:
                seen.add(n)
                stack.extend(parents.get(n, ()))
        return frozenset(seen)

    ancestors.term_count = len(parents)  # type: ignore[attr-defined]
    return ancestors


if __name__ == "__main__":
    anc = build_ancestors()
    print(f"terms with parents: {anc.term_count}")
    for t in ["PATO_0000122", "PO_0009052", "PATO_0000952"]:
        a = anc(t)
        print(f"{t}: {len(a)} ancestors -> {sorted(a)[:6]}{'...' if len(a) > 6 else ''}")
