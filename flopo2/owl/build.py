"""Phase 8 OWL build for FLOPO 2.0.

The curated trait database / gated JSONL is the source of truth. This builder emits a FLOPO OWL
candidate while preserving the identifier contract:

* existing ``EQ|PO|PATO`` and ``PHENO|PO`` signatures reuse their registry IRI;
* new signatures are minted after the maximum existing FLOPO id;
* only Phase-7 ``gate.status == accepted`` assertions become ontology classes;
* review/blocked rows remain database-only until curated.

The emitted logical pattern mirrors the 2016 builder:

* ``E phenotype`` EquivalentTo ``has_part some ((part_of some E) and has_quality some quality)``
* ``E Q`` EquivalentTo ``has_part some (E and has_quality some Q)``
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from rdflib import OWL, RDF, RDFS, BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import DC, DCTERMS, XSD

from flopo2.ids.registry import IdAllocator, load_registry
from flopo2.annotation.provenance import ensure_source_statements
from flopo2.owl.assertions import FLOPOANN, formal_assertion_iri
from flopo2.owl.io import serialize_ontology

OBO = "http://purl.obolibrary.org/obo/"
FLOPO_ONTOLOGY = URIRef(OBO + "flopo.owl")
HAS_PART = URIRef(OBO + "BFO_0000051")
PART_OF = URIRef(OBO + "BFO_0000050")
HAS_QUALITY = URIRef(OBO + "RO_0000053")
QUALITY_ROOT = URIRef(OBO + "PATO_0000001")
ROOT_CLASS = URIRef(OBO + "FLOPO_0000000")
IAO_DEF = URIRef(OBO + "IAO_0000115")
IAO_0000116 = URIRef(OBO + "IAO_0000116")  # editor note
FLOPO_SUPPORT_COUNT = URIRef(OBO + "FLOPO_supporting_assertion_count")
SUPPORTED_BY_ASSERTION = FLOPOANN.supported_by_assertion
ANNOTATION_PROPERTIES = (
    IAO_DEF,
    IAO_0000116,
    FLOPO_SUPPORT_COUNT,
    SUPPORTED_BY_ASSERTION,
    DCTERMS.title,
    DCTERMS.description,
    DCTERMS.license,
    DC.rights,
)


@dataclass(frozen=True)
class Candidate:
    po_id: str
    pato_id: str
    po_label: str
    pato_label: str
    support: int
    supporting_assertion_iris: tuple[str, ...]
    value_operator: str = "atomic"
    value_term_ids: tuple[str, ...] = ()
    value_labels: tuple[str, ...] = ()

    @property
    def eq_signature(self) -> str:
        if self.value_operator == "atomic" and len(self.value_term_ids) == 1:
            return f"EQ|{self.po_id}|{self.value_term_ids[0]}"
        if self.value_operator in {"one_of", "all_of"} and self.value_term_ids:
            values = "&".join(sorted(self.value_term_ids))
            return f"EQV|{self.po_id}|{self.value_operator.upper()}|{values}"
        return f"EQ|{self.po_id}|{self.pato_id}"

    @property
    def pheno_signature(self) -> str:
        return f"PHENO|{self.po_id}"

    @property
    def display_quality(self) -> str:
        if not self.value_labels:
            return self.pato_label
        joiner = " or " if self.value_operator == "one_of" else " and "
        return joiner.join(self.value_labels)


def _obo(curie: str) -> URIRef:
    return URIRef(OBO + curie)


def _load_labels(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with Path(path).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            out[row["id"]] = row["label"]
    return out


def _load_attribute_terms(path: Path) -> set[str]:
    out: set[str] = set()
    with Path(path).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if "attribute_slim" in (row.get("slim") or "").split("|"):
                out.add(row["id"])
    return out


def _restriction(g: Graph, prop: URIRef, filler) -> BNode:
    node = BNode()
    g.add((node, RDF.type, OWL.Restriction))
    g.add((node, OWL.onProperty, prop))
    g.add((node, OWL.someValuesFrom, filler))
    return node


def _intersection(g: Graph, members: list) -> BNode:
    node = BNode()
    head = BNode()
    Collection(g, head, members)
    _strip_list_types(g, head)
    g.add((node, OWL.intersectionOf, head))
    return node


def _union(g: Graph, members: list) -> BNode:
    node = BNode()
    head = BNode()
    Collection(g, head, members)
    _strip_list_types(g, head)
    g.add((node, OWL.unionOf, head))
    return node


def _strip_list_types(g: Graph, head) -> None:
    """Remove redundant rdf:List type triples that make rdflib's RDF/XML serializer warn."""
    cur = head
    while cur and cur != RDF.nil:
        g.remove((cur, RDF.type, RDF.List))
        cur = next(g.objects(cur, RDF.rest), None)


