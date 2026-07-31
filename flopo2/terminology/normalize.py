"""Conservative normalization shared by registries, retrieval, and span matching."""

from __future__ import annotations

import re
import unicodedata

_NON_WORD = re.compile(r"[^a-z0-9]+")
_TOKEN = re.compile(r"[^\W_]+(?:[’'][^\W_]+)?|\d+(?:[.,]\d+)?", re.UNICODE)
_IRREGULAR = {
    "leaves": "leaf",
    "teeth": "tooth",
    "axes": "axis",
    "calyces": "calyx",
    "indices": "index",
    "fleurs": "fleur",
    "feuilles": "feuille",
    "folioles": "foliole",
    "petales": "petale",
    "sepales": "sepale",
}


def fold(text: str) -> str:
    """Case/accent/punctuation-fold text without applying linguistic stemming."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("’", "'")
    return _NON_WORD.sub(" ", text).strip()


def inflection_key(token: str) -> str:
    """Return a deliberately small EN/FR morphology key used only for mention matching."""
    token = fold(token)
    if token in _IRREGULAR:
        return _IRREGULAR[token]
    if len(token) > 5 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 5 and token.endswith("es") and not token.endswith(("ses", "xes")):
        return token[:-2]
    if len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def morphology_key(text: str) -> str:
    return " ".join(inflection_key(token) for token in fold(text).split())


def text_tokens(text: str) -> list[tuple[str, str, int, int]]:
    """Return ``(folded, morphology-key, start, end)`` tokens with source offsets."""
    out = []
    for match in _TOKEN.finditer(text or ""):
        normalized = fold(match.group())
        if normalized:
            out.append((normalized, inflection_key(normalized), match.start(), match.end()))
    return out


def char_ngrams(text: str, n: int = 3) -> set[str]:
    compact = f"  {fold(text).replace(' ', '_')}  "
    return {compact[i : i + n] for i in range(max(0, len(compact) - n + 1))}
