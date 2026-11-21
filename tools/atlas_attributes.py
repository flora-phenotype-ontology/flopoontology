"""The attribute of every quality value, for the Compare page of the atlas (attributes.json).

Two statements are comparable when they are about the same entity and their qualities are values
of the same attribute; the attribute of a PATO value is its most specific superclass in PATO's
``attribute_slim`` (Gkoutos, Schofield and Hoehndorf 2018, doi:10.1093/bib/bbx035, "Direct and
comparative phenotype descriptions"). The annotator finds the attribute the same way
(``flopo2.ingest.llm_term_rules.nearest_attribute``); this writes the result for every PATO
quality and every FLOPO flora value, so the browser does not have to walk the hierarchy.

    {"of": {value id: attribute id}, "label": {attribute id: name}}

Identifiers are local names (``PATO_0000453``).

    python -m tools.atlas_attributes OUT.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from flopo2.ingest.llm_term_rules import flopo_local_terms, nearest_attribute
from flopo2.saudi.vocab import parse_obo

PATO = Path("ont/quality.obo")


def _subsets(path: Path) -> dict[str, set[str]]:
    """PATO subset name -> ids (local names), obsolete terms left out."""

    out: dict[str, set[str]] = {}
    current, tags, obsolete = "", [], False

    def close() -> None:
        if current and not obsolete:
            for tag in tags:
                out.setdefault(tag, set()).add(current)

    for line in path.open(encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("["):
            close()
            current, tags, obsolete = "", [], False
        elif line.startswith("id: PATO:"):
            current = line[4:].strip().replace(":", "_", 1)
        elif line.startswith("subset: "):
            tags.append(line[8:].split()[0])
        elif line == "is_obsolete: true":
            obsolete = True
    close()
    return out


def build(pato: Path = PATO, flopo: Path = Path("ontology/flopo.owl")) -> dict:
    terms = parse_obo(pato)
    subsets = _subsets(pato)
    attributes = subsets.get("attribute_slim", set())
    of: dict[str, str] = {}
    for term in terms.values():
        if not term.id.startswith("PATO:"):
            continue
        local = term.id.replace(":", "_", 1)
        attribute = nearest_attribute(terms, local, attributes)
        if attribute in attributes:  # a quality under no attribute is comparable with nothing
            of[local] = attribute
    for local, (_label, parent) in flopo_local_terms(flopo).items():
        if parent.startswith("PATO_"):
            attribute = nearest_attribute(terms, parent, attributes)
            if attribute in attributes:
                of[local] = attribute
    used = sorted(set(of.values()))
    return {
        "of": dict(sorted(of.items())),
        "label": {a: terms[a.replace("_", ":", 1)].name for a in used},
    }


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    target = Path(args[0])
    target.write_text(json.dumps(build(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    data = json.loads(target.read_text())
    print(f"{target}: {len(data['of'])} values, {len(data['label'])} attributes")


if __name__ == "__main__":
    main()
