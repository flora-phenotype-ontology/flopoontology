"""Recover exact PATO compound-colour terms from withheld flora spans.

The deterministic baseline deliberately withholds every quality cue touching a hyphen or slash.
That is correct for unreviewed botanical compounds such as ``ovate-lanceolate``, but it also
withholds standardized atomic colours already represented in PATO, for example ``yellow-green``
and ``reddish-brown``.  This module performs a deliberately narrower second pass:

* a source phrase must match a PATO colour preferred label or an ``EXACT`` synonym after only
  whitespace/dash normalization;
* ``RELATED`` and other non-exact synonyms are never used;
* the complete hyphenated token must match (no decomposition of a larger compound);
* alternatives, transitions, temporal changes, negation, and developmental contexts remain
  unresolved for a logical/contextual parser; and
* an assertion is emitted only when the existing conservative bearer resolver returns a PO id.

The input baseline is never overwritten.  Every promoted assertion retains exact character
offsets and the original source phrase; all non-promoted evidence is copied unchanged.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from flopo2.annotation.provenance import ensure_source_statements
from flopo2.extract import baseline
from flopo2.extract.ground import Lexicon


PATO_COLOR = "PATO:0000014"
TARGET_REASON = "hyphenated_or_slash_compound"
_DASHES = "-\u2013\u2014"
_TOKEN_PUNCTUATION = frozenset(_DASHES + "'\u2019")
_REPORT_QUOTE_PAIRS = (("“", "”"), ("«", "»"), ('"', '"'))
_LOGICAL_CONNECTOR = re.compile(r"\b(?:or|ou|to|through)\b|\band\s*/\s*or\b", re.I)
_TEMPORAL_CONNECTOR = re.compile(
    r"\b(?:turning|becoming|maturing|ripen(?:s|ed|ing)?|ripe|rife|unripe|"
    r"later|eventually|then|afterwards?|initially|at\s+first|with\s+age|"
    r"before\s+peeling|after\s+peeling|devenant|puis|ensuite|matur(?:ation|ité|ite)|"
    r"m[ûu]r(?:e|es|s|it|issant|issante|issants|issantes)?)\b",
    re.I,
)
_PARENTHETICAL_VARIANT_AFTER = re.compile(
    r"^\s*(?:\(\s*)?(?:rarely|occasionally|sometimes|exceptionally|"
    r"rarement|parfois|occasionnellement)\b",
    re.IGNORECASE,
)
_RELATIVE_MODALITY_BEFORE = re.compile(
    r"\b(?:less|more)\s+(?:often|frequently)\s*$",
    re.IGNORECASE,
)
_COORDINATED_MODALITY_BEFORE = re.compile(
    r"\b(?:normally|usually|generally|typically|often|sometimes|occasionally|rarely|"
    r"normalement|g[ée]n[ée]ralement|habituellement|souvent|parfois|rarement)\b"
    r"[^;:.]{1,96}$",
    re.IGNORECASE,
)
_REPORTED_ATTRIBUTION_AFTER = re.compile(
    r"\b(?:<i>\s*)?fide(?:\s*</i>)?\b",
    re.IGNORECASE,
)
_LIFE_STATE_AFTER = re.compile(
    r"^\s*\(\s*in\s+life\s*\)",
    re.IGNORECASE,
)
_RELATIONAL_FLOWER_CATEGORY_BEFORE = re.compile(
    r"\b(?:male|female|hermaphrodite|staminate|pistillate|short[- ]styled|long[- ]styled)"
    r"\s+flowers?\s*:.{0,260}$|"
    r"\bfleurs?\s+(?:m[âa]les?|femelles?|hermaphrodites?|stamin[ée]es?|pistill[ée]es?)"
    r"\s*:.{0,260}$",
    re.IGNORECASE,
)
_PRECEDING_WORD = re.compile(r"[^\W\d_]+(?:['\u2019][^\W\d_]+)?\s*$", re.UNICODE)
_SCOPE_PATTERNS = (
    (
        "surface_or_subregion",
        re.compile(
            r"\b(?:upper|lower|inner|outer|adaxial|abaxial)\s+"
            r"(?:surface|face|side)|"
            r"\b(?:middle|inner|outer)\s+"
            r"(?:(?:surface|layer)\s+of\s+(?:the\s+)?)?bark\b|"
            r"\b(?:middle|inner|outer)\s+(?:bark\s+)?(?:surface|layer)\b|"
            r"\bunder[- ]?bark\b|"
            r"\b(?:surface|face|veins?|nerves?|nervures?|midribs?|costae?|costas?|"
            r"côtes?|cotes?|styleheads?|style[- ]heads?|margin|edge|bord|marge)\b|"
            r"\b(?:spike\s+proper|the\s+spike\s+proper)\b|"
            r"\b(?:above|below|beneath|adaxially|abaxially)\b|"
            r"\b(?:base|apex|tips?|mouth|throat|opening|interior|exterior|inside|outside|"
            r"intérieur|interieur|extérieur|exterieur)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "unsupported_covering_or_appendage",
        re.compile(
            r"\b(?:indumentum|indument|tomentum|pubescence|"
            r"setae?|bristles?|prickles?|spines?|scales?|gland(?:ular)?[ -]dots?|"
            r"glands?|spots?|patches?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "unsupported_tube_or_lobe",
        re.compile(
            r"\b(?:tubes?|lobes?|teeth|segments?|parts?|parties?|spurs?|"
            r"pulp|flesh|sarcotesta|exotesta|endotesta|sheaths?|filaments?|filets?|"
            r"standards?|étendards?|etendards?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "relational_bearer_context",
        re.compile(
            r"\b(?:short|long)[- ]styled\s+flowers?\b",
            re.IGNORECASE,
        ),
    ),
)
_PATTERN_COLOUR_BEFORE = re.compile(
    r"\b(?:streaked|striped|striated|lineate|flecked|mottled|speckled|"
    r"blotched|banded|marked)(?:\s+(?:densely|finely|faintly|indistinctly|"
    r"dark|light|pale|bright|dull))*\s+(?:with\s+)?"
    r"(?:(?:dark|light|pale|bright|dull|deep|darker|lighter|paler|brighter|"
    r"faintly|indistinctly)\s+)*$",
    re.IGNORECASE,
)
_PATTERN_COLOUR_AFTER = re.compile(
    r"^\s+(?:flecks?|streaks?|stripes?|markings?|bands?|dots?|stains?|"
    r"mottling|speckles?|blotches?|flecked|streaked|striped|marked|spotted|"
    r"mottled|banded|tinged|suffused|flushed)\b",
    re.IGNORECASE,
)
_VARIEGATED_COLOUR_BEFORE = re.compile(
    r"\b(?:variegated|variegate|panach[ée]s?)\b[^;:.]{0,72}$",
    re.IGNORECASE,
)
_COLOURED_INDUMENT_AFTER = re.compile(
    r"^\s+(?:strigose|strigulose|tomentose|tomentellous|pubescent|puberulous|"
    r"hairy|hirsute|subhirsute|hirtellous|hispid|pilose|villous|velvety|"
    r"velutinous|subvelutinous|sericeous|lepidote|lepidotous|scurfy|scurfily|"
    r"tomenteux|tomenteuse|velu|velue|poilu|poilue|soyeux|soyeuse)\b",
    re.IGNORECASE,
)
_COLOUR_MODIFIER_BEFORE = re.compile(
    r"(?<!\w)(?:pale|light|dark|bright|deep|dull|vivid|pastel|rich|buffish|"
    r"paler|lighter|darker|brighter|deeper|"
    r"greyish|grayish|brownish|reddish|yellowish|greenish|bluish|orangish|"
    r"purplish|pinkish|"
    r"pâle|clair|claire|foncé|fonce|foncée|foncee|vif|vive)"
    r"(?:[\s\-–—]+(?:greyish|grayish|brownish|reddish|yellowish|greenish))?"
    r"[\s\-–—]*$",
    re.IGNORECASE,
)
_PARENTHETICAL_COLOUR_MODIFIER_BEFORE = re.compile(
    r"\(\s*(?:pale|light|dark|bright|deep|dull|vivid|pastel|"
    r"pâle|clair|claire|foncé|fonce|foncée|foncee|vif|vive)\s*\)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PatoTerm:
    pato_id: str
    label: str
    parents: tuple[str, ...]
    exact_synonyms: tuple[str, ...]


@dataclass(frozen=True)
class CompoundMatch:
    start: int
    end: int
    pato_id: str
    pato_label: str
    lexical_form: str
    unresolved_indexes: tuple[int, ...]


@dataclass(frozen=True)
class BearerResolution:
    po_id: str
    method: str
    surface_form: str = ""


def _normal_form(value: str) -> str:
    return re.sub(rf"[\s{re.escape(_DASHES)}]+", " ", value.casefold()).strip()


def load_pato_terms(path: Path) -> dict[str, PatoTerm]:
    """Read just the fields needed for exact lexical and colour-ancestry checks."""

    terms: dict[str, PatoTerm] = {}
    current_id = ""
    name = ""
    parents: list[str] = []
    exact_synonyms: list[str] = []

    def finish() -> None:
        nonlocal current_id, name, parents, exact_synonyms
        if current_id and name:
            terms[current_id] = PatoTerm(
                current_id.replace(":", "_"),
                name,
                tuple(parents),
                tuple(exact_synonyms),
            )
        current_id = ""
        name = ""
        parents = []
        exact_synonyms = []

    with Path(path).open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line == "[Term]":
                finish()
            elif line.startswith("["):
                finish()
            elif line.startswith("id: PATO:"):
                current_id = line.removeprefix("id: ")
            elif line.startswith("name: "):
                name = line.removeprefix("name: ")
            elif line.startswith("is_a: PATO:"):
                parents.append(line.removeprefix("is_a: ").split()[0])
            elif line.startswith("synonym: ") and " EXACT " in line:
                match = re.match(r'^synonym: "(.*)" EXACT(?: \[.*\])?$', line)
                if match:
                    exact_synonyms.append(match.group(1))
            elif not line:
                finish()
    finish()
    return terms


def exact_compound_colour_lexicon(path: Path) -> dict[str, tuple[str, str]]:
    """Return unambiguous compound colour forms from PATO labels and EXACT synonyms."""

    terms = load_pato_terms(path)

    @lru_cache(maxsize=None)
    def is_colour(term_id: str) -> bool:
        if term_id == PATO_COLOR:
            return True
        return any(is_colour(parent) for parent in terms.get(term_id, PatoTerm("", "", (), ())).parents)

    candidates: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for obo_id, term in terms.items():
        if not is_colour(obo_id):
            continue
        for lexical_form in (term.label, *term.exact_synonyms):
            normalized = _normal_form(lexical_form)
            if " " in normalized:
                candidates[normalized].add((term.pato_id, term.label))
    # A lexical form used EXACTly by multiple classes is not deterministic evidence.
    return {
        lexical_form: next(iter(values))
        for lexical_form, values in candidates.items()
        if len(values) == 1
    }


def _word_character(character: str) -> bool:
    return character.isalpha() or character in _TOKEN_PUNCTUATION


def _compound_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = start
    right = end

    def grow(current_left: int, current_right: int) -> tuple[int, int]:
        while current_left > 0 and _word_character(text[current_left - 1]):
            current_left -= 1
        while current_right < len(text) and _word_character(text[current_right]):
            current_right += 1
        return current_left, current_right

    left, right = grow(left, right)
    # Printed floras frequently insert one layout space after a line-breaking dash
    # (``red- brown``).  It is the same whole token as ``red-brown`` and must be tested against
    # PATO as a unit.  Bridge only whitespace immediately adjacent to a dash, never ordinary
    # inter-word spaces.
    for _ in range(4):
        changed = False
        if right > 0 and text[right - 1] in _DASHES:
            following = re.match(r"^[ \t]+(?=[^\W\d])", text[right:])
            if following:
                left, right = grow(left, right + following.end())
                changed = True
        if left > 0:
            preceding = re.search(
                rf"[^\W\d][\w'\u2019]*[{re.escape(_DASHES)}][ \t]+$",
                text[:left],
            )
            if preceding:
                left, right = grow(preceding.start(), right)
                changed = True
        if not changed:
            break
    return left, right


def _nearby_context_reason(text: str, start: int, end: int) -> str:
    """Return why an exact compound still cannot be asserted atomically."""

    contextual = baseline._negated_or_hedged(text, start)
    if contextual:
        return contextual
    clause, clause_start = baseline._clause_at(text, start)
    # A colour anywhere in a semicolon/sentence clause that explicitly contrasts or conditions a
    # ripening/maturity state is stage-dependent.  This also catches the earlier value in
    # ``Fruit yellow-green, ... ripening evenly red``; proximity-only checks incorrectly promoted
    # that as an unconditional fruit colour.
    if _TEMPORAL_CONNECTOR.search(clause):
        return "developmental_stage_context"
    local_start = start - clause_start
    local_end = end - clause_start
    before = clause[max(0, local_start - 96) : local_start]
    after = clause[local_end : min(len(clause), local_end + 96)]
    if _REPORTED_ATTRIBUTION_AFTER.search(after):
        return "reported_attribution_context"
    if _LIFE_STATE_AFTER.match(after):
        return "unmodeled_life_state_context"
    if _PARENTHETICAL_VARIANT_AFTER.match(after):
        return "logical_compound_context"
    if _RELATIVE_MODALITY_BEFORE.search(before):
        return "unmodeled_relative_modality"
    if _COORDINATED_MODALITY_BEFORE.search(before) and not (
        _COLOUR_MODIFIER_BEFORE.search(before)
        or _PARENTHETICAL_COLOUR_MODIFIER_BEFORE.search(before)
    ):
        _fields, _qualifier_start, qualifier_text = baseline._modality_context(text, start)
        if not qualifier_text:
            return "unmodeled_coordinated_modality"
    # A connector is relevant only when the intervening text is short.  This covers values with
    # modifiers (``or pale yellow-green``) without treating an unrelated connector elsewhere in a
    # long clause as part of this colour expression.
    before_connector = list(_LOGICAL_CONNECTOR.finditer(before))
    if before_connector and len(before) - before_connector[-1].end() <= 72:
        return "logical_compound_context"
    after_connector = _LOGICAL_CONNECTOR.search(after)
    if after_connector and after_connector.start() <= 72:
        return "logical_compound_context"
    return ""


class BearerResolver:
    """Fast, exact heading grounding plus the baseline's local attachment rules."""

    def __init__(self, po_lexicon: Path) -> None:
        self.po_lexicon = Lexicon.load(Path(po_lexicon))

    def heading(self, organ: object) -> str:
        key = str(organ or "").strip().casefold()
        return (
            baseline.ORGAN_OVERRIDES.get(key)
            or baseline.FDAC_FRENCH_ORGAN_OVERRIDES.get(key)
            or self.po_lexicon.label_to_id.get(key)
            or self.po_lexicon.label_to_id.get(key.rstrip("s"))
            or ""
        )

    def resolve(
        self, record: dict, start: int, end: int, candidate_pato_id: str
    ) -> BearerResolution:
        """Resolve a bearer while retaining whether support was local or heading-only."""

        text = str(record.get("text", ""))
        clause, left = baseline._clause_at(text, start)
        local_start = start - left
        local_end = end - left
        candidates: list[tuple[int, int, int, int, str, str, str]] = []

        def scored_gap(match: re.Match[str]) -> tuple[int, int, int]:
            gap, side, length = baseline._match_gap(match, local_start, local_end)
            if match.end() <= local_start:
                relation = clause[max(0, match.start() - 48) : match.start()]
                if re.search(
                    r"\b(?:of|de|du|des|per|par)\b[^,;:.]{0,40}$|"
                    r"\b(?:in|on)\b[^,;:.]{0,32}$|"
                    r"\b(?:dans|sur|sous|contre)\b[^,;:.]{0,32}$|"
                    r"\b(?:below|above|beneath|under|near|from|against|beyond|within|"
                    r"outside|inside)\b[^,;:.]{0,32}$|"
                    r"\b(?:exceeding|overtopping|surpassing|reaching|equalling|equaling)\b"
                    r"[^,;:.]{0,24}$|"
                    r"\bd['’][^,;:.]{0,40}$",
                    relation,
                    re.IGNORECASE,
                ):
                    gap += 96
                object_prefix = clause[max(0, match.start() - 32) : match.start()]
                if re.search(
                    r"\b(?:filling|containing|enclosing|surrounding|covering)\s+"
                    r"(?:an?\s+|the\s+)?$",
                    object_prefix,
                    re.IGNORECASE,
                ):
                    gap += 96
            elif match.start() >= local_end:
                bridge = clause[local_end : match.start()]
                # A later structure introduced after punctuation or by ``with`` normally starts
                # a nested/new characterization.  Without this penalty, ``seeds red-brown,
                # glossy, testa cells ...`` is incorrectly attached to the later testa, and
                # ``seeds chestnut-brown with a white hilum`` to the hilum.
                if re.search(
                    r"[,;:]|\b(?:with|bearing|having|whose|avec)\b",
                    bridge,
                    re.IGNORECASE,
                ):
                    gap += 96
            return gap, side, length

        for po_id, pattern in baseline.LOCAL_BEARER_PATTERNS:
            for match in pattern.finditer(clause):
                gap, side, length = scored_gap(match)
                candidates.append(
                    (gap, 1, side, length, po_id, "explicit_local", match.group(0))
                )
        for po_id, pattern, allowed_pato_ids in baseline.CONTEXTUAL_BEARER_PATTERNS:
            for match in pattern.finditer(clause):
                resolved = po_id if candidate_pato_id in allowed_pato_ids else ""
                gap, side, length = scored_gap(match)
                candidates.append(
                    (
                        gap,
                        0,
                        side,
                        length,
                        resolved,
                        "contextual_local" if resolved else "blocked_local",
                        match.group(0),
                    )
                )
        for pattern in baseline.UNRESOLVED_BEARER_PATTERNS:
            for match in pattern.finditer(clause):
                gap, side, length = scored_gap(match)
                candidates.append(
                    (gap, 0, side, length, "", "blocked_local", match.group(0))
                )
        heading = self.heading(record.get("organ"))
        if heading:
            # A typed source heading is safer than a distant local noun reached only through a
            # relational or post-comma phrase. Nearby explicit bearers still win this score.
            candidates.append(
                (
                    80,
                    2,
                    0,
                    0,
                    heading,
                    "organ_heading",
                    str(record.get("organ", "") or ""),
                )
            )
        if candidates:
            selected = min(candidates)
            return BearerResolution(selected[4], selected[5], selected[6])
        return BearerResolution(
            heading,
            "organ_heading" if heading else "missing",
            str(record.get("organ", "") or ""),
        )

    def local(self, record: dict, start: int, end: int, candidate_pato_id: str) -> str:
        return self.resolve(record, start, end, candidate_pato_id).po_id


