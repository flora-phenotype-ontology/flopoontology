"""Occurrence assertions from the NCVC Saudi native-plants guide.

Inputs: ``derived/ncvc-saudi-distribution.tsv`` (one row per taxon x region / locality),
``gazetteer.tsv`` (803 localities) and ``raw/pages-*.jsonl`` (the Arabic distribution paragraph
``ksa_distribution_ar`` is the source statement; place offsets are computed inside it).
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path

from flopo2.geo.gazetteer import ncvc_place, sa_regions
from flopo2.geo.models import OccurrenceAssertion, Place, occurrence_id, statement_id

EXTRACTOR = "flopo2.geo.ncvc/0.1"
STATEMENT_FIELD = "ksa_distribution_ar"

_ABUNDANCE = {
    "rare": "rare",
    "widespread": "widespread",
    "common": "common",
    "dense (common along coasts)": "common",
    "forms dense forests": "common",
    "occupies extensive areas": "widespread",
}


def abundance_of(text: str) -> str:
    t = (text or "").strip().lower()
    if t in _ABUNDANCE:
        return _ABUNDANCE[t]
    return "unspecified"


def load_raw_pages(raw_dir: Path) -> dict[str, dict]:
    out = {}
    for path in sorted(raw_dir.glob("pages-*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                out[f"{rec['source']}:page-{int(rec['pdf_page']):03d}"] = rec
    return out


def _taxon_id(row: dict[str, str]) -> str:
    ids = [t.strip() for t in (row.get("taxa_wfo_or_powo_id") or "").split("|") if t.strip()]
    return ids[0] if ids else ""


class _Cursor:
    """Find successive verbatim mentions in the statement (localities are listed in order)."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def find(self, needle: str) -> tuple[int, int] | None:
        if not needle:
            return None
        i = self.text.find(needle, self.pos)
        if i < 0:
            i = self.text.find(needle)  # out of order: fall back to first occurrence
            if i < 0:
                return None
        else:
            self.pos = i + len(needle)
        return i, i + len(needle)


def iter_occurrences(
    rows: Iterable[dict[str, str]],
    gazetteer: dict[str, dict[str, str]],
    raw: dict[str, dict],
) -> Iterator[OccurrenceAssertion]:
    by_page: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_page[row["source_id"]].append(row)
    regions = sa_regions()
    for source_id, page_rows in by_page.items():
        rec = raw.get(source_id, {})
        text = rec.get(STATEMENT_FIELD) or ""
        sid = statement_id(page_rows[0]["source"], source_id, STATEMENT_FIELD, text)
        abundance_text = (rec.get("abundance_en") or "").strip()
        base_notes = ["establishment_means=native from source scope (guide to native plants)"]
        region_cursor, locality_cursor = _Cursor(text), _Cursor(text)
        stated_regions: set[str] = set()
        derived: dict[str, list[str]] = defaultdict(list)
        emitted: list[OccurrenceAssertion] = []

        def make(row: dict[str, str], place: Place, **kw) -> OccurrenceAssertion:
            span = kw.pop("span", None)
            basis = kw.pop("basis")
            occ_id = occurrence_id(
                row["source"],
                source_id,
                sid,
                row["taxon"],
                place.feature_iri,
                basis,
                span[0] if span else None,
                kw.get("stated_region", ""),
            )
            return OccurrenceAssertion(
                occurrence_id=occ_id,
                source=row["source"],
                source_id=source_id,
                source_statement_id=sid,
                statement_text=text,
                statement_language="ar",
                taxon_name=row["taxon"],
                taxon_rank="species",
                taxon_family=row.get("taxa_accepted_family") or row.get("taxon_family", ""),
                taxon_id=_taxon_id(row),
                place=place,
                place_start=span[0] if span else None,
                place_end=span[1] if span else None,
                basis=basis,
                establishment_means="native",
                endemic="endemic" in abundance_text.lower(),
                abundance=abundance_of(abundance_text),
                status_text=abundance_text,
                status_source="abundance_en" if abundance_text else "",
                extractor=EXTRACTOR,
                **kw,
            )

        for row in page_rows:
            if row["level"] == "region":
                region = regions[row["iso_3166_2"]]
                place = region.place(names={"en": row["region_name"]})
                if row["basis"] == "stated_whole_kingdom":
                    occ = make(
                        row,
                        place,
                        basis="inferred",
                        place_text="",
                        mapping_notes=base_notes
                        + ["whole-kingdom statement expanded to every ADM1 region"],
                    )
                else:
                    verb = row.get("verbatim_ar", "")
                    span = region_cursor.find(verb)
                    occ = make(
                        row,
                        place,
                        basis="stated",
                        place_text=verb,
                        span=span,
                        mapping_notes=list(base_notes),
                    )
                stated_regions.add(row["iso_3166_2"])
                emitted.append(occ)
                continue
            gaz = gazetteer.get(row.get("gaz_locality_key", ""))
            if gaz is None:  # no gazetteer row: local feature from the TSV row itself
                gaz = {
                    "locality_key": f"{row.get('verbatim_ar', '')}|{row['locality_name'].lower()}",
                    "name_en_canonical": row["locality_name"],
                    "verbatim_ar": row.get("verbatim_ar", ""),
                    "feature_type": row.get("feature_type", ""),
                }
            place = ncvc_place(gaz)
            verb = row.get("verbatim_ar", "")
            span = locality_cursor.find(verb)
            stated = row.get("iso_3166_2", "")
            conflict = bool(
                stated and place.admin1_iso_3166_2 and stated != place.admin1_iso_3166_2
            )
            notes = list(base_notes)
            if (gaz.get("conflict") or "") == "yes" and not conflict:
                notes.append("gazetteer flags a region conflict on another page for this locality")
            occ = make(
                row,
                place,
                basis="stated",
                place_text=verb,
                span=span,
                stated_region=stated,
                stated_region_basis=row.get("basis", "") if stated else "",
                conflict=conflict,
                conflict_note=(
                    f"text places locality in {stated}; gazetteer ADM1 "
                    f"{'of its anchor ' if place.anchor_iris else ''}is "
                    f"{place.admin1_iso_3166_2}"
                    if conflict
                    else ""
                ),
                mapping_notes=notes,
            )
            emitted.append(occ)
            if place.within and place.admin1_iso_3166_2:
                derived[place.admin1_iso_3166_2].append(occ.occurrence_id)
        yield from emitted
        # region occurrences implied by gazetteer containment of a stated locality
        for iso, occ_ids in sorted(derived.items()):
            if iso in stated_regions:
                continue
            row = page_rows[0]
            yield make(
                row,
                regions[iso].place(),
                basis="gazetteer",
                place_text="",
                derived_from=occ_ids,
                mapping_notes=base_notes
                + ["region implied by GeoNames ADM1 of stated localities (geo:sfWithin)"],
            )


def build(corpus_dir: Path) -> list[OccurrenceAssertion]:
    with (corpus_dir / "derived" / "ncvc-saudi-distribution.tsv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    with (corpus_dir / "gazetteer.tsv").open(encoding="utf-8") as fh:
        gazetteer = {r["locality_key"]: r for r in csv.DictReader(fh, delimiter="\t")}
    raw = load_raw_pages(corpus_dir / "raw")
    return list(iter_occurrences(rows, gazetteer, raw))