def _equiv_some_has_part(g: Graph, cls: URIRef, filler) -> None:
    g.add((cls, OWL.equivalentClass, _restriction(g, HAS_PART, filler)))


def _definition(po_label: str, pato_label: str | None = None) -> str:
    if pato_label:
        return f"A flora phenotype in which a(n) {po_label} exhibits the quality {pato_label}."
    return f"A flora phenotype affecting a(n) {po_label} or one of its parts."


def _value_definition(po_label: str, labels: tuple[str, ...], operator: str) -> str:
    if operator == "one_of":
        values = " or ".join(labels)
        return f"A flora phenotype in which a(n) {po_label} has one of the alternative values: {values}."
    if operator == "all_of":
        values = " and ".join(labels)
        return f"A flora phenotype in which a(n) {po_label} exhibits all component qualities: {values}."
    return _definition(po_label, labels[0] if labels else None)


def _load_combination_status(path: Path) -> dict[tuple[str, str], str]:
    if not Path(path).exists():
        return {}
    out: dict[tuple[str, str], str] = {}
    with Path(path).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            out[(row["po_id"], row["pato_id"])] = row.get("status", "")
    return out


def _obsolete_class(g: Graph, iri: str, label: str, reason: str) -> None:
    cls = URIRef(iri)
    g.add((cls, RDF.type, OWL.Class))
    obsolete_label = f"obsolete {label}" if label and not label.lower().startswith("obsolete ") else label
    if obsolete_label:
        g.add((cls, RDFS.label, Literal(obsolete_label, lang="en")))
    g.add((cls, IAO_DEF, Literal(f"Obsolete flora phenotype class: {label or iri}.", lang="en")))
    g.add((cls, OWL.deprecated, Literal(True)))
    # IAO:0000231 takes an OMO obsolescence-reason individual, never free text. The release
    # builder does not have enough information to select one of those controlled reasons, so the
    # diagnostic belongs in an editor note. Exact replacements are handled by a reviewed
    # migration and IAO:0100001, not guessed here.
    g.add(
        (
            cls,
            IAO_0000116,
            Literal(
                "FLOPO 2.0 release validation obsoleted this class in place; "
                f"the IRI remains reserved. Diagnostic: {reason}",
                lang="en",
            ),
        )
    )