def _unsafe_bearer_scope(
    text: str, start: int, end: int, bearer: BearerResolution
) -> tuple[str, str] | None:
    """Return an anatomical scope that the closed bearer resolver cannot model safely."""

    clause, clause_start = baseline._clause_at(text, start)
    local_start = start - clause_start
    local_end = end - clause_start
    before = clause[max(0, local_start - 72) : local_start]
    after = clause[local_end : min(len(clause), local_end + 40)]
    if _RELATIONAL_FLOWER_CATEGORY_BEFORE.search(text[max(0, start - 300) : start]):
        return "relational_bearer_context", "flower category heading"
    if re.match(r"^\s+(?:within|inside|outside)\b", clause[local_end:], re.IGNORECASE):
        return "surface_or_subregion", "direct postposed surface qualifier"
    if re.match(r"^\s+lips?\b", clause[local_end:], re.IGNORECASE):
        return "unsupported_tube_or_lobe", "lip"
    if bearer.po_id == "PO_0000282" and re.match(
        r"^[^;]{0,160}\bwith\b[^;]{0,120}\b(?:hairs?|trichomes?|poils?)\b",
        clause[local_end:],
        re.IGNORECASE,
    ):
        # In ``Pod reddish-brown, ... with sparse white hairs``, a later covering must not
        # steal the colour from an unsupported/implicit earlier subject.  Preserve the span for
        # a relational bearer parser instead of asserting that the (explicitly white) hairs are
        # reddish-brown.
        return "postposed_nested_covering", bearer.surface_form
    if (
        _PATTERN_COLOUR_BEFORE.search(before)
        or _VARIEGATED_COLOUR_BEFORE.search(clause[max(0, local_start - 96) : local_start])
        or _PATTERN_COLOUR_AFTER.match(after)
    ):
        return "pattern_or_marking_colour", ""
    if _COLOURED_INDUMENT_AFTER.match(after) and bearer.po_id != "PO_0000282":
        return "unsupported_covering_or_appendage", ""
    window = clause[max(0, local_start - 52) : min(len(clause), local_end + 52)]
    for reason, pattern in _SCOPE_PATTERNS:
        match = pattern.search(window)
        if match:
            return reason, match.group(0)
    # Ordinary hair/trichome colour is the one locally supported covering pattern in the baseline.
    hair = re.search(r"\b(?:hairs?|trichomes?|poils?)\b", window, re.IGNORECASE)
    if hair and bearer.po_id != "PO_0000282":
        return "unsupported_covering_or_appendage", hair.group(0)
    return None


