"""Occurrence assertions from FlorML ``<distributionLocality>`` elements.

FlorML (Flore du Gabon, Flora Malesiana) marks up places inside ``<feature class="distribution">``
with ``class`` (world / continent / continental region / country / region / province / locality
...) and optional ``status``, ``frequency``, ``doubtful`` and ``extra`` attributes.  Each element
becomes one :class:`OccurrenceAssertion`; the statement is the sentence that contains it and the
place offsets are exact offsets into that sentence.

Place resolution is offline: countries and continents resolve to GeoNames features through the
curated alias table (``data/place_aliases.tsv``) plus English GeoNames country names; directional
or parenthetical qualifiers ("Nord-Ouest du Gabon", "S Nigeria", "Afrique centrale",
"Philippines (Luzon)") become local features ``geo:sfWithin`` the resolved country/continent.
Everything else stays a FLOPO-minted local feature.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from flopo2.geo.gazetteer import RefFeature, normalize_name, resolve_florml_region, resolve_name
from flopo2.geo.models import (
    OccurrenceAssertion,
    Place,
    geonames_iri,
    local_feature_iri,
    occurrence_id,
    statement_id,
)
from flopo2.ingest.florml import _accepted_taxon, _fill_context, _parse_tree

EXTRACTOR = "flopo2.geo.florml/0.1"

CLASS_TO_TYPE = {
    "world": "world",
    "continent": "continent",
    "continental region": "continental_region",
    "oceanic region": "oceanic_region",
    "country": "country",
    "locality": "locality",
    "other": "other",
}  # region, province, district, department, state, subprovince, territory ... -> region

_STATUS = {
    "endemic": dict(occurrence_status="present", establishment_means="native", endemic=True),
    "native": dict(occurrence_status="present", establishment_means="native"),
    "introduced": dict(occurrence_status="present", establishment_means="introduced"),
    "naturalized": dict(occurrence_status="present", establishment_means="naturalised"),
    "cultivated": dict(occurrence_status="present", establishment_means="cultivated"),
    "expected": dict(occurrence_status="expected"),
    "possible": dict(occurrence_status="doubtful", epistemic_modality="possible"),
    "absent": dict(occurrence_status="absent"),
    "extinct": dict(occurrence_status="extinct"),
}
_FREQUENCY = {
    "rare": "rare",
    "uncommon": "occasional",
    "common": "common",
    "widespread": "widespread",
    "extensive": "widespread",
}

_DOUBT = re.compile(r"^\s*(\(\?\)|\?)\s*|\s*(\(\?\)|\?)\s*$")
_ARTICLE = re.compile(r"^(?:(?:the|la|le|les)\s+|l')")
_PREFIX_EN = re.compile(
    r"^(throughout (?:the )?|(?:n|s|e|w|ne|nw|se|sw|c|north|south|east|west|northern|southern|"
    r"eastern|western|central|peninsular|lower|upper|tropical|continental|"
    r"north eastern|south eastern|north western|south western|northeastern|southeastern|"
    r"northwestern|southwestern)\s+)(.+)$"
)
_PREFIX_FR = re.compile(
    r"^(?:(?:nord|sud|est|ouest|centre|bas|haut)(?: (?:nord|sud|est|ouest))?)\s+"
    r"(?:du|des|de la|de l'|de|d'|au)?\s*(.+)$"
)
_SUFFIX = re.compile(
    r"^(.+?)\s+(?:orientale?|occidentale?|meridionale?|septentrionale?|centrale?|tropicale?|"
    r"australe|intertropicale|equatoriale|continentale|subtropicale|"
    r"du sud|du nord|de l'est|de l'ouest|\([^)]*\))$"
)
_SENT = re.compile(r"(?<=[.;!?])\s+(?=[A-ZÀ-ÖØ-Þ0-9(])")


@dataclass
class _Mention:
    element: etree._Element
    start: int
    end: int


def _flatten(feature: etree._Element) -> tuple[str, list[_Mention]]:
    """Whitespace-normalised text of a feature with exact spans of its distributionLocality."""
    chars: list[str] = []
    marks: list[tuple[etree._Element, int, int]] = []

    def walk(el: etree._Element) -> None:
        if el.tag in {"br", "li", "p", "tr", "td"}:
            chars.append(" ")
        start = len(chars)
        if el.text and el.tag not in {"footnoteRef", "num"}:
            chars.extend(el.text)
        for child in el:
            walk(child)
            if child.tail:
                chars.extend(child.tail)
        if el.tag == "distributionLocality":
            marks.append((el, start, len(chars)))

    for child in feature:
        walk(child)
        if child.tail:
            chars.extend(child.tail)
    raw = "".join(chars)
    # collapse whitespace keeping an old->new index map
    new: list[str] = []
    index = [0] * (len(raw) + 1)
    for i, ch in enumerate(raw):
        index[i] = len(new)
        if ch.isspace():
            if new and new[-1] != " ":
                new.append(" ")
        else:
            new.append(ch)
    index[len(raw)] = len(new)
    text = "".join(new)
    mentions = []
    for el, s, e in marks:
        ns, ne = index[s], index[e]
        while ns < ne and text[ns] == " ":
            ns += 1
        while ne > ns and text[ne - 1] == " ":
            ne -= 1
        if ne > ns:
            mentions.append(_Mention(el, ns, ne))
    return text, mentions


def _sentences(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENT.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return spans


def _strip_markers(label: str) -> tuple[str, bool]:
    doubtful = bool(_DOUBT.search(label))
    clean = _DOUBT.sub("", label).strip(" .,;:")
    return clean, doubtful


def _parent_of(name: str) -> RefFeature | None:
    """Resolve the country/continent inside a qualified name ("S Nigeria", "Afrique centrale")."""
    norm = _ARTICLE.sub("", normalize_name(name))
    for rx in (_PREFIX_FR, _PREFIX_EN):
        m = rx.match(norm)
        if m:
            inner = _ARTICLE.sub("", m.group(m.lastindex))
            ref = resolve_name(inner)
            if ref:
                return ref
    m = _SUFFIX.match(norm)
    if m:
        return resolve_name(_ARTICLE.sub("", m.group(1)))
    return None


def resolve_florml_place(label: str, cls: str, flora: str) -> tuple[Place, list[str]]:
    """Map one element to a Place; returns (place, mapping notes)."""
    ftype = CLASS_TO_TYPE.get(cls, "region")
    notes: list[str] = []
    if cls not in {"world", "oceanic region"}:
        kinds = ("continent",) if cls in {"continent", "continental region"} else ("country",)
        ref = resolve_name(_ARTICLE.sub("", normalize_name(label)), kinds)
        if ref is None and cls not in {"continent", "continental region"}:
            ref = resolve_name(_ARTICLE.sub("", normalize_name(label)), ("country",))
        if ref is not None:
            if ref.kind == "country" and cls != "country":
                notes.append(f"FlorML class={cls!r} resolved to country {ref.code}")
            place = ref.place()
            place.names = {"verbatim": label}
            return place, notes
    region_place = resolve_florml_region(label)
    if region_place is not None:
        region_place.names = {"verbatim": label}
        notes.append(
            f"resolved via flopo2/geo/data/florml_regions.tsv (feature_type={region_place.feature_type})"
        )
        return region_place, notes
    parent = _parent_of(label) if cls not in {"world"} else None
    place = Place(
        feature_iri=local_feature_iri(f"florml|{flora}|{ftype}", label),
        label=label,
        feature_type=ftype,
        resolved=False,
        country_code=parent.country_code if parent and parent.kind == "country" else "",
        within=[geonames_iri(parent.geonames_id)] if parent else [],
        gazetteer="flopo2/geo/data/place_aliases.tsv (qualifier parse)" if parent else "",
        names={},
    )
    if parent:
        notes.append(f"qualified name: local feature geo:sfWithin {parent.kind} {parent.code}")
    return place, notes


def _taxa_by_element(root: etree._Element) -> dict[etree._Element, object]:
    out = {}
    last_family = last_genus = ""
    for taxon_el in root.iter("taxon"):
        taxon = _accepted_taxon(taxon_el)
        if taxon.family:
            last_family, last_genus = taxon.family, ""
        if taxon.genus:
            last_genus = taxon.genus
        out[taxon_el] = _fill_context(taxon, last_family, last_genus)
    return out


def iter_file(path: Path, source: str | None = None) -> Iterator[OccurrenceAssertion]:
    tree = _parse_tree(path)
    root = tree.getroot()
    language = (root.get("lang") or "en").split("-")[0].lower()
    source = source or path.parent.name
    taxa = _taxa_by_element(root)
    for feature in root.iter("feature"):
        if feature.get("class") != "distribution":
            continue
        taxon_el = next((a for a in feature.iterancestors("taxon")), None)
        if taxon_el is None:
            continue
        taxon = taxa[taxon_el]
        text, mentions = _flatten(feature)
        sentences = _sentences(text)
        source_id = f"{path.name}#{taxon_el.getroottree().getpath(feature)}"
        for m in mentions:
            s0, s1 = next((a, b) for a, b in sentences if a <= m.start < b or b == len(text))
            s1 = max(s1, m.end)
            sentence = text[s0:s1]
            sid = statement_id(source, source_id, f"{s0}:{s1}", sentence)
            label_raw = text[m.start : m.end]
            label, doubtful_marker = _strip_markers(label_raw)
            cls = (m.element.get("class") or "other").strip()
            place, notes = resolve_florml_place(label or label_raw, cls, source)
            fields: dict = dict(occurrence_status="present", establishment_means="unspecified")
            status_bits = []
            status = (m.element.get("status") or "").strip()
            if status:
                fields.update(_STATUS.get(status, {}))
                status_bits.append(f"status={status}")
                if status not in _STATUS:
                    notes.append(f"unmapped status {status!r}")
            freq = (m.element.get("frequency") or "").strip()
            if freq:
                status_bits.append(f"frequency={freq}")
                if freq == "absent":
                    fields["occurrence_status"] = "absent"
                    fields["establishment_means"] = "unspecified"
                elif freq in _FREQUENCY:
                    fields["abundance"] = _FREQUENCY[freq]
                else:
                    notes.append(f"unmapped frequency {freq!r}")
            if (m.element.get("doubtful") or "").lower() == "true" or doubtful_marker:
                status_bits.append("doubtful=true" if not doubtful_marker else "'?' marker")
                if fields["occurrence_status"] == "present":
                    fields["occurrence_status"] = "doubtful"
                fields.setdefault("epistemic_modality", "uncertain")
            if (m.element.get("extra") or "").lower() == "true":
                fields["extralimital"] = True
                status_bits.append("extra=true")
            start, end = m.start - s0, m.end - s0
            occ_id = occurrence_id(
                source, source_id, sid, taxon.name_string, place.feature_iri, "stated", start
            )
            yield OccurrenceAssertion(
                occurrence_id=occ_id,
                source=source,
                source_id=source_id,
                source_statement_id=sid,
                statement_text=sentence,
                statement_language=language,
                taxon_name=taxon.name_string,
                taxon_rank=taxon.rank,
                taxon_family=taxon.family,
                place=place,
                place_text=label_raw,
                place_start=start,
                place_end=end,
                basis="stated",
                status_text="; ".join(status_bits),
                status_source="FlorML distributionLocality attributes" if status_bits else "",
                extractor=EXTRACTOR,
                mapping_notes=[f"FlorML class={cls}"] + notes,
                **fields,
            )


def iter_dirs(dirs: list[Path]) -> Iterator[OccurrenceAssertion]:
    for d in dirs:
        for path in sorted(d.glob("*.xml")):
            yield from iter_file(path, source=d.name)
