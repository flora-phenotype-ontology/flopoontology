"""Parse Kew's African Flora export (``floras-other/Kew African Flora Species.xml``).

This file is NOT FlorML — it is a Microsoft Access ``<dataroot>`` export with one ``<Specieslist>``
record per taxon::

    <Specieslist>
      <Name.family>Ranunculaceae</Name.family>
      <Name.genus>Clematis</Name.genus>
      <Name.rank>species</Name.rank>
      <author>...</author>
      <description>Mostly woody climbing ... Leaves opposite ... Flowers regular ...</description>
    </Specieslist>

The description is a single English free-text block with no organ markup, so we emit one segment
with organ ``"description"`` (the LLM infers per-sentence organ downstream). Parsed with
``iterparse`` + ``el.clear()`` to stream the ~37 MB file without loading it all into memory.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from lxml import etree

from flopo2.ingest.models import Taxon, TextSegment

_WS_RE = re.compile(r"\s+")


def _text(el: etree._Element, tag: str) -> str:
    child = el.find(tag)
    return _WS_RE.sub(" ", "".join(child.itertext())).strip() if child is not None else ""


def iter_segments(path: Path, source: str = "kew-african", language: str = "en") -> Iterator[TextSegment]:
    context = etree.iterparse(
        Path(path).as_posix(), events=("end",), tag="Specieslist", recover=True, huge_tree=True
    )
    for _event, el in context:
        description = _text(el, "description")
        if description:
            taxon = Taxon(
                family=_text(el, "Name.family"),
                genus=_text(el, "Name.genus"),
                species=_text(el, "Name.species"),
                author=_text(el, "author"),
            )
            yield TextSegment(
                source=source,
                source_id=_text(el, "name_id") or _text(el, "taxon_id"),
                taxon=taxon,
                organ="description",
                text=description,
                char_start=0,
                char_end=len(description),
                language=language,
            )
        # Free the element (and its now-processed siblings) to keep memory flat.
        el.clear()
        while el.getprevious() is not None:
            del el.getparent()[0]