def _colour_modifier_start(text: str, start: int) -> int:
    """Return the start of a directly attached lexical colour modifier, if present."""

    left = max(0, start - 48)
    prefix = text[left:start]
    match = _COLOUR_MODIFIER_BEFORE.search(prefix) or _PARENTHETICAL_COLOUR_MODIFIER_BEFORE.search(
        prefix
    )
    return left + match.start() if match else start


def _reported_quote_context(text: str, start: int, end: int) -> tuple[int, int, str] | None:
    """Return the shortest explicit quotation enclosing a recovered descriptor.

    Floras sometimes reproduce a descriptor from another source in quotation marks.  The
    phenotype remains representable, but its epistemic force is ``reported`` rather than an
    unqualified assertion by the flora author.  Retaining the complete quoted phrase also keeps
    the provenance needed for later source-level review.
    """

    contexts: list[tuple[int, int, str]] = []
    for opening, closing in _REPORT_QUOTE_PAIRS:
        search_start = max(0, start - 512)
        quote_start = text.rfind(opening, search_start, start)
        if quote_start < 0:
            continue
        if opening == closing:
            # The immediately preceding straight quote is opening only when the number of quotes
            # in the local prefix is odd.  Otherwise it closed an earlier quotation.
            if text[search_start:start].count(opening) % 2 == 0:
                continue
        elif text.find(closing, quote_start + len(opening), start) >= 0:
            # Do not let two separate quoted phrases bracket an unquoted phenotype, e.g.
            # ``“columnar” ... red-brown ... “ant-galls”``.
            continue
        quote_end = text.find(closing, end, min(len(text), end + 512))
        if quote_end < 0:
            continue
        quote_end += len(closing)
        contexts.append((quote_start, quote_end, text[quote_start:quote_end]))
    return min(contexts, key=lambda row: row[1] - row[0]) if contexts else None


