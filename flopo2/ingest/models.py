"""Shared ingestion data model.

A :class:`TextSegment` is the atomic unit of input to extraction and the anchor for provenance:
one organ-scoped block of description text for one taxon, with exact character offsets into the
source so every downstream trait assertion can point back to the words that justify it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Morphological feature classes worth extracting traits from (vs. distribution/specimens/taxonomy
# which are not phenotype descriptions). FlorML `<feature class=...>` values.
MORPHOLOGY_FEATURES = {"description", "morphology", "bark", "wood", "habit"}


@dataclass(frozen=True)
class Taxon:
    """Accepted-name parts of a taxon, as found in a flora treatment (pre-normalization)."""

    family: str = ""
    genus: str = ""
    species: str = ""
    infraspecies: str = ""
    author: str = ""
    year: str = ""

    @property
    def name_string(self) -> str:
        """Best-effort scientific name string for GNparser (Phase 2).

        Requires a genus (then include species/infraspecies/author) or, failing that, a family.
        An author fragment alone (e.g. "Juss.") is not a usable taxon name and yields "".
        """
        if self.genus:
            parts = [self.genus, self.species, self.infraspecies, self.author]
            return " ".join(p for p in parts if p).strip()
        return self.family

    @property
    def rank(self) -> str:
        if self.infraspecies:
            return "infraspecies"
        if self.species:
            return "species"
        if self.genus:
            return "genus"
        if self.family:
            return "family"
        return "unknown"


@dataclass(frozen=True)
class TextSegment:
    """One organ-scoped description block for one taxon, with provenance offsets."""

    source: str  # e.g. "flora-gabon" / "fdac"
    source_id: str  # file name or row id
    taxon: Taxon
    organ: str  # FlorML `char class` / fdac subheading (the anatomical prior)
    text: str  # normalized plain text of the block
    char_start: int  # offset of this block within the taxon's concatenated description
    char_end: int
    language: str  # "fr" / "en"

    def to_row(self) -> dict:
        d = asdict(self)
        d["taxon"] = self.taxon.name_string
        d["taxon_family"] = self.taxon.family
        d["taxon_rank"] = self.taxon.rank
        return d


@dataclass
class Sentence:
    """A sentence within a segment, with offsets relative to the segment text."""

    text: str
    start: int
    end: int
    meta: dict = field(default_factory=dict)
