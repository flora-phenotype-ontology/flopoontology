"""Gazetteer join: turn place names/codes into GeoSPARQL features.

Reference tables (``flopo2/geo/data``) are built offline from pinned GeoNames and Wikidata
extracts (see ``scratchpad/geo-occurrence-20260918/build_reference_tables.py``):

* ``countries.tsv`` -- ISO 3166-1 -> GeoNames country feature, Wikidata item, point.
* ``sa_regions.tsv`` -- ISO 3166-2 (Saudi ADM1) -> GeoNames ADM1 feature, Wikidata item, point.
* ``continents.tsv`` -- GeoNames ``L.CONT`` features.
* ``place_aliases.tsv`` -- curated French/English/historical names -> country or continent.

No network access happens here.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from flopo2.geo.models import Geometry, Place, geonames_iri, local_feature_iri, point_wkt
from flopo2.geo.vocab import WD

DATA = Path(__file__).resolve().parent / "data"
REFERENCE_VERSION = "flopo-geo-reference-2026-09-18"


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        lines = [ln for ln in fh if not ln.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def normalize_name(text: str) -> str:
    """Case-fold, strip diacritics/dots, unify hyphens and apostrophes, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("’", "'").replace("`", "'").replace(".", "")
    text = re.sub(r"\s*'\s*", "'", text)
    text = re.sub(r"[-‐–—]", " ", text)
    return " ".join(text.split()).strip(" ,;:")


@dataclass(frozen=True)
class RefFeature:
    kind: str  # country | admin1 | continent
    code: str  # ISO2 / ISO 3166-2 / continent code
    label: str
    geonames_id: str
    geonames_feature_code: str
    wikidata_id: str
    lat: str
    lon: str
    country_code: str = ""
    within: tuple[str, ...] = field(default_factory=tuple)

    def place(self, *, names: dict[str, str] | None = None) -> Place:
        geometry = None
        if self.lat and self.lon:
            src = "wikidata" if self.kind == "country" else "geonames"
            geometry = Geometry(wkt=point_wkt(self.lat, self.lon), source=src)
        return Place(
            feature_iri=geonames_iri(self.geonames_id),
            label=self.label,
            feature_type={"admin1": "admin1"}.get(self.kind, self.kind),
            resolved=True,
            geonames_id=self.geonames_id,
            geonames_feature_code=self.geonames_feature_code,
            wikidata_id=self.wikidata_id,
            same_as=[WD + self.wikidata_id] if self.wikidata_id else [],
            country_code=self.country_code,
            iso_3166_2=self.code if self.kind == "admin1" else "",
            admin1_iso_3166_2=self.code if self.kind == "admin1" else "",
            within=list(self.within),
            geometry=geometry,
            gazetteer=REFERENCE_VERSION,
            resolution_confidence="high",
            names=names or {},
        )


@lru_cache(maxsize=1)
def continents() -> dict[str, RefFeature]:
    return {
        r["continent"]: RefFeature(
            "continent",
            r["continent"],
            r["name_en"],
            r["geonames_id"],
            "L.CONT",
            r["wikidata_id"],
            r["lat"],
            r["lon"],
        )
        for r in _read_tsv(DATA / "continents.tsv")
    }


@lru_cache(maxsize=1)
def countries() -> dict[str, RefFeature]:
    conts = continents()
    out = {}
    for r in _read_tsv(DATA / "countries.tsv"):
        cont = conts.get(r["continent"])
        out[r["iso2"]] = RefFeature(
            "country",
            r["iso2"],
            r["name_en"],
            r["geonames_id"],
            "A.PCLI",
            r["wikidata_id"],
            r["lat"],
            r["lon"],
            country_code=r["iso2"],
            within=(geonames_iri(cont.geonames_id),) if cont else (),
        )
    return out


@lru_cache(maxsize=1)
def sa_regions() -> dict[str, RefFeature]:
    sa = countries()["SA"]
    return {
        r["iso_3166_2"]: RefFeature(
            "admin1",
            r["iso_3166_2"],
            r["geonames_name"],
            r["geonames_id"],
            r["geonames_feature_code"],
            r["wikidata_id"],
            r["lat"],
            r["lon"],
            country_code="SA",
            within=(geonames_iri(sa.geonames_id),),
        )
        for r in _read_tsv(DATA / "sa_regions.tsv")
    }


@lru_cache(maxsize=1)
def aliases() -> dict[str, tuple[str, str]]:
    """normalised name -> (kind, code); curated rows win over automatic English names."""
    out: dict[str, tuple[str, str]] = {}
    for iso2, ref in countries().items():
        out.setdefault(normalize_name(ref.label), ("country", iso2))
    for code, ref in continents().items():
        out.setdefault(normalize_name(ref.label), ("continent", code))
    for r in _read_tsv(DATA / "place_aliases.tsv"):
        out[normalize_name(r["alias"])] = (r["kind"], r["code"])
    return out


def resolve_name(
    name: str, allowed_kinds: tuple[str, ...] = ("country", "continent")
) -> RefFeature | None:
    hit = aliases().get(normalize_name(name))
    if not hit or hit[0] not in allowed_kinds:
        return None
    kind, code = hit
    return (countries() if kind == "country" else continents()).get(code)


# --- FlorML region/island/province table -----------------------------------------------------
# Malesian regions and islands and Central African provinces that are not a country or continent
# (``data/florml_regions.tsv``), each pinned to a GeoNames feature or, failing that, a Wikidata
# item or a documented local note (see the file's header for how each row was resolved).