def _bearer_evidence_fields(
    text: str,
    bearer: BearerResolution,
    po_id: str,
    quality_start: int,
) -> dict[str, object]:
    """Return occurrence-safe bearer provenance for the resolver's selected PO term."""

    if po_id != bearer.po_id or not bearer.surface_form:
        return {}
    matches = list(re.finditer(re.escape(bearer.surface_form), text, re.IGNORECASE))
    if not matches:
        return {}
    selected = min(matches, key=lambda match: abs(match.start() - quality_start))
    return {
        "raw_entity_text": text[selected.start() : selected.end()],
        "bearer_start": selected.start(),
        "bearer_end": selected.end(),
    }


def _coordinated_postposed_bearers(
    record: dict, compound: CompoundMatch
) -> tuple[str, ...]:
    """Return both nouns in a direct ``red-brown sepals and petals`` phrase."""

    text = str(record.get("text", ""))
    clause, clause_start = baseline._clause_at(text, compound.start)
    local_end = compound.end - clause_start
    candidates: set[tuple[int, int, str]] = set()
    for po_id, pattern in baseline.LOCAL_BEARER_PATTERNS:
        for match in pattern.finditer(clause, local_end):
            if match.start() - local_end <= 72:
                candidates.add((match.start(), match.end(), po_id))
    ordered = sorted(candidates)
    if len(ordered) < 2:
        return ()
    first, second = ordered[:2]
    if not re.fullmatch(r"\s*", clause[local_end : first[0]]):
        return ()
    if not re.fullmatch(r"\s*(?:and|et)\s*", clause[first[1] : second[0]], re.I):
        return ()
    return tuple(dict.fromkeys((first[2], second[2])))


