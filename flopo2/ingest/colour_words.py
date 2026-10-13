"""Read colour phrases of flora descriptions on FLOPO's ISCC-NBS colour backbone.

The word list is ``config/botanical_colour_synonyms.tsv`` (curator-approved English and French
colour words) plus the backbone class labels themselves (``config/flopo_colour_backbone_id_registry.tsv``).

Readings, in order:

1. the phrase is a listed word or backbone label: that class (its listed scope);
2. a compound of two hues ("orange-red", "red-orange", "orange-yellow", "pink-purple"): the
   ISCC-NBS level-2 category between the two hues when the backbone has one ("reddish orange",
   "orange yellow", "purplish pink"). ISCC-NBS names such intermediate hues with an adjectival
   first hue ("reddish") or a juxtaposed one ("orange yellow"); both hue orders are tried, so the
   phrase reads as the intermediate category rather than as its last word alone;
3. a modified or two-word colour without such a category ("pale yellow" when not listed,
   "creamy-white", "bright magenta-pink"): the class of the head (final) colour, NARROW, or
   RELATED when the head is itself only RELATED (the colour-backbone migration's reading of
   compounds that ISCC-NBS does not name).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

COLOUR_SYNONYMS = Path("config/botanical_colour_synonyms.tsv")
COLOUR_BACKBONE = Path("config/flopo_colour_backbone_id_registry.tsv")
COLOUR_ATTRIBUTE = "PATO_0000014"

# Hue words and the adjectival form ISCC-NBS uses in intermediate names.
HUES = {
    "red": "reddish", "orange": "orange", "yellow": "yellowish", "green": "greenish",
    "blue": "bluish", "purple": "purplish", "violet": "violet", "pink": "pinkish",
    "brown": "brownish", "olive": "olive",
}
HUE_ALIASES = {
    "reddish": "red", "orangish": "orange", "yellowish": "yellow", "greenish": "green",
    "bluish": "blue", "purplish": "purple", "pinkish": "pink", "brownish": "brown",
    "lilac": "purple", "mauve": "purple", "magenta": "purple", "crimson": "red", "scarlet": "red",
    "rose": "pink", "rosy": "pink",
}
MODIFIERS = {
    "pale", "deep", "dark", "bright", "light", "dull", "pure", "vivid", "brilliant", "rich",
    "clear", "intense", "soft", "strong", "dusky", "rusty", "dirty", "translucent", "glossy",
    "shiny", "velvety", "waxy", "very", "almost", "bluish", "pinkish", "reddish", "yellowish",
    "greenish", "purplish", "brownish", "greyish", "grayish", "whitish",
}


def load_colour_words(
    synonyms: Path = COLOUR_SYNONYMS, backbone: Path = COLOUR_BACKBONE
) -> dict[str, tuple[str, str]]:
    """English colour word -> (backbone class id, scope).

    Backbone class labels take precedence over listed words, and the lowest ISCC-NBS level wins
    for a label shared by several levels ("yellow" is the level-1 class)."""

    words: dict[str, tuple[str, str]] = {}
    with synonyms.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["language"] != "en" or not row["ontology_id"].startswith("FLOPO:"):
                continue
            words.setdefault(row["word"].lower(), (row["ontology_id"].replace(":", "_"), row["scope"]))
    labels: dict[str, tuple[str, str]] = {}
    with backbone.open(encoding="utf-8", newline="") as handle:
        rows = [r for r in csv.DictReader(handle, delimiter="\t") if r["kind"] == "backbone_class" and r["status"] != "obsolete"]
    for row in sorted(rows, key=lambda r: min(int(x) for x in re.findall(r"\d", r["iscc_nbs_level"] or "9"))):
        label = re.sub(r"\s*\(ISCC-NBS level \d\)", "", row["label"]).lower()
        labels.setdefault(label, (row["ontology_id"].replace(":", "_"), "EXACT"))
    words.update(labels)
    for word in list(words):
        if "gray" in word:
            words.setdefault(word.replace("gray", "grey"), words[word])
    return words


def _hue(token: str) -> str:
    return token if token in HUES else HUE_ALIASES.get(token, "")


def intermediate_hue(first: str, second: str, words: dict[str, tuple[str, str]]) -> str:
    """The backbone class named for the hue between two hues, e.g. red+orange -> reddish orange."""

    a, b = _hue(first), _hue(second)
    if not a or not b or a == b:
        return ""
    for name in (f"{HUES[a]} {b}", f"{HUES[b]} {a}", f"{a} {b}", f"{b} {a}"):
        if name in words and words[name][1] == "EXACT":
            return name
    return ""


def colour_value(phrase: str, words: dict[str, tuple[str, str]]) -> tuple[str, str, str] | None:
    """Return ``(backbone id, scope, reading)`` for a colour phrase, else ``None``."""

    key = re.sub(r"\s+", " ", str(phrase or "").lower().strip(" ,;."))
    key = key.replace("colored", "coloured").replace("greygreen", "grey-green")
    spaced = key.replace("-", " ")
    for candidate in (key, spaced):
        if candidate in words and words[candidate][1] == "EXACT":
            return *words[candidate], "exact word"
    tokens = spaced.split()
    hue_tokens = [t for t in tokens if _hue(t)]
    if len(tokens) >= 2 and len(hue_tokens) >= 2:
        name = intermediate_hue(hue_tokens[-2], hue_tokens[-1], words)
        if name:
            others = [t for t in tokens if t not in hue_tokens[-2:]]
            if all(t in MODIFIERS for t in others):
                backbone, _scope = words[name]
                scope = "NARROW" if others else "EXACT"
                return backbone, scope, f"intermediate hue of a two-hue compound: {name} (ISCC-NBS)"
    # grey/gray + hue: the ISCC-NBS "grayish <hue>" category (grey-green = grayish green).
    if len(tokens) >= 2 and tokens[-2] in {"grey", "gray", "greyish", "grayish"} and _hue(tokens[-1]):
        name = f"grayish {_hue(tokens[-1])}"
        if name in words and all(t in MODIFIERS for t in tokens[:-2]):
            return words[name][0], "NARROW" if tokens[:-2] else "EXACT", f"grey-tinged hue: {name} (ISCC-NBS)"
    for candidate in (key, spaced):
        if candidate in words:
            return *words[candidate], "listed colour word"
    if len(tokens) < 2 or tokens[-1] not in words:
        return None
    if all(t in MODIFIERS or t in words or t.rstrip("y") in words for t in tokens[:-1]):
        backbone, scope = words[tokens[-1]]
        reading = "head colour of a compound/modified colour (head-final, NARROW)"
        return backbone, "RELATED" if scope == "RELATED" else "NARROW", reading
    return None