def load_candidates(
    gated_jsonl: Path,
    po_lex: Path = Path("config/po_lexicon.tsv"),
    pato_lex: Path = Path("config/pato_lexicon.tsv"),
    flopo_registry: Path = Path("config/flopo_id_registry.tsv"),
    flopo_value_axioms: Path = Path("config/flopo_value_axioms.tsv"),
) -> list[Candidate]:
    """Aggregate accepted gated assertions into unique PO/PATO class candidates."""
    po_labels = _load_labels(po_lex)
    pato_labels = _load_labels(pato_lex)
    attribute_pato_ids = _load_attribute_terms(pato_lex)
    flopo_labels: dict[str, str] = {}
    if Path(flopo_registry).exists():
        with Path(flopo_registry).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                flopo_labels[row["flopo_iri"].rsplit("/", 1)[-1]] = row.get("label", "")
    # Reviewed FLOPO-local PO extensions are valid anatomical bearers.  Keep their ontology
    # labels available to the same reusable phenotype builder without pretending they are PO IDs.
    po_labels.update({identifier: label for identifier, label in flopo_labels.items() if label})
    if Path(flopo_value_axioms).exists():
        with Path(flopo_value_axioms).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                flopo_labels[row["flopo_id"]] = row.get("label", "")
    support: Counter[tuple[str, str, str, tuple[str, ...]]] = Counter()
    assertion_iris: dict[tuple[str, str, str, tuple[str, ...]], list[str]] = defaultdict(list)
    logical_attributes: dict[tuple[str, str, tuple[str, ...]], set[str]] = defaultdict(set)
    source_positions: Counter[tuple[str, str]] = Counter()

    with Path(gated_jsonl).open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            obj = json.loads(line)
            source_key = (str(obj.get("source", "")), str(obj.get("source_id", "")))
            obj.setdefault("source_segment_index", source_positions[source_key])
            source_positions[source_key] += 1
            obj = ensure_source_statements(obj)
            for assertion_index, a in enumerate(obj.get("assertions", []) or []):
                gate = a.get("gate") or {}
                if gate.get("status") != "accepted":
                    continue
                if str(a.get("cardinality", "") or "").strip():
                    raise ValueError(
                        "accepted assertion contains semantics the OWL builder cannot encode; "
                        "rerun Phase 7 gates before building"
                    )
                po_id, pato_id = a.get("po_id", ""), a.get("pato_id", "")
                if not po_id or not pato_id:
                    continue
                operator = a.get("value_operator", "atomic") or "atomic"
                values = tuple(
                    sorted(set(a.get("value_terms", []) or a.get("value_term_ids", []) or []))
                )
                # Arbitrary disjunctions and unreviewed composites belong to the source assertion
                # class description, not FLOPO's reusable vocabulary.  Their PATO attribute trait
                # remains reusable and is therefore still emitted here.
                reusable_composite = operator == "all_of" and gate.get("flopo_status") == "existing"
                if operator == "one_of" or (operator == "all_of" and not reusable_composite):
                    operator = "atomic"
                    values = ()
                if (
                    operator == "atomic"
                    and len(values) == 1
                    and attribute_pato_ids
                    and pato_id != values[0]
                    and pato_id not in attribute_pato_ids
                ):
                    raise ValueError(
                        "accepted atomic value has an incompatible top-level PATO term; "
                        "rerun Phase 7 gates before building"
                    )
                # ``shape + cylindrical`` and direct ``cylindrical`` are two wire encodings of
                # the same atomic EQ. Phase 7 guarantees the primary term is either the attribute
                # or the sole value, so aggregate both under the value-quality signature.
                effective_pato_id = (
                    values[0] if operator == "atomic" and len(values) == 1 else pato_id
                )
                key = (po_id, effective_pato_id, operator, values)
                if operator in {"one_of", "all_of"} and values:
                    logical_attributes[(po_id, operator, values)].add(pato_id)
                support[key] += 1
                source_statement_id = a.get("source_statement_id", "")
                assertion_iris[key].append(
                    str(formal_assertion_iri(source_statement_id, assertion_index, a))
                )

    inconsistent = {
        key: attributes
        for key, attributes in logical_attributes.items()
        if len(attributes) > 1
    }
    if inconsistent:
        raise ValueError(
            "logical value signature has inconsistent top-level PATO attributes: "
            f"{inconsistent!r}"
        )

    return [
        Candidate(
            po_id=po,
            pato_id=pato,
            po_label=po_labels.get(po, po),
            pato_label=pato_labels.get(pato, pato),
            support=count,
            supporting_assertion_iris=tuple(
                dict.fromkeys(assertion_iris[(po, pato, operator, values)])
            ),
            value_operator=operator,
            value_term_ids=values,
            value_labels=tuple(
                pato_labels.get(value, flopo_labels.get(value, value)) for value in values
            ),
        )
        for (po, pato, operator, values), count in sorted(support.items())
    ]


