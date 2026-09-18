#!/usr/bin/env python3
"""Stage FLOPO EQ phenotype classes for the NCVC Saudi guide's approved PO x PATO pairs.

Curator decision D1 (2026-09-18) mints a FLOPO EQ class for every PO x PATO combination that the
NCVC Saudi native-plants guide ingest asserts, that has no live FLOPO class, and whose pair is
``allowed`` in ``config/valid_combinations.tsv`` (the pairs were approved the same day in
``curation/curator-2026-09-18-po-pato-approvals.tsv``). Each class follows the reviewed
combination pattern of ``flopo2/owl/build.py``::

    <E Q> EquivalentTo BFO:0000051 some (E and RO:0000053 some Q)
    <E Q> SubClassOf <E phenotype>

with the label ``"<entity> <quality>"`` and the generated definition of
``flopo2.owl.build._definition``. A bearer without a live ``<E phenotype>`` parent gets one minted
in the same way (``PHENO|E``).

Two steps:

``propose``
    Read the annotated NCVC dispositions, keep every EQ signature without a live FLOPO class,
    and write the specification ``curation/ncvc_saudi_eq_classes_20260918.tsv``. Every row is
    either ``accept`` or ``exclude`` with a reason. Exclusions apply the screen of the 2026-09-18
    pair approvals (``scratchpad/pair-approvals-20260918/excluded.tsv``): pairs that are not
    ``allowed``, live duplicates, PATO homonym traps, abnormal-sense PATO values, non-PATO
    qualities, and pairs whose only evidence is mis-grounded.

``build``
    Allocate identifiers in the reserved block FLOPO_0989000-FLOPO_0989999
    (``config/flopo_ncvc_eq_id_registry.tsv``; existing allocations never change) and write the
    module ``ontology/flopo-ncvc-eq-extension.ttl`` from the accepted rows only.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, BNode, Graph, Literal, URIRef
from rdflib.collection import Collection

from flopo2.owl.build import _definition
from tools.build_flopo_growth_form_extension import live_obo_ids, serialize


OBO = "http://purl.obolibrary.org/obo/"
MODULE = URIRef(OBO + "flopo-ncvc-eq-extension.owl")
HAS_PART = URIRef(OBO + "BFO_0000051")
PART_OF = URIRef(OBO + "BFO_0000050")
HAS_QUALITY = URIRef(OBO + "RO_0000053")
QUALITY_ROOT = URIRef(OBO + "PATO_0000001")
ROOT_CLASS = URIRef(OBO + "FLOPO_0000000")
IAO_DEFINITION = URIRef(OBO + "IAO_0000115")
IAO_EDITOR_NOTE = URIRef(OBO + "IAO_0000116")
CONTRIBUTOR = URIRef("https://orcid.org/0000-0001-8149-5890")
ID_BLOCK = (989000, 989999)
DECISIONS = {"accept", "exclude"}

SPEC = Path("curation/ncvc_saudi_eq_classes_20260918.tsv")
REGISTRY = Path("config/flopo_ncvc_eq_id_registry.tsv")
FLOPO_REGISTRY = Path("config/flopo_id_registry.tsv")
COMBINATIONS = Path("config/valid_combinations.tsv")
PAIR_APPROVALS = Path("curation/curator-2026-09-18-po-pato-approvals.tsv")
PAIR_EXCLUSIONS = Path("scratchpad/pair-approvals-20260918/excluded.tsv")
DERIVED = Path("local-corpora/saudi-ncvc-guide/derived")
DISPOSITIONS = DERIVED / "ncvc-saudi-phenotype-dispositions.tsv"
NOVEL = DERIVED / "ncvc-saudi-novel-eq-candidates.tsv"
PO_LEXICON = Path("config/po_lexicon.tsv")
PATO_LEXICON = Path("config/pato_lexicon.tsv")
PO = Path("ont/plant_ontology.obo")
PATO = Path("ont/quality.obo")
OUTPUT = Path("ontology/flopo-ncvc-eq-extension.ttl")

SOURCE_ID = "ncvc-saudi-native-plants-guide-2024"
SOURCE_CITATION = (
    "National Center for Vegetation Cover Development and Combating Desertification (NCVC). "
    "Guide to Native Plants in the Kingdom of Saudi Arabia. Riyadh, 2024 "
    f"(FLOPO source {SOURCE_ID})."
)
DECISION = (
    "Curator decision D1 (Robert Hoehndorf, 2026-09-18): mint FLOPO EQ phenotype classes for "
    "the NCVC Saudi guide's PO x PATO candidates through the reviewed-combination path."
)

SPEC_FIELDS = [
    "signature",
    "po_id",
    "po_label",
    "pato_id",
    "pato_label",
    "label",
    "definition",
    "parent",
    "pair_status",
    "pair_source",
    "assertions",
    "accepted_assertions",
    "taxa",
    "pages",
    "example_1",
    "example_2",
    "decision",
    "reason",
]
REGISTRY_FIELDS = ["proposal_key", "flopo_id", "label", "signature", "kind"]

# PATO classes whose labels are botanical homonyms of a different quality (flopo2/verify/gates.py
# MANUAL_REVIEW_PATO_IDS; flopo2/terminology/annotate.py).
HOMONYM_PATO = {
    "PATO_0000389": "PATO homonym trap: PATO:0000389 acute is a process duration, not an acute "
    "(pointed) organ shape",
    "PATO_0000455": "PATO homonym trap: PATO:0000455 pubescent is onset-of-puberty maturity; the "
    "indumentum sense is PATO:0000454 hairy or FLOPO pubescent",
    "PATO_0002147": "PATO homonym trap: PATO:0002147 is reduced virulence, not attenuate",
}
# Abnormal-sense PATO values (increased/decreased relative to a normal reference); the source
# states a plain descriptive value. Same set as the 2026-09-18 pair screen.
ABNORMAL_PATO = {
    "PATO_0000587",
    "PATO_0000574",
    "PATO_0000599",
    "PATO_0000586",
    "PATO_0000470",
    "PATO_0000591",
    "PATO_0000573",
    "PATO_0000592",
    "PATO_0001596",
    "PATO_0001893",
    "PATO_0001779",
    "PATO_0002285",
    "PATO_0000569",
    "PATO_0000969",
    "PATO_0001227",
}
# Quality branches that ``ontology/flopo.owl`` blocks with a general class axiom
# ``BFO:0000051 some (owl:Thing and RO:0000053 some <quality>) SubClassOf owl:Nothing``: an EQ class
# over them is unsatisfiable. Sex qualities in particular are recorded as taxon-level reproductive
# statements, not as flora phenotypes. The ELK run of the release tool is the backstop for any
# further blocked branch.
BLOCKED_QUALITY_ROOTS = {
    "PATO_0001894": "phenotypic sex",
    "PATO_0000370": "up",
    "PATO_0000365": "down",
}
ABNORMAL_REASON = (
    "abnormal-sense PATO (increased/decreased relative to a normal reference); source states a "
    "plain descriptive value"
)
# Pairs whose every NCVC assertion is mis-grounded (the quality belongs to another structure or
# is a count). Checked against the dispositions: the exclusion only holds while the evidence is
# exactly the reviewed text.
MISGROUNDED = {
    ("PO_0005032", "PATO_0002215"): (
        "on a short, hooked stalk",
        "mis-grounded: Ephedra foeminea 'hooked stalk' describes the cone stalk, not a falciform "
        "megasporangiate strobilus",
    ),
    ("PO_0030102", "PATO_0002215"): (
        "hooked beak",
        "mis-grounded: Alkanna orientalis 'hooked beak' describes the nutlet beak, not a "
        "falciform nut fruit",
    ),
    ("PO_0030105", "PATO_0000327"): (
        "dark spines",
        "mis-grounded: Gomphocarpus sinaicus 'dark spines' describes the fruit spines, not a dark "
        "follicle",
    ),
    ("PO_0020075", "PATO_0000406"): (
        "with two horns curved at the apex",
        "mis-grounded: the curved structures are the two apical horns, not the mericarp",
    ),
    ("PO_0000049", "PATO_0000952"): (
        "hairs tending to brown beneath",
        "mis-grounded: the brown structures are the hairs beneath, not the abaxial epidermis",
    ),
    ("PO_0009010", "PATO_0002118"): (
        "seeds numerous",
        "count, not a PATO value: 'seeds numerous' is a seed number (same criterion as "
        "'has number of' / 'many seeds' in the pair screen)",
    ),
}


def blocked_qualities(pato_path: Path = PATO) -> dict[str, str]:
    """Return every PATO identifier under a quality branch the release blocks, with its root."""

    parents: dict[str, list[str]] = {}
    current: str | None = None
    for line in pato_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("id: "):
            current = line[4:].strip().replace(":", "_", 1)
        elif line.startswith("is_a: ") and current:
            parents.setdefault(current, []).append(line[6:].split("!")[0].strip().replace(":", "_", 1))
        elif line.startswith("["):
            current = None
    blocked = dict(BLOCKED_QUALITY_ROOTS)
    changed = True
    while changed:
        changed = False
        for child, ancestors in parents.items():
            if child in blocked:
                continue
            for ancestor in ancestors:
                if ancestor in blocked:
                    blocked[child] = blocked[ancestor]
                    changed = True
                    break
    return blocked


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def _labels(path: Path) -> dict[str, str]:
    return {row["id"]: row["label"] for row in _rows(path)}


def registry_index(path: Path) -> tuple[dict[str, tuple[str, str]], dict[str, str], set[int]]:
    """Return live signature -> (IRI, label), FLOPO id -> label and every allocated number."""

    live: dict[str, tuple[int, str, str]] = {}
    labels: dict[str, str] = {}
    numbers: set[int] = set()
    for row in _rows(path):
        number = int(row["flopo_num"])
        numbers.add(number)
        identifier = row["flopo_iri"].rsplit("/", 1)[-1]
        labels[identifier] = row["label"]
        if row["deprecated"] in {"1", "true", "True"} or row["signature"] == "OTHER":
            continue
        previous = live.get(row["signature"])
        if previous is None or number > previous[0]:
            live[row["signature"]] = (number, row["flopo_iri"], row["label"])
    return {sig: (iri, label) for sig, (_n, iri, label) in live.items()}, labels, numbers


def _pair_status(path: Path) -> dict[tuple[str, str], tuple[str, str]]:
    return {(r["po_id"], r["pato_id"]): (r["status"], r["source"]) for r in _rows(path)}


def _pair_exclusions(path: Path) -> dict[tuple[str, str], str]:
    if not path.exists():
        return {}
    return {(r["po_id"], r["pato_id"]): r["reason"] for r in _rows(path)}


def propose(
    dispositions_path: Path = DISPOSITIONS,
    novel_path: Path = NOVEL,
    flopo_registry_path: Path = FLOPO_REGISTRY,
    combinations_path: Path = COMBINATIONS,
    pair_exclusions_path: Path = PAIR_EXCLUSIONS,
    po_lexicon: Path = PO_LEXICON,
    pato_lexicon: Path = PATO_LEXICON,
    po_path: Path = PO,
    pato_path: Path = PATO,
) -> list[dict]:
    """Return one screened specification row per unlinked NCVC EQ signature."""

    live, flopo_labels, _numbers = registry_index(flopo_registry_path)
    pairs = _pair_status(combinations_path)
    pair_exclusions = _pair_exclusions(pair_exclusions_path)
    po_labels = _labels(po_lexicon)
    pato_labels = _labels(pato_lexicon)
    live_terms = live_obo_ids(po_path, pato_path)
    blocked = blocked_qualities(pato_path)

    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _rows(dispositions_path):
        signature = row.get("flopo_signature", "")
        if signature.startswith("EQ|") and not row.get("flopo_iri"):
            groups[signature].append(row)
    novel = {row["signature"] for row in _rows(novel_path)} if novel_path.exists() else set()
    missing = novel - set(groups)
    if missing:
        raise ValueError(f"novel NCVC candidates without dispositions: {sorted(missing)[:5]}")

    out = []
    for signature, members in groups.items():
        _eq, bearer, quality = signature.split("|")
        if bearer.startswith("FLOPO_"):
            bearer_label = flopo_labels.get(bearer, "")
        else:
            bearer_label = po_labels.get(bearer, "")
        quality_label = pato_labels.get(quality, flopo_labels.get(quality, ""))
        status, source = pairs.get((bearer, quality), ("novel", ""))
        texts = {m.get("source_en", "") for m in members}
        reason = ""
        if not quality.startswith("PATO_"):
            reason = (
                f"not a PO x PATO pair: quality {quality} ({quality_label}) is FLOPO-local; "
                "outside the reviewed-combination path"
            )
        elif status != "allowed":
            prior = pair_exclusions.get((bearer, quality))
            reason = f"pair {status} in config/valid_combinations.tsv" + (
                f" (curator pair screen 2026-09-18: {prior})" if prior else ""
            )
        elif signature in live:
            iri, label = live[signature]
            reason = f"duplicate of live {iri.rsplit('/', 1)[-1]} ({label})"
        elif quality in blocked:
            reason = (
                f"blocked quality branch: {quality.replace('_', ':')} is under "
                f"{blocked[quality]}, which ontology/flopo.owl excludes with a general class "
                "axiom (the EQ class would be unsatisfiable)"
            )
        elif quality in HOMONYM_PATO:
            reason = HOMONYM_PATO[quality]
        elif quality in ABNORMAL_PATO or quality_label.startswith(("increased ", "decreased ")):
            reason = ABNORMAL_REASON
        elif (bearer, quality) in MISGROUNDED:
            evidence, why = MISGROUNDED[(bearer, quality)]
            if texts == {evidence}:
                reason = why
        if not reason:
            curies = {quality.replace("_", ":", 1)}
            if bearer.startswith("PO_"):
                curies.add(bearer.replace("_", ":", 1))
            if not bearer_label or not quality_label or not curies <= live_terms:
                reason = "bearer or quality is not a live labelled term of the pinned PO/PATO"
        parent = live.get(f"PHENO|{bearer}", ("", ""))[0].rsplit("/", 1)[-1]
        pages = sorted({int(m["pdf_page"]) for m in members if m.get("pdf_page", "").isdigit()})
        examples = [f"{m.get('taxon', '')} (p{m.get('pdf_page', '')}): {m.get('source_en', '')}" for m in members[:2]]
        out.append(
            {
                "signature": signature,
                "po_id": bearer,
                "po_label": bearer_label,
                "pato_id": quality,
                "pato_label": quality_label,
                "label": f"{bearer_label} {quality_label}",
                "definition": _definition(bearer_label, quality_label),
                "parent": parent or f"PHENO|{bearer}",
                "pair_status": status,
                "pair_source": source,
                "assertions": len(members),
                "accepted_assertions": sum(m.get("status") == "accepted" for m in members),
                "taxa": len({m.get("taxon", "") for m in members}),
                "pages": "|".join(map(str, pages)),
                "example_1": examples[0] if examples else "",
                "example_2": examples[1] if len(examples) > 1 else "",
                "decision": "exclude" if reason else "accept",
                "reason": reason or DECISION,
            }
        )
    out.sort(key=lambda r: (r["decision"], -int(r["assertions"]), r["signature"]))
    return out


def _allocate(
    accepted: list[dict[str, str]],
    registry_path: Path,
    flopo_registry_path: Path,
    other_numbers: set[int],
) -> list[dict[str, str]]:
    """Extend the block registry for accepted rows; existing allocations never move."""

    existing = _rows(registry_path) if registry_path.exists() else []
    by_key = {row["proposal_key"]: row for row in existing}
    _live, _labels_by_id, released = registry_index(flopo_registry_path)
    own = {int(row["flopo_id"].removeprefix("FLOPO_")) for row in existing}
    used = (released | other_numbers) - own
    if own & used:
        raise ValueError("NCVC EQ registry collides with another FLOPO identifier source")
    wanted: list[tuple[str, str, str]] = []
    for row in accepted:
        wanted.append((row["signature"], row["label"], "phenotype"))
    for row in accepted:
        if row["parent"].startswith("PHENO|"):
            key = row["parent"]
            if key not in {w[0] for w in wanted}:
                wanted.append((key, f"{row['po_label']} phenotype", "phenotype_parent"))
    number = max(own, default=ID_BLOCK[0] - 1) + 1
    for key, label, kind in wanted:
        if key in by_key:
            if by_key[key]["label"] != label:
                raise ValueError(f"allocated label changed for {key}")
            continue
        while number in used or number in own:
            number += 1
        if number > ID_BLOCK[1]:
            raise ValueError("reserved NCVC EQ identifier block is exhausted")
        by_key[key] = {
            "proposal_key": key,
            "flopo_id": f"FLOPO_{number:07d}",
            "label": label,
            "signature": key,
            "kind": kind,
        }
        own.add(number)
    return sorted(by_key.values(), key=lambda r: r["flopo_id"])


# Cross-cutting modules that legitimately reference/repoint *existing* classes from any block
# (never mint a fresh id there) rather than allocate new ones. A number appearing only because
# one of these modules edited an already-allocated class (e.g. re-pointing its colour filler) is
# not a competing allocation and must not be flagged as one.
_REPOINTING_MODULES = frozenset({"flopo-colour-backbone.ttl"})


def other_block_numbers(config_dir: Path = Path("config"), ontology_dir: Path = Path("ontology")) -> set[int]:
    """FLOPO numbers used by other block registries and staged ontology modules."""

    import re

    numbers: set[int] = set()
    pattern = re.compile(r"FLOPO[_:](\d{7})")
    for path in sorted(config_dir.glob("*registry*.tsv")):
        if path.name in {REGISTRY.name, FLOPO_REGISTRY.name}:
            continue
        numbers |= {int(value) for value in pattern.findall(path.read_text(encoding="utf-8"))}
    for path in sorted(ontology_dir.glob("*.ttl")):
        if path.name == OUTPUT.name or path.name in _REPOINTING_MODULES:
            continue
        numbers |= {int(value) for value in pattern.findall(path.read_text(encoding="utf-8"))}
    return numbers


def _obo(identifier: str) -> URIRef:
    return URIRef(OBO + identifier)


def _some(graph: Graph, prop: URIRef, filler) -> BNode:
    node = BNode()
    graph.add((node, RDF.type, OWL.Restriction))
    graph.add((node, OWL.onProperty, prop))
    graph.add((node, OWL.someValuesFrom, filler))
    return node


def _and(graph: Graph, members: list) -> BNode:
    node = BNode()
    head = BNode()
    Collection(graph, head, members)
    graph.add((node, RDF.type, OWL.Class))
    graph.add((node, OWL.intersectionOf, head))
    return node


def build_module(
    spec_path: Path = SPEC,
    registry_path: Path = REGISTRY,
    flopo_registry_path: Path = FLOPO_REGISTRY,
    combinations_path: Path = COMBINATIONS,
    release_date: str = "2026-09-18",
) -> Graph:
    """Build the module from accepted specification rows and the block registry."""

    spec = _rows(spec_path)
    for row in spec:
        if row["decision"] not in DECISIONS:
            raise ValueError(f"{row['signature']}: unknown decision {row['decision']!r}")
    accepted = [row for row in spec if row["decision"] == "accept"]
    signatures = [row["signature"] for row in accepted]
    if len(signatures) != len(set(signatures)):
        raise ValueError("duplicate accepted signature in the NCVC EQ specification")
    allocations = {row["proposal_key"]: row for row in _rows(registry_path)}
    live, _labels_by_id, _numbers = registry_index(flopo_registry_path)
    pairs = _pair_status(combinations_path)

    graph = Graph()
    for prefix, namespace in (
        ("obo", OBO),
        ("owl", str(OWL)),
        ("rdfs", str(RDFS)),
        ("dcterms", str(DCTERMS)),
        ("xsd", str(XSD)),
    ):
        graph.bind(prefix, namespace)
    graph.add((MODULE, RDF.type, OWL.Ontology))
    graph.add((MODULE, RDFS.label, Literal("FLOPO NCVC Saudi guide EQ phenotypes", lang="en")))
    graph.add((MODULE, DCTERMS.description, Literal(DECISION, lang="en")))
    graph.add((MODULE, DCTERMS.source, Literal(SOURCE_CITATION)))
    graph.add((MODULE, DCTERMS.created, Literal(release_date, datatype=XSD.date)))
    graph.add((MODULE, DCTERMS.license, URIRef("https://creativecommons.org/publicdomain/zero/1.0/")))
    for prop in (HAS_PART, PART_OF, HAS_QUALITY):
        graph.add((prop, RDF.type, OWL.ObjectProperty))
    for prop in (IAO_DEFINITION, IAO_EDITOR_NOTE, DCTERMS.contributor, DCTERMS.created, DCTERMS.source):
        graph.add((prop, RDF.type, OWL.AnnotationProperty))

    minted: set[str] = set()

    def class_for(key: str) -> URIRef:
        entry = allocations.get(key)
        if entry is None:
            raise ValueError(f"{key} has no allocation in {registry_path}")
        number = int(entry["flopo_id"].removeprefix("FLOPO_"))
        if not ID_BLOCK[0] <= number <= ID_BLOCK[1]:
            raise ValueError(f"{entry['flopo_id']} is outside the reserved block")
        released = live.get(key)
        if released and released[0] != OBO + entry["flopo_id"]:
            raise ValueError(f"{key} is already live as {released[0]}")
        return _obo(entry["flopo_id"])

    def provenance(cls: URIRef, note: str) -> None:
        graph.add((cls, DCTERMS.contributor, CONTRIBUTOR))
        graph.add((cls, DCTERMS.created, Literal(release_date, datatype=XSD.date)))
        graph.add((cls, DCTERMS.source, Literal(SOURCE_CITATION)))
        graph.add((cls, DCTERMS.source, Literal(PAIR_APPROVALS.as_posix())))
        graph.add((cls, DCTERMS.source, Literal(SPEC.as_posix())))
        graph.add((cls, IAO_EDITOR_NOTE, Literal(note, lang="en")))

    for row in accepted:
        bearer, quality = row["po_id"], row["pato_id"]
        if pairs.get((bearer, quality), ("",))[0] != "allowed":
            raise ValueError(f"{row['signature']}: pair is not allowed in {combinations_path}")
        if row["signature"] != f"EQ|{bearer}|{quality}":
            raise ValueError(f"{row['signature']}: signature does not match its pair")
        if row["label"] != f"{row['po_label']} {row['pato_label']}":
            raise ValueError(f"{row['signature']}: label is not '<entity> <quality>'")
        if row["definition"] != _definition(row["po_label"], row["pato_label"]):
            raise ValueError(f"{row['signature']}: definition is not the generated definition")
        cls = class_for(row["signature"])
        minted.add(row["signature"])
        parent_key = row["parent"]
        if parent_key.startswith("PHENO|"):
            parent = class_for(parent_key)
            if parent_key not in minted:
                minted.add(parent_key)
                graph.add((parent, RDF.type, OWL.Class))
                graph.add((parent, RDFS.label, Literal(f"{row['po_label']} phenotype", lang="en")))
                graph.add((parent, IAO_DEFINITION, Literal(_definition(row["po_label"]), lang="en")))
                graph.add((parent, RDFS.subClassOf, ROOT_CLASS))
                graph.add(
                    (
                        parent,
                        OWL.equivalentClass,
                        _some(
                            graph,
                            HAS_PART,
                            _and(
                                graph,
                                [_some(graph, PART_OF, _obo(bearer)), _some(graph, HAS_QUALITY, QUALITY_ROOT)],
                            ),
                        ),
                    )
                )
                provenance(parent, f"Bearer phenotype parent minted for the NCVC Saudi guide EQ classes. {DECISION}")
        else:
            parent = _obo(parent_key)
            graph.add((parent, RDF.type, OWL.Class))
        graph.add((cls, RDF.type, OWL.Class))
        graph.add((cls, RDFS.label, Literal(row["label"], lang="en")))
        graph.add((cls, IAO_DEFINITION, Literal(row["definition"], lang="en")))
        graph.add((cls, RDFS.subClassOf, parent))
        graph.add(
            (
                cls,
                OWL.equivalentClass,
                _some(graph, HAS_PART, _and(graph, [_obo(bearer), _some(graph, HAS_QUALITY, _obo(quality))])),
            )
        )
        graph.add((_obo(bearer), RDF.type, OWL.Class))
        graph.add((_obo(quality), RDF.type, OWL.Class))
        provenance(
            cls,
            f"{DECISION} Pair {bearer.replace('_', ':')} x {quality.replace('_', ':')} approved in "
            f"{PAIR_APPROVALS.as_posix()}; attested by {row['assertions']} assertion(s) for "
            f"{row['taxa']} taxon/taxa in {SOURCE_ID} (PDF pages {row['pages'].replace('|', ', ')}).",
        )
    stale = set(allocations) - minted
    if stale:
        raise ValueError(f"registry allocations without an accepted row: {sorted(stale)[:5]}")
    return graph


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("propose", help="write the screened specification")
    p.add_argument("--dispositions", type=Path, default=DISPOSITIONS)
    p.add_argument("--novel", type=Path, default=NOVEL)
    p.add_argument("--flopo-registry", type=Path, default=FLOPO_REGISTRY)
    p.add_argument("--combinations", type=Path, default=COMBINATIONS)
    p.add_argument("--pair-exclusions", type=Path, default=PAIR_EXCLUSIONS)
    p.add_argument("-o", "--out", type=Path, default=SPEC)
    b = sub.add_parser("build", help="allocate identifiers and write the module")
    b.add_argument("--spec", type=Path, default=SPEC)
    b.add_argument("--id-registry", type=Path, default=REGISTRY)
    b.add_argument("--flopo-registry", type=Path, default=FLOPO_REGISTRY)
    b.add_argument("--combinations", type=Path, default=COMBINATIONS)
    b.add_argument("-o", "--out", type=Path, default=OUTPUT)
    b.add_argument("--date", default="2026-09-18")
    args = parser.parse_args()

    if args.command == "propose":
        rows = propose(
            args.dispositions,
            args.novel,
            args.flopo_registry,
            args.combinations,
            args.pair_exclusions,
        )
        _write(args.out, SPEC_FIELDS, rows)
        decisions = Counter(row["decision"] for row in rows)
        print(f"signatures {len(rows)} " + " ".join(f"{k} {v}" for k, v in sorted(decisions.items())))
        print(f"output {args.out}")
        return

    accepted = [row for row in _rows(args.spec) if row["decision"] == "accept"]
    allocations = _allocate(accepted, args.id_registry, args.flopo_registry, other_block_numbers())
    _write(args.id_registry, REGISTRY_FIELDS, allocations)
    graph = build_module(args.spec, args.id_registry, args.flopo_registry, args.combinations, args.date)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(serialize(graph), encoding="utf-8")
    kinds = Counter(row["kind"] for row in allocations)
    print(f"allocated {len(allocations)} " + " ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    print(f"range {allocations[0]['flopo_id']}..{allocations[-1]['flopo_id']}" if allocations else "range none")
    print(f"output {args.out}")


if __name__ == "__main__":
    main()
