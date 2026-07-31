"""Stable identities for OWL phenotype class expressions used by annotations.

FLOPO IRIs remain reserved for curated ontology vocabulary.  Annotation classes live in a
separate W3ID namespace and are identified by the SHA-256 digest of a canonical logical
signature.  Source, taxon, modality, confidence, and provenance never participate in this
identity: two assertions that refer to the same OWL class expression therefore reuse one IRI.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from typing import Any


OBO = "http://purl.obolibrary.org/obo/"
FLOPOANN = "https://w3id.org/flopo/annotation/"
SIO = "http://semanticscience.org/resource/"
GEOGRAPHIC_CONTEXT = "https://w3id.org/flopo/geographic-context/"
ANNOTATION_CLASS_BASE = "https://w3id.org/flopo/annotation-class/"
ANNOTATION_EXTENSION_ONTOLOGY = "https://w3id.org/flopo/annotation-extension"
SIGNATURE_VERSION = 1

_OBO_PREFIXES = {"PO", "PATO", "UO", "ENVO", "FLOPO", "RO", "BFO"}
_OBO_ID = re.compile(r"^(PO|PATO|UO|ENVO|FLOPO|RO|BFO)_([A-Za-z0-9_.-]+)$")

_UNIT_IRIS = {
    "m": OBO + "UO_0000008",
    "meter": OBO + "UO_0000008",
    "metre": OBO + "UO_0000008",
    "cm": OBO + "UO_0000015",
    "centimeter": OBO + "UO_0000015",
    "centimetre": OBO + "UO_0000015",
    "mm": OBO + "UO_0000016",
    "millimeter": OBO + "UO_0000016",
    "millimetre": OBO + "UO_0000016",
    "µm": OBO + "UO_0000017",
    "μm": OBO + "UO_0000017",
    "um": OBO + "UO_0000017",
    "micrometer": OBO + "UO_0000017",
    "micrometre": OBO + "UO_0000017",
    "nm": OBO + "UO_0000018",
    "nanometer": OBO + "UO_0000018",
    "nanometre": OBO + "UO_0000018",
}

_SEASON_IRIS = {
    "season": OBO + "ENVO_03000096",
    "warm": OBO + "ENVO_03000097",
    "warm_season": OBO + "ENVO_03000097",
    "cold": OBO + "ENVO_03000098",
    "cold_season": OBO + "ENVO_03000098",
    "monsoon": OBO + "ENVO_03000129",
    "monsoon_season": OBO + "ENVO_03000129",
    "spring": FLOPOANN + "spring_season",
    "spring_season": FLOPOANN + "spring_season",
    "summer": FLOPOANN + "summer_season",
    "summer_season": FLOPOANN + "summer_season",
    "autumn": FLOPOANN + "autumn_season",
    "fall": FLOPOANN + "autumn_season",
    "autumn_season": FLOPOANN + "autumn_season",
    "winter": FLOPOANN + "winter_season",
    "winter_season": FLOPOANN + "winter_season",
    "wet": FLOPOANN + "wet_season",
    "rainy": FLOPOANN + "wet_season",
    "wet_season": FLOPOANN + "wet_season",
    "dry": FLOPOANN + "dry_season",
    "dry_season": FLOPOANN + "dry_season",
}


def canonical_iri(value: object) -> str:
    """Expand a supported CURIE/underscore identifier to its canonical absolute IRI."""

    text = str(value or "").strip()
    if not text:
        raise ValueError("class-expression identifier is empty")
    if text.startswith(("http://", "https://")):
        return text
    if ":" in text:
        prefix, local = text.split(":", 1)
        upper = prefix.upper()
        if upper in _OBO_PREFIXES:
            return f"{OBO}{upper}_{local}"
        if upper == "NCBITAXON":
            return f"{OBO}NCBITaxon_{local}"
        if upper == "FLOPOANN":
            return FLOPOANN + local
        if upper == "SIO":
            return SIO + (local if local.startswith("SIO_") else f"SIO_{local}")
    match = _OBO_ID.fullmatch(text)
    if match:
        return OBO + text
    if text.startswith("NCBITaxon_"):
        return OBO + text
    raise ValueError(f"unsupported class-expression identifier: {value!r}")


def canonical_unit_iri(value: object) -> str:
    """Return the UO IRI denoted by a unit CURIE or supported flora abbreviation."""

    text = str(value or "").strip().rstrip(".")
    if not text:
        raise ValueError("quantitative phenotype has no unit")
    try:
        direct = canonical_iri(text)
    except ValueError:
        direct = ""
    if direct.startswith(OBO + "UO_"):
        return direct
    key = text.lower()
    singular = key[:-1] if key.endswith("s") else key
    unit = _UNIT_IRIS.get(key) or _UNIT_IRIS.get(singular)
    if unit is None:
        raise ValueError(f"unsupported quantitative phenotype unit: {value!r}")
    return unit


def _decimal_token(value: object | None) -> str | None:
    if value is None:
        return None
    decimal = Decimal(str(value))
    if not decimal.is_finite():
        raise ValueError(f"non-finite quantitative phenotype bound: {value!r}")
    if decimal == 0:
        return "0"
    return format(decimal.normalize(), "f")


def _geographic_iri(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return canonical_iri(text)
    except ValueError:
        digest = hashlib.sha256(text.lower().encode("utf-8")).hexdigest()[:20]
        return GEOGRAPHIC_CONTEXT + digest


def _season_term_iri(value: object) -> str:
    text = str(value or "").strip()
    if text:
        try:
            return canonical_iri(text)
        except ValueError:
            mapped = _SEASON_IRIS.get(text.lower().replace(" ", "_"))
            if mapped is not None:
                return mapped
    return FLOPOANN + "SeasonContext"


def _canonical_season(context: dict[str, Any]) -> dict[str, Any]:
    geographic = _geographic_iri(context.get("geographic_context"))
    hemisphere = str(context.get("hemisphere", "") or "").strip().lower()
    if hemisphere and hemisphere != "unspecified":
        hemisphere = _geographic_iri(f"{hemisphere} hemisphere") or ""
    else:
        hemisphere = ""
    return {
        "term": _season_term_iri(context.get("season_term")),
        "start_month": (
            int(context["start_month"]) if context.get("start_month") is not None else None
        ),
        "end_month": (
            int(context["end_month"]) if context.get("end_month") is not None else None
        ),
        "geographic_context": geographic or None,
        "hemisphere_context": hemisphere or None,
        "property": (
            OBO + "RO_0002092"
            if (context.get("temporal_relation", "present_during") or "present_during")
            == "happens_during"
            else FLOPOANN + "present_during"
        ),
    }


def _canonical_developmental_stage(context: dict[str, Any]) -> dict[str, str]:
    """Canonicalize the logical part of a PO developmental-stage context.

    Verbatim cue text and character offsets are provenance and therefore deliberately do not
    participate in FAC identity.
    """

    term = canonical_iri(context.get("stage_term"))
    if not term.startswith((OBO + "PO_", OBO + "FLOPO_")):
        raise ValueError(
            "developmental stage must be a PO class or reviewed FLOPO-local PO extension: "
            f"{context.get('stage_term')!r}"
        )
    relation = str(context.get("temporal_relation", "present_during") or "present_during")
    if relation != "present_during":
        raise ValueError(f"unsupported developmental-stage relation: {relation!r}")
    return {
        "term": term,
        "property": FLOPOANN + "present_during_developmental_stage",
    }


def annotation_class_signature(assertion: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical logical signature of an assertion's phenotype class expression."""

    low = _decimal_token(assertion.get("value_low"))
    high = _decimal_token(assertion.get("value_high"))
    numeric = low is not None or high is not None
    values = sorted(
        {
            canonical_iri(value)
            for value in (
                assertion.get("value_terms", [])
                or assertion.get("value_term_ids", [])
                or []
            )
        }
    )
    operator = str(assertion.get("value_operator", "atomic") or "atomic")
    if numeric:
        quality: dict[str, Any] = {
            "kind": "numeric",
            "attribute": canonical_iri(assertion.get("pato_id")),
            "lower_inclusive": low,
            "upper_inclusive": high,
            "unit": canonical_unit_iri(assertion.get("unit")),
        }
        # The historical numeric signature encodes inclusive bounds implicitly. To keep every
        # pre-existing numeric FAC identity byte-for-byte stable, a strict bound is recorded with
        # an additive marker present only when the bound is exclusive; an inclusive bound is
        # unchanged and a strict bound therefore mints a distinct FAC IRI.
        if low is not None and not bool(assertion.get("value_low_inclusive", True)):
            quality["lower_bound_exclusive"] = True
        if high is not None and not bool(assertion.get("value_high_inclusive", True)):
            quality["upper_bound_exclusive"] = True
    elif values:
        if operator == "atomic" and len(values) != 1:
            raise ValueError("atomic phenotype class has multiple categorical values")
        if operator in {"one_of", "all_of"} and len(values) < 2:
            raise ValueError(f"{operator} phenotype class has fewer than two values")
        if operator not in {"atomic", "one_of", "all_of"}:
            raise ValueError(f"unsupported categorical value operator: {operator!r}")
        quality = {"kind": operator, "terms": values}
    else:
        quality = {
            "kind": "atomic",
            "terms": [canonical_iri(assertion.get("pato_id"))],
        }

    bearer_context_qualities = sorted(
        {
            canonical_iri(value)
            for value in (assertion.get("bearer_context_qualities", []) or [])
        }
    )
    for context_quality in bearer_context_qualities:
        if not context_quality.startswith(OBO + "PATO_"):
            raise ValueError(
                "bearer context quality must be a PATO class: "
                f"{context_quality!r}"
            )
    primary_quality_terms = set(quality.get("terms", []))
    duplicated = primary_quality_terms.intersection(bearer_context_qualities)
    if duplicated:
        raise ValueError(
            "bearer context quality duplicates the primary categorical quality: "
            f"{sorted(duplicated)!r}"
        )

    season_operator = str(assertion.get("season_operator", "atomic") or "atomic")
    if season_operator not in {"atomic", "one_of", "all_of"}:
        raise ValueError(f"unsupported season operator: {season_operator!r}")
    grouped_seasons: dict[str, list[dict[str, Any]]] = {}
    for row in assertion.get("season_contexts", []) or []:
        season = _canonical_season(row)
        grouped_seasons.setdefault(season.pop("property"), []).append(season)
    season_restrictions = []
    for prop, rows in sorted(grouped_seasons.items()):
        unique = {
            json.dumps(row, sort_keys=True, separators=(",", ":")): row for row in rows
        }
        ordered = [unique[key] for key in sorted(unique)]
        season_restrictions.append(
            {
                "property": prop,
                "kind": "one_of" if season_operator == "one_of" and len(ordered) > 1 else "all_of",
                "fillers": ordered,
            }
        )

    stage_operator = str(assertion.get("developmental_stage_operator", "atomic") or "atomic")
    if stage_operator not in {"atomic", "one_of", "all_of"}:
        raise ValueError(f"unsupported developmental-stage operator: {stage_operator!r}")
    grouped_stages: dict[str, list[dict[str, str]]] = {}
    for row in assertion.get("developmental_stage_contexts", []) or []:
        stage = _canonical_developmental_stage(row)
        grouped_stages.setdefault(stage.pop("property"), []).append(stage)
    stage_restrictions = []
    for prop, rows in sorted(grouped_stages.items()):
        unique = {
            json.dumps(row, sort_keys=True, separators=(",", ":")): row for row in rows
        }
        ordered = [unique[key] for key in sorted(unique)]
        stage_restrictions.append(
            {
                "property": prop,
                "kind": (
                    "one_of"
                    if stage_operator == "one_of" and len(ordered) > 1
                    else "all_of"
                ),
                "fillers": ordered,
            }
        )

    negated = bool(assertion.get("negated", False))
    negation_scope = str(assertion.get("negation_scope", "") or "").strip()
    if negated:
        # Legacy negated assertions compiled as complement-of the complete EQ expression.  Keep
        # that direct API behaviour while requiring new materialized data to state scope through
        # the schema/data-model validator.
        negation_scope = negation_scope or "absence"
        if negation_scope not in {"quality", "absence"}:
            raise ValueError(f"unsupported negation scope: {negation_scope!r}")
    elif negation_scope:
        raise ValueError("negation_scope is present while negated is false")

    signature = {
        "signature_version": SIGNATURE_VERSION,
        "phenotype_root": SIO + "SIO_010056",
        "bearer": canonical_iri(assertion.get("po_id")),
        "quality": quality,
        "negated": negated,
        "season_restrictions": season_restrictions,
    }
    # This is an additive optional grammar feature under signature v1.  Omitting the key for
    # the empty case preserves every pre-context FAC identity byte-for-byte.
    if bearer_context_qualities:
        signature["bearer_context_qualities"] = bearer_context_qualities
    if stage_restrictions:
        signature["developmental_stage_restrictions"] = stage_restrictions
    if negated:
        signature["negation_scope"] = negation_scope
    return signature


def canonical_signature_json(assertion: dict[str, Any]) -> str:
    return json.dumps(
        annotation_class_signature(assertion),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def annotation_class_digest(assertion: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_signature_json(assertion).encode("utf-8")).hexdigest()


def annotation_class_iri(assertion: dict[str, Any]) -> str:
    """Mint a stable non-FLOPO IRI for the assertion's OWL class expression."""

    return ANNOTATION_CLASS_BASE + "FAC_" + annotation_class_digest(assertion)[:32]


def ensure_annotation_class_iri(assertion: dict[str, Any]) -> str:
    """Set and verify the authoritative annotation-class link on an assertion."""

    expected = annotation_class_iri(assertion)
    existing = str(assertion.get("phenotype_class_iri", "") or "").strip()
    if existing and existing != expected:
        raise ValueError(
            "phenotype_class_iri does not match the canonical OWL class expression: "
            f"stored={existing!r}, expected={expected!r}"
        )
    assertion["phenotype_class_iri"] = expected
    return expected
