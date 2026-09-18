"""Parsers for the heterogeneous botanical glossaries already bundled with FLOPO."""

from __future__ import annotations

import csv
import hashlib
import html
import re
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

from flopo2.terminology.model import GlossaryTerm, SourceSpec
from flopo2.terminology.normalize import fold

_QUALITY_CATEGORIES = {
    "architecture",
    "arrangement",
    "character",
    "color",
    "coloration",
    "condition",
    "configuration",
    "count",
    "dehiscence",
    "external texture",
    "fusion",
    "habit",
    "internal texture",
    "length",
    "life stage",
    "odor",
    "odour",
    "orientation",
    "pattern",
    "position",
    "prominence",
    "reflectance",
    "relief",
    "reproduction",
    "shape",
    "size",
    "surface",
    "texture",
    "venation",
    "width",
}

_ORGAN_BY_FILE = {
    "plantbasics": "whole plant",
    "root": "root",
    "stem": "stem",
    "bud": "bud",
    "leaves": "leaf",
    "inflorescence": "inflorescence",
    "flowers": "flower",
    "perianth": "perianth",
    "androecium": "androecium",
    "gynoecium": "gynoecium",
    "fruits": "fruit",
    "seeds": "seed",
}


def _bool(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def load_source_manifest(path: Path) -> list[SourceSpec]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader((line for line in handle if line.strip() and not line.startswith("#")), delimiter="\t")
        return [
            SourceSpec(
                source_id=row["source_id"],
                parser=row["parser"],
                path=row.get("path", ""),
                language=row.get("language", ""),
                version=row.get("version", ""),
                source_url=row.get("source_url", ""),
                license=row.get("license", ""),
                license_status=row.get("license_status", "unknown"),
                redistributable=_bool(row.get("redistributable", "")),
                definition_policy=row.get("definition_policy", "exclude") or "exclude",
                enabled=_bool(row.get("enabled", "1")),
                notes=row.get("notes", ""),
            )
            for row in rows
        ]


def _term_id(source_id: str, record_id: str, surface: str, language: str, qualifier: str = "") -> str:
    key = "\u241f".join((source_id, record_id, fold(surface), language, qualifier))
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]
    return f"BTERM:{source_id}:{digest}"


def infer_role(category: str = "", surface: str = "", pos: str = "") -> str:
    category_folded = fold(category).replace("_", " ")
    if category_folded == "structure" or any(
        marker in category_folded
        for marker in ("flower part", "leaf part", "fruit part", "seed part", "root part", "stem part")
    ):
        return "entity"
    if any(category_folded == q or category_folded.startswith(q + " ") for q in _QUALITY_CATEGORIES):
        return "quality"
    pos = fold(pos)
    if pos.startswith("adj") or "adject" in pos:
        return "quality"
    if re.search(r"\bn [mf]\b", pos) or pos.startswith("noun"):
        return "entity"
    if surface.lower().endswith(("ous", "ose", "ate", "iform", "aceous", "ulent")):
        return "quality"
    return "ambiguous"


def _base(spec: SourceSpec, record_id: str, surface: str, language: str, **kwargs) -> GlossaryTerm:
    language = language or spec.language or "und"
    return GlossaryTerm(
        term_id=_term_id(spec.source_id, record_id, surface, language, kwargs.get("category", "")),
        surface_form=surface.strip(),
        language=language,
        semantic_role=kwargs.pop("semantic_role", "ambiguous"),
        source_id=spec.source_id,
        source_record_id=record_id,
        source_version=spec.version,
        source_url=spec.source_url,
        license=spec.license,
        **kwargs,
    )


def _fna(spec: SourceSpec, path: Path) -> Iterator[GlossaryTerm]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader((line for line in handle if line.strip() and not line.startswith("#")))
        for row in rows:
            surface = (row.get("term") or "").strip()
            if not surface:
                continue
            category = (row.get("category") or "").strip()
            record_id = row.get("termID") or f"row-{rows.line_num}"
            yield _base(
                spec,
                record_id,
                surface,
                "en",
                category=category,
                semantic_role=infer_role(category, surface),
            )


def _attributes(spec: SourceSpec, path: Path) -> Iterator[GlossaryTerm]:
    with path.open(encoding="latin-1", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            raw = (row.get("Term") or "").strip()
            if not raw:
                continue
            category = " > ".join(
                part.strip()
                for part in (row.get("Category", ""), row.get("Class", ""), row.get("Subclass", ""))
                if part and part.strip()
            )
            for position, surface in enumerate(part.strip() for part in raw.split(";") if part.strip()):
                yield _base(
                    spec,
                    f"row-{number}:{position}",
                    surface,
                    "en",
                    category=category,
                    definition=(row.get("Description") or "").strip(),
                    semantic_role="quality",
                )


def _bilingual(spec: SourceSpec, path: Path) -> Iterator[GlossaryTerm]:
    with path.open(encoding="utf-8", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle, delimiter="\t"), start=2):
            record_id = (row.get("ID") or f"row-{number}").strip()
            group = f"{spec.source_id}:{record_id}"
            pos = row.get("Type", "")
            definition = (row.get("Definition") or "").strip().strip('"')
            for language, column in (("en", "English"), ("fr", "French")):
                raw = (row.get(column) or "").strip().strip('"')
                for position, surface in enumerate(part.strip() for part in raw.split(";") if part.strip()):
                    yield _base(
                        spec,
                        f"{record_id}:{language}:{position}",
                        surface,
                        language,
                        definition=definition,
                        translation_group=group,
                        semantic_role=infer_role(surface=surface, pos=pos),
                        notes=f"part_of_speech={pos}" if pos else "",
                    )