def _coordinated_preposed_bearers(
    record: dict, compound: CompoundMatch
) -> tuple[str, ...]:
    """Return both subjects in ``pedicels and calyx both red-brown``."""

    text = str(record.get("text", ""))
    clause, clause_start = baseline._clause_at(text, compound.start)
    local_start = compound.start - clause_start
    candidates: set[tuple[int, int, str]] = set()
    for po_id, pattern in baseline.LOCAL_BEARER_PATTERNS:
        for match in pattern.finditer(clause[:local_start]):
            if local_start - match.end() <= 96:
                candidates.add((match.start(), match.end(), po_id))
    ordered = sorted(candidates)
    if len(ordered) < 2:
        return ()
    first, second = ordered[-2:]
    if not re.fullmatch(r"\s*(?:and|et)\s*", clause[first[1] : second[0]], re.I):
        return ()
    if not re.fullmatch(
        r"\s*(?:(?:both|together|all|tous\s+deux|toutes\s+deux)\s+)?",
        clause[second[1] : local_start],
        re.I,
    ):
        return ()
    return tuple(dict.fromkeys((first[2], second[2])))


def find_exact_compounds(record: dict, lexicon: dict[str, tuple[str, str]]) -> list[CompoundMatch]:
    """Find complete, exact PATO compound-colour spans represented by unresolved cues."""

    text = str(record.get("text", ""))
    unresolved = record.get("unresolved_spans", []) or []
    matches: dict[tuple[int, int, str], CompoundMatch] = {}
    for index, span in enumerate(unresolved):
        if span.get("reason") != TARGET_REASON:
            continue
        start = int(span.get("start", -1))
        end = int(span.get("end", -1))
        if not 0 <= start < end <= len(text):
            continue
        token_start, token_end = _compound_bounds(text, start, end)
        token = text[token_start:token_end]
        if not any(dash in token for dash in _DASHES):
            continue
        if token[0] in _DASHES or token[-1] in _DASHES or "/" in token:
            continue

        starts = [token_start]
        cursor = token_start
        for _ in range(3):
            preceding = _PRECEDING_WORD.search(text[:cursor])
            if preceding is None:
                break
            starts.append(preceding.start())
            cursor = preceding.start()
        candidates = []
        for candidate_start in starts:
            lexical_form = _normal_form(text[candidate_start:token_end])
            mapped = lexicon.get(lexical_form)
            if mapped:
                candidates.append(
                    (token_end - candidate_start, candidate_start, token_end, lexical_form, mapped)
                )
        if not candidates:
            continue
        _length, matched_start, matched_end, lexical_form, (pato_id, label) = max(candidates)
        key = (matched_start, matched_end, pato_id)
        covered = tuple(
            i
            for i, row in enumerate(unresolved)
            if row.get("reason") == TARGET_REASON
            and matched_start <= int(row.get("start", -1))
            and int(row.get("end", -1)) <= matched_end
        )
        matches[key] = CompoundMatch(
            matched_start,
            matched_end,
            pato_id,
            label,
            lexical_form,
            covered,
        )
    return sorted(matches.values(), key=lambda row: (row.start, row.end, row.pato_id))