@lru_cache(maxsize=1)
def florml_regions() -> dict[str, dict[str, str]]:
    return {normalize_name(r["alias"]): r for r in _read_tsv(DATA / "florml_regions.tsv")}


def resolve_florml_region(label: str) -> Place | None:
    """Look up a FlorML place label in ``florml_regions.tsv``.

    GeoNames id present -> the GeoNames feature (resolved). Otherwise a Wikidata QID -> a local
    feature with ``skos:exactMatch``. Neither -> a local feature carrying the row's note only (a
    historical/floristic term such as "Oubangui" with no single matching gazetteer entry).
    """
    row = florml_regions().get(normalize_name(label))
    if row is None:
        return None
    gid = row.get("geonames_id", "").strip()
    wid = row.get("wikidata_id", "").strip()
    country = row.get("country_code", "").strip()
    note = row.get("note", "").strip()
    within = []
    if country:
        c = countries().get(country)
        if c:
            within = [geonames_iri(c.geonames_id)]
    geometry = None
    if row.get("lat") and row.get("lon"):
        geometry = Geometry(
            wkt=point_wkt(row["lat"], row["lon"]), source="geonames" if gid else "wikidata"
        )
    common = dict(
        label=row["alias"],
        feature_type=row["kind"],
        country_code=country,
        within=within,
        geometry=geometry,
        gazetteer="flopo2/geo/data/florml_regions.tsv" + (f" ({note})" if note else ""),
        names={},
    )
    if gid:
        return Place(
            feature_iri=geonames_iri(gid),
            resolved=True,
            geonames_id=gid,
            geonames_feature_code=row.get("geonames_feature_code", ""),
            wikidata_id=wid,
            same_as=[WD + wid] if wid else [],
            resolution_confidence="high",
            **common,
        )
    if wid:
        return Place(
            feature_iri=local_feature_iri("florml-region", row["alias"]),
            resolved=False,
            same_as=[WD + wid],
            resolution_confidence="medium",
            **common,
        )
    return Place(
        feature_iri=local_feature_iri("florml-region", row["alias"]),
        resolved=False,
        resolution_confidence="",
        **common,
    )


# --- NCVC gazetteer ---------------------------------------------------------------------------

NCVC_FEATURE_TYPES = {
    "governorate": "governorate",
    "city": "city",
    "town": "town",
    "village": "village",
    "mountain": "mountain",
    "wadi": "wadi",
    "natural_region": "natural_region",
    "desert": "desert",
    "island": "island",
    "coast": "coast",
    "plateau": "plateau",
    "harrah": "harrah",
    "other": "other",
    "": "locality",
}
_RELATIVE = re.compile(r"relative/sub-locality|\banchor\b", re.I)


def is_relative_locality(notes: str) -> bool:
    """Gazetteer rows whose IDs/coordinates are those of an anchor, not of the place itself."""
    return bool(_RELATIVE.search(notes or ""))


def ncvc_place(row: dict[str, str], scope: str = "ncvc-saudi-gazetteer") -> Place:
    """Build the feature for one row of ``local-corpora/saudi-ncvc-guide/gazetteer.tsv``.

    * GeoNames id and not relative -> the GeoNames feature itself (resolved).
    * relative ("10 km E of Jeddah") -> local feature; the GeoNames/Wikidata ids become anchors
      and the anchor point is kept as an approximate geometry.
    * Wikidata only -> local feature ``skos:exactMatch`` the Wikidata item.
    * nothing -> local feature with name and type only.

    ``geo:sfWithin`` the ADM1 region is asserted from the gazetteer admin1 code for non-relative
    features only (a relative locality may lie across a boundary from its anchor).
    """
    label = row.get("name_en_canonical") or row.get("locality_key", "")
    gid = (row.get("geonames_id") or "").strip()
    qid = (row.get("wikidata_qid") or "").strip()
    relative = is_relative_locality(row.get("notes", ""))
    admin1 = (row.get("admin1_iso_3166_2") or "").strip()
    region = sa_regions().get(admin1)
    geometry = None
    if row.get("lat") and row.get("lon"):
        src = "geonames" if gid else "wikidata"
        geometry = Geometry(
            wkt=point_wkt(row["lat"], row["lon"]),
            source=src,
            anchor_note="coordinates of the anchor feature" if relative else "",
        )
    names = {"ar": row["verbatim_ar"]} if row.get("verbatim_ar") else {}
    common = dict(
        label=label,
        feature_type=NCVC_FEATURE_TYPES.get(row.get("feature_type", ""), "other"),
        wikidata_id="" if relative else qid,
        country_code="SA" if admin1 else "",
        admin1_iso_3166_2=admin1 if region else "",
        geometry=geometry,
        gazetteer="ncvc-saudi-guide/gazetteer.tsv (GeoNames+Wikidata, 2026-09)",
        resolution_confidence=row.get("confidence", ""),
        names=names,
    )
    within = [geonames_iri(region.geonames_id)] if region and not relative else []
    if gid and not relative:
        return Place(
            feature_iri=geonames_iri(gid),
            resolved=True,
            geonames_id=gid,
            same_as=[WD + qid] if qid else [],
            within=within,
            **common,
        )
    anchors = []
    if relative:
        anchors = [geonames_iri(gid)] if gid else []
        anchors += [WD + qid] if qid else []
    return Place(
        feature_iri=local_feature_iri(scope, row.get("locality_key") or label),
        resolved=False,
        same_as=[WD + qid] if qid and not relative else [],
        anchor_iris=anchors,
        within=within,
        **common,
    )


def load_ncvc_gazetteer(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["locality_key"]: r for r in csv.DictReader(fh, delimiter="\t")}
