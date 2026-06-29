"""Parse FlorML XML floras (Flore du Gabon, Flora Malesiana, Kew) into :class:`TextSegment`s.

FlorML structure (confirmed against ``flora-gabon/fdgvol1_final.xml``)::

    <publication lang="fr">
      <treatment>
        <taxon>
          <nomenclature><homotypes>
            <nom class="accepted">
              <name class="family">Sapotaceae</name>
              <name class="genus">Gambeya</name>
              <name class="species">africana</name>
              <name class="author">...</name>
            </nom>
          </homotypes></nomenclature>
          <feature class="description">
            <char class="leaves">Feuilles oblongues ... <br/> ...</char>
            <char class="flowers">...</char>
          </feature>
        </taxon>
      </treatment>
    </publication>

We keep only morphology features (see ``MORPHOLOGY_FEATURES``) — distribution/specimens/taxonomy
blocks are not phenotype descriptions. Description text contains nested presentational markup
(``<br/>``, ``<ol><li>``); we flatten it to plain text via ``itertext`` and normalize whitespace.
The ``char class`` becomes the segment's ``organ`` (a strong anatomical prior for the LLM, which
the 2016 pipeline did not exploit).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from lxml import etree

from flopo2.ingest.models import MORPHOLOGY_FEATURES, Sentence, Taxon, TextSegment

_WS_RE = re.compile(r"\s+")
# Sentence boundary: period/!/? + space + capital/digit. Floras abbreviate heavily ("env.", "cm.",
# "Vol."), so this is intentionally conservative; the LLM works per-segment anyway, and sentence
# splitting is only for finer provenance display.
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ0-9])")


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _element_text(el: etree._Element) -> str:
    """All descendant text of an element, flattened and whitespace-normalized.

    Block-level breaks (``<br/>``, ``<li>``, ``<p>``) are turned into spaces so adjacent
    sentences/list items don't merge into one token when their separating newline is absent.
    """
    for br in el.iter("br", "li", "p"):
        br.tail = " " + (br.tail or "")
    return _norm("".join(el.itertext()))


def _accepted_taxon(taxon_el: etree._Element) -> Taxon:
    """Extract the accepted-name parts from a <taxon> element.

    Uses the first ``<nom class="accepted">`` if present, else the first ``<nom>``. Name parts
    accumulate across the homotype block (family may sit on a parent taxon, but each taxon repeats
    the parts it carries)."""
    nom = taxon_el.find('.//nom[@class="accepted"]')
    if nom is None:
        nom = taxon_el.find(".//nom")
    if nom is None:
        return Taxon()
    parts: dict[str, str] = {}
    for name in nom.findall("name"):
        cls = name.get("class", "")
        val = _norm("".join(name.itertext()))
        if cls and val and cls not in parts:
            parts[cls] = val
    return Taxon(
        family=parts.get("family", ""),
        genus=parts.get("genus", ""),
        species=parts.get("species", ""),
        infraspecies=parts.get("infraspecies", parts.get("subspecies", parts.get("variety", ""))),
        author=parts.get("author", ""),
        year=parts.get("year", ""),
    )


def _fill_context(taxon: Taxon, family: str, genus: str) -> Taxon:
    """Fill missing family/genus on a taxon from document context, never overwriting present parts."""
    if taxon.family and taxon.genus:
        return taxon
    from dataclasses import replace

    return replace(taxon, family=taxon.family or family, genus=taxon.genus or genus)


def _parse_tree(path: Path) -> etree._ElementTree:
    # recover=True tolerates the occasional malformed entity in decades-old digitized files.
    parser = etree.XMLParser(recover=True, huge_tree=True)
    return etree.parse(path.as_posix(), parser)


def iter_segments(path: Path, source: str | None = None) -> Iterator[TextSegment]:
    """Yield one :class:`TextSegment` per morphological ``<char>`` block in a FlorML file."""
    tree = _parse_tree(path)
    root = tree.getroot()
    language = (root.get("lang") or "en").split("-")[0].lower()
    source = source or path.parent.name
    source_id = path.name

    # Family (and sometimes genus) is declared once on a higher-rank taxon and not repeated on the
    # species beneath it. Taxa appear in document (preorder) sequence, so we forward-fill the most
    # recently seen family/genus onto lower-rank taxa that omit them.
    last_family = ""
    last_genus = ""

    for taxon_el in root.iter("taxon"):
        taxon = _accepted_taxon(taxon_el)
        if taxon.family:
            last_family = taxon.family
            last_genus = ""  # a new family resets the genus context
        if taxon.genus:
            last_genus = taxon.genus
        taxon = _fill_context(taxon, last_family, last_genus)
        cursor = 0  # running offset within this taxon's concatenated description
        for feature in taxon_el.iter("feature"):
            if feature.get("class") not in MORPHOLOGY_FEATURES:
                continue
            for char in feature.iter("char"):
                organ = char.get("class", "") or feature.get("class", "")
                text = _element_text(char)
                if not text:
                    continue
                start = cursor
                end = start + len(text)
                cursor = end + 1  # +1 for the joining space between blocks
                yield TextSegment(
                    source=source,
                    source_id=source_id,
                    taxon=taxon,
                    organ=organ,
                    text=text,
                    char_start=start,
                    char_end=end,
                    language=language,
                )


def iter_segments_dir(directory: Path, pattern: str = "*.xml") -> Iterator[TextSegment]:
    """Yield segments across all FlorML files in a directory."""
    for path in sorted(Path(directory).glob(pattern)):
        yield from iter_segments(path, source=Path(directory).name)


def split_sentences(text: str) -> list[Sentence]:
    """Split a segment into sentences with offsets relative to the segment text."""
    sentences: list[Sentence] = []
    pos = 0
    for piece in _SENT_RE.split(text):
        idx = text.find(piece, pos)
        if idx < 0:
            idx = pos
        sentences.append(Sentence(text=piece, start=idx, end=idx + len(piece)))
        pos = idx + len(piece)
    return sentences
