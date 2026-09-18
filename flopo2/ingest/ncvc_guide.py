"""Ingest the NCVC Saudi native-plants guide (Arabic, 2024) into FLOPO text segments.

The source PDF is a photo-heavy Arabic field guide with one species per two-page spread. It is
transcribed page by page (verbatim Arabic plus a faithful English translation) into JSONL records
described in ``local-corpora/saudi-ncvc-guide/EXTRACTION_BRIEF.md``. This module reads those
records; raw PDFs, transcriptions, and derived text stay under the git-ignored
``local-corpora/`` tree.

Three views are produced from each species record:

* :func:`iter_segments` -- one Arabic and one English ``description`` segment per species, plus a
  ``habitat`` segment when the guide describes ecological conditions;
* :func:`iter_distribution_rows` -- taxon occurrence rows by ISO 3166-2 region and named locality;
* :func:`iter_phenotype_rows` -- transcribed entity-quality statements grounded to PO/PATO only
  through exact lexicon labels or exact synonyms (never through identifiers written by the
  transcriber).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

from flopo2.ingest.models import Taxon, TextSegment

SOURCE = "ncvc-saudi-native-plants-guide-2024"

# ISO 3166-2:SA administrative regions (SA-13 is unassigned).
SAUDI_REGIONS = {
    "SA-01": "Riyadh",
    "SA-02": "Makkah",
    "SA-03": "Al Madinah",
    "SA-04": "Eastern Province",
    "SA-05": "Al Qassim",
    "SA-06": "Ha'il",
    "SA-07": "Tabuk",
    "SA-08": "Northern Borders",
    "SA-09": "Jazan",
    "SA-10": "Najran",
    "SA-11": "Al Bahah",
    "SA-12": "Al Jawf",
    "SA-14": "Asir",
}

_WS_RE = re.compile(r"\s+")
_INFRA_MARKERS = {"var.", "subsp.", "ssp.", "forma", "f."}


def _normalize(text: str | None) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def iter_records(path: Path) -> Iterator[dict]:
    """Yield species records from one JSONL file or every ``*.jsonl`` in a directory.

    Non-species pages are skipped. Records are yielded in PDF page order when reading a
    directory so segment identities are deterministic.
    """
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    records: list[dict] = []
    for file in files:
        with file.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("non_species_page") or not rec.get("scientific_name"):
                    continue
                records.append(rec)
    records.sort(key=lambda r: (int(r.get("pdf_page", 0)), r.get("scientific_name", "")))
    yield from records


def taxon_from_record(rec: dict) -> Taxon:
    parts = _normalize(rec.get("scientific_name")).split()
    genus = parts[0] if parts else ""
    species = parts[1] if len(parts) > 1 else ""
    infra = " ".join(parts[2:]) if len(parts) > 2 and parts[2] in _INFRA_MARKERS else ""
    return Taxon(
        family=_normalize(rec.get("family")),
        genus=genus,
        species=species,
        infraspecies=infra,
        author=_normalize(rec.get("authority")),
    )


def _source_id(rec: dict) -> str:
    return f"{SOURCE}:page-{int(rec['pdf_page']):03d}"


def iter_segments_from_records(records: Iterable[dict]) -> Iterator[TextSegment]:
    for rec in records:
        taxon = taxon_from_record(rec)
        source_id = _source_id(rec)
        index = 0
        for organ, field, language in (
            ("description", "description_ar", "ar"),
            ("description", "description_en", "en"),
            ("habitat", "ecology_ar", "ar"),
            ("habitat", "ecology_en", "en"),
        ):
            text = _normalize(rec.get(field))
            if not text:
                continue
            yield TextSegment(
                source=SOURCE,
                source_id=source_id,
                taxon=taxon,
                organ=organ,
                text=text,
                char_start=0,
                char_end=len(text),
                language=language,
                source_segment_index=index,
            )
            index += 1


def iter_segments(path: Path) -> Iterator[TextSegment]:
    yield from iter_segments_from_records(iter_records(path))


DISTRIBUTION_FIELDS = [
    "source",
    "source_id",
    "taxon",
    "taxon_family",
    "level",
    "iso_3166_2",
    "region_name",
    "locality_name",
    "feature_type",
    "basis",
    "verbatim_ar",
]


def iter_distribution_rows(records: Iterable[dict]) -> Iterator[dict]:
    """Yield one row per (taxon, region) and per (taxon, locality).

    Region codes outside :data:`SAUDI_REGIONS` are rejected rather than passed through, so a
    transcription error cannot introduce an unknown geography.
    """
    for rec in records:
        base = {
            "source": SOURCE,
            "source_id": _source_id(rec),
            "taxon": taxon_from_record(rec).name_string,
            "taxon_family": _normalize(rec.get("family")),
        }
        if rec.get("ksa_regions_all"):
            for code, name in SAUDI_REGIONS.items():
                yield {
                    **base,
                    "level": "region",
                    "iso_3166_2": code,
                    "region_name": name,
                    "locality_name": "",
                    "feature_type": "",
                    "basis": "stated_whole_kingdom",
                    "verbatim_ar": "",
                }
        seen: set[str] = set()
        for region in rec.get("ksa_regions") or []:
            code = _normalize(region.get("iso_3166_2"))
            if code not in SAUDI_REGIONS:
                raise ValueError(f"{base['source_id']}: unknown region code {code!r}")
            if code in seen or rec.get("ksa_regions_all"):
                continue
            seen.add(code)
            yield {
                **base,
                "level": "region",
                "iso_3166_2": code,
                "region_name": SAUDI_REGIONS[code],
                "locality_name": "",
                "feature_type": "",
                "basis": "stated",
                "verbatim_ar": _normalize(region.get("verbatim_ar")),
            }
        for loc in rec.get("localities") or []:
            code = _normalize(loc.get("region_iso_3166_2"))
            if code and code not in SAUDI_REGIONS:
                raise ValueError(f"{base['source_id']}: unknown locality region code {code!r}")
            yield {
                **base,
                "level": "locality",
                "iso_3166_2": code,
                "region_name": SAUDI_REGIONS.get(code, ""),
                "locality_name": _normalize(loc.get("name_en")),
                "feature_type": _normalize(loc.get("feature_type")),
                "basis": _normalize(loc.get("region_basis")) if code else "",
                "verbatim_ar": _normalize(loc.get("verbatim_ar")),
            }


def load_lexicon(path: Path) -> dict[str, list[str]]:
    """Map lower-cased labels and exact synonyms to their identifiers.

    The PO/PATO lexicon TSVs store all synonyms in one column; only labels and the
    ``synonyms`` column are indexed, and a form mapping to several identifiers is kept as a
    collision so the caller can refuse to ground it.
    """
    index: dict[str, list[str]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            forms = [row.get("label", "")] + (row.get("synonyms") or "").split("|")
            for form in forms:
                key = _normalize(form).lower()
                if key and row["id"] not in index.setdefault(key, []):
                    index[key].append(row["id"])
    return index


def load_obo_exact_lexicon(path: Path, prefix: str) -> dict[str, list[str]]:
    """Index live labels and EXACT synonyms of one ontology from its OBO file.

    Used for PO because ``config/po_lexicon.tsv`` keeps synonyms of every scope, which is
    retrieval metadata rather than an exact-grounding index.
    """
    from flopo2.terminology.catalog import load_obo_metadata

    index: dict[str, list[str]] = {}
    for curie, meta in load_obo_metadata(path).items():
        if not curie.startswith(f"{prefix}_") or meta.get("deprecated") or not meta.get("label"):
            continue
        exact = [syn for syn, scope in meta.get("synonym_scopes", ()) if scope == "EXACT"]
        for form in [meta["label"], *exact]:
            key = _normalize(form).lower()
            if key and curie not in index.setdefault(key, []):
                index[key].append(curie)
    return index


def _ground(label: str, lexicon: dict[str, list[str]]) -> tuple[str, str]:
    key = _normalize(label).lower()
    if not key:
        return "", "unlabelled"
    ids = lexicon.get(key, [])
    if len(ids) == 1:
        return ids[0], "exact_label_or_synonym"
    if len(ids) > 1:
        return "", "collision"
    return "", "not_in_lexicon"


PHENOTYPE_FIELDS = [
    "source",
    "source_id",
    "taxon",
    "row",
    "entity_en",
    "quality_en",
    "po_label",
    "po_id",
    "po_status",
    "pato_label",
    "pato_id",
    "pato_status",
    "flopo_id",
    "flopo_label",
    "value_low",
    "value_high",
    "unit",
    "negated",
    "stage",
    "frequency",
    "alternatives",
    "source_en",
    "source_ar",
]


def load_eq_registry(path: Path) -> dict[tuple[str, str], tuple[str, str]]:
    """Map live ``EQ|PO|PATO`` signatures in the FLOPO ID registry to (FLOPO id, label)."""
    eq: dict[tuple[str, str], tuple[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            parts = row["signature"].split("|")
            if len(parts) == 3 and parts[0] == "EQ" and row.get("deprecated") == "0":
                flopo_id = "FLOPO_" + row["flopo_iri"].rsplit("FLOPO_", 1)[-1]
                eq[(parts[1], parts[2])] = (flopo_id, row["label"])
    return eq


def iter_phenotype_rows(
    records: Iterable[dict],
    po_lexicon: dict[str, list[str]],
    pato_lexicon: dict[str, list[str]],
    eq_registry: dict[tuple[str, str], tuple[str, str]] | None = None,
) -> Iterator[dict]:
    for rec in records:
        taxon = taxon_from_record(rec).name_string
        for i, ph in enumerate(rec.get("phenotypes") or []):
            po_id, po_status = _ground(ph.get("po_label", ""), po_lexicon)
            pato_id, pato_status = _ground(ph.get("pato_label", ""), pato_lexicon)
            q = ph.get("qualifiers") or {}
            flopo_id, flopo_label = (eq_registry or {}).get((po_id, pato_id), ("", ""))
            yield {
                "source": SOURCE,
                "source_id": _source_id(rec),
                "taxon": taxon,
                "row": i,
                "entity_en": _normalize(ph.get("entity_en")),
                "quality_en": _normalize(ph.get("quality_en")),
                "po_label": _normalize(ph.get("po_label")),
                "po_id": po_id,
                "po_status": po_status,
                "pato_label": _normalize(ph.get("pato_label")),
                "pato_id": pato_id,
                "pato_status": pato_status,
                "flopo_id": flopo_id,
                "flopo_label": flopo_label,
                "value_low": "" if ph.get("value_low") is None else ph["value_low"],
                "value_high": "" if ph.get("value_high") is None else ph["value_high"],
                "unit": _normalize(ph.get("unit")),
                "negated": bool(q.get("negated")),
                "stage": _normalize(q.get("stage")),
                "frequency": _normalize(q.get("frequency")),
                "alternatives": "|".join(_normalize(a) for a in q.get("alternatives") or []),
                "source_en": _normalize(ph.get("source_en")),
                "source_ar": _normalize(ph.get("source_ar")),
            }


def _write_tsv(path: Path, fields: list[str], rows: Iterable[dict]) -> int:
    n = 0
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            n += 1
    return n


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("raw", type=Path, help="raw transcription JSONL file or directory")
    ap.add_argument("-o", "--out-dir", type=Path, required=True)
    ap.add_argument("--po-obo", type=Path, default=Path("ont/plant_ontology.obo"))
    ap.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    ap.add_argument("--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    args = ap.parse_args(argv)

    records = list(iter_records(args.raw))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    n_seg = 0
    with (args.out_dir / "ncvc-saudi-segments.jsonl").open("w", encoding="utf-8") as fh:
        for seg in iter_segments_from_records(records):
            fh.write(json.dumps(seg.to_row(), ensure_ascii=False) + "\n")
            n_seg += 1
    n_dist = _write_tsv(
        args.out_dir / "ncvc-saudi-distribution.tsv",
        DISTRIBUTION_FIELDS,
        iter_distribution_rows(records),
    )
    n_ph = _write_tsv(
        args.out_dir / "ncvc-saudi-phenotypes.tsv",
        PHENOTYPE_FIELDS,
        iter_phenotype_rows(
            records,
            load_obo_exact_lexicon(args.po_obo, "PO"),
            load_lexicon(args.pato_lexicon),
            load_eq_registry(args.flopo_registry),
        ),
    )
    json.dump(
        {
            "species": len(records),
            "segments": n_seg,
            "distribution_rows": n_dist,
            "phenotype_rows": n_ph,
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
