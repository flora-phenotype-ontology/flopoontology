"""Deterministically recover clause-initial hyphenated shape continua and exact colour compounds.

The baseline withholds every quality cue touching a hyphen or slash
(``hyphenated_or_slash_compound``).  Earlier passes recovered exact PATO/FLOPO colour compounds
and sent isolated gross-outline pairs to two-model LLM review, but both used a broad
proximity-only logical-connector guard: any ``or``/``to`` within 72 characters, including
numeric ranges and alternatives of other attributes, withheld the compound.  This pass replaces
proximity with an explicit phrase structure, and it only accepts a compound when all of the
following hold.

* The whole hyphenated token is either two distinct planar gross-outline values
  (``ovate-lanceolate``, ``oblongues-elliptiques``) or an exact PATO compound-colour label/EXACT
  synonym or an audited live FLOPO composite-colour value (``yellow-green``, ``greenish-brown``).
  Shape endpoints are read from a closed EN/FR lexicon; ambiguous oval/ovale/obovale, 3-D solids,
  apex/base terms (acuminate, cordate) and prefix modifiers (sub-, long-, much-) are excluded.
* The bearer is an explicit PO noun (a baseline bearer cue, ``leaf-blade``, or an exact PO
  lexicon label/synonym) that opens its semicolon/sentence clause.  The compound either follows
  it directly or opens a later comma member, and every member in between is a safe descriptive
  member: measurements, counts, degree adverbs and adjective-shaped words, but no nested or
  subset noun (lobes, pinnae, paillettes, axillary, lateral, the ...) and no relational
  preposition.  French adjective compounds must agree in number/gender with the bearer.  When no
  explicit bearer exists, a compound in the first clause of a typed organ-heading segment
  (``gousses``, ``graines``) may use that heading.  Any other direct pre-modifier (``pale``,
  ``±``, ``sub-``) blocks the pass.
* E2 (schema extension, curator approval 2026-09-18): a closed width-degree cue directly before
  a shape compound (``narrowly oblong-lanceolate``, ``largement ovales-elliptiques``) modifies the
  whole compound.  It is kept at assertion level (``degree_qualifier`` narrowly/broadly, verbatim
  ``modality_text`` with offsets) and the expression span starts at the cue; the relation
  endpoints are unchanged.
* E3 (schema extension, curator approval 2026-09-18; :mod:`flopo2.annotation.positional`):
  - an indumentum compound (``stellate-pubescent``, ``white-tomentose``, ``tomenteux-étoilé``)
    asserts the closed pilosity head on the organ and the element (hair shape or colour) as a
    ``has_part`` restriction on PO trichome, with the verbatim element as ``part_text``;
  - a colour compound naming hairs (``with reddish-brown hairs``, ``à poils brun-rouge``) asserts
    hairy on the organ and the colour on the trichome part, never on the organ;
  - a directly attached surface cue (``beneath``, ``above``, ``en dessous``, ``à la face
    inférieure``; ``inside``/``outside`` for perianth members and bracts) on an indumentum or
    colour compound substitutes the reviewed PO surface class of
    :func:`flopo2.annotation.positional.surface_scope` as bearer and records ``bearer_scope``
    (``mode = substituted_bearer``); shape compounds never take a surface scope.
  Without its own cue, an indumentum or colour compound is withheld when the clause names any
  surface (the value may be restricted to one side), and another pilosity value in the clause
  blocks an indumentum assertion.
* The compound is directly followed by punctuation, end of text, a measurement, or ``in outline``;
  never by a noun, a connector, or a parenthetical variant.
* No other value of the same family occurs anywhere else in the clause, so alternatives, ranges
  (``ovate to ovate-lanceolate``) and lists of shapes/colours stay unresolved.
* Negation, comparison, developmental/temporal context, sex/category-restricted bearers, reported
  attributions and (for colour) pattern, covering and subregion scopes are excluded.
* The emitted assertion passes the production gate with an allowed PO-PATO combination.

A shape continuum is a ``qualitative_value_relation`` (interpretation ``continuum``) on PATO
shape, exactly like the reviewed shape campaigns; colour compounds are atomic EQ assertions (PATO)
or PATO colour with a FLOPO value in ``value_terms``.  No identifier is minted.  Output is a
per-segment delta; :func:`apply_delta` applies it to a copy for validation.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from flopo2.annotation.operands import parse_qualifier_cue
from flopo2.annotation.positional import HAS_PART, TRICHOME, find_surface_cues, surface_scope
from flopo2.annotation.provenance import ensure_source_statements
from flopo2.extract import baseline
from flopo2.extract.leaflet_context import leaflet_bearer
from flopo2.owl.annotation_class import ensure_annotation_class_iri
from flopo2.verify import recover_exact_pato_compounds as exact
from flopo2.verify.gates import (
    check_assertion,
    load_catalog_ids,
    load_combinations,
    load_eq_registry,
    load_flopo_ids,
    load_pato_attribute_terms,
    load_signature_registry,
)
from flopo2.verify.local_bearer_table import load_reviewed_bearers
from flopo2.verify.recover_flopo_value_compounds import flopo_value_lexicon


TARGET_REASON = "hyphenated_or_slash_compound"
EXTRACTOR = "deterministic_claude_hyphen_compound_recovery_v1"
SHAPE_ATTRIBUTE = "PATO_0000052"
COLOUR_ATTRIBUTE = "PATO_0000014"
LEAF_LAMINA = "PO_0020039"
DASHES = "-–—"

# Closed planar gross-outline lexicon.  Oval/ovale/obovale are deliberately absent (PATO maps
# oval to both ovate and elliptic), as are 3-D solids (ovoid, ellipsoid, globose) whose pairing
# with planar terms mixes dimensions, and apex/base qualities (acuminate, cordate, obtuse).
SHAPE_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("PATO_0002330", r"oblanceolate|oblanc[ée]ol[ée](?:e|es|s)?"),
    ("PATO_0001877", r"lanceolate|lanc[ée]ol[ée](?:e|es|s)?"),
    ("PATO_0001199", r"linear|lin[ée]aires?"),
    ("PATO_0000946", r"oblong(?:ue|ues|s)?"),
    ("PATO_0000947", r"elliptic(?:al)?|elliptiques?"),
    ("PATO_0001936", r"obovate|obov[ée](?:e|es|s)?"),
    ("PATO_0001891", r"ovate|ov[ée](?:e|es|s)?"),
    ("PATO_0001875", r"triangular|triangulaires?|deltoid|delto[ïi]des?"),
    ("PATO_0001934", r"orbicular|orbiculaires?"),
    ("PATO_0001937", r"spat?hulate|spatul[ée](?:e|es|s)?"),
    ("PATO_0001954", r"subulate|subul[ée](?:e|es|s)?"),
    ("PATO_0001938", r"rhomboid(?:al)?|rhombo[ïi]d(?:al|ale|aux|ales|e|es)"),
)
# E3 closed indumentum lexicon.  Heads are the pilosity values the baseline grounds (pubescent is
# the baseline's PATO_0001320 ``pubescent hair``; PATO_0000455 stays manual-review); elements are
# the hair shape ``stellate`` and plain PATO colours whose trichome pairs are curator-approved.
INDUMENT_HEADS: tuple[tuple[str, str], ...] = (
    ("PATO_0001320", r"pubescent|pubescente|pubescents|pubescentes"),
    ("PATO_0002341", r"tomentose|tomenteux|tomenteuse|tomenteuses"),
    ("PATO_0000454", r"hairy|velu|velue|velus|velues"),
    ("PATO_0104041", r"velutinous|velvety|velout[ée]|velout[ée]e|velout[ée]s|velout[ée]es"),
)
INDUMENT_ELEMENTS: tuple[tuple[str, str], ...] = (
    ("PATO_0002065", r"stellate|[ée]toil[ée](?:e|es|s)?"),
    ("PATO_0000323", r"white|blanc|blanche|blancs|blanches"),
    ("PATO_0000950", r"grey|gray|gris|grise|grises"),
    ("PATO_0000952", r"brown|brun|brune|bruns|brunes"),
    ("PATO_0000324", r"yellow|jaune|jaunes"),
    ("PATO_0000317", r"black|noir|noire|noirs|noires"),
    ("PATO_0000322", r"red|rouge|rouges"),
)
HAIRY = "PATO_0000454"
PILOSITY_IDS = frozenset(
    {"PATO_0000453", "PATO_0000455", "PATO_0000454", "PATO_0001320", "PATO_0002341", "PATO_0104041"}
)
_HEAD_ALT = "|".join(f"(?:{pattern})" for _id, pattern in INDUMENT_HEADS)
_ELEMENT_ALT = "|".join(f"(?:{pattern})" for _id, pattern in INDUMENT_ELEMENTS)
_INDUMENT_TOKEN = re.compile(
    rf"^(?P<element>{_ELEMENT_ALT})(?P<dash>[{DASHES}])(?P<head>{_HEAD_ALT})$", re.IGNORECASE
)
# French also writes the head first (``tomenteux-étoilé``).
_INDUMENT_TOKEN_HEAD_FIRST = re.compile(
    rf"^(?P<head>{_HEAD_ALT})(?P<dash>[{DASHES}])(?P<element>{_ELEMENT_ALT})$", re.IGNORECASE
)
_HAIR_PREFIX = re.compile(
    r"(?:\b(?:with|covered\s+with|clothed\s+with)|\b(?:à|de|couverte?s?\s+de)\s+poils)\s+"
    r"(?:(?:short|long|dense|sparse|scattered|appressed|spreading|stiff|soft|fine|minute|"
    r"numerous|courts|longs|denses|[ée]pars|appliqu[ée]s|appr?im[ée]s|[ée]tal[ée]s|raides|fins)"
    r"\s*,?\s+)*$",
    re.IGNORECASE,
)
_HAIR_NOUN_AFTER = re.compile(r"^\s+(?:hairs|trichomes)\b", re.IGNORECASE)
_FRENCH_HAIR_PREFIX = re.compile(r"poils\s+(?:\w+\s+)*$", re.IGNORECASE)
_OTHER_PILOSITY = re.compile(
    r"(?<![\w])(?:glab\w*|pub[eé]\w*|tomen\w*|hair\w*|hirs\w*|hirt\w*|pilos\w*|pilu\w*|"
    r"villo\w*|velu\w*|velout\w*|velut\w*|lanat\w*|lain\w*|seric\w*|soyeu\w*|strig\w*|"
    r"scabr\w*|setos\w*|s[ée]teu\w*|hisp\w*|cili\w*|poil\w*|indument\w*|squam\w*|"
    r"l[ée]pido\w*|woolly|downy|floccos\w*|farin\w*|arachn\w*)",
    re.IGNORECASE,
)
_SURFACE_FAMILIES = frozenset({"indumentum", "hair_colour", "colour"})
_E3_FAMILIES = frozenset({"indumentum", "hair_colour"})
_NOVEL_PAIR_REASONS = frozenset({"po_pato_novel", "nested_po_pato_novel"})


def _lexicon_id(table: tuple[tuple[str, str], ...], word: str) -> str:
    for identifier, pattern in table:
        if re.fullmatch(pattern, word, re.IGNORECASE):
            return identifier
    return ""


def match_indument(text: str, start: int, end: int) -> CompoundValue | None:
    """E3: ``<element>-<pilosity head>`` (or French head-first) indumentum compound."""

    token = text[start:end]
    match = _INDUMENT_TOKEN.match(token) or _INDUMENT_TOKEN_HEAD_FIRST.match(token)
    if match is None:
        return None
    head_id = _lexicon_id(INDUMENT_HEADS, match.group("head"))
    element_id = _lexicon_id(INDUMENT_ELEMENTS, match.group("element"))
    if not head_id or not element_id:
        return None
    element_start = start + match.start("element")
    element_end = start + match.end("element")
    part = {
        "property": HAS_PART,
        "filler_class": TRICHOME,
        "qualities": [element_id],
        "part_text": text[element_start:element_end],
        "part_start": element_start,
        "part_end": element_end,
    }
    return CompoundValue(
        "indumentum", start, end, token, head_id, (), None, _normal_form(token), part=part
    )


def with_hair_context(text: str, compound: CompoundValue, language: str) -> CompoundValue:
    """E3: a colour compound naming hairs (``with reddish-brown hairs``) colours the trichomes."""

    if compound.family != "colour":
        return compound
    window = text[max(0, compound.start - 80) : compound.start]
    prefix = _HAIR_PREFIX.search(window)
    suffix = _HAIR_NOUN_AFTER.match(text[compound.end :])
    if prefix is None:
        return compound
    is_french = "poils" in prefix.group(0).lower()
    if is_french == bool(suffix):
        # English needs the hair noun after the colour; French names it before the colour.
        return compound
    colour_id = compound.value_terms[0] if compound.value_terms else compound.pato_id
    part = {
        "property": HAS_PART,
        "filler_class": TRICHOME,
        "qualities": [colour_id],
        "part_text": text[compound.start : compound.end],
        "part_start": compound.start,
        "part_end": compound.end,
    }
    return replace(
        compound,
        family="hair_colour",
        pato_id=HAIRY,
        value_terms=(),
        part=part,
        prefix_start=max(0, compound.start - 80) + prefix.start(),
        suffix_end=compound.end + suffix.end() if suffix else None,
    )


def with_surface_cue(text: str, compound: CompoundValue) -> CompoundValue:
    """E3: attach a surface cue directly after or directly before the expression."""

    if compound.family not in _SURFACE_FAMILIES:
        return compound
    start, end = compound.expression_start, compound.expression_end
    gap = re.match(r"[ \t]+", text[end:])
    if gap:
        cue_start = end + gap.end()
        cues = [cue for cue in find_surface_cues(text, cue_start, min(len(text), cue_start + 40))
                if cue[1] == cue_start]
        if cues:
            side, cue_s, cue_e = max(cues, key=lambda cue: cue[2])
            return replace(compound, surface=(side, cue_s, cue_e))
    before = re.search(r"[ \t]+$", text[max(0, start - 40) : start])
    if before:
        cue_end = start - len(before.group(0))
        cues = [cue for cue in find_surface_cues(text, max(0, cue_end - 40), cue_end)
                if cue[2] == cue_end]
        if cues:
            side, cue_s, cue_e = min(cues, key=lambda cue: cue[1])
            return replace(compound, surface=(side, cue_s, cue_e))
    return compound


_SHAPE_WORD = {
    pato_id: re.compile(rf"(?:{pattern})", re.IGNORECASE) for pato_id, pattern in SHAPE_ENDPOINTS
}
_SHAPE_IDS = frozenset(pato_id for pato_id, _pattern in SHAPE_ENDPOINTS)
_SHAPE_ALTERNATION = "|".join(f"(?:{pattern})" for _pato, pattern in SHAPE_ENDPOINTS)
_SHAPE_TOKEN = re.compile(
    rf"^(?P<left>{_SHAPE_ALTERNATION})(?P<dash>[{DASHES}])(?P<gap>[ \t]?)"
    rf"(?P<right>{_SHAPE_ALTERNATION})$",
    re.IGNORECASE,
)

# Any other gross-outline word in the clause signals a list, alternative or range.
_OTHER_SHAPE = re.compile(
    r"(?<![\w])(?:sub)?(?:"
    r"(?:ob)?lanc[eé]ol\w*|lin[eé]a(?:r|ire)\w*|oblong\w*|ellip\w*|(?:ob)?ov(?:at|al|oid|o[ïi]d)\w*|"
    r"(?:ob)?ov[eé]\w*|triang\w*|delto\w*|orbic\w*|spat\w*|subul\w*|rhomb\w*|reni\w*|"
    r"r[ée]niform\w*|filiform\w*|glob\w*|falcat\w*|falciform\w*|trullat\w*|cun[eé]i\w*|"
    r"round(?:ed|ish)?|rond\w*|arrondi\w*|circula\w*|cylindr\w*|fusiform\w*|clavat\w*|"
    r"sagitt\w*|hastat\w*|cordat\w*|cordiform\w*|lyr[ée]\w*|pandur\w*)",
    re.IGNORECASE,
)
_OTHER_COLOUR = re.compile(
    r"(?<![\w])(?:white|whitish|cream\w*|yellow\w*|orange\w*|red|reddish|pink\w*|purpl\w*|"
    r"violet\w*|blue|bluish|green\w*|brown\w*|black\w*|grey\w*|gray\w*|golden|gold|silver\w*|"
    r"ferrugin\w*|rust\w*|fulvous|tawny|straw|maroon|crimson|scarlet|lilac|mauve|magenta|"
    r"rose|rosy|bronze\w*|olive|chestnut|fawn|buff|ochr\w*|tinged|flushed|suffused|spotted|"
    r"streaked|striped|mottled|variegated|dotted|blotched|banded|marked|"
    r"blanc\w*|jaun\w*|rouge\w*|vert|verte|verts|vertes|verd\w*|brun\w*|noir\w*|gris\w*|"
    r"bleu\w*|viol\w*|pourpr\w*|ros[ée]\w*|orang[ée]\w*|roux|rousse\w*|dor[ée]\w*|"
    r"argent\w*|teint\w*|tach\w*|ray[ée]\w*|stri[ée]\w*)(?![\w])",
    re.IGNORECASE,
)
_RIGHT_BOUNDARY = re.compile(
    r"^(?:\s*$|\s*[,;.:)\]]|\s*\(\s*\d|\s+\d|\s+(?:c\.|ca\.|ca\s|about|up\s+to|"
    r"env\.|environ|d['’]environ|de\s+\(?\d|jusqu)|\s+in\s+(?:outline|shape|general\s+outline)"
    r"\b|\s+en\s+contour\b|\s+dans\s+l['’]ensemble\b)",
    re.IGNORECASE,
)
_EXTRA_BEARERS = (
    # ``Leaf-blade`` must not attach to the whole leaf through the generic ``leaf`` cue.
    (LEAF_LAMINA, re.compile(r"\bleaf[- ]?blades?\b", re.IGNORECASE)),
)


@lru_cache(maxsize=1)
def _reviewed_bearers() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Exact aliases from ``config/reviewed_local_bearers.tsv`` (live PO and released
    FLOPO-local support classes such as calyx lobe); contextual rows are excluded."""

    path = Path("config/reviewed_local_bearers.tsv")
    if not path.exists():
        return ()
    out = []
    for row in load_reviewed_bearers(path):
        words = re.split(r"[\s-]+", str(row.get("surface_form", "") or "").strip())
        if words and words[0] and row.get("po_id"):
            phrase = r"[\s-]+".join(re.escape(word) for word in words)
            out.append((row["po_id"], re.compile(rf"\b{phrase}\b", re.IGNORECASE)))
    return tuple(out)
