"""Readings of the annotation patterns 19 to 25 (docs/odp), added after the second-model review
of 23 November 2026.

Each function reads one construction from a transcribed row and its source span and returns the
slot of the annotation record, or ``None`` when the construction is not there. The annotator
(:mod:`flopo2.ingest.ncvc_annotate`) calls them at the place where it would otherwise leave the
statement unresolved.

* 19 ``maximum_at_least``: "to more than 1.5 m", "to at least 6 cm", "up to 4 cm long or longer"
* 20 ``extent``: "exserted 5-6 mm", "fused for 1.2 cm", "decurrent 3-20 mm"
* 21 a growth-form noun ("Lianas", "Vines") is a rule to a habit value: no code here
* 22 a part present at a place ("rooting at the nodes") is a presence rule with a place: the
  annotator reads the place from the rule
* 23 ``presence_variable``: "with or without stipules", "lenticellate or not", "pedicels absent or to 0.5 mm"
* 24 a stage boundary: "after anthesis", "before flowering", "by flowering"
* 25 ``towards`` with an implied counterpart: "paler beneath", "the inner smaller"
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

EXTENT_QUALITIES = Path("config/extent_qualities.tsv")

# 19 ---------------------------------------------------------------------------------------------
_COMPARATIVE = r"(?:more|longer|taller|higher|larger|wider|broader|greater|thicker|bigger)"
_MAXIMUM_AT_LEAST = re.compile(
    r"\b(?P<to>(?:up\s+)?to|reaching|attaining|jusqu['’]?\s*[aà]|hasta)\s+"
    r"(?P<cue>more\s+than|over|at\s+least|above|plus\s+de|m[aá]s\s+de)\b"
    r"|(?P<tail>\bor\s+" + _COMPARATIVE + r"\b|\band\s+more\b|\bou\s+plus\b|\bo\s+m[aá]s\b)",
    re.IGNORECASE,
)
_RARE = re.compile(r"\b(?:rarely|seldom|never|not|scarcely|hardly|occasionally|sometimes)\b", re.IGNORECASE)


def _numbers(low, high) -> set | None:
    """The numbers of a row; ``None`` when a slot holds a word (Qwen writes "width", "lanceolate")."""

    try:
        return {float(v) for v in (low, high) if v is not None and v != ""}
    except (TypeError, ValueError):
        return None


def maximum_at_least(span_text: str, low, high) -> dict | None:
    """"to more than 1.5 m": the largest plants are larger than the number, and how large is not
    said. ``{value, inclusive, cue_text, cue_start, cue_end}`` (offsets within the span); ``None``
    when the span has no such cue, a range, or a word that makes the bound a rare case."""

    numbers = _numbers(low, high)
    if numbers is None:
        return None
    if len(numbers) != 1 or _RARE.search(span_text):
        return None
    found = _MAXIMUM_AT_LEAST.search(span_text)
    if found is None:
        return None
    if found.group("tail"):
        # "up to 4 cm long or longer" bounds the maximum; "8 or more sporangia" is a lower bound
        # on every plant (pattern 02, :func:`lower_bound_tail`)
        if not re.search(r"\b(?:to|reaching|attaining|jusqu['’]?\s*[aà]|hasta)\b[^\d]*\d", span_text[:found.start()], re.IGNORECASE):
            return None
        inclusive = True
    else:
        inclusive = bool(re.fullmatch(r"at\s+least", found.group("cue"), re.IGNORECASE))
    return {"value": numbers.pop(), "inclusive": inclusive, "cue_text": found.group(0),
            "cue_start": found.start(), "cue_end": found.end()}


def lower_bound_tail(span_text: str, low, high) -> bool:
    """"8 or more sporangia", "1 m or more in diameter": one number with "or more" after it and no
    "to" before it is a lower bound (pattern 02)."""

    numbers = _numbers(low, high)
    if numbers is None:
        return False
    found = _MAXIMUM_AT_LEAST.search(span_text)
    return bool(len(numbers) == 1 and found and found.group("tail") and not _RARE.search(span_text)
                and re.search(r"\d", span_text[:found.start()]) and maximum_at_least(span_text, low, high) is None)


def without_bound_tail(span_text: str) -> str:
    """The span without "or longer", for the checks that look for alternatives."""

    from flopo2.verify.gates import BOUND_TAIL

    return BOUND_TAIL.sub(" ", span_text)


# 20 ---------------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def extent_qualities(path: Path = EXTENT_QUALITIES) -> dict[str, dict]:
    """``{quality class: row}`` of the states and relations whose extent a flora measures."""

    with path.open(encoding="utf-8", newline="") as handle:
        return {row["quality"]: row for row in csv.DictReader(handle, delimiter="\t")}


def extent_quality(pato_id: str, value_terms: list[str]) -> str:
    """The class of the row that may carry an extent, or ``""``."""

    known = extent_qualities()
    return next((term for term in [*value_terms, pato_id] if term in known), "")


# 23 ---------------------------------------------------------------------------------------------
_OPTIONAL = re.compile(
    r"\bwith\s+or\s+without\b|\bpresent\s+or\s+(?:absent|lacking|wanting|missing|not)\b"
    r"|\b(?:absent|lacking|wanting|missing|none|0)\s+or\b|\bor\s+(?:absent|lacking|wanting|missing|none|not|0)\b"
    r"|\bsometimes\s+(?:absent|lacking|wanting|missing)\b|\bavec\s+ou\s+sans\b|\bcon\s+o\s+sin\b",
    re.IGNORECASE,
)


def optional_part(span_text: str) -> dict | None:
    """"with or without stipules", "lenticellate or not", "pedicels absent or to 0.5 mm": the
    part is there in some plants of the taxon and not in others. ``{cue_text, cue_start,
    cue_end}`` (offsets within the span) or ``None``."""

    found = _OPTIONAL.search(span_text)
    if found is None or len(_OPTIONAL.findall(span_text)) != 1:
        return None
    return {"cue_text": found.group(0), "cue_start": found.start(), "cue_end": found.end()}


# 24 ---------------------------------------------------------------------------------------------
_BOUNDARY = re.compile(
    r"^(?P<word>after|following|since|post|apr[eè]s|despu[eé]s\s+de"
    r"|before|prior\s+to|until|avant|antes\s+de"
    r"|by)\s+(?:the\s+)?(?P<stage>.+)$",
    re.IGNORECASE,
)
_RELATION = {"after": "present_after", "following": "present_after", "since": "present_after",
             "post": "present_after", "après": "present_after", "apres": "present_after",
             "before": "present_before", "prior to": "present_before", "until": "present_before",
             "avant": "present_before", "antes de": "present_before", "by": "present_during"}


def stage_boundary(res, word: str, text: str, start: int, end: int):
    """"after anthesis", "before flowering", "by flowering": ``(reading, cue_start, cue_end,
    relation)`` when the words after the preposition have a reviewed reading as a stage and the
    phrase stands once in the clause; else ``None``. "by flowering" says that the state is
    reached no later than the stage, so it holds during it."""

    match = _BOUNDARY.match(" ".join(str(word).split()))
    if match is None:
        return None
    key = " ".join(match.group("word").lower().split())
    relation = _RELATION.get(key) or ("present_after" if key.startswith("desp") else None)
    if relation is None:
        return None
    stage = match.group("stage").strip().lower()
    words = getattr(res, "context_words", None) or {}
    reading = None
    for candidate in (stage, f"at {stage}", f"in {stage}", f"when {stage}"):
        reading = next((r for r in words.get(candidate, []) if r["kind"] == "stage"), None)
        if reading is not None:
            break
    if reading is None:
        return None
    left = max(text.rfind(c, 0, start) for c in ".;") + 1
    right = min([i for i in (text.find(c, end) for c in ".;") if i >= 0] or [len(text)])
    phrase = r"\s+".join(re.escape(part) for part in str(word).split())
    found = list(re.finditer(r"(?<![\w-])" + phrase + r"(?![\w-])", text[left:right], re.IGNORECASE))
    if len(found) != 1:
        return None
    return reading, left + found[0].start(), left + found[0].end(), relation


# 25 ---------------------------------------------------------------------------------------------
# comparative word -> quality; the colour words have no relational class in PATO and take the
# value they compare by ("paler": low saturation, with the other side as the second term)
IMPLIED_COMPARISONS = {
    "shorter": "PATO_0000574", "longer": "PATO_0000573", "longest": "PATO_0000573", "shortest": "PATO_0000574",
    "broader": "PATO_0000600", "wider": "PATO_0000600", "narrower": "PATO_0000599",
    "larger": "PATO_0000586", "bigger": "PATO_0000586", "largest": "PATO_0000586",
    "smaller": "PATO_0000587", "smallest": "PATO_0000587",
    "thicker": "PATO_0000591", "thinner": "PATO_0000592",
    "paler": "PATO_0000328", "lighter": "PATO_0000665", "darker": "PATO_0000327",
}
# position word -> (kind, own key); the counterpart is the opposite key of the same kind
_SIDES = {"abaxial": "adaxial", "adaxial": "abaxial"}
_SIDE_WORDS = {
    "beneath": "abaxial", "below": "abaxial", "underneath": "abaxial", "abaxially": "abaxial",
    "abaxial": "abaxial", "lower surface": "abaxial", "lower side": "abaxial", "underside": "abaxial",
    "above": "adaxial", "adaxially": "adaxial", "adaxial": "adaxial", "upper surface": "adaxial",
    "upper side": "adaxial",
}
_SERIES = {"FLOPO_0991378": "FLOPO_0991379", "FLOPO_0991379": "FLOPO_0991378",   # inner / outer
           "FLOPO_0991376": "FLOPO_0991377", "FLOPO_0991377": "FLOPO_0991376",   # upper / lower
           "FLOPO_0991002": "FLOPO_0991117", "FLOPO_0991117": "FLOPO_0991002"}   # basal / cauline
_SERIES_WORDS = {
    "inner": "FLOPO_0991378", "outer": "FLOPO_0991379", "upper": "FLOPO_0991376", "lower": "FLOPO_0991377",
    "uppermost": "FLOPO_0991376", "lowermost": "FLOPO_0991377", "lowest": "FLOPO_0991377",
    "basal": "FLOPO_0991002", "radical": "FLOPO_0991002", "cauline": "FLOPO_0991117", "stem": "FLOPO_0991117",
}
_WORD = re.compile(r"(?<![\w-])(" + "|".join(sorted(map(re.escape, IMPLIED_COMPARISONS), key=len, reverse=True)) + r")(?![\w-])",
                   re.IGNORECASE)
_SIDE = re.compile(r"(?<![\w-])(" + "|".join(sorted(map(re.escape, _SIDE_WORDS), key=len, reverse=True)) + r")(?![\w-])",
                   re.IGNORECASE)
_SERIES_RE = re.compile(r"(?<![\w])(" + "|".join(sorted(map(re.escape, _SERIES_WORDS), key=len, reverse=True)) + r")(?![\w])",
                        re.IGNORECASE)
_THAN_OTHER = re.compile(r"\bthan\s+(?:the\s+)?(" + "|".join(map(re.escape, _SERIES_WORDS)) + r")\b(?!\s+[a-z])",
                         re.IGNORECASE)


def implied_counterpart(phenotype: dict, span_text: str, bearer: str, surface_class, positioned) -> dict | None:
    """"paler beneath", "the inner smaller", "narrower than the upper": a comparison whose second
    term is the same part at the opposite place.

    ``surface_class(bearer, side)`` gives the class of a side of the bearer or ``""``;
    ``positioned`` is the table of named positioned parts ``{(part, position): (class, label)}``.
    Returns the updates of the record: ``pato_id``, optionally ``po_id`` or
    ``bearer_context_qualities``, and ``towards`` (with ``implied: True`` and, where the second
    term has no class of its own, ``counterpart_position``). Offsets are within the span.
    """

    quality = " ".join(str(phenotype.get("quality_en") or "").lower().split())
    word = _WORD.search(span_text) or _WORD.search(quality)
    if word is None or len({m.group(1).lower() for m in _WORD.finditer(span_text)}) > 1:
        return None
    if re.search(r"\b(?:not|no|never|nor)\s+" + re.escape(word.group(1)), span_text, re.IGNORECASE):
        return None
    pato = IMPLIED_COMPARISONS[word.group(1).lower()]
    cue = _SIDE.search(span_text)
    if cue is not None and len(_SIDE.findall(span_text)) == 1:
        own = _SIDE_WORDS[cue.group(1).lower()]
        own_class, other_class = surface_class(bearer, own), surface_class(bearer, _SIDES[own])
        if own_class and other_class and own_class != other_class:
            return {"pato_id": pato, "po_id": own_class, "outer_bearer": bearer,
                    "towards": {"target_term": other_class, "target_text": cue.group(0), "start": cue.start(),
                                "end": cue.end(), "comparison_text": word.group(1), "implied": True},
                    "provenance": f"relation: {word.group(1)!r} {cue.group(0)!r} -> {pato} of the {own} side "
                                  f"({own_class}) towards the {_SIDES[own]} side ({other_class})"}
        return None
    than = _THAN_OTHER.search(span_text)
    if than is not None:
        other, cue = _SERIES_WORDS[than.group(1).lower()], than
        own = _SERIES[other]
    else:
        found = list(_SERIES_RE.finditer(span_text))
        if len(found) != 1:
            return None
        cue = found[0]
        own = _SERIES_WORDS[cue.group(1).lower()]
        other = _SERIES[own]
    out = {"pato_id": pato}
    own_named, other_named = positioned.get((bearer, own)), positioned.get((bearer, other))
    target = {"target_text": cue.group(0), "start": cue.start(), "end": cue.end(),
              "comparison_text": word.group(1), "implied": True}
    if own_named and other_named:
        out["po_id"], target["target_term"] = own_named[0], other_named[0]
        out["outer_bearer"] = bearer
    else:
        out["bearer_context_qualities"] = [own]
        target.update({"target_term": bearer, "counterpart_position": other})
    out["towards"] = target
    out["provenance"] = (f"relation: {word.group(1)!r} with {cue.group(0)!r} -> {pato}, the part at {own} "
                         f"towards the same part at {other}")
    return out
