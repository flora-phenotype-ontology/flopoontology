"""Parse Collenette's illustrated Saudi field-guide OCR into FLOPO text segments.

This source is a two-column, photo-heavy field guide rather than structured FlorML. The parser is
therefore conservative: it extracts one English ``description`` segment per species entry when a
Latin-name heading is followed by enough descriptive prose. Raw OCR/PDF files should live under the
git-ignored ``local-corpora/`` tree.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

from flopo2.ingest.models import Taxon, TextSegment

_WS_RE = re.compile(r"\s+")
_PAGE_RE = re.compile(r"\f")
_BAD_LINE_RE = re.compile(r"^(?:\d+|[=@<>«»#¢4]+)$")
_FAMILY_RE = re.compile(r"^[A-Z][A-Z -]{4,}(?:ACEAE|IFERAE)$")
_ENTRY_RE = re.compile(
    r"^(?:[@#¢4]\s*)?"
    r"(?P<name>[A-Z][a-zA-Z-]+(?:\s+(?:cf\.|sp\.|aff\.|nov\.|var\.|ssp\.|subsp\.|forma|sensu|[a-z][a-z-]+|[A-Z]\.)){1,8})"
    r"(?:\s+[@#¢4»]+)?$"
)
_MORPH_WORD_RE = re.compile(
    r"\b(?:annual|aquatic|aromatic|bark|branching|bushy|creeping|erect|flower|flowers|"
    r"foliage|fruit|fruits|glabrous|hairy|herb|leaf|leafy|leaves|petals|prostrate|"
    r"scandent|scent|shrub|spines|stem|stems|tree|tendrils|vine|woody)\b",
    re.I,
)
_BAD_GENUS_WORDS = {
    "Ad",
    "Al",
    "Almost",
    "Among",
    "Ash",
    "Between",
    "Common",
    "Fairly",
    "Halfway",
    "Jabal",
    "Locally",
    "Low",
    "Most",
    "Near",
    "North",
    "One",
    "South",
    "The",
    "This",
    "Very",
    "Wadi",
    "West",
    "Widespread",
}


def _normalize(text: str) -> str:
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return _WS_RE.sub(" ", text).strip()


def _clean_line(line: str) -> str:
    line = _normalize(line)
    line = re.sub(r"^[=@<>«»#¢4]+\s*", "", line)
    line = re.sub(r"\s*[@#¢4»]+\s*$", "", line)
    return line.strip(" ;")


def _looks_like_entry(line: str) -> re.Match[str] | None:
    line = _clean_line(line)
    if not line or len(line) > 90 or _FAMILY_RE.match(line):
        return None
    if any(ch.isdigit() for ch in line):
        return None
    m = _ENTRY_RE.match(line)
    if not m:
        return None
    if m.group("name").split()[0] in _BAD_GENUS_WORDS:
        return None
    return m


def _taxon_from_name(name: str, family: str) -> Taxon:
    parts = name.split()
    genus = parts[0] if parts else ""
    species = ""
    infra = ""
    author = ""
    if len(parts) > 1 and parts[1] not in {"sp.", "cf.", "aff.", "nov."}:
        species = parts[1]
        rest = parts[2:]
    else:
        rest = parts[1:]
    if rest:
        if any(p in {"var.", "ssp.", "subsp.", "forma"} for p in rest):
            infra = " ".join(rest)
        else:
            author = " ".join(rest)
    return Taxon(family=family, genus=genus, species=species, infraspecies=infra, author=author)


def _pdftotext(path: Path, first_page: int, last_page: int) -> str:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "ocr.txt"
        subprocess.run(
            ["pdftotext", "-f", str(first_page), "-l", str(last_page), path.as_posix(), out.as_posix()],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return out.read_text(encoding="utf-8", errors="replace")


def read_text(path: Path, first_page: int = 30, last_page: int = 507) -> str:
    """Return OCR text from a Collenette PDF or a plain text cache."""
    if path.suffix.lower() == ".pdf":
        return _pdftotext(path, first_page, last_page)
    return path.read_text(encoding="utf-8", errors="replace")


def _page_lines(page: str) -> list[str]:
    lines: list[str] = []
    for raw in page.splitlines():
        line = _clean_line(raw)
        if not line or _BAD_LINE_RE.match(line):
            continue
        lines.append(line)
    return lines


def iter_segments_from_text(
    text: str,
    source_id: str = "collenette-saudi",
    min_chars: int = 45,
    page_start: int = 1,
) -> Iterator[TextSegment]:
    family = ""
    entry_count = 0
    for page_no, page in enumerate(_PAGE_RE.split(text), start=page_start):
        lines = _page_lines(page)
        current_name = ""
        current_start = 0
        current_body: list[str] = []

        def flush() -> TextSegment | None:
            nonlocal current_name, current_body, entry_count
            body = _normalize(" ".join(current_body))
            name = current_name
            current_name = ""
            current_body = []
            if len(body) < min_chars or not _MORPH_WORD_RE.search(body):
                return None
            entry_count += 1
            return TextSegment(
                source="collenette-saudi",
                source_id=f"{source_id}:page-{page_no}:entry-{entry_count}",
                taxon=_taxon_from_name(name, family),
                organ="description",
                text=body,
                char_start=current_start,
                char_end=current_start + len(body),
                language="en",
            )

        for idx, line in enumerate(lines):
            if _FAMILY_RE.match(line):
                seg = flush()
                if seg:
                    yield seg
                family = line.title()
                continue
            m = _looks_like_entry(line)
            if m:
                seg = flush()
                if seg:
                    yield seg
                current_name = m.group("name")
                current_start = idx
                continue
            if current_name:
                current_body.append(line)
        seg = flush()
        if seg:
            yield seg


def iter_segments(
    path: Path,
    first_page: int = 30,
    last_page: int = 507,
    source_id: str | None = None,
) -> Iterator[TextSegment]:
    """Yield Collenette Saudi field-guide segments from PDF or cached text."""
    text = read_text(path, first_page=first_page, last_page=last_page)
    yield from iter_segments_from_text(
        text,
        source_id=source_id or "collenette-saudi",
        page_start=first_page if path.suffix.lower() == ".pdf" else 1,
    )