_UNMODELLED_HEADING = re.compile(
    r"(?<!\w)(?:♂|♀|male|female|staminate|pistillate|m[âa]les?|femelles?|st[ée]riles?|"
    r"fertiles?|young|jeunes?|mature|m[ûu]rs?|description|habit)(?!\w)",
    re.IGNORECASE,
)
_SEX_CATEGORY = re.compile(
    r"(?<!\w)(?:♂|♀|male|female|staminate|pistillate|m[âa]les?|femelles?)(?!\w)",
    re.IGNORECASE,
)
_ABSENCE = re.compile(
    r"\b(?:absent|absents|absente|absentes|wanting|lacking|missing|manquant\w*|nul|nuls|"
    r"nulle|nulles|or\s+0|ou\s+0)\b",
    re.IGNORECASE,
)
_BEARER_TAIL = re.compile(r"^\s*[,:]?\s*$")
_SUBREGION_SCOPE = re.compile(
    r"\b(?:apex|apices|apical(?:ly)?|base|bases|basal(?:ly)?|tips?|margins?|sommets?|"
    r"extr[ée]mit[ée]s?|marges?|bords?|pointes?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CompoundValue:
    family: str  # "shape" or "colour"
    start: int
    end: int
    token: str
    pato_id: str  # top-level quality (attribute for shape/FLOPO colour; value for PATO colour)
    value_terms: tuple[str, ...] = ()
    relation: dict[str, Any] | None = None
    lexical_form: str = ""
    # E2: verbatim width-degree cue directly before the compound (assertion-level qualifier).
    degree_start: int | None = None
    degree_end: int | None = None
    degree_qualifier: str = ""
    # E3: typed trichome part (indumentum element or hair colour), a verbatim prefix/suffix
    # (``with ... hairs``) and a directly attached surface cue ``(cue_side, start, end)``.
    part: dict[str, Any] | None = None
    prefix_start: int | None = None
    suffix_end: int | None = None
    surface: tuple[str, int, int] | None = None

    @property
    def expression_start(self) -> int:
        starts = [self.start]
        starts += [value for value in (self.degree_start, self.prefix_start) if value is not None]
        if self.surface is not None:
            starts.append(self.surface[1])
        return min(starts)

    @property
    def expression_end(self) -> int:
        ends = [self.end, self.suffix_end if self.suffix_end is not None else self.end]
        if self.surface is not None:
            ends.append(self.surface[2])
        return max(ends)


@dataclass(frozen=True)
class Bearer:
    po_id: str
    method: str  # "clause_initial_explicit" or "organ_heading"
    text: str = ""
    start: int | None = None
    end: int | None = None


class Resources:
    """Catalogues and lexicons shared by every record."""

    def __init__(
        self,
        *,
        po_lexicon: Path = Path("config/po_lexicon.tsv"),
        pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
        registry: Path = Path("config/flopo_id_registry.tsv"),
        combinations: Path = Path("config/valid_combinations.tsv"),
        pato_obo: Path = Path("ont/quality.obo"),
    ) -> None:
        self.bearers = exact.BearerResolver(po_lexicon)
        self.po_ids = load_catalog_ids(po_lexicon)
        self.pato_ids = load_catalog_ids(pato_lexicon)
        self.attribute_ids = load_pato_attribute_terms(pato_lexicon)
        self.flopo_ids = load_flopo_ids(registry)
        self.registry = load_eq_registry(registry)
        self.signature_registry = load_signature_registry(registry)
        self.combinations = load_combinations(combinations)
        pato_colours = exact.exact_compound_colour_lexicon(pato_obo)
        flopo_colours = flopo_value_lexicon(registry)
        # PATO first: a live PATO class wins over a FLOPO value with the same lexical form.
        self.colours: dict[str, tuple[str, str, str]] = {
            form: ("flopo", flopo_id, label) for form, (flopo_id, label) in flopo_colours.items()
        }
        for form, (pato_id, label) in pato_colours.items():
            if pato_id in self.pato_ids:
                self.colours[form] = ("pato", pato_id, label)
        self.colour_ids = frozenset(identifier for _kind, identifier, _label in self.colours.values())
        missing = [
            pato_id
            for pato_id, _pattern in SHAPE_ENDPOINTS
            if pato_id not in self.pato_ids
        ]
        if missing or SHAPE_ATTRIBUTE not in self.attribute_ids:
            raise ValueError(f"shape lexicon references unknown PATO ids: {missing}")


def _normal_form(value: str) -> str:
    return re.sub(rf"[\s{re.escape(DASHES)}]+", " ", value.casefold()).strip()


def _shape_id(word: str) -> str:
    for pato_id, pattern in _SHAPE_WORD.items():
        if pattern.fullmatch(word):
            return pato_id
    return ""


def match_compound(text: str, start: int, end: int, resources: Resources) -> CompoundValue | None:
    """Return the complete-token compound value at ``[start, end)``, if it is in scope."""

    token = text[start:end]
    if "/" in token or not any(dash in token for dash in DASHES):
        return None
    if token[0] in DASHES or token[-1] in DASHES:
        return None
    shape = _SHAPE_TOKEN.match(token)
    if shape:
        left_id = _shape_id(shape.group("left"))
        right_id = _shape_id(shape.group("right"))
        if not left_id or not right_id or left_id == right_id:
            return None
        from_start = start + shape.start("left")
        from_end = start + shape.end("left")
        connector_start = start + shape.start("dash")
        connector_end = start + shape.end("dash")
        to_start = start + shape.start("right")
        to_end = start + shape.end("right")
        relation = {
            "interpretation": "continuum",
            "from_value": left_id,
            "to_value": right_id,
            "from_text": text[from_start:from_end],
            "from_start": from_start,
            "from_end": from_end,
            "connector_text": text[connector_start:connector_end],
            "connector_start": connector_start,
            "connector_end": connector_end,
            "to_text": text[to_start:to_end],
            "to_start": to_start,
            "to_end": to_end,
        }
        return CompoundValue(
            "shape", start, end, token, SHAPE_ATTRIBUTE, (), relation, _normal_form(token)
        )
    indument = match_indument(text, start, end)
    if indument is not None:
        return indument
    colour = resources.colours.get(_normal_form(token))
    if colour:
        kind, identifier, _label = colour
        if kind == "pato":
            return CompoundValue("colour", start, end, token, identifier, (), None, _normal_form(token))
        return CompoundValue(
            "colour", start, end, token, COLOUR_ATTRIBUTE, (identifier,), None, _normal_form(token)
        )
    return None


_MEMBER_SPLIT = re.compile(r"(?<!\d),|,(?!\d)|:")
_NUMERIC = re.compile(r"^[\d(\[][\d.,·/()\[\]–—\-+×x≈?]*$|^[–—\-(]+\d[\d.,·()–—\-]*$")
_TAIL_WORDS = frozenset(
    """
    mm mm. cm cm. dm dm. m m. µm long wide broad by pairs pair paires paire jugate diam
    diam. diameter across high tall c. ca. ca about up to or and ou et x × ± d'env. env.
    environ long. longs longue longues large larges haut haute hauts hautes lg. lat. × ≈
    """.split()
)
_ADVERBS = frozenset(
    """
    very densely sparsely slightly usually often sometimes rarely somewhat almost nearly
    thinly firmly shortly not more less or and to ou et ± rather quite distinctly minutely
    finely strongly weakly markedly generally mostly always never shallowly deeply
    très peu plus moins souvent parfois généralement non densément
    """.split()
)
_ADJECTIVE_WORDS = frozenset(
    """
    opposite subopposite compound entire free flat thin thick erect simple fleshy large small short long broad narrow dense
    lax stiff soft hard smooth rough firm fine sessile acute obtuse glabrous subsessile
    """.split()
)
_EN_ADJECTIVE_SUFFIX = re.compile(
    r"(?:ous|ose|ate|ated|ed|ent|ant|ic|ical|id|ile|ine|ish|less|ular|ary|oid|form|ing|ly|"
    r"escent|ulate|ellate)$",
    re.IGNORECASE,
)
_FR_ADJECTIVE_SUFFIX = re.compile(
    r"(?:ée?s?|eux|euse|euses|aires?|iques?|iles?|ent(?:e|es|s)?|ant(?:e|es|s)?|aux|ales?|"
    r"i[fv]e?s?|[âa]tres?|o[ïi]des?|formes?|bres?|aves?|aces?|ues?|gu[ëe]s?)$",
    re.IGNORECASE,
)
_FR_ADJECTIVE_WORDS = frozenset(
    """
    étroit étroite étroits étroites épais épaisse épaisses mince minces grêle grêles large
    larges court courte courts courtes plan plane plans planes glabre glabres libre libres
    entier entière entiers entières obtus obtuse obtuses aigu aiguë aigus aiguës égaux égales
    inégaux inégales subégaux subégales raide raides mou molle molles lisse lisses rigide
    rigides souple souples charnu charnue charnus charnues alterne alternes opposé opposée
    opposés opposées simple simples
    """.split()
)
# Measurement phrases whose preposition does not introduce a nested noun.
_MEASURE_PHRASE = re.compile(
    r"\b(?:de|d['’]env\.?|d['’]environ)\s+(?=[\d(±≤≥]|c\.|env)|"
    r"\bde\s+(?:long|large|diam\.?|diam[èe]tre|haut|hauteur|[ée]paisseur)\b|"
    r"\bin\s+(?:diam\.?|diameter|outline|width|length|\(?\d[\d–\-()]*\s+pairs?)\b|"
    r"\bin\s+(?=\(?\d)",
    re.IGNORECASE,
)
_NESTED_NOUN = re.compile(
    r"^(?:lobes?|lobules?|dents?|teeth|tooth|segments?|pinnae?|pinnules?|pinnas?|[ée]cailles?|"
    r"scales?|poils?|hairs?|glumes?|lemmas?|lemmes?|pal[ée]as?|articles?|loges?|locules?|ailes?|"
    r"wings?|stries?|nervures?|veins?|nerves?|ribs?|c[ôo]tes?|marges?|margins?|bords?|edges?|"
    r"sommets?|apex|apices|tips?|bases?|spines?|[ée]pines?|awns?|ar[êe]tes?|parts?|parties?|"
    r"tubes?|gorges?|throats?|mouths?|surfaces?|faces?|sides?|c[ôo]t[ée]s?|claws?|onglets?|"
    r"limbs?|blades?|ones?|those|these|les|la|le|the|ceux|celles|l['’]\w*|d['’]\w*|"
    r"male|female|lateral|dorsal|ventral|inner|outer|upper|lower|median|middle|terminal|basal|"
    r"apical|cauline|radical|externes?|internes?|sup[ée]rieure?s?|inf[ée]rieure?s?|lat[ée]ra(?:l|le|les|ux)|"
    r"m[ée]dian(?:e|es|s)?|terminal(?:e|es)?|terminaux|basa(?:l|le|les|ux)|with|avec|of|du|des|"
    r"sur|sous|in|on|at|au|aux|par|from|into|dans|en|between|entre|each|chaque|some|certain\w*|"
    r"quelques|other|autres?|similar|semblables?|like|comme|glandes?|glands?|stipes?|nectaires?|"
    r"disques?|discs?|disks?|rings?|anneaux|t[êe]tes?|heads?|ligules?|lips?|l[èe]vres?|callus|"
    r"spurs?|[ée]perons?|beaks?|becs?|rays?|rayons?|bristles?|soies?|setae?|paillettes?|"
    r"squames?|glandules?|trichomes?|prickles?|aiguillons?|tunics?|tuniques?|sheaths?|gaines?|"
    r"stalks?|pieds?|ocreae?|oc?hr[ée]as?|spathes?|pappus|involucres?|auricles?|oreillettes?|"
    r"axillar\w*|submerg\w*|flott\w*|floating|a[ée]ri\w*|primar\w*|secondar\w*|principa\w*|"
    r"juv[ée]nile\w*|st[ée]riles?|fertiles?|caulinaires?|radicales?|rosulate|basales?|"
    r"distal|proximal|distaux|proximaux|central\w*|marginal\w*|peripheral|p[ée]riph[ée]riques?)$",
    re.IGNORECASE,
)
_WORD = re.compile(r"[^\s]+")

# E2: closed outline (width-axis) degree cues licensed directly before a shape compound; an
# optional intensity word may precede them (``very narrowly``) and stays in the verbatim cue.
_SHAPE_DEGREE_PREFIX = re.compile(
    r"(?<![\w\-–—±])(?P<cue>(?:(?:very|rather|très|tres|assez)\s+)?"
    r"(?:narrowly|broadly|widely|étroitement|etroitement|largement))\s+$",
    re.IGNORECASE,
)

_INDUMENT_DEGREE_PREFIX = re.compile(
    r"(?<![\w\-–—±])(?P<cue>(?:(?:very|rather|très|tres|assez)\s+)?"
    r"(?:densely|sparsely|sparingly|thinly|laxly|finely|minutely|shortly|densément|densement|"
    r"éparsement|eparsement|finement|brièvement|brievement|courtement))\s+$",
    re.IGNORECASE,
)
_RANGE_BEFORE_DEGREE = re.compile(r"\b(?:to|or|and|à|ou|et)\s+$", re.IGNORECASE)


def with_degree_prefix(text: str, compound: CompoundValue) -> CompoundValue:
    """Attach a directly preceding degree cue to a shape (E2) or indumentum (E3) compound.

    Shape compounds take width cues (narrowly/broadly); indumentum compounds take density,
    texture and extent cues (densely, sparsely, finely, shortly).  A cue that ends a range
    (``densely to sparingly stellate-pubescent``) is not attached.
    """

    if compound.family == "shape":
        pattern, allowed = _SHAPE_DEGREE_PREFIX, {"narrowly", "broadly"}
    elif compound.family == "indumentum":
        pattern, allowed = _INDUMENT_DEGREE_PREFIX, {"densely", "sparsely", "finely", "shortly"}
    else:
        return compound
    window_start = max(0, compound.start - 40)
    match = pattern.search(text, window_start, compound.start)
    if match is None:
        return compound
    if _RANGE_BEFORE_DEGREE.search(text[max(0, match.start("cue") - 12) : match.start("cue")]):
        return compound
    cue = match.group("cue")
    degree = parse_qualifier_cue(cue)["degree_qualifier"]
    if degree not in allowed:
        return compound
    return replace(
        compound,
        degree_start=match.start("cue"),
        degree_end=match.end("cue"),
        degree_qualifier=degree,
    )


def _is_bearer_word(word: str) -> bool:
    return any(
        pattern.fullmatch(word)
        for _po, pattern in (*_EXTRA_BEARERS, *_reviewed_bearers(), *baseline.LOCAL_BEARER_PATTERNS)
    ) or any(pattern.fullmatch(word) for _po, pattern, _ids in baseline.CONTEXTUAL_BEARER_PATTERNS)


def _safe_word(word: str, *, tail: bool) -> bool:
    bare = word.strip("()[];.")
    if not bare or _NUMERIC.match(word) or _NUMERIC.match(bare):
        return True
    lower = bare.casefold()
    if lower in _TAIL_WORDS:
        return True
    if tail:
        return False
    if _NESTED_NOUN.match(lower) or _is_bearer_word(lower):
        return False
    if lower in _ADVERBS or lower in _ADJECTIVE_WORDS or lower in _FR_ADJECTIVE_WORDS:
        return True
    if "-" in lower:
        return all(
            _safe_word(part, tail=False) for part in lower.split("-") if part
        )
    return bool(_EN_ADJECTIVE_SUFFIX.search(lower) or _FR_ADJECTIVE_SUFFIX.search(lower))


def _safe_member(member: str, *, tail: bool) -> bool:
    member = _MEASURE_PHRASE.sub(" ", member)
    return all(_safe_word(word, tail=tail) for word in _WORD.findall(member))


def _members(clause: str, local_start: int) -> list[tuple[int, int]]:
    """Comma/colon members of ``clause[:local_start]`` as local ``(start, end)`` pairs."""

    bounds = [-1, *(match.start() for match in _MEMBER_SPLIT.finditer(clause, 0, local_start))]
    edges = [*bounds, local_start]
    return [(edges[i] + 1, edges[i + 1]) for i in range(len(edges) - 1)]


_LEXICON_BEARER_DENY = frozenset(
    """
    scale scales lobe lobes wing wings tube tubes segment segments part parts body axis apex base
    tip tips margin margins head heads ray rays sheath sheaths plant plants organ organs portion
    side sides surface face layer spine spines hair hairs cell cells stalk stalks
    pale pyrene pyrenes thallus thalli squamule squamules ligule ligules
    """.split()
)
_LEADING_WORDS = re.compile(r"^([A-Za-z]+)(?:([- ])([A-Za-z]+))?")


def _lexicon_variants(phrase: str) -> list[str]:
    phrase = phrase.casefold()
    variants = [phrase]
    if phrase.endswith("ies"):
        variants.append(phrase[:-3] + "y")
    if phrase.endswith("ae"):
        variants.append(phrase[:-1])
    if phrase.endswith("es"):
        variants.append(phrase[:-2])
    if phrase.endswith("s"):
        variants.append(phrase[:-1])
    return variants


def _bearer_at(
    member: str, label_to_id: dict[str, str] | None = None
) -> tuple[str, int, str, str] | None:
    """Return ``(po_id, length, surface, method)`` for a PO noun opening ``member``."""

    stripped = member.lstrip()
    best: tuple[str, int, str, str] | None = None
    for po_id, pattern in (*_EXTRA_BEARERS, *_reviewed_bearers(), *baseline.LOCAL_BEARER_PATTERNS):
        match = pattern.match(stripped)
        if match and (best is None or match.end() > best[1]):
            best = (po_id, match.end(), match.group(0), "explicit")
    if best is not None or not label_to_id:
        return best
    words = _LEADING_WORDS.match(stripped)
    if words is None:
        return None
    phrases = []
    if words.group(3):
        phrases.append((words.end(), f"{words.group(1)} {words.group(3)}"))
    phrases.append((words.end(1), words.group(1)))
    for length, phrase in phrases:
        if phrase.casefold() in _LEXICON_BEARER_DENY:
            continue
        for variant in _lexicon_variants(phrase):
            if variant in _LEXICON_BEARER_DENY:
                break
            po_id = label_to_id.get(variant, "")
            if po_id.startswith("PO_"):
                return po_id, length, stripped[:length], "po_lexicon"
    return None


# E3 surface scope: apex/base/margin phrases of the same laminar organ (``apex acute``,
# ``rounded to cuneate at the base``) are descriptive members before a ``beneath``/``above``
# member; other nested nouns (lobes, petiole, veins) still block.
_SUBREGION_PHRASE_WORDS = re.compile(
    r"\b(?:apex|apices|base|bases|margins?|tips?|sommet|marges?|bords?|at|to|the|towards?|"
    r"au|à|a|la|le|vers)\b",
    re.IGNORECASE,
)
_OF_AFTER_SUBREGION = re.compile(
    r"\b(?:apex|base|margins?|tips?|sommet|marges?|bords?)\s+(?:of|du|de|des|d['’])",
    re.IGNORECASE,
)


def _subregion_member(member: str) -> bool:
    if _OF_AFTER_SUBREGION.search(member):
        return False
    cleaned = _SUBREGION_PHRASE_WORDS.sub(" ", member)
    # Colour and outline words of the same organ are descriptive adjectives here.
    cleaned = _OTHER_COLOUR.sub(" ", _OTHER_SHAPE.sub(" ", cleaned))
    return _safe_member(cleaned, tail=False)


def _explicit_bearer(
    clause: str,
    clause_start: int,
    start: int,
    label_to_id: dict[str, str] | None = None,
    *,
    skip_subregion_members: bool = False,
) -> tuple[Bearer | None, bool]:
    """Find the nearest member-initial PO noun licensing the compound.

    Returns ``(bearer, clean_prefix)``.  ``clean_prefix`` is true when every member between the
    clause start and the compound is a safe descriptive member, which licenses an organ-heading
    fallback when no explicit bearer exists.
    """

    local_start = start - clause_start
    members = _members(clause, local_start)
    own_start, own_end = members[-1]
    own = clause[own_start:own_end]
    # The compound must open its member, unless its member is ``bearer + compound``.
    if own.strip():
        found = _bearer_at(own, label_to_id)
        if found is None:
            return None, False
        po_id, length, surface, kind = found
        tail = own.lstrip()[length:]
        if not _BEARER_TAIL.fullmatch(tail):
            return None, False
        offset = clause_start + own_start + len(own) - len(own.lstrip())
        if len(members) != 1:
            return None, False
        return Bearer(po_id, f"clause_initial_{kind}", surface, offset, offset + length), True
    for member_start, member_end in reversed(members[:-1]):
        member = clause[member_start:member_end]
        found = _bearer_at(member, label_to_id)
        if found is not None:
            if member_start != 0:
                # A bearer opening a later comma member often names a subset or nested part of
                # an earlier subject (``stamens included ..., anthers``); stay conservative.
                return None, False
            po_id, length, surface, kind = found
            tail = member.lstrip()[length:]
            if not _safe_member(tail, tail=False):
                return None, False
            offset = clause_start + member_start + len(member) - len(member.lstrip())
            return Bearer(po_id, f"clause_initial_{kind}", surface, offset, offset + length), True
        if skip_subregion_members and _subregion_member(member):
            # E3 surface scope: apex/base/margin members describe regions of the same laminar
            # organ; a following ``beneath``/``above`` member still describes the organ's side.
            continue
        if not _safe_member(member, tail=False):
            return None, False
    return None, True


def _heading_bearer(record: dict, resources: Resources, clause_start: int) -> Bearer | None:
    """A compound in the first clause of a typed organ-heading segment describes that organ."""

    organ = str(record.get("organ", "") or "")
    if clause_start != 0 or _UNMODELLED_HEADING.search(organ):
        return None
    po_id = resources.bearers.heading(organ)
    if not po_id:
        return None
    return Bearer(po_id, "organ_heading", organ)


def _other_value_in_clause(
    clause: str,
    local_start: int,
    local_end: int,
    family: str,
    bearer: Bearer,
    *,
    own_member_only: bool = False,
) -> bool:
    """Whether another value of the same family occurs in the clause.

    For shape, comma members explicitly scoped to the apex, base, tip or margin describe terminal
    or basal shape, not an alternative gross outline, and are skipped.
    """

    rest = clause[:local_start] + " " * (local_end - local_start) + clause[local_end:]
    other = _OTHER_SHAPE if family == "shape" else _OTHER_COLOUR
    if own_member_only:
        member_start, member_end = _own_member(clause, local_start, local_end)
        return bool(other.search(rest[member_start:member_end]))
    cursor = 0
    for boundary in [*(m.start() for m in _MEMBER_SPLIT.finditer(rest)), len(rest)]:
        member = rest[cursor:boundary]
        cursor = boundary + 1
        if family == "shape" and _SUBREGION_SCOPE.search(member):
            continue
        if other.search(member):
            return True
    return False


_FR_FEMININE_BEARERS = re.compile(
    r"^(?:feuilles?|folioles?|bract[ée]es?|bract[ée]oles?|stipules?|gousses?|graines?|capsules?|"
    r"baies?|fleurs?|anth[èe]res?|[ée]tamines?|tiges?|drupes?|siliques?|ligules?|carènes?|"
    r"ailes?|[ée]cailles?|glumes?|glumelles?|valves?|corolles?|samares?|akènes?|"
    r"inflorescences?|panicules?|grappes?|cymes?|[ée]corces?|racines?|plantules?)$",
    re.IGNORECASE,
)
_FR_MASCULINE_BEARERS = re.compile(
    r"^(?:limbes?|p[ée]tales?|s[ée]pales?|fruits?|rhizomes?|p[ée]dicelles?|p[ée]tioles?|"
    r"ovaires?|styles?|stigmates?|calices?|[ée]tendards?|filets?|carpelles?|boutons?|"
    r"rameaux|ramilles?|troncs?|p[ée]doncules?|m[ée]ricarpes?|p[ée]rigones?|staminodes?|"
    r"connectifs?|arilles?|follicules?|r[ée]ceptacles?|disques?|t[ée]pales?)$",
    re.IGNORECASE,
)


def _french_agreement_mismatch(bearer_text: str, compound: CompoundValue, language: str) -> bool:
    """Whether a French adjective compound visibly disagrees with its bearer noun.

    ``hérissé de paillettes ..., linéaires-lancéolées`` after ``Rhizome`` agrees with the nested
    feminine plural noun, not the masculine singular bearer; such attachments are rejected.
    """

    if compound.relation is None or language != "fr":
        return False
    noun = bearer_text.strip().split()[0] if bearer_text.strip() else ""
    adjective = compound.relation["to_text"].casefold()
    if not (_FR_FEMININE_BEARERS.match(noun) or _FR_MASCULINE_BEARERS.match(noun)):
        return False
    noun_plural = noun.casefold().endswith(("s", "x"))
    adjective_plural = adjective.endswith("s")
    if noun_plural != adjective_plural and not adjective.endswith(("ux",)):
        return True
    feminine_adjective = bool(re.search(r"(?:ée|ées|ongue|ongues)$", adjective))
    masculine_adjective = bool(re.search(r"(?:é|és|ong|ongs)$", adjective))
    if _FR_MASCULINE_BEARERS.match(noun) and feminine_adjective:
        return True
    if _FR_FEMININE_BEARERS.match(noun) and masculine_adjective:
        return True
    return False


def context_exclusion(
    record: dict, compound: CompoundValue, resources: Resources
) -> tuple[str, Bearer | None]:
    """Return ``(reason, bearer)``; an empty reason means the compound may be asserted."""

    text = str(record.get("text", "") or "")
    start, end = compound.start, compound.end
    clause, clause_start = baseline._clause_at(text, start)
    local_start, local_end = start - clause_start, end - clause_start
    expression_start = max(compound.expression_start, clause_start)
    expression_end = min(compound.expression_end, clause_start + len(clause))
    if compound.expression_end > clause_start + len(clause):
        return "expression_crosses_clause", None
    bearer_clause = clause
    if compound.surface is not None:
        # Earlier members scoped to the other side (``glabrous above, stellate-pubescent
        # beneath``) are descriptive members of the same organ once their cue is set aside.
        for _side, cue_start, cue_end in find_surface_cues(clause, 0, len(clause)):
            bearer_clause = (
                bearer_clause[:cue_start] + " " * (cue_end - cue_start) + bearer_clause[cue_end:]
            )
    bearer, clean_prefix = _explicit_bearer(
        bearer_clause,
        clause_start,
        expression_start,
        resources.bearers.po_lexicon.label_to_id,
        skip_subregion_members=compound.surface is not None,
    )
    if bearer is None and clean_prefix:
        bearer = _heading_bearer(record, resources, clause_start)
    if bearer is None:
        return "no_clause_initial_bearer", None
    if _french_agreement_mismatch(bearer.text, compound, str(record.get("language", "") or "")):
        return "french_agreement_mismatch", bearer
    after = clause[expression_end - clause_start :]
    if not _RIGHT_BOUNDARY.match(after):
        return "right_context_not_phrase_boundary", bearer
    e3_reason = _e3_scope_reason(
        clause, clause_start, expression_start, expression_end, compound
    )
    if e3_reason:
        return e3_reason, bearer
    if compound.family in {"shape", "colour"} and _other_value_in_clause(
        clause,
        local_start,
        local_end,
        compound.family,
        bearer,
        own_member_only=compound.surface is not None,
    ):
        return f"other_{compound.family}_value_in_clause", bearer
    contextual = baseline._negated_or_hedged(text, start)
    if contextual:
        return contextual, bearer
    if exact._TEMPORAL_CONNECTOR.search(clause):
        return "developmental_stage_context", bearer
    if exact._REPORTED_ATTRIBUTION_AFTER.search(after[:96]):
        return "reported_attribution_context", bearer
    if baseline._unmodelled_bearer_category(text, start) or _UNMODELLED_HEADING.search(
        clause[:local_start]
    ):
        return "unmodelled_bearer_category", bearer
    if exact._RELATIONAL_FLOWER_CATEGORY_BEFORE.search(text[max(0, start - 300) : start]):
        return "relational_bearer_context", bearer
    if _SEX_CATEGORY.search(text[max(0, start - 400) : start]):
        return "sex_category_context", bearer
    if _ABSENCE.search(clause):
        return "absence_alternative_context", bearer
    organ = str(record.get("organ", "") or "")
    if re.search(r"(?<!\w)(?:male|female|m[âa]les?|femelles?|♂|♀)(?!\w)", organ, re.I):
        return "unmodelled_bearer_category", bearer
    if compound.family == "colour":
        resolution = exact.BearerResolution(
            bearer.po_id,
            "explicit_local" if bearer.start is not None else "organ_heading",
            bearer.text,
        )
        unsafe = exact._unsafe_bearer_scope(text, start, end, resolution)
        # A surface-scoped colour's own cue is the modelled scope; any other unsafe scope
        # (covering, appendage, apex/base/margin) still blocks.
        if unsafe and not (
            compound.surface is not None
            and unsafe[0] == "surface_or_subregion"
            and not _SUBREGION_SCOPE.search(clause)
        ):
            return f"bearer_scope:{unsafe[0]}", bearer
    return "", bearer


def _own_member(clause: str, local_start: int, local_end: int) -> tuple[int, int]:
    bounds = [match.start() for match in _MEMBER_SPLIT.finditer(clause)]
    member_start = max([-1, *(b for b in bounds if b < local_start)]) + 1
    member_end = min([len(clause), *(b for b in bounds if b >= local_end)])
    return member_start, member_end


def _e3_scope_reason(
    clause: str,
    clause_start: int,
    expression_start: int,
    expression_end: int,
    compound: CompoundValue,
) -> str:
    """Surface and pilosity safeguards for E3 indumentum, hair-colour and colour compounds."""

    if compound.family not in _SURFACE_FAMILIES:
        return ""
    local_start = expression_start - clause_start
    local_end = expression_end - clause_start
    masked = clause[:local_start] + " " * (local_end - local_start) + clause[local_end:]
    if compound.surface is None:
        # The surface audit: a value in a clause that names a surface may hold for one side only.
        if find_surface_cues(masked, 0, len(masked)):
            return "surface_cue_elsewhere_in_clause"
    if compound.family in _E3_FAMILIES:
        if _SUBREGION_SCOPE.search(masked if compound.surface is None else clause[local_start:local_end]):
            return "indumentum_subregion_scope"
        member_start, member_end = _own_member(clause, local_start, local_end)
        scope = masked[member_start:member_end] if compound.surface is not None else masked
        if _OTHER_PILOSITY.search(scope):
            return "other_pilosity_value_in_scope"
    if compound.family == "hair_colour":
        member_start, member_end = _own_member(clause, local_start, local_end)
        if _OTHER_COLOUR.search(masked[member_start:member_end]):
            return "other_colour_in_hair_member"
    return ""


def _overlaps(row: dict, start: int, end: int, start_key: str, end_key: str) -> bool:
    try:
        return int(row.get(start_key, -1)) < end and start < int(row.get(end_key, -1))
    except (TypeError, ValueError):
        return False


def _same_family(assertion: dict, family: str, resources: Resources) -> bool:
    """Whether an overlapping assertion already states a value of the compound's family.

    Contextual apex/base/indument assertions often carry a source window spanning the compound;
    they do not assert its gross outline or colour and must not block it.
    """

    values = {
        str(assertion.get("pato_id", "") or ""),
        *(str(value) for value in assertion.get("value_terms", []) or []),
    }
    relation = assertion.get("qualitative_value_relation") or {}
    values.update({str(relation.get("from_value", "")), str(relation.get("to_value", ""))})
    if family == "shape":
        return bool(values & (_SHAPE_IDS | {SHAPE_ATTRIBUTE}))
    if family in _E3_FAMILIES:
        return bool(values & PILOSITY_IDS) or bool(assertion.get("part_restrictions"))
    return bool(values & (resources.colour_ids | baseline.COLOR_PATO_IDS | {COLOUR_ATTRIBUTE}))


_FAMILY_PROVENANCE = {
    "indumentum": (
        "clause-initial hyphen indumentum compound: closed pilosity head on the organ; closed "
        "hair shape/colour element as a has_part restriction on PO trichome"
    ),
    "hair_colour": (
        "clause-initial colour compound naming hairs: organ hairy; colour borne by the PO "
        "trichome part, never by the organ"
    ),
}


def build_assertion(record: dict, compound: CompoundValue, bearer: Bearer) -> dict[str, Any] | None:
    """Return the assertion, or ``None`` when a surface cue has no reviewed scope class."""

    text = str(record.get("text", "") or "")
    expression_start = compound.expression_start
    expression_end = compound.expression_end
    provenance = [
        (
            "clause-initial hyphen compound: two distinct closed-lexicon planar gross-outline "
            "values joined by one printed dash; continuum"
            if compound.family == "shape"
            else _FAMILY_PROVENANCE[compound.family]
            if compound.family in _FAMILY_PROVENANCE
            else (
                "clause-initial hyphen compound: PATO preferred label or EXACT synonym; "
                "dash/space normalization only"
                if not compound.value_terms
                else "clause-initial hyphen compound: existing non-deprecated FLOPO composite-"
                "colour value; whole-token exact form; dash/space normalization only"
            )
        ),
        f"bearer_method:{bearer.method}",
        *(["bearer:organ_heading"] if bearer.method == "organ_heading" else []),
        *(
            [
                "compound_degree_qualifier:E2",
                f"degree_cue:{text[compound.degree_start:compound.degree_end]!r}->"
                f"{compound.degree_qualifier}",
            ]
            if compound.degree_qualifier
            else []
        ),
    ]
    # Leaf-part bearers in a leaflet description are re-borne on the FLOPO leaflet part; the
    # gate then decides whether that bearer x quality pair is admissible.
    po_id = leaflet_bearer(bearer.po_id, text, expression_start)
    if po_id != bearer.po_id:
        provenance.append(f"leaflet_context_bearer:{bearer.po_id}->{po_id}")
    bearer_scope: dict[str, Any] | None = None
    if compound.surface is not None:
        side, cue_start, cue_end = compound.surface
        scope = surface_scope(po_id, side, cue_start, cue_end)
        if scope is None:
            return None
        bearer_scope = {
            "outer_bearer": po_id,
            "scope_class": scope.scope_class,
            "mode": scope.mode,
            "scope_text": text[cue_start:cue_end],
            "scope_start": cue_start,
            "scope_end": cue_end,
        }
        provenance += [
            "bearer_scope:E3",
            f"surface_cue:{text[cue_start:cue_end]!r}->{scope.side}:{po_id}->{scope.scope_class}",
        ]
        po_id = scope.scope_class
    if compound.part is not None:
        provenance.append("indumentum_part:E3")
    assertion: dict[str, Any] = {
        "po_id": po_id,
        "pato_id": compound.pato_id,
        "negated": False,
        "negation_scope": "",
        "organ": record.get("organ", ""),
        "source_text": text[expression_start:expression_end],
        "source_start": expression_start,
        "source_end": expression_end,
        "raw_quality_text": compound.token,
        "value_text": "",
        "value_operator": "atomic",
        "value_terms": list(compound.value_terms),
        "bearer_context_qualities": [],
        "developmental_stage_contexts": [],
        "developmental_stage_operator": "atomic",
        "frequency_qualifier": "unspecified",
        "epistemic_modality": "asserted",
        "value_qualifier": "exact",
        "degree_qualifier": "unmodified",
        "modality_text": "",
        "season_contexts": [],
        "season_operator": "atomic",
        "normalization_status": (
            "compositional"
            if compound.family != "colour" or compound.value_terms or bearer_scope
            else "auto"
        ),
        "mapping_provenance": provenance,
        "extractor": EXTRACTOR,
        "composition": {
            "status": "accept",
            "confidence": 1.0,
            "reasons": [f"deterministic_clause_initial_{compound.family}_compound"],
        },
    }
    if compound.degree_qualifier:
        assertion.update(
            {
                "degree_qualifier": compound.degree_qualifier,
                "modality_text": text[compound.degree_start : compound.degree_end],
                "modality_start": compound.degree_start,
                "modality_end": compound.degree_end,
            }
        )
    if compound.relation is not None:
        assertion["qualitative_value_relation"] = dict(compound.relation)
    assertion["part_restrictions"] = [dict(compound.part)] if compound.part is not None else []
    if bearer_scope is not None:
        assertion["bearer_scope"] = bearer_scope
    if bearer.start is not None:
        assertion.update(
            {
                "raw_entity_text": bearer.text,
                "bearer_start": bearer.start,
                "bearer_end": bearer.end,
            }
        )
    if compound.relation is None:
        ensure_annotation_class_iri(assertion)
    return assertion


def _statement_for(record: dict, assertion: dict) -> tuple[dict, dict]:
    probe = dict(record)
    probe["assertions"] = [*(record.get("assertions", []) or []), assertion]
    upgraded = ensure_source_statements(probe)
    materialized = upgraded["assertions"][-1]
    statement_id = materialized.get("source_statement_id")
    matches = [
        row
        for row in upgraded.get("source_statements", []) or []
        if row.get("statement_id") == statement_id
    ]
    if len(matches) != 1:
        raise ValueError(f"source statement {statement_id!r} not materialized exactly once")
    return materialized, matches[0]


def segment_key(record: dict) -> dict[str, Any]:
    return {
        "source": record.get("source", ""),
        "source_id": record.get("source_id", ""),
        "source_segment_index": record.get("source_segment_index", 0),
        "taxon": record.get("taxon", ""),
        "organ": record.get("organ", ""),
        "char_start": record.get("char_start"),
        "char_end": record.get("char_end"),
    }


def recover_record(record: dict, resources: Resources) -> tuple[dict | None, Counter[str], list[dict]]:
    """Return ``(delta_or_None, outcomes, audit_rows)`` for one segment."""

    text = str(record.get("text", "") or "")
    unresolved = list(record.get("unresolved_spans", []) or [])
    outcomes: Counter[str] = Counter()
    audit: list[dict] = []
    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for span in unresolved:
        if span.get("reason") != TARGET_REASON:
            continue
        start, end = int(span["start"]), int(span["end"])
        if not (0 <= start < end <= len(text)) or text[start:end] != span.get("surface_form"):
            outcomes["span:not_verbatim"] += 1
            continue
        groups[exact._compound_bounds(text, start, end)].append(span)

    working = dict(record)
    working["assertions"] = list(record.get("assertions", []) or [])
    working["source_statements"] = list(record.get("source_statements", []) or [])
    known_statements = {row.get("statement_id") for row in working["source_statements"]}
    add_statements: list[dict] = []
    add_assertions: list[dict] = []
    removed: list[dict] = []
    for (start, end), members in sorted(groups.items()):
        compound = match_compound(text, start, end, resources)
        if compound is None:
            outcomes["span:out_of_scope_token"] += len(members)
            continue
        compound = with_degree_prefix(text, compound)
        compound = with_hair_context(text, compound, str(record.get("language", "") or ""))
        compound = with_surface_cue(text, compound)
        family = compound.family
        start = compound.expression_start
        end = compound.expression_end
        overlapping = [
            span for span in unresolved if _overlaps(span, start, end, "start", "end")
        ]
        if any(span.get("reason") != TARGET_REASON for span in overlapping) or len(
            overlapping
        ) != len(members):
            outcomes[f"{family}:other_unresolved_overlap"] += len(members)
            continue
        if any(
            _overlaps(row, start, end, "source_start", "source_end")
            and _same_family(row, family, resources)
            for row in working["assertions"]
        ):
            outcomes[f"{family}:overlapping_existing_assertion"] += len(members)
            continue
        reason, bearer = context_exclusion(record, compound, resources)
        if reason or bearer is None:
            outcomes[f"{family}:{reason or 'no_bearer'}"] += len(members)
            continue
        assertion = build_assertion(record, compound, bearer)
        if assertion is None:
            outcomes[f"{family}:surface_scope_unmapped"] += len(members)
            continue
        e3 = compound.family in _E3_FAMILIES or compound.surface is not None
        gate = check_assertion(
            text,
            assertion,
            resources.combinations,
            resources.registry,
            resources.signature_registry,
            resources.attribute_ids,
            taxon_provenance=record.get("taxon") if "taxon" in record else None,
            pato_catalog_ids=resources.pato_ids,
            flopo_catalog_ids=resources.flopo_ids,
            po_catalog_ids=resources.po_ids,
        )
        expected_flopo = {"structured_annotation_only"} if family == "shape" else None
        # E3 assertions may enter as ``review`` when their only issue is a novel (not blocked)
        # bearer x quality pair; every other gate failure withholds them.
        e3_review = (
            e3
            and gate.status == "review"
            and set(gate.reasons) <= _NOVEL_PAIR_REASONS
        )
        if not e3_review and (
            gate.status != "accepted"
            or gate.po_pato_status != "allowed"
            or (expected_flopo is not None and gate.flopo_status not in expected_flopo)
        ):
            outcomes[f"{family}:gate_held"] += len(members)
            continue
        if e3:
            outcomes[f"{family}:e3_gate:{gate.status}"] += 1
            if compound.surface is not None:
                outcomes[f"{family}:surface:{compound.surface[0]}"] += 1
        assertion["gate"] = asdict(gate)
        assertion, statement = _statement_for(working, assertion)
        if statement["statement_id"] not in known_statements:
            known_statements.add(statement["statement_id"])
            add_statements.append(statement)
            working["source_statements"].append(statement)
        working["assertions"].append(assertion)
        add_assertions.append(assertion)
        for span in members:
            removed.append(
                {
                    "start": span["start"],
                    "end": span["end"],
                    "reason": span["reason"],
                    "surface_form": span["surface_form"],
                }
            )
        outcomes[f"{family}:resolved_spans"] += len(members)
        outcomes[f"{family}:assertions"] += 1
        outcomes[f"{family}:bearer_method:{bearer.method}"] += 1
        if compound.degree_qualifier:
            outcomes[f"{family}:degree:{compound.degree_qualifier}"] += 1
            outcomes[f"{family}:degree_resolved_spans"] += len(members)
        audit.append(
            {
                "family": family,
                "language": record.get("language", ""),
                "source": record.get("source", ""),
                "token": compound.token,
                "surface_cue": (
                    text[compound.surface[1] : compound.surface[2]] if compound.surface else ""
                ),
                "part": (compound.part or {}).get("qualities", []),
                "gate_status": gate.status,
                "degree_cue": (
                    text[compound.degree_start : compound.degree_end]
                    if compound.degree_qualifier
                    else ""
                ),
                "start": start,
                "end": end,
                "po_id": assertion["po_id"],
                "bearer_text": bearer.text,
                "bearer_method": bearer.method,
                "quality": compound.pato_id,
                "value_terms": list(compound.value_terms),
                "relation": (
                    f"{compound.relation['from_value']}~{compound.relation['to_value']}"
                    if compound.relation
                    else ""
                ),
                "spans": len(members),
                "window": text[max(0, start - 90) : min(len(text), end + 60)],
                "key": segment_key(record),
            }
        )
    if not add_assertions:
        return None, outcomes, audit
    delta = {
        "key": segment_key(record),
        "add_source_statements": add_statements,
        "add_assertions": add_assertions,
        "remove_unresolved": removed,
    }
    return delta, outcomes, audit


def _key_tuple(key: dict) -> tuple:
    return (
        key.get("source"),
        key.get("source_id"),
        key.get("source_segment_index"),
        key.get("taxon"),
        key.get("organ"),
        key.get("char_start"),
        key.get("char_end"),
    )


def apply_delta_record(record: dict, delta: dict) -> dict:
    """Apply one delta row to a copied segment, failing closed on drift."""

    out = dict(record)
    statements = list(record.get("source_statements", []) or [])
    statement_ids = {row.get("statement_id") for row in statements}
    for statement in delta.get("add_source_statements", []) or []:
        if statement.get("statement_id") in statement_ids:
            raise ValueError(f"duplicate source statement {statement.get('statement_id')}")
        statements.append(statement)
        statement_ids.add(statement.get("statement_id"))
    assertions = list(record.get("assertions", []) or [])
    for assertion in delta.get("add_assertions", []) or []:
        if assertion.get("source_statement_id") not in statement_ids:
            raise ValueError("added assertion references a missing source statement")
        assertions.append(assertion)
    remaining = list(record.get("unresolved_spans", []) or [])
    for target in delta.get("remove_unresolved", []) or []:
        index = next(
            (
                i
                for i, span in enumerate(remaining)
                if (span.get("start"), span.get("end"), span.get("reason"), span.get("surface_form"))
                == (target["start"], target["end"], target["reason"], target["surface_form"])
            ),
            None,
        )
        if index is None:
            raise ValueError(f"unresolved span to remove is absent: {target}")
        remaining.pop(index)
    out["source_statements"] = statements
    out["assertions"] = assertions
    out["unresolved_spans"] = remaining
    return out


def apply_delta(input_path: Path, delta_path: Path, output_path: Path) -> dict[str, int]:
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("apply output must differ from its input")
    deltas: dict[tuple, dict] = {}
    with Path(delta_path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                key = _key_tuple(row["key"])
                if key in deltas:
                    raise ValueError(f"duplicate delta key {key}")
                deltas[key] = row
    applied = 0
    with Path(input_path).open(encoding="utf-8") as source, Path(output_path).open(
        "w", encoding="utf-8"
    ) as output:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            delta = deltas.get(_key_tuple(segment_key(record)))
            if delta is not None:
                record = apply_delta_record(record, delta)
                applied += 1
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    if applied != len(deltas):
        raise ValueError(f"applied {applied} of {len(deltas)} delta rows")
    return {"applied_segments": applied}


def stratified_sample(audit: list[dict], size: int, seed: int) -> list[dict]:
    """Seeded sample stratified by family x language x source, proportional with a floor."""

    strata: dict[tuple, list[dict]] = defaultdict(list)
    for row in audit:
        strata[(row["family"], row["language"], row["source"])].append(row)
    rng = random.Random(seed)
    total = len(audit)
    chosen: list[dict] = []
    for key in sorted(strata):
        rows = strata[key]
        quota = max(3, round(size * len(rows) / max(total, 1)))
        chosen.extend(rng.sample(rows, min(quota, len(rows))))
    return chosen


def recover_file(
    input_path: Path,
    output_dir: Path,
    *,
    resources: Resources | None = None,
    sample_size: int = 160,
    seed: int = 20260918,
) -> dict[str, Any]:
    resources = resources or Resources()
    output_dir.mkdir(parents=True, exist_ok=True)
    outcomes: Counter[str] = Counter()
    by_language: Counter[str] = Counter()
    target_spans = 0
    audit: list[dict] = []
    segments = 0
    with Path(input_path).open(encoding="utf-8") as source, (output_dir / "delta.jsonl").open(
        "w", encoding="utf-8"
    ) as output:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            target_spans += sum(
                span.get("reason") == TARGET_REASON
                for span in record.get("unresolved_spans", []) or []
            )
            delta, record_outcomes, record_audit = recover_record(record, resources)
            outcomes.update(record_outcomes)
            audit.extend(record_audit)
            if delta is not None:
                segments += 1
                by_language[str(record.get("language", ""))] += len(delta["remove_unresolved"])
                output.write(json.dumps(delta, ensure_ascii=False, sort_keys=True) + "\n")
    with (output_dir / "recovered-audit.jsonl").open("w", encoding="utf-8") as handle:
        for row in audit:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    sample = stratified_sample(audit, sample_size, seed)
    with (output_dir / "sample-candidates.jsonl").open("w", encoding="utf-8") as handle:
        for row in sample:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "input": str(input_path),
        "target_spans": target_spans,
        "touched_segments": segments,
        "resolved_spans": sum(v for k, v in outcomes.items() if k.endswith(":resolved_spans")),
        "added_assertions": sum(v for k, v in outcomes.items() if k.endswith(":assertions")),
        "resolved_spans_by_language": dict(sorted(by_language.items())),
        "outcomes": dict(sorted(outcomes.items())),
        "sample_size": len(sample),
        "seed": seed,
    }
    (output_dir / "recovery-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="write delta.jsonl, audit and report")
    run.add_argument("input", type=Path)
    run.add_argument("-o", "--output-dir", type=Path, required=True)
    run.add_argument("--sample-size", type=int, default=160)
    run.add_argument("--seed", type=int, default=20260918)
    apply = sub.add_parser("apply", help="apply a delta to a copy of the corpus")
    apply.add_argument("input", type=Path)
    apply.add_argument("delta", type=Path)
    apply.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        report = recover_file(
            args.input, args.output_dir, sample_size=args.sample_size, seed=args.seed
        )
    else:
        report = apply_delta(args.input, args.delta, args.output)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
