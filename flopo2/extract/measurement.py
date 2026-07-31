"""Conservative deterministic parsing of botanical linear measurements.

Botanical descriptions routinely express scalar attributes as a number, a unit, and an
attribute cue (for example, ``1.2 cm wide``). Treating the adjective alone as a categorical
quality produces serious false positives in flora prose: ``wide plain`` and ``high altitude``
are not plant phenotypes. This module therefore requires a numeric value and a recognized
length unit, and keeps the exact source span for provenance.

The parser is intentionally small and deterministic. It handles common English and French
postposed and preposed constructions, but does not infer attributes from bare dimension pairs
such as ``3 x 2 mm``; those require an independently tested botanical convention parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Measurement:
    """A numeric plant-trait measurement grounded in an exact source span."""

    start: int
    end: int
    attribute_id: str
    value_low: float | None
    value_high: float
    unit_id: str
    unit_text: str
    source_text: str
    cue: str
    modifier: str = ""
    modifier_text: str = ""
    value_low_inclusive: bool = True
    value_high_inclusive: bool = True


@dataclass(frozen=True)
class _Pattern:
    attribute_id: str
    language: str
    regex: re.Pattern[str]


_NUMBER = r"\d+(?:[.,]\d+)?"
_RANGE = rf"(?P<low>{_NUMBER})(?:\s*(?:[-\u2013\u2014]|to|\u00e0)\s*(?P<high>{_NUMBER}))?"

# Upper-bound comparators. A limit turns the parse into an *upper bound* (value_low=None). The
# inclusive family renders xsd:maxInclusive (<= X); the strict family renders xsd:maxExclusive
# (< X). ``atteindre``-negation WITHOUT a following ``plus de`` is strict ("never reaches X"),
# while ``d\u00e9passer``/``exc\u00e9der``-negation, ``pas plus de``, ``n'atteignant pas plus de``, and the
# English ``no/not more than`` / ``not exceeding`` / ``not over`` / ``up to`` families are all
# inclusive.  The inclusive alternatives are matched first so ``n'atteignant pas plus de`` cannot
# be captured as the strict ``n'atteignant pas``.
_LIMIT_INCLUSIVE = (
    r"up\s+to|jusqu(?:['\u2019]\s*)?[\u00e0a]|"
    r"no\s+more\s+than|not\s+more\s+than|not\s+exceeding|not\s+over|"
    r"not\s+longer\s+than|not\s+surpassing|at\s+most|maximum|max\.|"
    r"au\s+plus|pas\s+plus\s+de|"
    r"(?:ne\s+|n['\u2019])(?:d[\u00e9e]passant|d[\u00e9e]passe(?:nt)?|"
    r"exc[\u00e9e]dant|exc[\u00e9e]de(?:nt)?)\s+pas|"
    r"(?:ne\s+|n['\u2019])atteign(?:ant|ent|e)\s+pas\s+plus\s+de|"
    r"(?:ne\s+|n['\u2019])atteint\s+pas\s+plus\s+de"
)
_LIMIT_STRICT = (
    r"(?:ne\s+|n['\u2019])atteign(?:ant|ent|e)\s+pas(?!\s+plus\s+de)|"
    r"(?:ne\s+|n['\u2019])atteint\s+pas(?!\s+plus\s+de)"
)
_LIMIT = rf"(?P<limit>{_LIMIT_INCLUSIVE}|{_LIMIT_STRICT})?"
_STRICT_LIMIT_RE = re.compile(rf"(?:{_LIMIT_STRICT})", re.IGNORECASE)
_APPROX = r"(?:(?P<approx>ca\.?|c\.?|about|approximately|environ)\s+)?"
_UNIT = (
    r"(?P<unit>"
    r"[\u00b5\u03bc]m|um|microm(?:eter|etre)s?|microm(?:\u00e8|e)tre?s?|"
    r"mm|millim(?:eter|etre)s?|millim(?:\u00e8|e)tre?s?|"
    r"cm|centim(?:eter|etre)s?|centim(?:\u00e8|e)tre?s?|"
    r"m|meters?|metres?|m(?:\u00e8|e)tres?"
    r")"
)


def _postfix(cue: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![\w.,]){_APPROX}{_LIMIT}\s*{_RANGE}\s*{_UNIT}\s+(?P<cue>{cue})(?!\w)",
        re.IGNORECASE,
    )


def _prefix(cue: str, connector: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<!\w)(?P<cue>{cue})(?!\w)\s*(?:{connector})\s*"
        rf"{_APPROX}{_LIMIT}\s*{_RANGE}\s*{_UNIT}(?!\w)",
        re.IGNORECASE,
    )


_PATTERNS = (
    # English: numeric value followed by an adjective or an ``in ATTRIBUTE`` phrase.
    _Pattern("PATO_0000122", "en", _postfix(r"long|in\s+length")),
    _Pattern("PATO_0000921", "en", _postfix(r"wide|in\s+width|across")),
    _Pattern("PATO_0000119", "en", _postfix(r"tall|high|in\s+height")),
    _Pattern("PATO_0000915", "en", _postfix(r"thick|in\s+thickness")),
    _Pattern("PATO_0001334", "en", _postfix(r"(?:in\s+)?diam(?:eter|\.)")),
    # English attribute nouns can precede a value (``width: 2 cm``).
    _Pattern("PATO_0000122", "en", _prefix(r"length", r"(?::|=|of)?")),
    _Pattern("PATO_0000921", "en", _prefix(r"width", r"(?::|=|of)?")),
    _Pattern("PATO_0000119", "en", _prefix(r"height", r"(?::|=|of)?")),
    _Pattern("PATO_0000915", "en", _prefix(r"thickness", r"(?::|=|of)?")),
    _Pattern("PATO_0001334", "en", _prefix(r"diam(?:eter|\.)", r"(?::|=|of)?")),
    # French postposed constructions.
    _Pattern(
        "PATO_0000122",
        "fr",
        _postfix(r"long(?:ue|ues|s)?|(?:de|en)\s+long(?:ueur)?"),
    ),
    _Pattern(
        "PATO_0000921",
        "fr",
        _postfix(r"large(?:s)?|(?:de|en)\s+largeur"),
    ),
    _Pattern(
        "PATO_0000119",
        "fr",
        _postfix(r"haut(?:e|es|s)?|(?:de|en)\s+hauteur"),
    ),
    _Pattern(
        "PATO_0000915",
        "fr",
        _postfix(r"(?:d['\u2019]|de\s+|en\s+)?\u00e9paisseur|\u00e9pais(?:se|ses|s)?"),
    ),
    _Pattern(
        "PATO_0001334",
        "fr",
        _postfix(r"(?:de|en)\s+diam(?:\u00e8|e)tre|diam\."),
    ),
    # French adjectives/nouns commonly precede ``de VALUE UNIT``.
    _Pattern(
        "PATO_0000122",
        "fr",
        _prefix(r"long(?:ue|ues|s)?|longueur", r"(?::|=|de)?"),
    ),
    _Pattern(
        "PATO_0000921",
        "fr",
        _prefix(r"large(?:s)?|largeur", r"(?::|=|de)?"),
    ),
    _Pattern(
        "PATO_0000119",
        "fr",
        _prefix(r"haut(?:e|es|s)?|hauteur", r"(?::|=|de)?"),
    ),
    _Pattern(
        "PATO_0000915",
        "fr",
        _prefix(r"\u00e9pais(?:se|ses|s)?|\u00e9paisseur", r"(?::|=|de|d['\u2019])?"),
    ),
    _Pattern(
        "PATO_0001334",
        "fr",
        _prefix(r"diam(?:\u00e8|e)tre|diam\.", r"(?::|=|de)?"),
    ),
)


_UNIT_NORMALIZATION = {
    "m": ("m", "UO:0000008"),
    "meter": ("m", "UO:0000008"),
    "meters": ("m", "UO:0000008"),
    "metre": ("m", "UO:0000008"),
    "metres": ("m", "UO:0000008"),
    "m\u00e8tre": ("m", "UO:0000008"),
    "m\u00e8tres": ("m", "UO:0000008"),
    "cm": ("cm", "UO:0000015"),
    "centimeter": ("cm", "UO:0000015"),
    "centimeters": ("cm", "UO:0000015"),
    "centimetre": ("cm", "UO:0000015"),
    "centimetres": ("cm", "UO:0000015"),
    "centim\u00e8tre": ("cm", "UO:0000015"),
    "centim\u00e8tres": ("cm", "UO:0000015"),
    "mm": ("mm", "UO:0000016"),
    "millimeter": ("mm", "UO:0000016"),
    "millimeters": ("mm", "UO:0000016"),
    "millimetre": ("mm", "UO:0000016"),
    "millimetres": ("mm", "UO:0000016"),
    "millim\u00e8tre": ("mm", "UO:0000016"),
    "millim\u00e8tres": ("mm", "UO:0000016"),
    "\u00b5m": ("\u00b5m", "UO:0000017"),
    "\u03bcm": ("\u00b5m", "UO:0000017"),
    "um": ("\u00b5m", "UO:0000017"),
    "micrometer": ("\u00b5m", "UO:0000017"),
    "micrometers": ("\u00b5m", "UO:0000017"),
    "micrometre": ("\u00b5m", "UO:0000017"),
    "micrometres": ("\u00b5m", "UO:0000017"),
    "microm\u00e8tre": ("\u00b5m", "UO:0000017"),
    "microm\u00e8tres": ("\u00b5m", "UO:0000017"),
}

# Symbols/names that can legitimately populate the wire model's measurement-unit slot.  The
# deterministic parser emits the canonical subset (m, cm, mm, µm); the contextual extractor may
# also encounter decimetres/nanometres or emit a UO CURIE directly.  Keeping this closed prevents
# ordinals and cardinalities such as ``5e feuille`` from masquerading as measurements with
# ``unit: leaf``.
_SUPPORTED_LENGTH_UNITS = frozenset(_UNIT_NORMALIZATION) | {
    "dm",
    "decimeter",
    "decimeters",
    "decimetre",
    "decimetres",
    "nm",
    "nanometer",
    "nanometers",
    "nanometre",
    "nanometres",
    "uo:0000008",  # meter
    "uo:0000015",  # centimeter
    "uo:0000016",  # millimeter
    "uo:0000017",  # micrometer
    "uo:0000018",  # nanometer
    "uo_0000008",
    "uo_0000015",
    "uo_0000016",
    "uo_0000017",
    "uo_0000018",
}


def is_supported_length_unit(unit: object) -> bool:
    """Return whether ``unit`` is a recognized linear-measurement unit token."""

    if not isinstance(unit, str):
        return False
    return unit.strip().rstrip(".").lower() in _SUPPORTED_LENGTH_UNITS


def _number(value: str) -> float:
    return float(value.replace(",", "."))


def _languages(language: str) -> set[str]:
    language = (language or "").strip().lower()
    if language.startswith("en"):
        return {"en"}
    if language.startswith("fr"):
        return {"fr"}
    # Legacy inputs do not always carry a language field. Requiring number+unit+cue still keeps
    # this multilingual fallback conservative.
    return {"en", "fr"}


def parse_measurements(text: str, language: str = "") -> list[Measurement]:
    """Return deterministic numeric measurements supported by exact spans in ``text``."""

    allowed = _languages(language)
    found: list[Measurement] = []
    seen: set[tuple[int, int, str]] = set()
    for spec in _PATTERNS:
        if spec.language not in allowed:
            continue
        for match in spec.regex.finditer(text or ""):
            key = (match.start(), match.end(), spec.attribute_id)
            if key in seen:
                continue
            seen.add(key)
            low = _number(match.group("low"))
            high_text = match.group("high")
            high = _number(high_text) if high_text else low
            # Descending explicit ranges in digitized floras are ambiguous OCR/source errors
            # (for example ``8-7 mm`` or a dropped decimal point in ``11-3.5 cm``).  Reordering
            # would invent an interpretation, while retaining them violates the range contract.
            if high_text and high < low:
                continue
            limit_text = match.group("limit")
            value_low: float | None = None if limit_text else low
            # A bare ``atteindre``-negation is a strict (exclusive) upper bound; every other
            # comparator, and a plain range, is inclusive.
            high_inclusive = not (limit_text and _STRICT_LIMIT_RE.fullmatch(limit_text.strip()))
            unit_key = match.group("unit").lower()
            unit_text, unit_id = _UNIT_NORMALIZATION[unit_key]
            found.append(
                Measurement(
                    start=match.start(),
                    end=match.end(),
                    attribute_id=spec.attribute_id,
                    value_low=value_low,
                    value_high=high,
                    unit_id=unit_id,
                    unit_text=unit_text,
                    source_text=text[match.start() : match.end()],
                    cue=match.group("cue"),
                    modifier="approximately" if match.group("approx") else "",
                    modifier_text=match.group("approx") or "",
                    value_high_inclusive=high_inclusive,
                )
            )
    return sorted(found, key=lambda item: (item.start, item.end, item.attribute_id))