def _organ_vocabs(spec: SourceSpec, path: Path) -> Iterator[GlossaryTerm]:
    paths = sorted(path.glob("*.vocab")) if path.is_dir() else [path]
    for vocab in paths:
        stem = vocab.stem.split("_", 1)[-1]
        organ = _ORGAN_BY_FILE.get(stem, stem)
        for number, line in enumerate(vocab.read_text(encoding="utf-8").splitlines(), start=1):
            cells = [cell.strip() for cell in line.split("|")]
            if len(cells) < 4:
                continue
            category = " > ".join(cell for cell in cells[:3] if cell)
            definition = cells[4] if len(cells) > 4 else ""
            for position, surface in enumerate(part.strip() for part in cells[3].split(";") if part.strip()):
                yield _base(
                    spec,
                    f"{vocab.name}:{number}:{position}",
                    surface,
                    "en",
                    category=category,
                    organ_context=organ,
                    definition=definition,
                    semantic_role=infer_role(category, surface),
                )


def _strip_markup(value: str) -> str:
    return re.sub(r"<[^>]+>", "", html.unescape(value or "")).strip()


def _fdg(spec: SourceSpec, path: Path) -> Iterator[GlossaryTerm]:
    text = path.read_text(encoding="utf-8", errors="replace")
    for number, item in enumerate(re.findall(r"<li>(.*?)</li>", text, flags=re.I | re.S), start=1):
        item = _strip_markup(item)
        if ":" not in item:
            continue
        head, definition = item.split(":", 1)
        pos_match = re.search(r"\((n\.[mf]|adj\.)\)", head, flags=re.I)
        pos = pos_match.group(1) if pos_match else ""
        surface = re.sub(r"\s*\([^)]*\)\s*", " ", head).strip(" ,.;")
        if not surface:
            continue
        yield _base(
            spec,
            f"item-{number}",
            surface,
            "fr",
            definition=definition.strip(),
            semantic_role=infer_role(surface=surface, pos=pos),
            notes=f"part_of_speech={pos}" if pos else "",
        )


def _flopo_value_mappings(spec: SourceSpec, path: Path) -> Iterator[GlossaryTerm]:
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            surface = row["label"].strip()
            target = row["pato_id"].strip()
            yield _base(
                spec,
                row["flopo_id"],
                surface,
                "en",
                semantic_role="quality",
                target_id=target,
                target_label=row.get("pato_label", ""),
                target_namespace="PATO",
                mapping_relation="skos:exactMatch",
                mapping_confidence=1.0,
                mapping_method="pato_merged_replacement",
                review_status="reviewed",
                curator_orcid="0000-0001-8149-5890",
                mapping_date="2026-07-13",
                evidence=row.get("provenance", ""),
            )


def _flopo_value_axioms(spec: SourceSpec, path: Path) -> Iterator[GlossaryTerm]:
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            surface = row["label"].strip()
            axiom_type = row.get("axiom_type", "")
            operator = "one_of" if axiom_type == "union" else "all_of" if axiom_type == "components" else "atomic"
            yield _base(
                spec,
                row["flopo_id"],
                surface,
                "en",
                semantic_role="value",
                definition=row.get("definition", ""),
                target_id=row["flopo_id"],
                target_label=surface,
                target_namespace="FLOPO",
                mapping_relation="skos:exactMatch",
                mapping_confidence=1.0,
                mapping_method="reviewed_flopo_value_axiom",
                review_status="reviewed",
                curator_orcid="0000-0001-8149-5890",
                mapping_date="2026-07-13",
                component_ids=tuple((row.get("logical_target_ids") or "").split("|")),
                logical_operator=operator,
                attribute_id=(row.get("parent_ids") or "").split("|")[0],
                evidence=row.get("sources", ""),
                notes=f"axiom_type={axiom_type}",
            )


_PARSERS = {
    "fna_category_csv": _fna,
    "attributes_csv": _attributes,
    "bilingual_tsv": _bilingual,
    "organ_vocabs": _organ_vocabs,
    "fdg_html_text": _fdg,
    "flopo_value_mappings": _flopo_value_mappings,
    "flopo_value_axioms": _flopo_value_axioms,
}


def iter_source_terms(spec: SourceSpec, root: Path = Path(".")) -> Iterator[GlossaryTerm]:
    """Yield normalized source records while enforcing the manifest's definition policy."""
    if not spec.enabled:
        return
    parser = _PARSERS.get(spec.parser)
    if parser is None:
        raise ValueError(f"unsupported terminology source parser: {spec.parser}")
    path = root / spec.path
    if not path.exists():
        raise FileNotFoundError(f"terminology source {spec.source_id!r} is missing: {path}")
    for term in parser(spec, path):
        if not term.surface_form or not fold(term.surface_form):
            continue
        definition = term.definition if spec.definition_policy == "include" and spec.redistributable else ""
        notes = term.notes
        if term.definition and not definition:
            policy_note = "definition_excluded_by_source_manifest"
            notes = f"{notes}; {policy_note}" if notes else policy_note
        yield replace(term, definition=definition, notes=notes)


def iter_manifest_terms(manifest: Path, root: Path = Path(".")) -> Iterator[GlossaryTerm]:
    for spec in load_source_manifest(manifest):
        yield from iter_source_terms(spec, root=root)