def recover_record(
    record: dict,
    lexicon: dict[str, tuple[str, str]],
    bearers: BearerResolver,
) -> tuple[dict, Counter[str]]:
    """Return one copied record plus exact recovery outcome counts."""

    result = dict(record)
    assertions = [dict(row) for row in record.get("assertions", []) or []]
    unresolved = [dict(row) for row in record.get("unresolved_spans", []) or []]
    text = str(record.get("text", ""))
    outcomes: Counter[str] = Counter()
    removed_indexes: set[int] = set()
    seen = {
        (
            row.get("po_id", ""),
            row.get("pato_id", ""),
            row.get("source_start"),
            row.get("source_end"),
        )
        for row in assertions
    }
    for compound in find_exact_compounds(record, lexicon):
        context_reason = _nearby_context_reason(text, compound.start, compound.end)
        if context_reason:
            outcomes[f"retained:{context_reason}"] += 1
            continue
        candidate_id = next(
            (
                str(unresolved[index].get("candidate_pato_id", ""))
                for index in compound.unresolved_indexes
                if unresolved[index].get("candidate_pato_id")
            ),
            compound.pato_id,
        )
        bearer = bearers.resolve(record, compound.start, compound.end, candidate_id)
        unsafe_scope = _unsafe_bearer_scope(text, compound.start, compound.end, bearer)
        if unsafe_scope:
            outcomes[f"retained:bearer_scope:{unsafe_scope[0]}"] += 1
            continue
        modifier_start = _colour_modifier_start(text, compound.start)
        if modifier_start < compound.start:
            # ``pale reddish-brown`` is not exactly PATO:red brown.  It is a conjunction of the
            # hue term and a separate saturation/brightness quality, to be represented later by
            # a FAC ``all_of`` description (or a reviewed reusable composite), while any
            # frequency cue remains at assertion level.
            outcomes["retained:unmodeled_colour_modifier"] += 1
            continue
        if not bearer.po_id:
            outcomes["retained:missing_or_unsupported_bearer"] += 1
            continue
        if bearer.method == "organ_heading":
            outcomes["retained:heading_only_bearer_review"] += 1
            continue
        po_ids = (
            _coordinated_postposed_bearers(record, compound)
            or _coordinated_preposed_bearers(record, compound)
            or (bearer.po_id,)
        )
        qualifier_fields, qualifier_start, qualifier_text = baseline._modality_context(
            text, compound.start
        )
        reported_quote = _reported_quote_context(text, compound.start, compound.end)
        if reported_quote:
            quote_start, quote_end, quote_text = reported_quote
            qualifier_fields["epistemic_modality"] = "reported"
            qualifier_start = min(qualifier_start, quote_start)
            qualifier_text = quote_text
        seasons, season_operator, season_start, season_end = baseline._season_context(
            text, compound.start, compound.end
        )
        source_start = min(compound.start, qualifier_start, season_start)
        source_end = max(
            compound.end,
            season_end,
            reported_quote[1] if reported_quote else compound.end,
        )
        for po_id in po_ids:
            key = (po_id, compound.pato_id, compound.start, compound.end)
            if key in seen:
                outcomes["already_asserted"] += 1
                continue
            assertion = {
                "po_id": po_id,
                "pato_id": compound.pato_id,
                "negated": False,
                "organ": record.get("organ", ""),
                "source_text": text[source_start:source_end],
                "source_start": source_start,
                "source_end": source_end,
                "raw_quality_text": text[compound.start : compound.end],
                "modality_text": qualifier_text,
                "season_contexts": seasons,
                "season_operator": season_operator,
                "normalization_status": "auto",
                "mapping_provenance": [
                    "PATO preferred label or EXACT synonym; dash/space normalization only",
                    *(
                        ["directly coordinated explicit source bearers"]
                        if len(po_ids) > 1
                        else []
                    ),
                    *(
                        ["explicitly quoted source phrase; epistemic modality reported"]
                        if reported_quote
                        else []
                    ),
                ],
                "extractor": "deterministic_exact_pato_compound_recovery",
                **_bearer_evidence_fields(text, bearer, po_id, compound.start),
                **qualifier_fields,
            }
            assertions.append(assertion)
            seen.add(key)
            outcomes[f"promoted:{compound.pato_id}"] += 1
            outcomes[f"promoted_bearer_method:{bearer.method}"] += 1
            outcomes[f"promoted_po:{po_id}"] += 1
        removed_indexes.update(compound.unresolved_indexes)
        outcomes["resolved_evidence_spans"] += len(compound.unresolved_indexes)

    result["assertions"] = assertions
    result["unresolved_spans"] = [
        row for index, row in enumerate(unresolved) if index not in removed_indexes
    ]
    result.pop("annotation_extension_iri", None)
    if removed_indexes:
        result = ensure_source_statements(result)
    return result, outcomes


