"""Build source-scoped OWL modules for flora phenotype assertions.

``flopo.owl`` remains the reusable vocabulary.  This builder retains every source statement and
links each assertion to a stable named class in the separate annotation extension, where arbitrary
disjunctions, numerical intervals, negation, and seasons are defined.  Only strict accepted claims
become taxon subclass axioms; qualified claims remain meta-level SIO statements.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from rdflib import OWL, RDF, RDFS, BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import DCTERMS, XSD

from flopo2.annotation.provenance import ensure_source_statements
from flopo2.owl.annotation_class import (
    ANNOTATION_EXTENSION_ONTOLOGY,
    ensure_annotation_class_iri,
)
from flopo2.owl.io import serialize_ontology


OBO = "http://purl.obolibrary.org/obo/"
SIO = Namespace("http://semanticscience.org/resource/")
PROV = Namespace("http://www.w3.org/ns/prov#")
FLOPOANN = Namespace("https://w3id.org/flopo/annotation/")
SOURCE = "https://w3id.org/flopo/source/"
SOURCE_STATEMENT = "https://w3id.org/flopo/source-statement/"
FORMAL_ASSERTION = "https://w3id.org/flopo/flora-assertion/"
# Deprecated: source-specific expression identities have been replaced by stable FAC IRIs in
# the annotation extension.  Retained as a public constant for downstream compatibility only.
SOURCE_DESCRIPTION = "https://w3id.org/flopo/source-description/"
SOURCE_TAXON = "https://w3id.org/flopo/source-taxon/"
GEOGRAPHIC_CONTEXT = "https://w3id.org/flopo/geographic-context/"

FLOPO_ONTOLOGY = URIRef(OBO + "flopo.owl")
ANNOTATION_ONTOLOGY = URIRef("https://w3id.org/flopo/annotation")
ANNOTATION_EXTENSION = URIRef(ANNOTATION_EXTENSION_ONTOLOGY)
HAS_PART = URIRef(OBO + "BFO_0000051")
HAS_QUALITY = URIRef(OBO + "RO_0000053")
HAPPENS_DURING = URIRef(OBO + "RO_0002092")
HAS_PHENOTYPE = SIO.SIO_001279
SIO_STATEMENT = SIO.SIO_001183
SIO_DOCUMENT = SIO.SIO_000148
SIO_DATA_TRANSFORMATION = SIO.SIO_000594
SIO_DERIVED_FROM = SIO.SIO_000244
SIO_HAS_SOURCE = SIO.SIO_000253
SIO_HAS_INPUT = SIO.SIO_000230
SIO_HAS_OUTPUT = SIO.SIO_000229
SIO_IS_OUTPUT_OF = SIO.SIO_000232
SIO_HAS_VALUE = SIO.SIO_000300
SIO_PHENOTYPE = SIO.SIO_010056

UNIT_IRIS = {
    "m": "UO_0000008",
    "meter": "UO_0000008",
    "metre": "UO_0000008",
    "cm": "UO_0000015",
    "centimeter": "UO_0000015",
    "centimetre": "UO_0000015",
    "mm": "UO_0000016",
    "millimeter": "UO_0000016",
    "millimetre": "UO_0000016",
    "µm": "UO_0000017",
    "μm": "UO_0000017",
    "um": "UO_0000017",
    "micrometer": "UO_0000017",
    "micrometre": "UO_0000017",
    "nm": "UO_0000018",
    "nanometer": "UO_0000018",
    "nanometre": "UO_0000018",
}

SEASON_TERMS = {
    "season": URIRef(OBO + "ENVO_03000096"),
    "warm": URIRef(OBO + "ENVO_03000097"),
    "warm_season": URIRef(OBO + "ENVO_03000097"),
    "cold": URIRef(OBO + "ENVO_03000098"),
    "cold_season": URIRef(OBO + "ENVO_03000098"),
    "monsoon": URIRef(OBO + "ENVO_03000129"),
    "monsoon_season": URIRef(OBO + "ENVO_03000129"),
    "spring": FLOPOANN.spring_season,
    "spring_season": FLOPOANN.spring_season,
    "summer": FLOPOANN.summer_season,
    "summer_season": FLOPOANN.summer_season,
    "autumn": FLOPOANN.autumn_season,
    "fall": FLOPOANN.autumn_season,
    "autumn_season": FLOPOANN.autumn_season,
    "winter": FLOPOANN.winter_season,
    "winter_season": FLOPOANN.winter_season,
    "wet": FLOPOANN.wet_season,
    "rainy": FLOPOANN.wet_season,
    "wet_season": FLOPOANN.wet_season,
    "dry": FLOPOANN.dry_season,
    "dry_season": FLOPOANN.dry_season,
}

ANNOTATION_PROPERTIES = {
    DCTERMS.description,
    DCTERMS.identifier,
    FLOPOANN.logical_status,
    FLOPOANN.source_statement,
    FLOPOANN.formal_assertion,
    FLOPOANN.source_text,
    FLOPOANN.source_start,
    FLOPOANN.source_end,
    FLOPOANN.document_start,
    FLOPOANN.document_end,
    FLOPOANN.source_document,
    FLOPOANN.source_segment_index,
    FLOPOANN.source_collection,
    FLOPOANN.source_identifier,
    FLOPOANN.language,
    FLOPOANN.sentence_index,
    FLOPOANN.extractor,
    FLOPOANN.mapping_provenance,
    FLOPOANN.modality_cue,
    FLOPOANN.season_text,
    FLOPOANN.developmental_stage_text,
    FLOPOANN.curation_status,
    FLOPOANN.confidence,
    FLOPOANN.hemisphere,
    FLOPOANN.phenotype_class,
}


class _Nodes:
    """Deterministic blank-node allocator for reproducible source modules."""

    def __init__(self) -> None:
        self.counter = 0

    def new(self, role: str) -> BNode:
        self.counter += 1
        safe = re.sub(r"[^A-Za-z0-9]", "", role)[:24] or "node"
        return BNode(f"{safe}{self.counter:08d}")


def _strip_list_types(graph: Graph, head: BNode) -> None:
    current = head
    while current and current != RDF.nil:
        graph.remove((current, RDF.type, RDF.List))
        current = next(graph.objects(current, RDF.rest), None)


def _list_expression(graph: Graph, nodes: _Nodes, predicate: URIRef, members: list) -> BNode:
    expression = nodes.new("classExpression")
    head = nodes.new("list")
    Collection(graph, head, members)
    _strip_list_types(graph, head)
    graph.add((expression, predicate, head))
    return expression


def _intersection(graph: Graph, nodes: _Nodes, members: list) -> URIRef | BNode:
    if len(members) == 1:
        return members[0]
    return _list_expression(graph, nodes, OWL.intersectionOf, members)


def _union(graph: Graph, nodes: _Nodes, members: list) -> URIRef | BNode:
    if len(members) == 1:
        return members[0]
    return _list_expression(graph, nodes, OWL.unionOf, members)


def _complement(graph: Graph, nodes: _Nodes, expression) -> BNode:
    complement = nodes.new("complementExpression")
    graph.add((complement, OWL.complementOf, expression))
    return complement


def _some(graph: Graph, nodes: _Nodes, prop: URIRef, filler) -> BNode:
    restriction = nodes.new("someRestriction")
    graph.add((restriction, RDF.type, OWL.Restriction))
    graph.add((restriction, OWL.onProperty, prop))
    graph.add((restriction, OWL.someValuesFrom, filler))
    return restriction


def _has_value(graph: Graph, nodes: _Nodes, prop: URIRef, value: Literal) -> BNode:
    restriction = nodes.new("valueRestriction")
    graph.add((restriction, RDF.type, OWL.Restriction))
    graph.add((restriction, OWL.onProperty, prop))
    graph.add((restriction, OWL.hasValue, value))
    return restriction


def _curie_iri(value: object) -> URIRef | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith(("http://", "https://")):
        return URIRef(text)
    if ":" in text:
        prefix, local = text.split(":", 1)
        if prefix.upper() in {"PO", "PATO", "UO", "ENVO", "FLOPO", "RO", "BFO"}:
            return URIRef(f"{OBO}{prefix.upper()}_{local}")
        if prefix.upper() == "NCBITAXON":
            return URIRef(f"{OBO}NCBITaxon_{local}")
        if prefix.upper() == "FLOPOANN":
            return FLOPOANN[local]
        if prefix.upper() == "SIO":
            return SIO[f"SIO_{local}" if not local.startswith("SIO_") else local]
    if re.match(r"^(?:PO|PATO|UO|ENVO|FLOPO|RO|BFO)_", text):
        return URIRef(OBO + text)
    if text.startswith("NCBITaxon_"):
        return URIRef(OBO + text)
    return None


def _load_attributes(path: Path) -> set[str]:
    if not Path(path).exists():
        return set()
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {
            row.get("id", "")
            for row in csv.DictReader(handle, delimiter="\t")
            if "attribute_slim" in (row.get("slim") or "").split("|")
        }


def _decimal_literal(value: object) -> Literal:
    return Literal(Decimal(str(value)), datatype=XSD.decimal)


def _numeric_range(
    graph: Graph,
    nodes: _Nodes,
    low: object | None,
    high: object | None,
    low_inclusive: bool = True,
    high_inclusive: bool = True,
) -> BNode:
    datatype = nodes.new("numericDatatype")
    graph.add((datatype, RDF.type, RDFS.Datatype))
    graph.add((datatype, OWL.onDatatype, XSD.decimal))
    facets: list[BNode] = []
    if low is not None:
        facet = nodes.new("minimumFacet")
        graph.add(
            (facet, XSD.minInclusive if low_inclusive else XSD.minExclusive, _decimal_literal(low))
        )
        facets.append(facet)
    if high is not None:
        facet = nodes.new("maximumFacet")
        graph.add(
            (facet, XSD.maxInclusive if high_inclusive else XSD.maxExclusive, _decimal_literal(high))
        )
        facets.append(facet)
    head = nodes.new("facetList")
    Collection(graph, head, facets)
    _strip_list_types(graph, head)
    graph.add((datatype, OWL.withRestrictions, head))
    return datatype


def _unit_iri(unit: object) -> URIRef:
    direct = _curie_iri(unit)
    if direct is not None and str(direct).startswith(OBO + "UO_"):
        return direct
    key = str(unit or "").strip().rstrip(".").lower()
    singular = key[:-1] if key.endswith("s") else key
    curie = UNIT_IRIS.get(key) or UNIT_IRIS.get(singular)
    if not curie:
        raise ValueError(f"unsupported quantitative phenotype unit: {unit!r}")
    return URIRef(OBO + curie)


def _quality_restrictions(
    graph: Graph,
    nodes: _Nodes,
    assertion: dict,
    attribute_ids: set[str],
) -> tuple[list[BNode], bool, bool]:
    pato_id = str(assertion.get("pato_id", "") or "")
    pato = _curie_iri(pato_id)
    if pato is None:
        raise ValueError(f"invalid PATO identifier: {pato_id!r}")
    values = list(
        dict.fromkeys(assertion.get("value_terms", []) or assertion.get("value_term_ids", []) or [])
    )
    value_iris = [_curie_iri(value) for value in values]
    if any(value is None for value in value_iris):
        raise ValueError(f"invalid categorical phenotype value: {values!r}")
    operator = assertion.get("value_operator", "atomic") or "atomic"
    disjunctive = operator == "one_of" and len(value_iris) > 1
    numeric = assertion.get("value_low") is not None or assertion.get("value_high") is not None

    if numeric:
        normalized_pato = pato_id.replace(":", "_")
        if attribute_ids and normalized_pato not in attribute_ids:
            raise ValueError(
                "quantitative flora phenotype must use a PATO attribute-slim term: "
                f"{pato_id}"
            )
        members: list = [pato]
        graph.add((pato, RDF.type, OWL.Class))
        data_range = _numeric_range(
            graph,
            nodes,
            assertion.get("value_low"),
            assertion.get("value_high"),
            bool(assertion.get("value_low_inclusive", True)),
            bool(assertion.get("value_high_inclusive", True)),
        )
        members.append(_some(graph, nodes, FLOPOANN.has_magnitude, data_range))
        unit = _unit_iri(assertion.get("unit"))
        graph.add((unit, RDF.type, OWL.Class))
        members.append(_some(graph, nodes, FLOPOANN.has_value_unit, unit))
        quality = _intersection(graph, nodes, members)
        return [_some(graph, nodes, HAS_QUALITY, quality)], True, disjunctive

    if not value_iris:
        graph.add((pato, RDF.type, OWL.Class))
        return [_some(graph, nodes, HAS_QUALITY, pato)], False, disjunctive
    for value in value_iris:
        graph.add((value, RDF.type, OWL.Class))
    if operator == "one_of":
        return [
            _some(graph, nodes, HAS_QUALITY, _union(graph, nodes, value_iris))
        ], False, disjunctive
    if operator == "all_of":
        return [_some(graph, nodes, HAS_QUALITY, value) for value in value_iris], False, False
    if len(value_iris) != 1:
        raise ValueError("atomic phenotype value must contain exactly one value term")
    return [_some(graph, nodes, HAS_QUALITY, value_iris[0])], False, False


def _bearer_context_quality_restrictions(
    graph: Graph,
    nodes: _Nodes,
    assertion: dict,
) -> list[BNode]:
    """Compile contextual PATO qualities on the same anatomical bearer.

    Generic flora adjectives such as ``young`` and ``mature`` denote age/maturity qualities
    inhering in the bearer.  They are not PO developmental-stage processes and consequently use
    the same RO ``has quality`` pattern as the primary phenotype value.
    """

    primary = {
        str(value).replace(":", "_")
        for value in (
            assertion.get("value_terms", [])
            or assertion.get("value_term_ids", [])
            or [assertion.get("pato_id", "")]
        )
    }
    restrictions: list[BNode] = []
    seen: set[str] = set()
    for value in assertion.get("bearer_context_qualities", []) or []:
        normalized = str(value or "").strip().replace(":", "_")
        if not normalized.startswith("PATO_"):
            raise ValueError(f"bearer context quality must be a PATO class: {value!r}")
        if normalized in primary:
            raise ValueError(
                "bearer context quality duplicates the primary categorical quality: "
                f"{value!r}"
            )
        if normalized in seen:
            continue
        seen.add(normalized)
        iri = URIRef(OBO + normalized)
        graph.add((iri, RDF.type, OWL.Class))
        restrictions.append(_some(graph, nodes, HAS_QUALITY, iri))
    return restrictions


def _geographic_class(graph: Graph, value: str) -> URIRef:
    direct = _curie_iri(value)
    if direct is not None:
        graph.add((direct, RDF.type, OWL.Class))
        return direct
    digest = hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()[:20]
    iri = URIRef(GEOGRAPHIC_CONTEXT + digest)
    graph.add((iri, RDF.type, OWL.Class))
    graph.add((iri, RDFS.label, Literal(value, lang="en")))
    return iri


def _season_class(graph: Graph, nodes: _Nodes, context: dict) -> URIRef | BNode:
    term_text = str(context.get("season_term", "") or "").strip()
    term = _curie_iri(term_text)
    if term is None and term_text:
        term = SEASON_TERMS.get(term_text.lower().replace(" ", "_"))
    if term is None:
        term = FLOPOANN.SeasonContext
    graph.add((term, RDF.type, OWL.Class))
    members: list = [term]
    if context.get("start_month") is not None:
        members.append(
            _has_value(
                graph,
                nodes,
                FLOPOANN.start_month,
                Literal(int(context["start_month"]), datatype=XSD.integer),
            )
        )
    if context.get("end_month") is not None:
        members.append(
            _has_value(
                graph,
                nodes,
                FLOPOANN.end_month,
                Literal(int(context["end_month"]), datatype=XSD.integer),
            )
        )
    geographic = str(context.get("geographic_context", "") or "").strip()
    if geographic:
        members.append(
            _some(
                graph,
                nodes,
                FLOPOANN.in_geographic_context,
                _geographic_class(graph, geographic),
            )
        )
    hemisphere = str(context.get("hemisphere", "") or "").strip().lower()
    if hemisphere and hemisphere != "unspecified":
        members.append(
            _some(
                graph,
                nodes,
                FLOPOANN.in_geographic_context,
                _geographic_class(graph, f"{hemisphere} hemisphere"),
            )
        )
    return _intersection(graph, nodes, members)


def _season_restrictions(
    graph: Graph, nodes: _Nodes, assertion: dict
) -> tuple[list[BNode], bool]:
    contexts = assertion.get("season_contexts", []) or []
    if not contexts:
        return [], False
    operator = assertion.get("season_operator", "atomic") or "atomic"
    grouped: dict[str, list] = {}
    for context in contexts:
        relation = context.get("temporal_relation", "present_during") or "present_during"
        grouped.setdefault(relation, []).append(_season_class(graph, nodes, context))
    restrictions: list[BNode] = []
    for relation, fillers in grouped.items():
        prop = HAPPENS_DURING if relation == "happens_during" else FLOPOANN.present_during
        if operator == "one_of":
            restrictions.append(_some(graph, nodes, prop, _union(graph, nodes, fillers)))
        else:
            restrictions.extend(_some(graph, nodes, prop, filler) for filler in fillers)
    return restrictions, True


def _developmental_stage_restrictions(
    graph: Graph, nodes: _Nodes, assertion: dict
) -> list[BNode]:
    """Compile true PO developmental stages at the phenotype level.

    PATO age/maturity qualities of the anatomical bearer are handled separately by
    ``_bearer_context_quality_restrictions``.  Specimen conditions such as ``when dry`` are
    deliberately not accepted here.
    """

    contexts = assertion.get("developmental_stage_contexts", []) or []
    if not contexts:
        return []
    operator = assertion.get("developmental_stage_operator", "atomic") or "atomic"
    if operator not in {"atomic", "one_of", "all_of"}:
        raise ValueError(f"unsupported developmental-stage operator: {operator!r}")
    fillers: list[URIRef] = []
    seen: set[str] = set()
    for context in contexts:
        relation = context.get("temporal_relation", "present_during") or "present_during"
        if relation != "present_during":
            raise ValueError(f"unsupported developmental-stage relation: {relation!r}")
        term = _curie_iri(context.get("stage_term"))
        if term is None or not str(term).startswith((OBO + "PO_", OBO + "FLOPO_")):
            raise ValueError(
                "developmental stage must be a PO class or reviewed FLOPO-local PO extension: "
                f"{context.get('stage_term')!r}"
            )
        if str(term) in seen:
            continue
        seen.add(str(term))
        graph.add((term, RDF.type, OWL.Class))
        fillers.append(term)
    if operator == "one_of" and len(fillers) > 1:
        return [
            _some(
                graph,
                nodes,
                FLOPOANN.present_during_developmental_stage,
                _union(graph, nodes, fillers),
            )
        ]
    return [
        _some(graph, nodes, FLOPOANN.present_during_developmental_stage, filler)
        for filler in fillers
    ]


def _phenotype_expression(
    graph: Graph,
    nodes: _Nodes,
    assertion: dict,
    attribute_ids: set[str],
) -> tuple[URIRef | BNode, bool, bool, bool]:
    po = _curie_iri(assertion.get("po_id"))
    if po is None:
        raise ValueError(
            f"invalid PO or FLOPO-local bearer identifier: {assertion.get('po_id')!r}"
        )
    graph.add((po, RDF.type, OWL.Class))
    quality, numeric, disjunctive = _quality_restrictions(graph, nodes, assertion, attribute_ids)
    bearer_context = _bearer_context_quality_restrictions(graph, nodes, assertion)
    negated = bool(assertion.get("negated", False))
    negation_scope = str(assertion.get("negation_scope", "") or "").strip()
    if negated and not negation_scope:
        # Preserve the legacy direct-renderer meaning; the materialized data validator requires
        # all new negated assertions to state the scope explicitly.
        negation_scope = "absence"
    if negated and negation_scope == "quality":
        negated_quality = _complement(graph, nodes, _intersection(graph, nodes, quality))
        bearer = _intersection(graph, nodes, [po, negated_quality, *bearer_context])
        eq = _some(graph, nodes, HAS_PART, bearer)
    else:
        bearer = _intersection(graph, nodes, [po, *quality, *bearer_context])
        positive_eq = _some(graph, nodes, HAS_PART, bearer)
        if negated and negation_scope == "absence":
            eq = _complement(graph, nodes, positive_eq)
        elif negated:
            raise ValueError(f"unsupported negation scope: {negation_scope!r}")
        else:
            if negation_scope:
                raise ValueError("negation_scope is present while negated is false")
            eq = positive_eq
    seasons, seasonal = _season_restrictions(graph, nodes, assertion)
    stages = _developmental_stage_restrictions(graph, nodes, assertion)
    return (
        _intersection(graph, nodes, [SIO_PHENOTYPE, eq, *seasons, *stages]),
        numeric,
        seasonal,
        disjunctive,
    )


def _document_iri(record: dict) -> URIRef:
    identity = f"{record.get('source', '')}\n{record.get('source_id', '')}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return URIRef(SOURCE + digest)


def _statement_iri(statement_id: str) -> URIRef:
    return URIRef(SOURCE_STATEMENT + quote(statement_id, safe="-._~"))


def formal_assertion_iri(statement_id: str, index: int, assertion: dict) -> URIRef:
    """Return the stable IRI shared by source modules and reusable-vocabulary support links."""
    signature = {
        "statement": statement_id,
        "index": index,
        "po": assertion.get("po_id"),
        "pato": assertion.get("pato_id"),
        "values": assertion.get("value_terms", []),
        "operator": assertion.get("value_operator", "atomic"),
        "low": assertion.get("value_low"),
        "high": assertion.get("value_high"),
        "unit": assertion.get("unit"),
        "negated": assertion.get("negated", False),
        "seasons": assertion.get("season_contexts", []),
    }
    # Bound inclusivity participates in the identity only when strict, so every historical
    # inclusive-bound assertion keeps its exact digest while a strict bound gets a distinct IRI.
    if assertion.get("value_low") is not None and not bool(
        assertion.get("value_low_inclusive", True)
    ):
        signature["low_exclusive"] = True
    if assertion.get("value_high") is not None and not bool(
        assertion.get("value_high_inclusive", True)
    ):
        signature["high_exclusive"] = True
    if assertion.get("negated", False):
        signature["negation_scope"] = assertion.get("negation_scope", "absence") or "absence"
    if assertion.get("developmental_stage_contexts", []) or []:
        signature["developmental_stages"] = assertion.get("developmental_stage_contexts", [])
        signature["developmental_stage_operator"] = assertion.get(
            "developmental_stage_operator", "atomic"
        ) or "atomic"
    digest = hashlib.sha256(
        json.dumps(signature, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()[:28]
    return URIRef(FORMAL_ASSERTION + digest)


def _taxon_class(graph: Graph, record: dict) -> URIRef | None:
    for key in ("taxon_iri", "taxon_id", "taxon_curie"):
        taxon = _curie_iri(record.get(key))
        if taxon is not None:
            graph.add((taxon, RDF.type, OWL.Class))
            return taxon
    label = str(record.get("taxon", "") or "").strip()
    if not label:
        return None
    identity = {
        "source": record.get("source", ""),
        "source_id": record.get("source_id", ""),
        "name": label,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    taxon = URIRef(SOURCE_TAXON + digest)
    graph.add((taxon, RDF.type, OWL.Class))
    graph.add((taxon, RDFS.label, Literal(label)))
    return taxon


def _strict(assertion: dict, unqualified_as_universal: bool) -> bool:
    gate = assertion.get("gate") or {}
    if gate.get("status") != "accepted":
        return False
    frequency = assertion.get("frequency_qualifier", "unspecified") or "unspecified"
    frequency_is_strict = frequency == "universal" or (
        frequency == "unspecified" and unqualified_as_universal
    )
    return bool(
        frequency_is_strict
        and (assertion.get("epistemic_modality", "asserted") or "asserted") == "asserted"
        and (assertion.get("value_qualifier", "exact") or "exact") == "exact"
        and (assertion.get("degree_qualifier", "unmodified") or "unmodified")
        == "unmodified"
        and not str(assertion.get("cardinality", "") or "").strip()
    )


def _literal_annotation(graph: Graph, subject, prop: URIRef, value: object) -> None:
    if value is None or value == "":
        return
    graph.add((subject, prop, Literal(value)))


def _emit_statement(graph: Graph, record: dict, statement: dict) -> URIRef:
    document = _document_iri(record)
    graph.add((document, RDF.type, PROV.Entity))
    graph.add((document, RDF.type, SIO_DOCUMENT))
    _literal_annotation(graph, document, FLOPOANN.source_collection, record.get("source"))
    _literal_annotation(graph, document, FLOPOANN.source_identifier, record.get("source_id"))
    graph.add((document, DCTERMS.identifier, Literal(record.get("source_id", ""))))

    iri = _statement_iri(str(statement["statement_id"]))
    graph.add((iri, RDF.type, FLOPOANN.SourceStatement))
    graph.add((iri, RDF.type, SIO_STATEMENT))
    graph.add((iri, RDF.type, PROV.Entity))
    graph.add(
        (
            iri,
            SIO_HAS_VALUE,
            Literal(statement["verbatim_text"], lang=statement.get("language") or None),
        )
    )
    graph.add((iri, PROV.wasDerivedFrom, document))
    graph.add((iri, SIO_DERIVED_FROM, document))
    graph.add((iri, SIO_HAS_SOURCE, document))
    _literal_annotation(graph, iri, FLOPOANN.source_text, statement["verbatim_text"])
    _literal_annotation(graph, iri, FLOPOANN.source_start, statement["start"])
    _literal_annotation(graph, iri, FLOPOANN.source_end, statement["end"])
    _literal_annotation(graph, iri, FLOPOANN.document_start, statement.get("document_start"))
    _literal_annotation(graph, iri, FLOPOANN.document_end, statement.get("document_end"))
    _literal_annotation(graph, iri, FLOPOANN.sentence_index, statement.get("sentence_index"))
    _literal_annotation(graph, iri, FLOPOANN.language, statement.get("language"))
    _literal_annotation(
        graph, iri, FLOPOANN.source_segment_index, record.get("source_segment_index", 0)
    )
    return iri


def _logical_status(assertion: dict, strict: bool) -> str:
    gate_status = (assertion.get("gate") or {}).get("status", "unvalidated")
    if gate_status in {"review", "blocked"}:
        return gate_status
    if strict:
        return "strict_taxon_axiom"
    if assertion.get("negated", False):
        return "qualified_negation"
    return "qualified_meta_assertion"


def _emit_axiom_annotation(
    graph: Graph,
    nodes: _Nodes,
    taxon: URIRef,
    target: BNode,
    assertion_iri: URIRef,
    statement_iri: URIRef,
    assertion: dict,
) -> None:
    axiom = nodes.new("annotatedAxiom")
    graph.add((axiom, RDF.type, OWL.Axiom))
    graph.add((axiom, OWL.annotatedSource, taxon))
    graph.add((axiom, OWL.annotatedProperty, RDFS.subClassOf))
    graph.add((axiom, OWL.annotatedTarget, target))
    graph.add((axiom, FLOPOANN.formal_assertion, assertion_iri))
    graph.add((axiom, FLOPOANN.source_statement, statement_iri))
    for prop, key in (
        (FLOPOANN.source_text, "source_text"),
        (FLOPOANN.source_start, "source_start"),
        (FLOPOANN.source_end, "source_end"),
        (FLOPOANN.extractor, "extractor"),
        (FLOPOANN.modality_cue, "modality_text"),
    ):
        _literal_annotation(graph, axiom, prop, assertion.get(key))
    for provenance in assertion.get("mapping_provenance", []) or []:
        _literal_annotation(graph, axiom, FLOPOANN.mapping_provenance, provenance)


def _declare_vocabulary(graph: Graph) -> None:
    for cls in (
        FLOPOANN.SourceStatement,
        FLOPOANN.FloraAssertion,
        FLOPOANN.ExtractionActivity,
        FLOPOANN.SeasonContext,
        FLOPOANN.DevelopmentalStageContext,
        FLOPOANN.FrequencyQualifier,
        FLOPOANN.EpistemicModality,
        FLOPOANN.ValueQualifier,
        FLOPOANN.DegreeQualifier,
        SIO_STATEMENT,
        SIO_DOCUMENT,
        SIO_DATA_TRANSFORMATION,
        SIO_PHENOTYPE,
        PROV.Entity,
        PROV.Activity,
    ):
        graph.add((cls, RDF.type, OWL.Class))
    for prop in (
        HAS_PART,
        HAS_QUALITY,
        HAS_PHENOTYPE,
        HAPPENS_DURING,
        FLOPOANN.present_during,
        FLOPOANN.present_during_developmental_stage,
        FLOPOANN.has_value_unit,
        FLOPOANN.in_geographic_context,
        FLOPOANN.has_source_statement,
        FLOPOANN.refers_to_class_description,
        FLOPOANN.refers_to_taxon,
        FLOPOANN.has_frequency_qualifier,
        FLOPOANN.has_epistemic_modality,
        FLOPOANN.has_value_qualifier,
        FLOPOANN.has_degree_qualifier,
        PROV.wasDerivedFrom,
        PROV.wasGeneratedBy,
        PROV.used,
        SIO_DERIVED_FROM,
        SIO_HAS_SOURCE,
        SIO_HAS_INPUT,
        SIO_HAS_OUTPUT,
        SIO_IS_OUTPUT_OF,
    ):
        graph.add((prop, RDF.type, OWL.ObjectProperty))
    graph.add((FLOPOANN.has_magnitude, RDF.type, OWL.DatatypeProperty))
    graph.add((FLOPOANN.start_month, RDF.type, OWL.DatatypeProperty))
    graph.add((FLOPOANN.end_month, RDF.type, OWL.DatatypeProperty))
    graph.add((SIO_HAS_VALUE, RDF.type, OWL.DatatypeProperty))
    for prop in ANNOTATION_PROPERTIES:
        graph.add((prop, RDF.type, OWL.AnnotationProperty))


def build_assertion_ontology(
    gated_jsonl: Path,
    out_owl: Path,
    *,
    pato_lex: Path = Path("config/pato_lexicon.tsv"),
    version: str = "candidate",
    output_format: str = "turtle",
    unqualified_as_universal: bool = True,
    include_imports: bool = True,
    embed_annotation_classes: bool = False,
) -> dict:
    """Serialize a lossless, source-scoped flora assertion OWL module.

    Each formal assertion links to a stable named class in the annotation extension.  Class
    definitions are normally imported from that extension; ``embed_annotation_classes`` is a
    standalone-debugging option and must not be used as the released source-module design.
    """

    input_bytes = Path(gated_jsonl).read_bytes()
    module_digest = hashlib.sha256(input_bytes).hexdigest()[:20]
    ontology_iri = URIRef(f"https://w3id.org/flopo/assertion-module/{module_digest}")
    graph = Graph()
    nodes = _Nodes()
    graph.bind("flopoann", FLOPOANN)
    graph.bind("sio", SIO)
    graph.bind("prov", PROV)
    graph.bind("owl", OWL)
    graph.bind("obo", OBO)
    graph.add((ontology_iri, RDF.type, OWL.Ontology))
    if include_imports:
        graph.add((ontology_iri, OWL.imports, FLOPO_ONTOLOGY))
        graph.add((ontology_iri, OWL.imports, ANNOTATION_ONTOLOGY))
        graph.add((ontology_iri, OWL.imports, ANNOTATION_EXTENSION))
    graph.add((ontology_iri, OWL.versionInfo, Literal(version)))
    graph.add(
        (
            ontology_iri,
            DCTERMS.description,
            Literal(
                "Source-scoped flora phenotype assertions with lossless provenance, modality, "
                "quantitative value restrictions, and seasonal class descriptions.",
                lang="en",
            ),
        )
    )
    _declare_vocabulary(graph)
    attribute_ids = _load_attributes(pato_lex)
    counts: Counter[str] = Counter()
    annotation_classes: set[str] = set()
    embedded_classes: set[str] = set()
    source_positions: Counter[tuple[str, str]] = Counter()

    with Path(gated_jsonl).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            source_key = (str(record.get("source", "")), str(record.get("source_id", "")))
            record.setdefault("source_segment_index", source_positions[source_key])
            source_positions[source_key] += 1
            record = ensure_source_statements(record)
            statement_iris = {
                statement["statement_id"]: _emit_statement(graph, record, statement)
                for statement in record.get("source_statements", []) or []
            }
            counts["source_statements"] += len(statement_iris)
            taxon = _taxon_class(graph, record)

            for index, assertion in enumerate(record.get("assertions", []) or []):
                statement_id = assertion["source_statement_id"]
                statement_iri = statement_iris[statement_id]
                formal = formal_assertion_iri(statement_id, index, assertion)
                if str(assertion.get("cardinality", "") or "").strip():
                    raise ValueError(
                        "cannot link an annotation class while cardinality remains outside "
                        "the OWL phenotype expression"
                    )
                description = URIRef(ensure_annotation_class_iri(assertion))
                annotation_classes.add(str(description))
                graph.add((description, RDF.type, OWL.Class))
                if embed_annotation_classes and str(description) not in embedded_classes:
                    expression, _, _, _ = _phenotype_expression(
                        graph, nodes, assertion, attribute_ids
                    )
                    graph.add((description, OWL.equivalentClass, expression))
                    embedded_classes.add(str(description))

                numeric = (
                    assertion.get("value_low") is not None
                    or assertion.get("value_high") is not None
                )
                seasonal = bool(assertion.get("season_contexts", []) or [])
                developmental = bool(assertion.get("developmental_stage_contexts", []) or [])
                disjunctive = (
                    (assertion.get("value_operator", "atomic") or "atomic") == "one_of"
                    and len(
                        assertion.get("value_terms", [])
                        or assertion.get("value_term_ids", [])
                        or []
                    )
                    > 1
                )

                strict = _strict(assertion, unqualified_as_universal) and taxon is not None
                graph.add((formal, RDF.type, FLOPOANN.FloraAssertion))
                graph.add((formal, RDF.type, SIO_STATEMENT))
                graph.add((formal, RDF.type, PROV.Entity))
                graph.add((formal, PROV.wasDerivedFrom, statement_iri))
                graph.add((formal, SIO_DERIVED_FROM, statement_iri))
                graph.add((formal, FLOPOANN.has_source_statement, statement_iri))
                graph.add((formal, FLOPOANN.phenotype_class, description))
                if taxon is not None:
                    graph.add((formal, FLOPOANN.refers_to_taxon, taxon))
                    graph.add((taxon, RDF.type, OWL.NamedIndividual))
                frequency = assertion.get("frequency_qualifier", "unspecified") or "unspecified"
                epistemic = assertion.get("epistemic_modality", "asserted") or "asserted"
                value_qualifier = assertion.get("value_qualifier", "exact") or "exact"
                degree_qualifier = (
                    assertion.get("degree_qualifier", "unmodified") or "unmodified"
                )
                graph.add(
                    (formal, FLOPOANN.has_frequency_qualifier, FLOPOANN[str(frequency)])
                )
                graph.add(
                    (formal, FLOPOANN.has_epistemic_modality, FLOPOANN[str(epistemic)])
                )
                graph.add(
                    (formal, FLOPOANN.has_value_qualifier, FLOPOANN[str(value_qualifier)])
                )
                graph.add(
                    (formal, FLOPOANN.has_degree_qualifier, FLOPOANN[str(degree_qualifier)])
                )
                _literal_annotation(
                    graph, formal, FLOPOANN.logical_status, _logical_status(assertion, strict)
                )
                for prop, key in (
                    (FLOPOANN.source_text, "source_text"),
                    (FLOPOANN.source_start, "source_start"),
                    (FLOPOANN.source_end, "source_end"),
                    (FLOPOANN.extractor, "extractor"),
                    (FLOPOANN.modality_cue, "modality_text"),
                    (FLOPOANN.confidence, "confidence"),
                ):
                    _literal_annotation(graph, formal, prop, assertion.get(key))
                for context in assertion.get("season_contexts", []) or []:
                    _literal_annotation(
                        graph, formal, FLOPOANN.season_text, context.get("season_text")
                    )
                    _literal_annotation(
                        graph, formal, FLOPOANN.hemisphere, context.get("hemisphere")
                    )
                for context in assertion.get("developmental_stage_contexts", []) or []:
                    _literal_annotation(
                        graph,
                        formal,
                        FLOPOANN.developmental_stage_text,
                        context.get("stage_text"),
                    )
                for provenance in assertion.get("mapping_provenance", []) or []:
                    _literal_annotation(graph, formal, FLOPOANN.mapping_provenance, provenance)

                activity = URIRef(str(formal) + "/extraction")
                graph.add((activity, RDF.type, FLOPOANN.ExtractionActivity))
                graph.add((activity, RDF.type, SIO_DATA_TRANSFORMATION))
                graph.add((activity, RDF.type, PROV.Activity))
                graph.add((activity, PROV.used, statement_iri))
                graph.add((activity, SIO_HAS_INPUT, statement_iri))
                graph.add((activity, SIO_HAS_OUTPUT, formal))
                graph.add((formal, PROV.wasGeneratedBy, activity))
                graph.add((formal, SIO_IS_OUTPUT_OF, activity))
                _literal_annotation(
                    graph, activity, FLOPOANN.extractor, assertion.get("extractor")
                )

                if strict and taxon is not None:
                    target = _some(graph, nodes, HAS_PHENOTYPE, description)
                    graph.add((taxon, RDFS.subClassOf, target))
                    _emit_axiom_annotation(
                        graph, nodes, taxon, target, formal, statement_iri, assertion
                    )
                    counts["strict_axioms"] += 1
                else:
                    counts["qualified_or_nonlogical"] += 1
                counts["assertions"] += 1
                counts["numeric_descriptions"] += int(numeric)
                counts["seasonal_descriptions"] += int(seasonal)
                counts["developmental_stage_descriptions"] += int(developmental)
                counts["disjunctive_descriptions"] += int(disjunctive)

    out_owl.parent.mkdir(parents=True, exist_ok=True)
    serialize_ontology(graph, out_owl, output_format)
    return {
        **dict(counts),
        "annotation_classes": len(annotation_classes),
        "reused_annotation_class_links": counts["assertions"] - len(annotation_classes),
        "embedded_annotation_classes": len(embedded_classes),
        "ontology_iri": str(ontology_iri),
        "triples": len(graph),
        "out": str(out_owl),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a source-scoped flora assertion OWL module.")
    parser.add_argument("input", type=Path, help="Phase 7 gated JSONL")
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--pato-lex", type=Path, default=Path("config/pato_lexicon.tsv"))
    parser.add_argument("--version", default="candidate")
    parser.add_argument(
        "--unqualified-meta-only",
        action="store_true",
        help="Do not compile accepted flora prose without an explicit universal cue to a taxon axiom.",
    )
    parser.add_argument(
        "--format",
        default=None,
        choices=["ofn", "turtle", "xml", "pretty-xml", "nt", "json-ld"],
        help="OWL serialization format (default: ofn for .ofn output, otherwise turtle)",
    )
    parser.add_argument(
        "--no-imports",
        action="store_true",
        help="Omit owl:imports for a standalone structural/profile check.",
    )
    parser.add_argument(
        "--embed-annotation-classes",
        action="store_true",
        help="Embed FAC equivalent-class axioms for standalone debugging.",
    )
    args = parser.parse_args()
    stats = build_assertion_ontology(
        args.input,
        args.out,
        pato_lex=args.pato_lex,
        version=args.version,
        output_format=args.format or ("ofn" if args.out.suffix.lower() == ".ofn" else "turtle"),
        unqualified_as_universal=not args.unqualified_meta_only,
        include_imports=not args.no_imports,
        embed_annotation_classes=args.embed_annotation_classes,
    )
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