def build_ontology(
    gated_jsonl: Path,
    out_owl: Path,
    registry_tsv: Path = Path("config/flopo_id_registry.tsv"),
    po_lex: Path = Path("config/po_lexicon.tsv"),
    pato_lex: Path = Path("config/pato_lexicon.tsv"),
    version: str = "candidate",
    output_format: str = "turtle",
    combinations_tsv: Path = Path("config/valid_combinations.tsv"),
    obsolete_unsupported_existing: bool = False,
    reservations_tsv: Path | None = None,
) -> dict:
    entries = load_registry(registry_tsv)
    reservations = load_registry(reservations_tsv) if reservations_tsv is not None else []
    allocator = IdAllocator(entries, reservations)
    candidates = load_candidates(gated_jsonl, po_lex, pato_lex, registry_tsv)
    pato_labels = _load_labels(pato_lex)

    g = Graph()
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("obo", OBO)
    g.bind("flopoann", FLOPOANN)
    g.add((FLOPO_ONTOLOGY, RDF.type, OWL.Ontology))
    g.add((FLOPO_ONTOLOGY, OWL.versionInfo, Literal(version)))
    g.add((FLOPO_ONTOLOGY, DCTERMS.title, Literal("Flora Phenotype Ontology", lang="en")))
    g.add((FLOPO_ONTOLOGY, DCTERMS.description, Literal("FLOPO v2 candidate generated from gated flora trait assertions.", lang="en")))
    g.add((FLOPO_ONTOLOGY, DCTERMS.license, URIRef("https://creativecommons.org/publicdomain/zero/1.0/")))
    g.add((FLOPO_ONTOLOGY, DC.rights, Literal("CC0 1.0 Universal", lang="en")))

    for prop in ANNOTATION_PROPERTIES:
        g.add((prop, RDF.type, OWL.AnnotationProperty))
    for prop in (HAS_PART, PART_OF, HAS_QUALITY):
        g.add((prop, RDF.type, OWL.ObjectProperty))

    g.add((ROOT_CLASS, RDF.type, OWL.Class))
    g.add((ROOT_CLASS, RDFS.label, Literal("flora phenotype", lang="en")))
    g.add((ROOT_CLASS, IAO_DEF, Literal("A phenotype observed in a vascular plant flora description.", lang="en")))
    pheno_seen: set[str] = set()
    eq_iris: set[str] = set()
    pheno_iris: set[str] = set()
    reused = 0
    accepted_signatures: set[str] = set()
    emitted_flopo_iris: set[str] = {str(ROOT_CLASS)}

    existing_by_sig = {e.signature: e.iri for e in entries if e.signature != "OTHER"}

    for c in candidates:
        pheno_sig = c.pheno_signature
        accepted_signatures.add(pheno_sig)
        pheno_iri = URIRef(allocator.iri_for(pheno_sig))
        if pheno_sig not in pheno_seen:
            pheno_seen.add(pheno_sig)
            pheno_iris.add(str(pheno_iri))
            emitted_flopo_iris.add(str(pheno_iri))
            g.add((pheno_iri, RDF.type, OWL.Class))
            g.add((pheno_iri, RDFS.subClassOf, ROOT_CLASS))
            g.add((pheno_iri, RDFS.label, Literal(f"{c.po_label} phenotype", lang="en")))
            g.add((pheno_iri, IAO_DEF, Literal(_definition(c.po_label), lang="en")))
            filler = _intersection(g, [
                _restriction(g, PART_OF, _obo(c.po_id)),
                _restriction(g, HAS_QUALITY, QUALITY_ROOT),
            ])
            _equiv_some_has_part(g, pheno_iri, filler)
            g.add((_obo(c.po_id), RDF.type, OWL.Class))
            g.add((_obo(c.po_id), RDFS.label, Literal(c.po_label, lang="en")))
            bearer_vocabulary = "Plant Ontology" if c.po_id.startswith("PO_") else "FLOPO-local anatomy"
            g.add(
                (
                    _obo(c.po_id),
                    IAO_DEF,
                    Literal(f"Referenced {bearer_vocabulary} class: {c.po_label}.", lang="en"),
                )
            )

        eq_iri = URIRef(allocator.iri_for(c.eq_signature))
        accepted_signatures.add(c.eq_signature)
        if c.eq_signature in existing_by_sig:
            reused += 1
        eq_iris.add(str(eq_iri))
        emitted_flopo_iris.add(str(eq_iri))
        g.add((eq_iri, RDF.type, OWL.Class))
        g.add((eq_iri, RDFS.subClassOf, pheno_iri))
        g.add((eq_iri, RDFS.label, Literal(f"{c.po_label} {c.display_quality}", lang="en")))
        definition = (
            _value_definition(c.po_label, c.value_labels, c.value_operator)
            if c.value_term_ids
            else _definition(c.po_label, c.pato_label)
        )
        g.add((eq_iri, IAO_DEF, Literal(definition, lang="en")))
        g.add((eq_iri, FLOPO_SUPPORT_COUNT, Literal(c.support, datatype=XSD.integer)))
        for assertion_iri in c.supporting_assertion_iris:
            # Annotation link only: the formal assertion individual and all source text live in
            # the source-scoped assertion module, avoiding class/individual punning in flopo.owl.
            g.add((eq_iri, SUPPORTED_BY_ASSERTION, URIRef(assertion_iri)))
        if not c.value_term_ids:
            quality_restrictions = [_restriction(g, HAS_QUALITY, _obo(c.pato_id))]
        elif c.value_operator == "one_of":
            value_union = _union(g, [_obo(value) for value in c.value_term_ids])
            quality_restrictions = [_restriction(g, HAS_QUALITY, value_union)]
        elif c.value_operator == "all_of":
            quality_restrictions = [
                _restriction(g, HAS_QUALITY, _obo(value)) for value in c.value_term_ids
            ]
        else:
            quality_restrictions = [
                _restriction(g, HAS_QUALITY, _obo(c.value_term_ids[0]))
            ]
        filler = _intersection(g, [_obo(c.po_id), *quality_restrictions])
        _equiv_some_has_part(g, eq_iri, filler)
        g.add((_obo(c.pato_id), RDF.type, OWL.Class))
        g.add((_obo(c.pato_id), RDFS.label, Literal(pato_labels.get(c.pato_id, c.pato_id), lang="en")))
        g.add((_obo(c.pato_id), IAO_DEF, Literal(f"Referenced PATO quality: {pato_labels.get(c.pato_id, c.pato_id)}.", lang="en")))
        g.add((QUALITY_ROOT, RDF.type, OWL.Class))
        g.add((QUALITY_ROOT, RDFS.label, Literal(pato_labels.get("PATO_0000001", "quality"), lang="en")))
        g.add((QUALITY_ROOT, IAO_DEF, Literal("Referenced PATO quality root.", lang="en")))
        for value_id, value_label in zip(c.value_term_ids, c.value_labels, strict=True):
            g.add((_obo(value_id), RDF.type, OWL.Class))
            g.add((_obo(value_id), RDFS.label, Literal(value_label, lang="en")))

    obsoleted = 0
    if obsolete_unsupported_existing:
        combo_status = _load_combination_status(combinations_tsv)
        for entry in entries:
            if entry.iri in emitted_flopo_iris:
                continue
            parts = entry.signature.split("|")
            if len(parts) == 3 and parts[0] == "EQ":
                if entry.signature in accepted_signatures:
                    reason = "Legacy duplicate FLOPO signature retained as deprecated; another original IRI carries the accepted FLOPO 2.0 class."
                else:
                    status = combo_status.get((parts[1], parts[2]), "novel")
                    if status in {"blocked", "blocklisted", "invalid"}:
                        reason = f"Failed FLOPO 2.0 PO x PATO validity gate: {status}."
                    elif entry.deprecated:
                        reason = "Legacy FLOPO class was already deprecated and has no accepted FLOPO 2.0 support."
                    else:
                        reason = "No accepted supporting assertion in the current FLOPO 2.0 curated database."
            elif len(parts) == 2 and parts[0] == "PHENO":
                if entry.signature in accepted_signatures:
                    reason = "Legacy duplicate FLOPO signature retained as deprecated; another original IRI carries the accepted FLOPO 2.0 phenotype grouping."
                else:
                    reason = "No accepted supporting assertion for this anatomical phenotype grouping in the current FLOPO 2.0 curated database."
            elif len(parts) == 5 and parts[0] == "EQV":
                if entry.signature in accepted_signatures:
                    reason = "Legacy duplicate logical-value signature retained as deprecated; another original IRI carries the accepted FLOPO 2.0 class."
                else:
                    reason = "No accepted supporting assertion for this logical value expression in the current FLOPO 2.0 curated database."
            elif entry.signature == "OTHER":
                reason = "Legacy FLOPO class has no recoverable FLOPO 2.0 EQ/PHENO signature; obsoleted in place to preserve the original IRI."
            else:
                reason = "No validated FLOPO 2.0 logical signature support."
            _obsolete_class(g, entry.iri, entry.label, reason)
            emitted_flopo_iris.add(entry.iri)
            obsoleted += 1

    out_owl.parent.mkdir(parents=True, exist_ok=True)
    serialize_ontology(g, out_owl, output_format)
    return {
        "classes_eq": len(eq_iris),
        "classes_pheno": len(pheno_iris),
        "reused_existing_eq": reused,
        "reused_reviewed_reservations": len(allocator.reused_reservations),
        "minted": len(allocator.minted),
        "minted_iris": allocator.minted,
        "obsoleted_existing": obsoleted,
        "out": str(out_owl),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Build FLOPO OWL from Phase 7 gated assertions.")
    ap.add_argument("input", type=Path, help="Phase 7 gated JSONL")
    ap.add_argument("-o", "--out", type=Path, default=Path("ontology/flopo-v2-candidate.ofn"))
    ap.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    ap.add_argument(
        "--reservations",
        type=Path,
        default=Path("config/flopo_reviewed_id_reservations.tsv"),
        help="Reviewed but not-yet-released signature-to-IRI reservations",
    )
    ap.add_argument("--po-lex", type=Path, default=Path("config/po_lexicon.tsv"))
    ap.add_argument("--pato-lex", type=Path, default=Path("config/pato_lexicon.tsv"))
    ap.add_argument("--version", default="candidate")
    ap.add_argument("--combinations", type=Path, default=Path("config/valid_combinations.tsv"))
    ap.add_argument(
        "--obsolete-unsupported-existing",
        action="store_true",
        help="Release mode: emit unsupported legacy registry classes as owl:deprecated instead of omitting them",
    )
    ap.add_argument(
        "--format",
        default=None,
        choices=["ofn", "turtle", "xml", "pretty-xml", "nt", "json-ld"],
        help="OWL serialization format (default: ofn for .ofn output, otherwise turtle)",
    )
    args = ap.parse_args()
    stats = build_ontology(
        gated_jsonl=args.input,
        out_owl=args.out,
        registry_tsv=args.registry,
        po_lex=args.po_lex,
        pato_lex=args.pato_lex,
        version=args.version,
        output_format=args.format
        or ("ofn" if args.out.suffix.lower() == ".ofn" else "turtle"),
        combinations_tsv=args.combinations,
        obsolete_unsupported_existing=args.obsolete_unsupported_existing,
        reservations_tsv=args.reservations,
    )
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
