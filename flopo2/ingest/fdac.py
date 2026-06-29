"""Parse the Flore d'Afrique Centrale descriptions CSV into :class:`TextSegment`s.

``flora-central-africa/fdacDescriptions.csv`` is pipe-delimited with 25 columns (see header). The
``description`` column is French free text in which organ sections are delimited by
``<span class='subheading'>Organ</span>`` markers, e.g.::

    <span class='subheading'>Tiges</span> ... non ramifiées ...
    <span class='subheading'>Feuilles</span> souvent dressées ...

We split on those subheadings: each subheading becomes the segment ``organ`` (free text, grounded
to PO later) and the following text up to the next subheading is the segment text. Remaining HTML
tags are stripped. Text before the first subheading (often the habit) is emitted with organ "habit".
"""

from __future__ import annotations

import csv
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from flopo2.ingest.models import Taxon, TextSegment

_SUBHEAD_RE = re.compile(r"<span\s+class=['\"]subheading['\"]\s*>(.*?)</span>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# The CSV has very large description cells; lift the field-size limit.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _strip(text: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def _taxon_of(row: dict) -> Taxon:
    return Taxon(
        family=(row.get("family") or "").strip(),
        genus=(row.get("genus") or "").strip(),
        species=(row.get("species") or "").strip(),
        infraspecies=(row.get("subspecies") or row.get("variety") or "").strip(),
        author=(row.get("authority") or "").strip(),
    )


def _split_organs(description: str) -> list[tuple[str, str]]:
    """Split a description into (organ, text) sections on subheading spans."""
    sections: list[tuple[str, str]] = []
    matches = list(_SUBHEAD_RE.finditer(description))
    if not matches:
        text = _strip(description)
        return [("description", text)] if text else []

    # Preamble before the first subheading (typically the habit/growth form).
    pre = _strip(description[: matches[0].start()])
    if pre:
        sections.append(("habit", pre))

    for i, m in enumerate(matches):
        organ = _strip(m.group(1)).lower()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(description)
        text = _strip(description[body_start:body_end])
        if organ and text:
            sections.append((organ, text))
    return sections


def iter_segments(path: Path, source: str = "fdac", language: str = "fr") -> Iterator[TextSegment]:
    """Yield one :class:`TextSegment` per organ section per row of the fdac CSV."""
    with Path(path).open(encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="|")
        for row in reader:
            description = row.get("description") or ""
            if not description.strip():
                continue
            taxon = _taxon_of(row)
            row_id = (row.get("name_id") or row.get("uuid") or "").strip()
            cursor = 0
            for organ, text in _split_organs(description):
                start = cursor
                end = start + len(text)
                cursor = end + 1
                yield TextSegment(
                    source=source,
                    source_id=row_id,
                    taxon=taxon,
                    organ=organ,
                    text=text,
                    char_start=start,
                    char_end=end,
                    language=language,
                )
