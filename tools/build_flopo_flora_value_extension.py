#!/usr/bin/env python3
"""Build the FLOPO flora value-term module from ``config/flopo_flora_value_terms.tsv``.

Floras use quality words that PATO does not have: positions (axillary, leaf-opposed, basal),
arrangements (solitary, paired, rosulate, capitate, caespitose), habits (semi-prostrate,
creeping, mat-forming, twiggy, leafy), odours (sweet-, spicy-, sour-scented, musty, foetid),
surfaces (exfoliating, fissured), plus subsessile, bipinnate and unisexual.  Each becomes a
FLOPO-local value class directly beneath its closest live PATO class, the pattern of the
provisional PATO candidates in FLOPO_0985xxx, so every value is grounded in PATO and can later be
replaced by a PATO term.  The Saudi Flora corpora (NCVC 2024 and Collenette 1985) are the
evidence; ``source_words`` records the word and its frequency there.

Outputs
    ontology/flopo-flora-value-extension.ttl   the module (embedded in flopo.owl by
                                               tools/update_flopo_flora_value_release.py)
    flopo2/ingest/flora_value_term_rules.tsv   normalization rules (label and exact synonyms ->
                                               value term, top-level PATO attribute)
    config/valid_combinations.tsv              (bearer, attribute) pairs for the listed bearers,
                                               added as ``allowed`` when absent

Identifiers are the block FLOPO_0991000-FLOPO_0991999.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

from flopo2.saudi.vocab import parse_obo
from flopo2.verify.gates import load_pato_attribute_terms

ROOT = Path(__file__).resolve().parents[1]
OBO = Namespace("http://purl.obolibrary.org/obo/")
OIO = Namespace("http://www.geneontology.org/formats/oboInOwl#")
MODULE = URIRef(OBO + "flopo-flora-value-extension.owl")
SPEC = Path("config/flopo_flora_value_terms.tsv")
OUTPUT = Path("ontology/flopo-flora-value-extension.ttl")
RULES = Path("flopo2/ingest/flora_value_term_rules.tsv")
COMBINATIONS = Path("config/valid_combinations.tsv")
DECISION_DATE = "2026-10-06"
ID_BLOCK = (991000, 991999)
# Identifiers withdrawn before any release; never to be reused.
RETIRED_IDS = {"FLOPO:0991008": "semi-prostrate: rejected in the 2026-10-13 review (no criterion distinguishing it from PATO:0002343 decumbent)"}
DEFINITION = OBO.IAO_0000115
EDITOR_NOTE = OBO.IAO_0000116
# Value terms added without curator review are deployed as provisional (user, 2026-10-23).
CURATION_STATUS = OBO.IAO_0000114
PENDING_FINAL_VETTING = OBO.IAO_0000125
RULE_FIELDS = [
    "rule_id", "match_field", "match_key", "bearer_constraint", "kind", "po_id", "pato_id",
    "value_term", "flopo_class", "target_label", "evidence", "review_status",
]
# Taste/odour words that a fruit can carry as a taste ("sweet and edible"): odour readings only.
NOT_FRUIT = r"^(?!.*\b(?:fruit|berry|drupe|pod|capsule)s?\b).+"
ODOUR_WORDS_NOT_FRUIT = {"sour", "sweet", "spicy"}


def read_spec(root: Path = ROOT) -> list[dict[str, str]]:
    with (root / SPEC).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for row in rows:
        if row["flopo_id"] in RETIRED_IDS:
            raise ValueError(f"{row['flopo_id']} is retired: {RETIRED_IDS[row['flopo_id']]}")
        number = int(row["flopo_id"].split(":")[1])
        if not ID_BLOCK[0] <= number <= ID_BLOCK[1]:
            raise ValueError(f"{row['flopo_id']} is outside the reserved block")
    return rows


def _local(curie: str) -> str:
    return curie.replace(":", "_", 1)


def attribute_of(pato: dict, attributes: set[str], parent: str) -> str:
    """Nearest attribute-slim ancestor (the assertion's top-level PATO term)."""

    frontier, seen = [parent], set()
    while frontier:
        current = frontier.pop(0)
        if _local(current) in attributes:
            return _local(current)
        seen.add(current)
        term = pato.get(current)
        frontier += [p for p in (term.is_a if term else []) if p not in seen]
    raise ValueError(f"{parent} has no attribute-slim ancestor")


def build_graph(rows: list[dict[str, str]], pato: dict) -> Graph:
    graph = Graph()
    graph.bind("obo", OBO)
    graph.bind("oboInOwl", OIO)
    graph.bind("dcterms", DCTERMS)
    graph.add((MODULE, RDF.type, OWL.Ontology))
    graph.add((MODULE, RDFS.comment, Literal(__doc__.split("\n\n")[0], lang="en")))
    for row in rows:
        if row["parent"] not in pato:
            raise ValueError(f"{row['label']}: parent {row['parent']} is not a live PATO class")
        cls = OBO[_local(row["flopo_id"])]
        graph.add((cls, RDF.type, OWL.Class))
        graph.add((cls, RDFS.label, Literal(row["label"], datatype=XSD.string)))
        graph.add((cls, RDFS.subClassOf, OBO[_local(row["parent"])]))
        graph.add((cls, DEFINITION, Literal(row["definition"], lang="en")))
        for synonym in filter(None, row["exact_synonyms"].split("|")):
            graph.add((cls, OIO.hasExactSynonym, Literal(synonym, datatype=XSD.string)))
        for synonym in filter(None, row["related_synonyms"].split("|")):
            graph.add((cls, OIO.hasRelatedSynonym, Literal(synonym, datatype=XSD.string)))
        date = row.get("added") or DECISION_DATE
        note = (
            f"FLOPO-local value class beneath PATO {row['parent']} ({pato[row['parent']].name}), "
            f"added {date} for quality words of the Saudi Flora corpora that PATO lacks "
            f"(evidence: {row['source_words']}). Candidate for submission to PATO."
        )
        if row.get("status") == "provisional":
            note += " Provisional: not yet reviewed by the curator."
            graph.add((cls, CURATION_STATUS, PENDING_FINAL_VETTING))
        graph.add((cls, EDITOR_NOTE, Literal(note, lang="en")))
        graph.add((cls, DCTERMS.date, Literal(date, datatype=XSD.date)))
    return graph


def rule_rows(rows: list[dict[str, str]], pato: dict, attributes: set[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        attribute = attribute_of(pato, attributes, row["parent"])
        # Label, exact synonyms, and rule-only words: phrasings of the transcriptions ("head",
        # "sweet" for "sweet scent") that are not ontology synonyms.
        words = [row["label"], *filter(None, row["exact_synonyms"].split("|"))]
        words += [w for w in (row.get("rule_words") or "").split("|") if w]
        for word in words:
            key = word.lower()
            if key in seen:
                raise ValueError(f"word {key!r} maps to two value terms")
            seen.add(key)
            out.append(
                {
                    **dict.fromkeys(RULE_FIELDS, ""),
                    "rule_id": f"V{len(out) + 1:03d}",
                    "match_field": "quality",
                    "match_key": key,
                    "bearer_constraint": (row.get("rule_bearer_constraint") or "")
                    or (NOT_FRUIT if key.split()[0] in ODOUR_WORDS_NOT_FRUIT else ""),
                    "kind": "flopo_value",
                    "pato_id": attribute,
                    "value_term": _local(row["flopo_id"]),
                    "target_label": row["label"],
                    "evidence": f"{row['flopo_id']} {row['label']} ({_word_kind(row, word)}); "
                    f"FLOPO flora value module {row.get('added') or DECISION_DATE}",
                    "review_status": "claude_reviewed",
                }
            )
    return out


def _word_kind(row: dict[str, str], word: str) -> str:
    if word == row["label"]:
        return "label"
    if word in row["exact_synonyms"].split("|"):
        return "exact synonym"
    return "transcription phrasing"


def combination_rows(rows: list[dict[str, str]], pato: dict, attributes: set[str]) -> list[dict[str, str]]:
    out = []
    for row in rows:
        attribute = attribute_of(pato, attributes, row["parent"])
        for bearer in filter(None, row["bearers"].split("|")):
            out.append(
                {
                    "po_id": _local(bearer),
                    "pato_id": attribute,
                    "status": "allowed",
                    "source": f"flora_value_terms_{row.get('added') or DECISION_DATE}",
                    "example_label": f"{row['label']} ({row['flopo_id']})",
                }
            )
    return out


def write(root: Path = ROOT) -> dict[str, int]:
    rows = read_spec(root)
    pato = parse_obo(root / "ont/quality.obo")
    attributes = load_pato_attribute_terms(root / "config/pato_lexicon.tsv")
    graph = build_graph(rows, pato)
    text = (
        "# FLOPO flora value-term module. Generated by tools/build_flopo_flora_value_extension.py\n"
        "# from config/flopo_flora_value_terms.tsv; embedded by tools/update_flopo_flora_value_release.py.\n"
        + graph.serialize(format="turtle")
    )
    (root / OUTPUT).write_text(text, encoding="utf-8")

    rules = rule_rows(rows, pato, attributes)
    with (root / RULES).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, RULE_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rules)

    path = root / COMBINATIONS
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = reader.fieldnames
        existing = {(r["po_id"], r["pato_id"]) for r in reader}
    added = [r for r in combination_rows(rows, pato, attributes) if (r["po_id"], r["pato_id"]) not in existing]
    added = list({(r["po_id"], r["pato_id"]): r for r in added}.values())
    if added:
        with path.open("a", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fields, delimiter="\t", lineterminator="\n").writerows(added)
    return {"classes": len(rows), "rules": len(rules), "combinations_added": len(added)}


def main() -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    print(write())


if __name__ == "__main__":
    main()
