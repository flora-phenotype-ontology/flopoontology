"""Wire models for taxon occurrence assertions whose place is a GeoSPARQL ``geo:Feature``.

One :class:`OccurrenceAssertion` is one JSONL line.  It inlines its :class:`Place` so every
record is self-contained (the corpus-record style of ``*-annotated.jsonl``); the RDF and SQL
exports de-duplicate places by ``feature_iri``.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from flopo2.geo import vocab

Basis = Literal["stated", "inferred", "gazetteer"]
OccurrenceStatus = Literal["present", "absent", "doubtful", "expected", "excluded", "extinct"]
EstablishmentMeans = Literal[
    "native", "introduced", "naturalised", "cultivated", "uncertain", "unspecified"
]
Abundance = Literal["rare", "occasional", "common", "widespread", "unspecified"]
EpistemicModality = Literal["asserted", "probable", "possible", "uncertain", "reported"]

_ISO2 = re.compile(r"^[A-Z]{2}$")
_ISO3166_2 = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")
_QID = re.compile(r"^Q[1-9][0-9]*$")
_GEONAMES = re.compile(r"^[1-9][0-9]*$")
_WKT_POINT = re.compile(r"^POINT \(-?\d+(\.\d+)? -?\d+(\.\d+)?\)$")


def digest(*parts: object, n: int = 24) -> str:
    payload = json.dumps([str(p) for p in parts], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:n]


def geonames_iri(geonames_id: str) -> str:
    return f"{vocab.GN_FEATURE}{geonames_id}/"


def local_feature_iri(scope: str, label: str) -> str:
    """FLOPO-minted feature IRI: digest of the gazetteer scope and the normalised label.

    Mirrors ``flopo2.owl.annotation_class._geographic_iri`` (SHA-256, 20 hex characters, same
    base) but hashes ``scope|label`` so identical names from unrelated gazetteers do not merge.
    """
    key = f"{scope}|{' '.join(label.split()).lower()}"
    return vocab.GEOGRAPHIC_CONTEXT + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


class Geometry(BaseModel):
    """A ``geo:Geometry`` with a WKT serialisation (CRS84 longitude-latitude order)."""

    model_config = ConfigDict(extra="forbid")

    wkt: str
    source: str = Field(description="geonames | wikidata | gazetteer: where coordinates came from")
    anchor_note: str = ""

    @field_validator("wkt")
    @classmethod
    def _point(cls, v: str) -> str:
        if not _WKT_POINT.match(v):
            raise ValueError(f"only WKT POINT geometries are emitted, got {v!r}")
        lon, lat = (float(x) for x in v[7:-1].split())
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError(f"coordinates out of range: {v!r}")
        return v

    @property
    def lon_lat(self) -> tuple[float, float]:
        lon, lat = (float(x) for x in self.wkt[7:-1].split())
        return lon, lat


def _num(x: float | str) -> str:
    return f"{float(x):.6f}".rstrip("0").rstrip(".")


def point_wkt(lat: float | str, lon: float | str) -> str:
    return f"POINT ({_num(lon)} {_num(lat)})"


class Place(BaseModel):
    """A ``geo:Feature``: GeoNames feature when resolved, else a FLOPO-minted local feature."""

    model_config = ConfigDict(extra="forbid")

    feature_iri: str
    label: str
    feature_type: str
    resolved: bool = Field(description="True when feature_iri is a GeoNames feature IRI")
    geonames_id: str = ""
    geonames_feature_code: str = ""  # e.g. A.ADM1 (GeoNames class.code)
    wikidata_id: str = ""
    country_code: str = ""  # ISO 3166-1 alpha-2
    iso_3166_2: str = ""  # only for first-level subdivisions
    admin1_iso_3166_2: str = ""  # containing ADM1 per the gazetteer (GeoNames admin1 code)
    anchor_iris: list[str] = Field(
        default_factory=list,
        description="GeoNames/Wikidata IRIs of the anchor of a relative locality (10 km E of X)",
    )
    same_as: list[str] = Field(default_factory=list, description="exact-match IRIs (Wikidata)")
    within: list[str] = Field(default_factory=list, description="geo:sfWithin feature IRIs")
    geometry: Geometry | None = None
    gazetteer: str = ""  # gazetteer/table + version that resolved the place
    resolution_confidence: str = ""
    names: dict[str, str] = Field(default_factory=dict)  # language tag -> name (e.g. ar)

    @field_validator("country_code")
    @classmethod
    def _cc(cls, v: str) -> str:
        if v and not _ISO2.match(v):
            raise ValueError(f"bad ISO 3166-1 alpha-2 code {v!r}")
        return v

    @field_validator("iso_3166_2", "admin1_iso_3166_2")
    @classmethod
    def _iso2(cls, v: str) -> str:
        if v and not _ISO3166_2.match(v):
            raise ValueError(f"bad ISO 3166-2 code {v!r}")
        return v

    @field_validator("wikidata_id")
    @classmethod
    def _qid(cls, v: str) -> str:
        if v and not _QID.match(v):
            raise ValueError(f"bad Wikidata QID {v!r}")
        return v

    @field_validator("feature_type")
    @classmethod
    def _ftype(cls, v: str) -> str:
        if v not in vocab.FEATURE_TYPES:
            raise ValueError(f"unknown feature_type {v!r}")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> Place:
        if self.geonames_id and not _GEONAMES.match(self.geonames_id):
            raise ValueError(f"bad GeoNames id {self.geonames_id!r}")
        if self.resolved != (self.feature_iri == geonames_iri(self.geonames_id or "x")):
            raise ValueError("resolved places must use the GeoNames feature IRI and vice versa")
        if not self.resolved and not self.feature_iri.startswith(vocab.GEOGRAPHIC_CONTEXT):
            raise ValueError("unresolved places must use a FLOPO geographic-context IRI")
        if (
            self.iso_3166_2
            and self.country_code
            and not self.iso_3166_2.startswith(self.country_code + "-")
        ):
            raise ValueError("iso_3166_2 prefix does not match country_code")
        return self


class OccurrenceAssertion(BaseModel):
    """Taxon -- place -- status assertion extracted from one source statement."""

    model_config = ConfigDict(extra="forbid")

    occurrence_id: str
    source: str
    source_id: str
    source_statement_id: str
    statement_text: str
    statement_language: str = ""
    taxon_name: str
    taxon_rank: str = ""
    taxon_family: str = ""
    taxon_id: str = ""  # WFO / POWO / GBIF id when resolved
    place: Place
    place_text: str = ""  # verbatim place mention (any script); empty only for inferred places
    place_start: int | None = None
    place_end: int | None = None
    stated_region: str = ""  # ISO 3166-2 region the text attaches the place to
    stated_region_basis: Literal["", "stated", "inferred"] = ""
    basis: Basis
    occurrence_status: OccurrenceStatus = "present"
    establishment_means: EstablishmentMeans = "unspecified"
    endemic: bool = False
    extralimital: bool = False
    abundance: Abundance = "unspecified"
    epistemic_modality: EpistemicModality = "asserted"
    status_text: str = ""
    status_source: str = ""  # where status_text came from (attribute, field, ...)
    conflict: bool = False
    conflict_note: str = ""
    derived_from: list[str] = Field(default_factory=list)  # occurrence_ids (gazetteer basis)
    extractor: str
    mapping_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _spans(self) -> OccurrenceAssertion:
        if self.place_start is not None or self.place_end is not None:
            if self.place_start is None or self.place_end is None:
                raise ValueError("place_start/place_end must be given together")
            if self.statement_text[self.place_start : self.place_end] != self.place_text:
                raise ValueError(
                    f"{self.occurrence_id}: place_text is not verbatim at the given offsets"
                )
        if self.basis == "gazetteer" and not self.derived_from:
            raise ValueError(
                "gazetteer-basis occurrences must name the occurrences they derive from"
            )
        if self.occurrence_status in {"absent", "extinct"} and self.establishment_means in {
            "native",
            "introduced",
            "naturalised",
        }:
            raise ValueError("absent occurrence with a positive establishment means")
        return self

    @property
    def iri(self) -> str:
        return vocab.FLOPO_OCCURRENCE + self.occurrence_id


def validation_issues(occ: OccurrenceAssertion) -> list[str]:
    """Soft checks (reported, never fatal) mirroring the E4 validator names in PROPOSAL.md."""
    issues = []
    if occ.basis == "stated" and occ.place_start is None:
        issues.append("occurrence_place_not_verbatim")
    if occ.place.resolved and not occ.place.gazetteer:
        issues.append("gazetteer_basis_without_version")
    if occ.place.geometry is not None and not occ.place.geometry.source:
        issues.append("coordinates_without_gazetteer_or_source")
    if (
        occ.stated_region
        and occ.place.admin1_iso_3166_2
        and occ.stated_region != occ.place.admin1_iso_3166_2
        and not occ.conflict
    ):
        issues.append("stated_region_admin1_mismatch_unflagged")
    if not occ.place.resolved and not (occ.place.same_as or occ.place.anchor_iris):
        issues.append("place_unresolved")
    return issues


def occurrence_id(
    source: str,
    source_id: str,
    statement_id: str,
    taxon: str,
    feature_iri: str,
    basis: str,
    start: int | None,
    discriminator: str = "",
) -> str:
    return "occ-" + digest(
        source, source_id, statement_id, taxon, feature_iri, basis, start, discriminator
    )


def statement_id(source: str, source_id: str, field: str, text: str) -> str:
    return "statement-" + digest(source, source_id, field, text)