def recover_file(
    input_path: Path,
    output_path: Path,
    *,
    pato_obo: Path = Path("ont/quality.obo"),
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
) -> dict[str, object]:
    """Recover one baseline JSONL without modifying the input artifact."""

    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("recovery output must be distinct from its input")
    lexicon = exact_compound_colour_lexicon(pato_obo)
    bearers = BearerResolver(po_lexicon)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = 0
    source_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    with Path(input_path).open(encoding="utf-8") as source, output_path.open(
        "w", encoding="utf-8"
    ) as output:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            recovered, outcomes = recover_record(record, lexicon, bearers)
            output.write(json.dumps(recovered, ensure_ascii=False) + "\n")
            records += 1
            outcome_counts.update(outcomes)
            promoted = sum(
                count for outcome, count in outcomes.items() if outcome.startswith("promoted:")
            )
            if promoted:
                source_counts[str(record.get("source", ""))] += promoted
    return {
        "input": str(input_path),
        "output": str(output_path),
        "records": records,
        "exact_compound_lexical_forms": len(lexicon),
        "promoted_by_source": dict(sorted(source_counts.items())),
        "outcomes": dict(sorted(outcome_counts.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--pato-obo", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = recover_file(
        args.input,
        args.output,
        pato_obo=args.pato_obo,
        po_lexicon=args.po_lexicon,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
