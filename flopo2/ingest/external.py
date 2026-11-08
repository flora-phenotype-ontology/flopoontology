"""Ingest publicly available external and in-repo floras into taxon-level TextSegments.

Supports:
- eFloras (``eflora-fna`` Flora of North America, ``eflora-foc`` Flora of China,
  ``eflora-fop`` Flora of Pakistan, ``eflora-other`` Missouri / Moss Flora / Andean / etc.)
- Plants of the World Online (POWO) aggregated regional floras:
  ``powo-fz`` (Flora Zambesiaca), ``powo-ftea`` (Flora of Tropical East Africa),
  ``powo-fsom`` (Flora of Somalia), ``powo-fwta`` (Flora of West Tropical Africa),
  ``powo-fiq`` (Flora of Iraq), ``powo-cayman`` (Flora of the Cayman Islands),
  ``powo-tong`` (Trees of New Guinea), ``powo-neotropical`` (Colombia / Neotropikey),
  ``powo-kew`` (Kew Bulletin / Species Profiles / GrassBase / ILDIS / CATE)
- World Flora Online (``wfo`` descriptions from ``re_f.csv``)
- Plazi / Pensoft / BHL open-access taxonomic treatments (``plazi`` from Zenodo BLR)
- FlorML & in-repo floras concatenated into one coherent treatment per taxon:
  ``flora-guianas``, ``flora-malesiana``, ``kew-african``, ``flora-gabon``, ``fdac``
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path

from flopo2.ingest import fdac, florml, kew
from flopo2.ingest.models import Taxon, TextSegment

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

EXTERNAL_DIR = Path("local-corpora/external-floras")
CORPORA_DIR = Path("local-corpora")

# Source registry: metadata for every publicly available flora supported by the pipeline.
FLORA_SOURCES: dict[str, dict[str, str]] = {
    "eflora-fna": {
        "title": "Flora of North America North of Mexico (eFloras)",
        "short": "FNA (eFloras)",
        "language": "en",
        "family_group": "efloras",
    },
    "eflora-foc": {
        "title": "Flora of China (eFloras)",
        "short": "Flora of China",
        "language": "en",
        "family_group": "efloras",
    },
    "eflora-fop": {
        "title": "Flora of Pakistan (eFloras)",
        "short": "Flora of Pakistan",
        "language": "en",
        "family_group": "efloras",
    },
    "eflora-fom": {
        "title": "Steyermark's Flora of Missouri (eFloras)",
        "short": "Flora of Missouri",
        "language": "en",
        "family_group": "efloras",
    },
    "eflora-mfoc": {
        "title": "Moss Flora of China (eFloras)",
        "short": "Moss Flora China",
        "language": "en",
        "family_group": "efloras",
    },
    "eflora-andes": {
        "title": "Trees and Shrubs of the Andes of Ecuador & Flora of Chile (eFloras)",
        "short": "eFloras Andes/Chile",
        "language": "es",
        "family_group": "efloras",
    },
    "eflora-other": {
        "title": "eFloras Additional Floras (Missouri, Moss Flora of China, Andean)",
        "short": "eFloras Other",
        "language": "en",
        "family_group": "efloras",
    },
    "powo-fz": {
        "title": "Flora Zambesiaca (via Kew POWO)",
        "short": "Flora Zambesiaca",
        "language": "en",
        "family_group": "powo",
    },
    "powo-ftea": {
        "title": "Flora of Tropical East Africa (via Kew POWO)",
        "short": "FTEA (POWO)",
        "language": "en",
        "family_group": "powo",
    },
    "powo-fsom": {
        "title": "Flora of Somalia (via Kew POWO)",
        "short": "Flora of Somalia",
        "language": "en",
        "family_group": "powo",
    },
    "powo-fwta": {
        "title": "Flora of West Tropical Africa (via Kew POWO)",
        "short": "FWTA (POWO)",
        "language": "en",
        "family_group": "powo",
    },
    "powo-fiq": {
        "title": "Flora of Iraq (via Kew POWO)",
        "short": "Flora of Iraq",
        "language": "en",
        "family_group": "powo",
    },
    "powo-cayman": {
        "title": "Flora of the Cayman Islands (via Kew POWO)",
        "short": "Flora Cayman Isl.",
        "language": "en",
        "family_group": "powo",
    },
    "powo-tong": {
        "title": "Trees of New Guinea (via Kew POWO)",
        "short": "Trees New Guinea",
        "language": "en",
        "family_group": "powo",
    },
    "powo-neotropical": {
        "title": "Neotropical & Colombian Floras (CPLC, UPFC, UPB, Neotropikey via POWO)",
        "short": "POWO Neotropical",
        "language": "es",
        "family_group": "powo",
    },
    "powo-kew": {
        "title": "Kew Monographs & Databases (Kew Bulletin, GrassBase, ILDIS, CATE via POWO)",
        "short": "Kew Monographs",
        "language": "en",
        "family_group": "powo",
    },
    "powo-grassbase": {
        "title": "GrassBase — The Online World Grass Flora (RBG Kew via POWO)",
        "short": "GrassBase (Kew)",
        "language": "en",
        "family_group": "powo",
    },
    "powo-ildis": {
        "title": "ILDIS World Database of Legumes (via Kew POWO)",
        "short": "ILDIS Legumes",
        "language": "en",
        "family_group": "powo",
    },
    "powo-cate": {
        "title": "CATE Araceae & Palmweb Monocot Monographs (via Kew POWO)",
        "short": "CATE / Palmweb",
        "language": "en",
        "family_group": "powo",
    },
    "wfo": {
        "title": "World Flora Online Species Descriptions (WFO)",
        "short": "WFO Descriptions",
        "language": "en",
        "family_group": "wfo",
    },
    "plazi": {
        "title": "Plazi / Pensoft / BHL Open-Access Taxonomic Treatments (Zenodo BLR)",
        "short": "Plazi / Pensoft",
        "language": "en",
        "family_group": "plazi",
    },
    "flora-guianas": {
        "title": "Flora of the Guianas (FlorML)",
        "short": "Flora Guianas",
        "language": "en",
        "family_group": "florml",
    },
    "flora-malesiana": {
        "title": "Flora Malesiana (FlorML)",
        "short": "Flora Malesiana",
        "language": "en",
        "family_group": "florml",
    },
    "kew-african": {
        "title": "Kew African Flora Species",
        "short": "Kew African Flora",
        "language": "en",
        "family_group": "florml",
    },
    "flora-gabon": {
        "title": "Flore du Gabon (FlorML)",
        "short": "Flore du Gabon",
        "language": "fr",
        "family_group": "florml",
    },
    "fdac": {
        "title": "Flore d'Afrique Centrale (Meise Botanic Garden)",
        "short": "Flore Afr. Centr.",
        "language": "fr",
        "family_group": "florml",
    },
    "fdac-genera": {
        "title": "Flore du Congo Belge et du Ruanda-Urundi — Genera (Meise Botanic Garden)",
        "short": "Flore Congo Genera",
        "language": "fr",
        "family_group": "florml",
    },
    "flora-zimbabwe": {
        "title": "Flora of Zimbabwe (Hyde, Wursten, Ballings & Coates Palgrave)",
        "short": "Flora of Zimbabwe",
        "language": "en",
        "family_group": "eol-dwca",
    },
    "nybg-naf": {
        "title": "North American Flora Monographs (New York Botanical Garden)",
        "short": "NYBG N. Amer. Flora",
        "language": "en",
        "family_group": "eol-dwca",
    },
    "illinois-wildflowers": {
        "title": "Illinois Wildflowers (John Hilty)",
        "short": "Illinois Wildflowers",
        "language": "en",
        "family_group": "eol-xml",
    },
    "usda-plants": {
        "title": "USDA NRCS PLANTS Database — Botanical Descriptions",
        "short": "USDA PLANTS",
        "language": "en",
        "family_group": "eol-dwca",
    },
    "feis-plants": {
        "title": "USFS Fire Effects Information System (FEIS) — Plant Species",
        "short": "USFS FEIS Plants",
        "language": "en",
        "family_group": "eol-dwca",
    },
    "silvics-na": {
        "title": "Silvics of North America (USFS Agriculture Handbook 654)",
        "short": "Silvics N. Amer.",
        "language": "en",
        "family_group": "eol-dwca",
    },
    "plants-tibet": {
        "title": "Plants of Tibet (Flora Xizangica / Tibetan Plateau)",
        "short": "Plants of Tibet",
        "language": "en",
        "family_group": "eol-dwca",
    },
    "smithsonian-botany": {
        "title": "Smithsonian Contributions to Botany (NMNH Taxonomic Monographs)",
        "short": "Smithsonian Botany",
        "language": "en",
        "family_group": "eol-dwca",
    },
    "korup-flora": {
        "title": "Vascular Plants of Korup National Park (Cameroon)",
        "short": "Korup Flora",
        "language": "en",
        "family_group": "eol-dwca",
    },
    "africa-tree-db": {
        "title": "Africa Tree Database (ATDB)",
        "short": "Africa Tree DB",
        "language": "en",
        "family_group": "eol-dwca",
    },
    "phytokeys": {
        "title": "PhytoKeys Botanical Taxonomic Monographs (Pensoft)",
        "short": "PhytoKeys",
        "language": "en",
        "family_group": "eol-dwca",
    },
}

POWO_SOURCE_BUCKETS: dict[str, set[str]] = {
    "powo-fz": {"FZ"},
    "powo-ftea": {"FTEA"},
    "powo-fsom": {"FSOM"},
    "powo-fwta": {"FWTA"},
    "powo-fiq": {"FIQ"},
    "powo-cayman": {"Cayman"},
    "powo-tong": {"TONG", "PONG"},
    "powo-neotropical": {"CPLC", "UPFC", "UPB", "NTK"},
    "powo-kew": {"KBu", "KSP", "GB", "ILDIS", "LKGF", "CATE", "SCG", "LOWO", "O-EM", "FPS", "E-EM", "C-EM", "A-EM"},
    "powo-grassbase": {"GB"},
    "powo-ildis": {"ILDIS"},
    "powo-cate": {"CATE", "PONG"},
}

_FNA_RE = re.compile(
    r"  (Habit|Trees|Shrubs|Herbs|Plants|Stems|Leaves|Inflorescences|Flowers|Pistillate|Staminate|Fruits|Seeds|Capsules|Cypselae|2n)\b"
    r"|\b(Leaves|Inflorescences|Flowers|Stems|Fruits|Seeds|Perianth|Corollas|Calyces|Pistillate flowers|Staminate flowers|Ray florets|Disc florets|Cypselae|Pappi|2n)\s*:"
    r"|\bFlowering\s+(?:spring|summer|fall|winter|year-round|all year|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"|;\s*(?:0|[1-9]\d*)\s*[-–]\s*\d+\s*m;\s*(?:Ala\.|Alaska|Ariz\.|Ark\.|Calif\.|Colo\.|Fla\.|Ga\.|Idaho|Mont\.|Nev\.|N\.Mex\.|Oreg\.|Tex\.|Utah|Wash\.|Wyo\.|B\.C\.|Ont\.|Que\.)"
)
_FOC_RE = re.compile(
    r"Description from Flora of China|[\u4e00-\u9fff]|Fl\.\s*[A-Z][a-z]{2,8}(?:[-–][A-Z][a-z]{2,8})?\s*,\s*fr\."
    r"|\b(?:Anhui|Fujian|Gansu|Guangdong|Guangxi|Guizhou|Hainan|Hebei|Heilongjiang|Henan|Hubei|Hunan|Jiangsu|Jiangxi|Jilin|Liaoning|Nei Mongol|Ningxia|Qinghai|Shaanxi|Shandong|Shanxi|Sichuan|Taiwan|Xinjiang|Xizang|Yunnan|Zhejiang)\b"
)
_FOP_RE = re.compile(
    r"Fl\.\s*Per\.|Distribution:.*Pakistan|Type:.*Hb\.|\b(?:Sind|Baluchistan|N\.W\.F\.P\.|Rawalpindi|Karachi|Quetta|Chitral|Gilgit|Swat|Hazara|Kashmir)\b"
    r"|^[A-Z][a-z]+ [a-z]+.*\b(?:Linn\.|Roxb\.|Wall\.|Boiss\.|DC\.|Benth\.|Hook\.f\.)"
)
_WS_RE = re.compile(r"\s+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def _parse_binomial(name: str, family: str = "", author: str = "") -> Taxon:
    name = _norm(name.replace("_", " "))
    parts = name.split()
    if not parts:
        return Taxon(family=family)
    genus = parts[0].capitalize()
    species = ""
    infra = ""
    rest_author = author
    if len(parts) >= 2 and parts[1][0].islower() and parts[1] not in {"sp.", "cf.", "aff.", "sect.", "subg."}:
        species = parts[1]
        tail = parts[2:]
        if tail:
            if tail[0] in {"var.", "subsp.", "ssp.", "f.", "forma"} or (tail[0][0].islower() and len(tail) == 1):
                infra = " ".join(tail)
            elif not rest_author:
                rest_author = " ".join(tail)
    elif len(parts) >= 2 and not rest_author:
        rest_author = " ".join(parts[1:])
    return Taxon(family=family, genus=genus, species=species, infraspecies=infra, author=rest_author)


def _load_family_map(external_dir: Path) -> dict[str, str]:
    """Map genus (and species slug) -> family from flora_with_higher_taxaall.csv and fotw_powo_taxon_wide.csv."""
    fam_map: dict[str, str] = {}
    higher = external_dir / "flora_with_higher_taxaall.csv"
    if higher.exists():
        with higher.open(encoding="utf-8", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                sp = (row.get("scientificName") or "").strip()
                fam = (row.get("family") or "").strip()
                gen = (row.get("genus") or "").strip()
                if fam:
                    if sp:
                        fam_map[sp.lower()] = fam
                    if gen:
                        fam_map[gen.lower()] = fam
    powo_wide = external_dir / "fotw_powo_taxon_wide.csv"
    if powo_wide.exists():
        with powo_wide.open(encoding="utf-8", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                fam = (row.get("family") or "").strip()
                gen = (row.get("genus") or "").strip()
                if fam and gen:
                    fam_map.setdefault(gen.lower(), fam)
    return fam_map


_MOSS_RE = re.compile(
    r"\b(Plants|Stems|Leaves)\b.*\b(capsule|seta|peristome|calyptra|spores|costa|alar cells)\b",
    re.IGNORECASE,
)
_MISSOURI_RE = re.compile(r"\b(Missouri|Ozark|Steyermark|glade|prairie)\b")
_ANDES_ES_RE = re.compile(r"\b(Arbustos|Árboles|Hierbas|Hojas|Flores)\b")


def classify_eflora_row(desc: str) -> str:
    if _FOC_RE.search(desc):
        return "eflora-foc"
    if _FNA_RE.search(desc):
        return "eflora-fna"
    if _FOP_RE.search(desc):
        return "eflora-fop"
    return "eflora-other"


def _matches_eflora_source(desc: str, source_key: str) -> bool:
    if source_key == "eflora-andes":
        return bool(_ANDES_ES_RE.search(desc))
    primary = classify_eflora_row(desc)
    if source_key in {"eflora-foc", "eflora-fna", "eflora-fop"}:
        return primary == source_key
    if primary != "eflora-other":
        return False
    if source_key == "eflora-mfoc":
        return bool(_MOSS_RE.search(desc)) and not bool(_ANDES_ES_RE.search(desc))
    if source_key == "eflora-fom":
        return bool(_MISSOURI_RE.search(desc)) and not bool(_MOSS_RE.search(desc))
    return True


def _clean_eflora_text(desc: str) -> str:
    desc = re.sub(r"^Description from Flora of China\s*", "", desc)
    # Strip leading Chinese vernacular + pinyin header before the Latin binomial or description
    if _CJK_RE.search(desc[:80]):
        m = re.search(r"[A-Z][a-z]+\s+[a-z]{2,}", desc)
        if m and m.start() < 160:
            desc = desc[m.start():]
    # Add space where scraped HTML concatenated words (e.g. "1753Trees" -> "1753. Trees")
    desc = re.sub(r"(\d)([A-Z][a-z]{2,})", r"\1. \2", desc)
    desc = re.sub(r"([a-z]\.)([A-Z][a-z]{2,})", r"\1 \2", desc)
    return _norm(desc)


def iter_eflora_segments(
    source_key: str, external_dir: Path = EXTERNAL_DIR
) -> Iterator[TextSegment]:
    path = external_dir / "eflora_0702.csv"
    if not path.exists():
        return
    fam_map = _load_family_map(external_dir)
    seen_texts: set[str] = set()
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for idx, row in enumerate(csv.DictReader(fh)):
            sp_slug = (row.get("Species") or "").strip()
            raw_desc = (row.get("Description") or "").strip()
            if not raw_desc or raw_desc == "Description not found" or "_" not in sp_slug:
                continue
            if not _matches_eflora_source(raw_desc, source_key):
                continue
            text = _clean_eflora_text(raw_desc)
            if len(text.split()) < 15 or text in seen_texts:
                continue
            seen_texts.add(text)
            genus = sp_slug.split("_")[0].lower()
            family = fam_map.get(sp_slug.lower()) or fam_map.get(genus, "")
            taxon = _parse_binomial(sp_slug, family=family)
            lang = "es" if re.search(r"\b(Arbustos|Árboles|Hierbas|Hojas|Flores)\b", text) else "en"
            yield TextSegment(
                source=source_key,
                source_id=f"{source_key}:{sp_slug}:{idx}",
                taxon=taxon,
                organ="description",
                text=text,
                char_start=0,
                char_end=len(text),
                language=lang,
            )


POWO_KIND_HEADERS: dict[str, str] = {
    "morphologyGeneralHabit": "Habit",
    "habit": "Habit",
    "morphologyLeaf": "Leaves",
    "morphologyReproductiveInflorescence": "Inflorescence",
    "morphologyReproductiveFlower": "Flowers",
    "morphologyReproductiveFlowerCalyx": "Calyx",
    "morphologyReproductiveFlowerCorolla": "Corolla",
    "morphologyReproductiveFlowerAndroeciumStamen": "Stamens",
    "morphologyReproductiveFlowerGynoeciumPistil": "Pistil",
    "morphologyReproductiveFruit": "Fruit",
    "morphologyReproductiveSeed": "Seeds",
}


def iter_powo_segments(
    source_key: str, external_dir: Path = EXTERNAL_DIR
) -> Iterator[TextSegment]:
    desc_path = external_dir / "fotw_powo_descriptions_long.csv"
    wide_path = external_dir / "fotw_powo_taxon_wide.csv"
    if not desc_path.exists():
        return
    codes = POWO_SOURCE_BUCKETS.get(source_key, set())
    taxon_meta: dict[str, dict[str, str]] = {}
    if wide_path.exists():
        with wide_path.open(encoding="utf-8", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                taxon_meta[row["taxonID"]] = row

    # Group morphological clauses by (taxonID, source_code) so each taxon gets one rich treatment
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    names: dict[tuple[str, str], tuple[str, str]] = {}
    with desc_path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            sc = row.get("source_code") or ""
            if sc not in codes:
                continue
            kind = row.get("description_kind") or ""
            if not (kind.startswith("morphology") or kind in {"habit", "general", "diagnostic"}):
                continue
            txt = _norm(row.get("description_text") or "")
            if not txt:
                continue
            hdr = POWO_KIND_HEADERS.get(kind, "")
            if hdr and not txt.lower().startswith(hdr.lower()[:4]):
                txt = f"{hdr}: {txt}"
            key = (row["taxonID"], sc)
            if txt not in grouped[key]:
                grouped[key].append(txt)
            names[key] = (
                row.get("accepted_name") or row.get("scientificName") or "",
                row.get("accepted_ipni_id") or "",
            )

    min_words = 2 if source_key in {"powo-neotropical", "powo-ildis"} else 8
    for (tid, sc), parts in grouped.items():
        text = " ".join(p if p.endswith((".", ";")) else p + "." for p in parts)
        text = _norm(text)
        if len(text.split()) < min_words:
            continue
        meta = taxon_meta.get(tid, {})
        sci_name, ipni_id = names[(tid, sc)]
        family = meta.get("family", "")
        author = meta.get("accepted_author", "")
        taxon = _parse_binomial(sci_name, family=family, author=author)
        lang = "es" if re.search(r"\b(Arbustos|Árboles|Hierbas|Hojas|Flores|Caule|Folha|Hierba|Árbol|Arbusto)\b", text) else "en"
        yield TextSegment(
            source=source_key,
            source_id=f"{source_key}:{sc}:{ipni_id or tid}",
            taxon=taxon,
            organ="description",
            text=text,
            char_start=0,
            char_end=len(text),
            language=lang,
        )


def iter_wfo_segments(external_dir: Path = EXTERNAL_DIR) -> Iterator[TextSegment]:
    path = external_dir / "re_f.csv"
    if not path.exists():
        return
    seen_texts: set[str] = set()
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            wfo_id = (row.get("WFO ID") or "").strip()
            raw_desc = _norm(row.get("Description") or "")
            if not raw_desc or raw_desc == "Description not found" or len(raw_desc.split()) < 18:
                continue
            if raw_desc in seen_texts:
                continue
            seen_texts.add(raw_desc)
            sci_name = (row.get("scientificName") or "").strip()
            family = (row.get("family") or "").strip()
            taxon = _parse_binomial(sci_name, family=family)
            lang = "en"
            if re.search(r"\b(Feuilles|Fleurs|Tiges|Arbuste|Herbe)\b", raw_desc):
                lang = "fr"
            elif re.search(r"\b(Hojas|Flores|Tallos|Arbustos|Hierbas|Caule|Folha)\b", raw_desc):
                lang = "es"
            yield TextSegment(
                source="wfo",
                source_id=f"wfo:{wfo_id}",
                taxon=taxon,
                organ="description",
                text=raw_desc,
                char_start=0,
                char_end=len(raw_desc),
                language=lang,
            )


def iter_plazi_segments(external_dir: Path = EXTERNAL_DIR) -> Iterator[TextSegment]:
    path = external_dir / "plazi_treatments.jsonl"
    if not path.exists():
        return
    for line in path.open(encoding="utf-8"):
        row = json.loads(line)
        text = _norm(row.get("text") or "")
        if len(text.split()) < 20:
            continue
        taxon = _parse_binomial(
            row.get("scientific_name") or "",
            family=row.get("family") or "",
            author=row.get("authorship") or "",
        )
        yield TextSegment(
            source="plazi",
            source_id=f"plazi:zenodo-{row['zenodo_id']}",
            taxon=taxon,
            organ="description",
            text=text,
            char_start=0,
            char_end=len(text),
            language=row.get("language") or "en",
        )


def _concat_taxon_segments(segments: Iterator[TextSegment], source_key: str) -> Iterator[TextSegment]:
    """Combine organ-level FlorML/FDAC segments of one taxon treatment into a single treatment segment."""
    current_key: tuple[str, str] | None = None
    current_taxon: Taxon | None = None
    current_lang = "en"
    current_parts: list[str] = []
    idx = 0

    def flush() -> TextSegment | None:
        nonlocal idx
        if not current_parts or current_taxon is None or current_key is None:
            return None
        text = _norm(" ".join(current_parts))
        if len(text.split()) < 10:
            return None
        idx += 1
        return TextSegment(
            source=source_key,
            source_id=f"{source_key}:{current_key[0]}:{idx}",
            taxon=current_taxon,
            organ="description",
            text=text,
            char_start=0,
            char_end=len(text),
            language=current_lang,
        )

    for seg in segments:
        name = seg.taxon.name_string
        if not name:
            continue
        key = (seg.source_id, name)
        if key != current_key:
            out = flush()
            if out is not None:
                yield out
            current_key = key
            current_taxon = seg.taxon
            current_lang = seg.language
            current_parts = []
        prefix = f"{seg.organ.capitalize()}: " if seg.organ not in {"description", "morphology", "habit"} else ""
        piece = seg.text if seg.text.endswith((".", ";")) else seg.text + "."
        current_parts.append(prefix + piece)
    out = flush()
    if out is not None:
        yield out


def _clean_html(raw: str) -> str:
    txt = html.unescape(raw or "")
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html.unescape(txt)
    return _norm(txt)


def iter_fdac_genera_segments(root: Path = Path(".")) -> Iterator[TextSegment]:
    xml_path = root / "floras/familygenusdescriptions 3Dec2009.xml"
    if not xml_path.exists():
        xml_path = root / "floras/familygenusdescriptions.xml"
    if not xml_path.exists():
        return
    tree = ET.parse(xml_path)
    idx = 0
    for fam_el in tree.getroot().findall("{*}family"):
        fam_name = _norm((fam_el.findtext("{*}familyname") or "").capitalize())
        for gen_el in fam_el.findall("{*}genus"):
            gen_name = _norm((gen_el.findtext("{*}genusname") or "").capitalize())
            auth = _norm(gen_el.findtext("{*}authority") or "")
            descs: list[str] = []
            for d_el in gen_el.findall(".//{*}description"):
                txt = _norm("".join(d_el.itertext()))
                if txt and not re.match(r"^(Environ|Genre|Un genre|Deux genres|Plusieurs|\d+\s+espèces)", txt):
                    descs.append(txt)
            if not descs or not gen_name:
                continue
            full_text = _norm(" ".join(descs))
            if len(full_text.split()) < 12:
                continue
            idx += 1
            yield TextSegment(
                source="fdac-genera",
                source_id=f"fdac-genera:{gen_name.lower()}:{idx}",
                taxon=Taxon(family=fam_name, genus=gen_name, author=auth),
                organ="description",
                text=full_text,
                char_start=0,
                char_end=len(full_text),
                language="fr",
            )


_EOL_MORPH_SUBJECTS = {
    "description",
    "generaldescription",
    "diagnosticdescription",
    "morphology",
    "size",
}
_SILVICS_TITLES = {
    "flowering and fruiting",
    "rooting habit",
    "seedling development",
}
_VASCULAR_MORPH_RE = re.compile(
    r"\b(stem|stems|leaf|leaves|blade|petiole|flower|flowers|inflorescence|calyx|corolla|petal|sepal|stamen|anther|ovary|style|fruit|capsule|berry|achene|seed|seeds|rhizome|root|tree|shrub|herb|frond|pinnae|sori|perianth)\b",
    re.IGNORECASE,
)


def iter_eol_dwca_segments(
    source_key: str, external_dir: Path = EXTERNAL_DIR
) -> Iterator[TextSegment]:
    dwca_dir = external_dir / "zenodo-eol" / source_key
    if not dwca_dir.exists():
        return
    meta_files = [p for p in dwca_dir.rglob("meta.xml") if not p.name.startswith("._")]
    if not meta_files:
        return
    meta_path = meta_files[0]
    base_dir = meta_path.parent
    tree = ET.parse(meta_path)
    tables: dict[str, tuple[str, dict[str, int]]] = {}
    for elem in tree.iter():
        if elem.tag.endswith("table"):
            rtype = elem.attrib.get("rowType", "").split("/")[-1]
            locs = [c.text for g in elem for c in g if c.tag.endswith("location") and c.text]
            if not locs:
                continue
            fields = {
                c.attrib["term"].split("/")[-1].split("#")[-1]: int(c.attrib["index"])
                for c in elem
                if c.tag.endswith("field") and "index" in c.attrib
            }
            tables[rtype] = (locs[0], fields)
    if "Taxon" not in tables or "Document" not in tables:
        return

    fam_map = _load_family_map(external_dir)
    tax_loc, tax_f = tables["Taxon"]
    tid_idx = tax_f.get("taxonID", 0)
    sci_idx = tax_f.get("scientificName", 1)
    fam_idx = tax_f.get("family", -1)

    taxa_by_id: dict[str, tuple[str, str]] = {}
    with (base_dir / tax_loc).open(encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.reader(fh, delimiter="\t"):
            if len(row) <= max(tid_idx, sci_idx):
                continue
            tid = row[tid_idx].strip()
            sci = row[sci_idx].strip()
            fam = row[fam_idx].strip() if fam_idx >= 0 and len(row) > fam_idx else ""
            if tid and sci:
                taxa_by_id[tid] = (sci, fam)

    doc_loc, doc_f = tables["Document"]
    doc_tid_idx = doc_f.get("taxonID", 1)
    type_idx = doc_f.get("type", 2)
    subj_idx = doc_f.get("CVterm", doc_f.get("subject", -1))
    title_idx = doc_f.get("title", -1)
    desc_idx = doc_f.get("description", -1)

    grouped: dict[str, list[str]] = defaultdict(list)
    with (base_dir / doc_loc).open(encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.reader(fh, delimiter="\t"):
            if len(row) <= max(doc_tid_idx, type_idx, desc_idx):
                continue
            if "Text" not in row[type_idx]:
                continue
            tid = row[doc_tid_idx].strip()
            if tid not in taxa_by_id:
                continue
            subj = (
                row[subj_idx].split("#")[-1].split("/")[-1].lower()
                if subj_idx >= 0 and len(row) > subj_idx
                else ""
            )
            title = (
                row[title_idx].strip().lower()
                if title_idx >= 0 and len(row) > title_idx
                else ""
            )
            if source_key == "silvics-na":
                if title not in _SILVICS_TITLES:
                    continue
            else:
                if subj and subj not in _EOL_MORPH_SUBJECTS:
                    continue
                if "derivation" in title or "etymology" in title or "common name" in title:
                    continue
            txt = _clean_html(row[desc_idx])
            # Strip FEIS citation brackets like "[ 14 , 24 ]" and leading boilerplate
            txt = re.sub(r"More info for the term:\s*\w+\s*", "", txt)
            txt = re.sub(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]", "", txt)
            txt = _norm(txt)
            if len(txt.split()) < 15:
                continue
            if source_key == "nybg-naf" and not _VASCULAR_MORPH_RE.search(txt):
                continue
            if txt not in grouped[tid]:
                grouped[tid].append(txt)

    seen_texts: set[str] = set()
    for tid, parts in grouped.items():
        full_text = _norm(" ".join(parts))
        if len(full_text.split()) < 15 or full_text in seen_texts:
            continue
        seen_texts.add(full_text)
        sci_name, fam = taxa_by_id[tid]
        taxon = _parse_binomial(sci_name, family=fam)
        if not taxon.family and taxon.genus:
            taxon = Taxon(
                family=fam_map.get(f"{taxon.genus.lower()}_{taxon.species.lower()}")
                or fam_map.get(taxon.genus.lower(), ""),
                genus=taxon.genus,
                species=taxon.species,
                infraspecies=taxon.infraspecies,
                author=taxon.author,
            )
        safe_tid = re.sub(r"[^A-Za-z0-9_.-]+", "_", tid)[:48]
        yield TextSegment(
            source=source_key,
            source_id=f"{source_key}:{safe_tid}",
            taxon=taxon,
            organ="description",
            text=full_text,
            char_start=0,
            char_end=len(full_text),
            language="en",
        )


def iter_eol_xml_segments(
    source_key: str, external_dir: Path = EXTERNAL_DIR
) -> Iterator[TextSegment]:
    xml_dir = external_dir / "zenodo-eol" / source_key
    if not xml_dir.exists():
        return
    fam_map = _load_family_map(external_dir)
    seen_texts: set[str] = set()
    for xml_path in sorted(xml_dir.glob("*.xml")):
        if xml_path.name == "meta.xml":
            continue
        tree = ET.parse(xml_path)
        for tax_el in tree.getroot().findall("{*}taxon"):
            sci = _norm(tax_el.findtext("{*}ScientificName") or "")
            fam = _norm(tax_el.findtext("{*}Family") or "")
            tid = _norm(tax_el.findtext("{*}identifier") or sci.replace(" ", "_"))
            if not sci:
                continue
            parts: list[str] = []
            for dobj in tax_el.findall("{*}dataObject"):
                dtype = dobj.findtext("{*}dataType") or ""
                subj = (dobj.findtext("{*}subject") or "").split("#")[-1].lower()
                title = (dobj.findtext("{*}title") or "").lower()
                if "Text" not in dtype:
                    continue
                if subj and subj not in _EOL_MORPH_SUBJECTS and "description" not in title:
                    continue
                txt = _clean_html(dobj.findtext("{*}description") or "")
                if len(txt.split()) >= 15 and txt not in parts:
                    parts.append(txt)
            if not parts:
                continue
            full_text = _norm(" ".join(parts))
            if full_text in seen_texts:
                continue
            seen_texts.add(full_text)
            taxon = _parse_binomial(sci, family=fam)
            if not taxon.family and taxon.genus:
                taxon = Taxon(
                    family=fam_map.get(taxon.genus.lower(), ""),
                    genus=taxon.genus,
                    species=taxon.species,
                    infraspecies=taxon.infraspecies,
                    author=taxon.author,
                )
            safe_tid = re.sub(r"[^A-Za-z0-9_.-]+", "_", tid)[:48]
            yield TextSegment(
                source=source_key,
                source_id=f"{source_key}:{safe_tid}",
                taxon=taxon,
                organ="description",
                text=full_text,
                char_start=0,
                char_end=len(full_text),
                language="en",
            )


def iter_source_segments(
    source_key: str,
    *,
    root: Path = Path("."),
    external_dir: Path = EXTERNAL_DIR,
) -> Iterator[TextSegment]:
    meta = FLORA_SOURCES.get(source_key, {})
    fgroup = meta.get("family_group", "")
    if source_key.startswith("eflora-"):
        yield from iter_eflora_segments(source_key, external_dir)
    elif source_key.startswith("powo-"):
        yield from iter_powo_segments(source_key, external_dir)
    elif source_key == "wfo":
        yield from iter_wfo_segments(external_dir)
    elif source_key == "plazi":
        yield from iter_plazi_segments(external_dir)
    elif source_key == "flora-guianas":
        gdir = external_dir / "flora-guianas"
        raw = (s for p in sorted(gdir.rglob("*.xml")) for s in florml.iter_segments(p, source="flora-guianas"))
        yield from _concat_taxon_segments(raw, "flora-guianas")
    elif source_key == "flora-malesiana":
        raw = florml.iter_segments_dir(root / "flora-malesiana")
        yield from _concat_taxon_segments(raw, "flora-malesiana")
    elif source_key == "flora-gabon":
        raw = florml.iter_segments_dir(root / "flora-gabon")
        yield from _concat_taxon_segments(raw, "flora-gabon")
    elif source_key == "fdac":
        raw = fdac.iter_segments(root / "flora-central-africa/fdacDescriptions.csv", source="fdac")
        yield from _concat_taxon_segments(raw, "fdac")
    elif source_key == "fdac-genera":
        yield from iter_fdac_genera_segments(root)
    elif source_key == "kew-african":
        yield from kew.iter_segments(root / "floras-other/Kew African Flora Species.xml", source="kew-african")
    elif fgroup == "eol-dwca":
        yield from iter_eol_dwca_segments(source_key, external_dir)
    elif fgroup == "eol-xml":
        yield from iter_eol_xml_segments(source_key, external_dir)
    else:
        raise ValueError(f"Unknown flora source: {source_key!r}")


def dump_segments(
    source_key: str,
    *,
    out: Path | None = None,
    limit: int = 0,
    species_only: bool = True,
    root: Path = Path("."),
    external_dir: Path = EXTERNAL_DIR,
) -> Path:
    dest = out or (CORPORA_DIR / source_key / f"{source_key}-segments.jsonl")
    dest.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    allowed_ranks = (
        {"species", "infraspecies", "genus"}
        if source_key in {"powo-tong", "fdac-genera", "flora-zimbabwe"}
        else {"species", "infraspecies"}
    )
    with dest.open("w", encoding="utf-8") as fh:
        for seg in iter_source_segments(source_key, root=root, external_dir=external_dir):
            if species_only and seg.taxon.rank not in allowed_ranks:
                continue
            row = seg.to_row()
            row["source_segment_index"] = count
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
            if limit and count >= limit:
                break
    print(f"{source_key}: wrote {count:,} taxon treatment segments to {dest}")
    return dest


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list supported publicly available flora sources")
    st = sub.add_parser("stats", help="count taxon treatment segments per flora")
    st.add_argument("sources", nargs="*", default=list(FLORA_SOURCES))
    dm = sub.add_parser("dump", help="dump taxon treatment segments to local-corpora/<source>/")
    dm.add_argument("sources", nargs="+", help="source key(s) or 'all'")
    dm.add_argument("--limit", type=int, default=0, help="max segments per source (0 = all)")
    dm.add_argument("--include-higher-taxa", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        for k, meta in FLORA_SOURCES.items():
            print(f"{k:18s} [{meta['language']}] {meta['short']:20s} — {meta['title']}")
    elif args.cmd == "stats":
        for k in args.sources:
            n = 0
            taxa = set()
            for seg in iter_source_segments(k):
                if seg.taxon.rank in {"species", "infraspecies"}:
                    n += 1
                    taxa.add(seg.taxon.name_string)
            print(f"{k:18s}: {n:7,d} species treatments ({len(taxa):7,d} distinct taxa)")
    elif args.cmd == "dump":
        targets = list(FLORA_SOURCES) if "all" in args.sources else args.sources
        for k in targets:
            dump_segments(k, limit=args.limit, species_only=not args.include_higher_taxa)


if __name__ == "__main__":
    main()
