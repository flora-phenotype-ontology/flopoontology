"""Conservative recovery of bearer- and bearer-context-withheld flora traits.

The baseline deliberately withholds clauses containing age, maturity, specimen-state, or an
unsupported local bearer.  This second pass promotes only cases for which the same clause gives a
local bearer and an ontology-backed interpretation.  Generic age/maturity words are modeled as
additional PATO qualities on that bearer; they are not turned into PO process-stage classes.

The input is never overwritten.  Recovered assertions are appended to a distinct JSONL artifact,
and every unpromoted span is retained verbatim for later curation.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from flopo2.extract.baseline import (
    COLOR_PATO_IDS,
    LOCAL_BEARER_PATTERNS,
    QUALITY_PATTERNS,
    SHAPE_PATO_IDS,
    _clause_at,
    _local_bearer,
    _modality_context,
    _organ_to_po,
    _season_context,
    _unmodelled_bearer_category,
    _unsupported_numeric_comparator,
)
from flopo2.extract.measurement import Measurement, parse_measurements
from flopo2.verify.missing_bearers import _fold as _fold_bearer
from flopo2.verify.missing_bearers import _po_exact_forms
from flopo2.verify.missing_bearers import _po_forms


@dataclass(frozen=True)
class ContextCue:
    name: str
    pato_id: str
    kind: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class BearerMatch:
    po_id: str
    surface: str
    start: int
    end: int
    method: str


@dataclass(frozen=True)
class LocativeMapping:
    po_id: str
    po_label: str
    container_surface: str
    locative_phrase: str
    orientation: str
    attachment_rule: str
    normalization_scope: str
    clause_start: int
    clause_end: int


CONTEXT_CUES = (
    ContextCue(
        "young",
        "PATO_0000309",
        "developmental",
        re.compile(
            r"(?<!\w)(?:when\s+young|young(?:er|est)?|"
            r"lorsqu(?:e|'|’)\s*jeune|jeunes?)(?!\w)",
            re.IGNORECASE,
        ),
    ),
    ContextCue(
        "juvenile",
        "PATO_0001190",
        "developmental",
        re.compile(r"(?<!\w)(?:juvenile|juv[ée]nile)(?!\w)", re.IGNORECASE),
    ),
    ContextCue(
        "immature",
        "PATO_0001501",
        "developmental",
        re.compile(r"(?<!\w)immature(?!\w)", re.IGNORECASE),
    ),
    ContextCue(
        "mature",
        "PATO_0001701",
        "developmental",
        re.compile(
            r"(?<!\w)(?:at\s+maturity|when\s+mature|mature|"
            r"à\s+maturit[ée]|au\s+stade\s+mature)(?!\w)",
            re.IGNORECASE,
        ),
    ),
    ContextCue(
        "old",
        "PATO_0000308",
        "developmental",
        re.compile(
            r"(?<!\w)(?:old(?:er|est)?|vieil(?:le|les)?|vieux|âg[ée](?:e?s?)?)(?!\w)",
            re.IGNORECASE,
        ),
    ),
    # Only explicit preparation/state constructions are admitted. Bare ``dry/sec`` is excluded:
    # it may denote habitat, season, texture, or a different bearer rather than specimen state.
    ContextCue(
        "dehydrated_specimen",
        "PATO_0001801",
        "state",
        re.compile(
            r"(?<!\w)(?:when\s+dry|in\s+the\s+dry\s+state|in\s+sicco|"
            r"à\s+l['’]état\s+sec|sur\s+le\s+sec)(?!\w)",
            re.IGNORECASE,
        ),
    ),
)

TRANSITION = re.compile(
    r"(?<!\w)(?:later|eventually|becoming|becomes?|turning|turns?|turned|"
    r"taking\s+on|takes?\s+on|acquiring|acquires?|at\s+length|then|"
    r"devenant|devient|prenant|prend|acqu[ée]rant|acquiert|puis|plus\s+tard)(?!\w)",
    re.IGNORECASE,
)
EXCLUDED_CONTEXT = re.compile(
    r"(?<!\w)(?:when\s+fresh|fresh|frais|fraîche?|drying|dried)(?!\w)",
    re.IGNORECASE,
)
PREDICATE_CONTEXT = re.compile(
    r"^(?:when\b|at\s+maturity\b|à\s+maturit[ée]\b|au\s+stade\b|"
    r"lorsqu(?:e|'|’)\b|in\s+(?:the\s+dry\s+state|sicco)\b|"
    r"à\s+l['’]état\s+sec\b|sur\s+le\s+sec\b)",
    re.IGNORECASE,
)
NOMINAL_CONTEXT_BRIDGE = re.compile(
    r"^(?:\s|[-–—]|\b(?:very|très|tres|quite|assez)\b)*$",
    re.IGNORECASE,
)
STRUCTURAL_BRIDGE = re.compile(
    r"[;:.!?()]|\b(?:and|or|et|ou|but|mais|then|puis|"
    r"in|inside|on|sur|dans|within|par|by|with|avec|of|de|des|du|d['’]|"
    r"its|their|son|sa|ses|leur|leurs|à\s+(?:un|une|la|le|l['’])|à)\b",
    re.IGNORECASE,
)
DISJUNCTIVE_BRIDGE = re.compile(r"(?<!\w)(?:or|ou)(?!\w)", re.IGNORECASE)
VALUE_RANGE_BRIDGE = re.compile(r"(?<!\w)(?:to|through)(?!\w)", re.IGNORECASE)
HEDGED_CONTEXT = re.compile(
    r"(?<!\w)(?:appearance|apparence|appears?|seems?|semble|semblent|"
    r"described\s+as|reported\s+as|d[ée]crit(?:e|es|s)?\s+comme)(?!\w)",
    re.IGNORECASE,
)
SURFACE_LOCATIVE = re.compile(
    r"(?<!\w)(?:above|below|beneath|underneath|adaxial|abaxial|"
    r"upper\s+(?:surfaces?|sides?)|lower\s+(?:surfaces?|sides?)|undersides?|"
    r"dessus|dessous|face\s+sup[ée]rieure|face\s+inf[ée]rieure|"
    r"faces?\s+(?:externes?|internes?)|sur\s+les?\s+(?:deux\s+)?faces?|"
    r"internally|externally|int[ée]rieurement|ext[ée]rieurement)(?!\w)",
    re.IGNORECASE,
)
PILOSITY_NEIGHBOR = re.compile(
    r"(?<!\w)(?:hairy|haired|hirsute|setose|pilose|villous|woolly|velvety|"
    r"pubescent|puberulous|"
    r"tomentose|hair|hairs|indumentum|pubescence|poils?|hirsute|s[ée]tuleux|"
    r"pubescent(?:e|es|s)?|pub[ée]rulent(?:e|es|s)?|tomenteux|tomentelleux)(?!\w)",
    re.IGNORECASE,
)
PATTERN_NEIGHBOR = re.compile(
    r"(?<!\w)(?:spotted|striped|dotted|mottled|pointill[ée](?:e?s?)?|"
    r"tachet[ée](?:e?s?)?|ray[ée](?:e?s?)?|marbr[ée](?:e?s?)?)(?!\w)",
    re.IGNORECASE,
)
UNSCOPED_BEARER_BLOCKER = re.compile(
    r"(?<!\w)(?:hairs?|trichomes?|poils?|setae?|soies?|bristles?|awns?|ar[êe]tes?|"
    r"scales?|paillettes?|indumentum|pubescence|tomentum)(?!\w)",
    re.IGNORECASE,
)
UNMODELLED_CONDITION = re.compile(
    r"(?<!\w)(?:when\s+(?:flattened|spread|viewed|pressed)|"
    r"in\s+(?:side|cross-sectional|cross\s+section)\s+view|in\s+(?:outline|profile)|"
    r"not\s+yet\s+(?:mature|ripe)|"
    r"non\s+(?:(?:encore|enti[èe]rement)\s+)?m[ûu]r(?:e|es|s)?|"
    r"lorsqu(?:e|'|’)\s+(?:aplati|étalé|pressé)|"
    r"en\s+vue\s+(?:latérale|de\s+profil))(?!\w)",
    re.IGNORECASE,
)
REGIONAL_PILOSITY = re.compile(
    r"(?<!\w)(?:near|at|towards?)\s+(?:the\s+)?(?:tip|apex|base|margin)(?!\w)|"
    r"(?<!\w)(?:près|vers|à)\s+(?:de\s+|du\s+|la\s+|l['’])?"
    r"(?:sommet|apex|base|marge)(?!\w)",
    re.IGNORECASE,
)
COMPARATIVE_CONTEXT = re.compile(
    r"(?<!\w)(?:resembl(?:e|es|ing)|similar\s+to|like|"
    r"(?:larger|smaller|longer|shorter|broader|narrower)\s+than|"
    r"(?:more|less)\s+(?:[\w'’-]+\s+){1,4}than|"
    r"ressembl(?:e|ant|ant\s+à)|comme|"
    r"(?:plus|moins)\s+(?:[\wÀ-ÖØ-öø-ÿ'’-]+\s+){1,4}que)(?!\w)",
    re.IGNORECASE,
)
APPROXIMATE_VALUE = re.compile(
    r"(?<!\w)(?:almost|nearly|practically|virtually|quasi|presque|pratiquement)\s*$",
    re.IGNORECASE,
)
EXCEPTION_CONTEXT = re.compile(
    r"(?<!\w)(?:except(?:\s+for)?|excluding|save\s+for|apart\s+from|sauf|"
    r"à\s+l['’]exception\s+de)(?!\w)",
    re.IGNORECASE,
)
PILOSITY_TRANSITION = re.compile(
    r"(?<!\w)(?:glabrous|pubescent|puberulous|tomentose|glabre(?:s)?|"
    r"pubescent(?:e|es|s)?|pub[ée]rulent(?:e|es|s)?|tomenteux|tomentelleux)"
    r"[^,;:.!?]{0,32}(?:to|à)[^,;:.!?]{0,32}"
    r"(?:glabrous|pubescent|puberulous|tomentose|glabre(?:s)?|"
    r"pubescent(?:e|es|s)?|pub[ée]rulent(?:e|es|s)?|tomenteux|tomentelleux)(?!\w)",
    re.IGNORECASE,
)
SHAPE_COMPOUND_NEIGHBOR = re.compile(
    r"(?<!\w)(?:oval(?:e|es|s)?|ovo[ïi]de(?:s)?|oboval(?:e|es|s)?|"
    r"ellipti(?:c|que)(?:s)?|oblong(?:ue|ues|s)?)\s*$",
    re.IGNORECASE,
)
COLOUR_COMPOUND_WORD = (
    r"(?:white|black|red|green|yellow|brown|grey|gray|orange|purple|violet|pink|cream|blue|"
    r"light(?:er|est)?|dark(?:er|est)?|bright|pale|beige|whitish|blackish|reddish|greenish|yellowish|"
    r"brownish|greyish|grayish|bluish|pinkish|purplish|olivaceous|olive|straw|"
    r"blanc(?:he|hes|s)?|noir(?:e|es|s)?|rouge(?:s)?|vert(?:e|es|s)?|jaune(?:s)?|"
    r"brun(?:e|es|s)?|marron|gris(?:e|es)?|orang[ée](?:e?s?)?|pourpre|violet(?:te|tes|s)?|"
    r"violac[ée](?:e?s?)?|ochrac[ée](?:e?s?)?|ferrugineux|ferrugineuse(?:s)?|"
    r"bleu(?:e|es|s)?|beige(?:s)?|oliv[âa]tre(?:s)?|olive(?:s)?|paille|ros[ée](?:e?s?)?|"
    r"roux|rousse(?:s)?|bleu[âa]tre|cannelle|"
    r"saumon(?:é|ée|és|ées)|vermillon(?:ne|nes|s)?|"
    r"gris[âa]tre(?:s)?|vif|vive(?:s)?|"
    r"clair(?:e|es|s)?|fonc[ée](?:e?s?)?|sombre(?:s)?|pâle(?:s)?|pale(?:s)?|"
    r"blanch[âa]tre(?:s)?|noir[âa]tre(?:s)?|rouge[âa]tre(?:s)?|verd[âa]tre(?:s)?|"
    r"jaun[âa]tre(?:s)?|brun[âa]tre(?:s)?)"
)
WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]*")
AMBIGUOUS_SINGLETONS = {
    "apex",
    "base",
    "body",
    "branch",
    "center",
    "centre",
    "part",
    "peristome",
    "region",
    "side",
    "spur",
    "surface",
    "tip",
}
REGIONAL_BEARER_MODIFIER = re.compile(
    r"(?<!\w)(?:upper|lower|inner|outer|adaxial|abaxial|distal|proximal|"
    r"sup[ée]rieur(?:e|es|s)?|inf[ée]rieur(?:e|es|s)?|interne(?:s)?|externe(?:s)?)\s*$",
    re.IGNORECASE,
)
REGIONAL_HEAD_BEFORE_VALUE = re.compile(
    r"(?<!\w)(?:apex|base|tip|margin|surface|sommet|marge)\s*$",
    re.IGNORECASE,
)
REGIONAL_BEARER_MODIFIER_AFTER = re.compile(
    r"^\s*(?:upper|lower|inner|outer|adaxial|abaxial|distal|proximal|"
    r"sup[ée]rieur(?:e|es|s)?|inf[ée]rieur(?:e|es|s)?|interne(?:s)?|externe(?:s)?)"
    r"(?:\s+(?:slightly|strongly|weakly|very|l[ée]g[èe]rement|tr[èe]s|peu)){0,3}\s*$",
    re.IGNORECASE,
)
COMPOUND_HEAD_AFTER_BEARER = re.compile(
    r"^\s*(?:(?:with|à)\s+)?"
    r"(?:(?:c\.?\s*)?\d+(?:\s*[-–—]\s*\d+)?\s+)?"
    r"(?:tube|thecae?|th[èe]ques?|wall|surface|apex|base|margin|stalk|"
    r"scales?|paillettes?|hairs?|awns?|bristles?|ar[êe]tes?|appendage|lobes?|"
    r"acumens?|locules?|loges?)\b",
    re.IGNORECASE,
)
EXTREMAL_BEARER_MODIFIER = re.compile(
    r"(?<!\w)(?:longest|shortest|largest|smallest|"
    r"les?\s+plus\s+[A-Za-zÀ-ÖØ-öø-ÿ'’-]+)\s*$",
    re.IGNORECASE,
)
COORDINATED_BEARER_PREFIX = re.compile(
    r"(?<!\w)[A-Za-zÀ-ÖØ-öø-ÿ'’-]+\s+(?:and|et)\s*$",
    re.IGNORECASE,
)
ADJECTIVAL_FALSE_BEARER = re.compile(
    r"(?<!\w)bract[ée]ol[ée](?:e?s?)?(?!\w)",
    re.IGNORECASE,
)
CHRONOLOGICAL_AGE = re.compile(
    r"(?<!\w)(?:(?:one|two|three|four|five|six|seven|eight|nine|ten)|\d+)"
    r"[-–—\s]year[-–—\s]old(?!\w)",
    re.IGNORECASE,
)
REGION_SCOPED_SHAPE_IDS = {"PATO_0001935", "PATO_0002228"}
CONTEXT_FIELDNAMES = (
    "source",
    "source_id",
    "source_segment_index",
    "taxon",
    "organ",
    "reason",
    "surface_form",
    "candidate_pato_id",
    "bearer_po_id",
    "bearer_surface",
    "context_quality",
    "context_text",
    "disposition",
    "method",
    "clause",
)
PROMOTABLE_LOCATIVE_RULES = {
    "organ_specific_abaxial_epidermis",
    "organ_specific_adaxial_epidermis",
    "organ_specific_apex",
    "organ_specific_base",
    "organ_specific_margin",
    "organ_specific_tip",
}
CROSS_COMMA_HEAD_PO_IDS = {
    "PO_0009064",
    "PO_0009085",
    "PO_0009086",
    "PO_0009087",
    "PO_0020060",
    "PO_0025060",
    "PO_0030103",
    "PO_0030105",
}


def _fold(value: str) -> str:
    return _fold_bearer(value)


def _distance(start: int, end: int, position: int) -> int:
    if end <= position:
        return position - end
    if start >= position:
        return start - position
    return 0


def _span_distance(start: int, end: int, target_start: int, target_end: int) -> int:
    if end <= target_start:
        return target_start - end
    if start >= target_end:
        return start - target_end
    return 0


def _comma_phrase(text: str, position: int) -> tuple[str, int]:
    """Return the local comma member, without splitting French decimal commas."""

    clause, left = _clause_at(text, position)
    local = position - left
    commas = [
        match.start()
        for match in re.finditer(",", clause)
        if not (
            match.start() > 0
            and match.end() < len(clause)
            and clause[match.start() - 1].isdigit()
            and clause[match.end()].isdigit()
        )
    ]
    phrase_left = max((offset for offset in commas if offset < local), default=-1) + 1
    phrase_right = min((offset for offset in commas if offset >= local), default=len(clause))
    return clause[phrase_left:phrase_right], left + phrase_left


def _context_matches(text: str, position: int) -> list[tuple[ContextCue, re.Match[str], int]]:
    clause, left = _clause_at(text, position)
    return [
        (cue, match, left)
        for cue in CONTEXT_CUES
        for match in cue.pattern.finditer(clause)
    ]


_POSTPOSED_PARENTHETICAL_STAGE = re.compile(
    r"^[^;!?]{0,96}\(\s*(?:"
    r"not\s+yet\s+(?:mature|ripe)|"
    r"non\s+(?:(?:encore|enti[èe]rement)\s+)?m[ûu]r(?:e|es|s)?|"
    r"immature|mature|young|old|jeune|adulte|m[ûu]r(?:e|es|s)?"
    r")(?!\w)",
    re.IGNORECASE,
)


def _postposed_parenthetical_stage(text: str, end: int) -> bool:
    """Catch a stage restriction placed after a comma/measurement in the same clause."""

    return bool(_POSTPOSED_PARENTHETICAL_STAGE.match(text[end : min(len(text), end + 128)]))


def _questioned_value(text: str, start: int, end: int) -> bool:
    """Return whether the candidate itself is inside or immediately followed by ``(?)``."""

    clause, left = _clause_at(text, start)
    local_start, local_end = start - left, end - left
    opening = clause.rfind("(", 0, local_start + 1)
    closing = clause.find(")", local_end)
    if opening >= 0 and closing >= 0 and "?" in clause[opening : closing + 1]:
        return True
    return bool(re.match(r"^\s*\(\s*\?\s*\)", text[end : min(len(text), end + 16)]))


def _candidate_atomic_safe(text: str, start: int, end: int, pato_id: str) -> bool:
    """Reject a cue that is only one component of unresolved source-level logic or scope."""

    phrase, _phrase_left = _comma_phrase(text, start)
    if (
        TRANSITION.search(phrase)
        or DISJUNCTIVE_BRIDGE.search(phrase)
        or VALUE_RANGE_BRIDGE.search(phrase)
        or UNMODELLED_CONDITION.search(phrase)
        or COMPARATIVE_CONTEXT.search(phrase)
        or EXCEPTION_CONTEXT.search(phrase)
        or HEDGED_CONTEXT.search(phrase)
        or SURFACE_LOCATIVE.search(phrase)
        or APPROXIMATE_VALUE.search(text[max(0, start - 24) : start])
        or _unsupported_numeric_comparator(text, start)
        or _unmodelled_bearer_category(text, start)
        or _postposed_parenthetical_stage(text, end)
        or _questioned_value(text, start, end)
        or _compound_value(text, start, end, pato_id)
        or _cross_comma_colour_alternative(text, end, pato_id)
        or _cross_comma_value_alternative(text, end)
        or _cross_comma_transition(text, end, pato_id)
    ):
        return False
    if pato_id in {"PATO_0000453", "PATO_0001320", "PATO_0002341"} and REGIONAL_PILOSITY.search(
        phrase
    ):
        return False
    if pato_id in {"PATO_0000453", "PATO_0001320", "PATO_0002341"} and PILOSITY_TRANSITION.search(
        phrase
    ):
        return False
    if pato_id in REGION_SCOPED_SHAPE_IDS and REGIONAL_PILOSITY.search(phrase):
        return False
    if pato_id in SHAPE_PATO_IDS and SHAPE_COMPOUND_NEIGHBOR.search(
        text[max(0, start - 32) : start]
    ):
        return False
    before = text[max(0, start - 48) : start]
    after = text[end : min(len(text), end + 48)]
    # French ``A à B`` is a value range/transition.  Exempt only the already-reviewed specimen
    # state/maturity constructions; anatomical locatives need their own audited subregion bearer.
    if re.search(
        r"\b[\wÀ-ÖØ-öø-ÿ'’-]+\s+à\s+"
        r"(?:(?:très|tres|un\s+peu|longuement|courtement|largement|étroitement|"
        r"obtusément|brusquement|et)\s+){0,4}$",
        before,
        re.IGNORECASE,
    ):
        return False
    if re.match(
        r"^\s+à\s+(?!maturit[ée]\b|l['’]état\s+sec\b)"
        r"[A-Za-zÀ-ÖØ-öø-ÿ]",
        after,
        re.IGNORECASE,
    ):
        return False
    if pato_id in COLOR_PATO_IDS:
        prior_word = re.search(r"([A-Za-zÀ-ÖØ-öø-ÿ'’-]+)\s*$", before)
        next_word = re.match(r"^\s*([A-Za-zÀ-ÖØ-öø-ÿ'’-]+)", after)
        neighbors = " ".join(
            match.group(1) for match in (prior_word, next_word) if match is not None
        )
        neighborhood = f"{before[-48:]} {after[:48]}"
        if (
            PILOSITY_NEIGHBOR.search(neighbors)
            or PATTERN_NEIGHBOR.search(neighbors)
            or PILOSITY_NEIGHBOR.search(neighborhood)
            or PATTERN_NEIGHBOR.search(neighborhood)
        ):
            return False
    return True


def _embedded_partitive_bearer(
    text: str,
    phrase_left: int,
    cue_start: int,
    bearer: BearerMatch,
) -> bool:
    """Detect ``surface of young leaves``-like NPs whose head is not the selected bearer."""

    left = min(cue_start, bearer.start)
    prefix = text[max(phrase_left, left - 40) : left]
    if re.fullmatch(
        r"\s*(?:in|dans|en)\s+(?:(?:the|le|la|les|l['’])\s+)?"
        r"(?:(?:very|tr[èe]s)\s+)?",
        prefix,
        re.IGNORECASE,
    ):
        return True
    return bool(
        re.search(
            r"(?:\b[A-Za-zÀ-ÖØ-öø-ÿ'’-]+\s*,?\s+|,\s*)"
            r"(?:of|de|des|du|d['’]|in|dans|en)\s+"
            r"(?:(?:the|le|la|les|l['’])\s+)?"
            r"(?:(?:very|tr[èe]s)\s+)?$",
            prefix,
            re.IGNORECASE,
        )
    )


def _local_context(
    text: str,
    start: int,
    end: int,
    primary_pato_id: str,
    bearer: BearerMatch,
) -> tuple[ContextCue, int, int] | None:
    """Return one strictly local bearer-quality context, otherwise keep the span unresolved."""

    phrase, phrase_left = _comma_phrase(text, start)
    phrase_right = phrase_left + len(phrase)
    if (
        (bearer.start > 0 and text[bearer.start - 1] in "-–—/")
        or (bearer.end < len(text) and text[bearer.end] in "-–—/")
    ):
        return None
    if (
        TRANSITION.search(phrase)
        or EXCLUDED_CONTEXT.search(phrase)
        or CHRONOLOGICAL_AGE.search(phrase)
        or DISJUNCTIVE_BRIDGE.search(phrase)
        or HEDGED_CONTEXT.search(phrase)
        or SURFACE_LOCATIVE.search(phrase)
        or not _candidate_atomic_safe(text, start, end, primary_pato_id)
    ):
        return None
    candidates: list[tuple[int, ContextCue, int, int]] = []
    for cue, match, clause_left in _context_matches(text, start):
        cue_start, cue_end = clause_left + match.start(), clause_left + match.end()
        if cue.pato_id == primary_pato_id:
            continue
        if not (phrase_left <= cue_start and cue_end <= phrase_right):
            continue
        gap = _distance(cue_start, cue_end, start)
        if gap > 48:
            continue
        bridge = text[min(cue_end, end) : max(cue_start, start)]
        if re.search(r"[;:.!?()]|\b(?:and|or|et|ou|puis|then)\b", bridge, re.I):
            continue
        cue_surface = text[cue_start:cue_end]
        predicate = cue.kind == "state" or bool(PREDICATE_CONTEXT.match(cue_surface))
        if predicate:
            # Predicate contexts scope over the immediately preceding phenotype value.  A cue
            # before the value, or separated by another syntactic member, is not deterministic.
            if cue_start < end or cue_start - end > 36:
                continue
            if STRUCTURAL_BRIDGE.search(text[end:cue_start]):
                continue
        else:
            # Adjectival age/maturity must directly modify the explicit bearer.  A section
            # heading cannot establish that an intervening substructure has the same context.
            if bearer.method == "organ_heading":
                continue
            if _embedded_partitive_bearer(text, phrase_left, cue_start, bearer):
                continue
            bearer_context_bridge = text[
                min(cue_end, bearer.end) : max(cue_start, bearer.start)
            ]
            if not NOMINAL_CONTEXT_BRIDGE.fullmatch(bearer_context_bridge):
                continue

        if bearer.method != "organ_heading":
            if _distance(bearer.start, bearer.end, start) > 48:
                continue
            if bearer.end <= start:
                bearer_value_bridge = text[bearer.end:start]
                # Remove the accepted context cue before checking whether the value has crossed
                # into a nested structure ("young fruit ... in a black cupule").
                if bearer.end <= cue_start and cue_end <= start:
                    bearer_value_bridge = (
                        text[bearer.end:cue_start] + text[cue_end:start]
                    )
                if STRUCTURAL_BRIDGE.search(bearer_value_bridge):
                    reviewed_measurement_head = (
                        bearer.method == "reviewed_cross_comma_clause_head"
                        and str(primary_pato_id)
                        in {"PATO_0000119", "PATO_0000122", "PATO_0000915", "PATO_0000921", "PATO_0001334"}
                        and re.fullmatch(
                            r"\s*(?:[A-Za-zÀ-ÖØ-öø-ÿ'’-]+\s*){0,4},\s*"
                            r"(?:de|d['’])\s*",
                            bearer_value_bridge,
                            re.IGNORECASE,
                        )
                    )
                    if not reviewed_measurement_head:
                        continue
            elif end <= bearer.start:
                value_bearer_bridge = text[end:bearer.start]
                if end <= cue_start and cue_end <= bearer.start:
                    value_bearer_bridge = text[end:cue_start] + text[cue_end:bearer.start]
                if STRUCTURAL_BRIDGE.search(value_bearer_bridge):
                    # One explicit surface construction is safe: "pubescent on young branches"
                    # or its French equivalent.  The context still directly modifies the bearer.
                    full_bridge = text[end:bearer.start]
                    if primary_pato_id not in {
                        "PATO_0000453",
                        "PATO_0001320",
                        "PATO_0002341",
                    } or not re.fullmatch(
                        rf"\s*(?:on|sur)\s+(?:(?:the|les?|la|des?)\s+)?"
                        rf"{re.escape(cue_surface)}\s*",
                        full_bridge,
                        re.IGNORECASE,
                    ):
                        continue
        candidates.append((gap, cue, cue_start, cue_end))
    if not candidates:
        return None
    if len({row[1].pato_id for row in candidates}) > 1:
        return None
    candidates.sort(key=lambda row: (row[0], row[2], row[1].pato_id))
    best = candidates[0]
    # Two equally local, different contexts need explicit logical scope rather than guessing.
    if any(row[0] == best[0] and row[1].pato_id != best[1].pato_id for row in candidates[1:]):
        return None
    return best[1], best[2], best[3]


def _compound_value(text: str, start: int, end: int, pato_id: str) -> bool:
    """Return whether a withheld cue is only one component of a compound value phrase."""

    before = text[max(0, start - 24) : start]
    after = text[end : min(len(text), end + 24)]
    if (
        re.search(r"\w\s*[-–—/]\s*$", before)
        or re.search(r"\w\s*\(\s*[-–—/]\s*$", before)
        or re.match(r"^\s*[-–—/]\s*\w", after)
        or re.match(r"^\s*\(\s*[-–—/]\s*\w", after)
    ):
        return True
    if pato_id not in COLOR_PATO_IDS:
        return False
    return bool(
        re.search(rf"(?<!\w){COLOUR_COMPOUND_WORD}\s*$", before, re.IGNORECASE)
        or re.match(rf"^\s*{COLOUR_COMPOUND_WORD}(?!\w)", after, re.IGNORECASE)
    )


def _cross_comma_colour_alternative(text: str, end: int, pato_id: str) -> bool:
    """Catch colour alternatives whose comma would otherwise truncate the local phrase."""

    if pato_id not in COLOR_PATO_IDS:
        return False
    colour_phrase = (
        rf"{COLOUR_COMPOUND_WORD}"
        rf"(?:\s*[-–—/]\s*{COLOUR_COMPOUND_WORD})?"
    )
    return bool(
        re.match(
            rf"^\s*,\s*{colour_phrase}\s+(?:or|ou)\s+{colour_phrase}(?!\w)",
            text[end : min(len(text), end + 96)],
            re.IGNORECASE,
        )
    )


def _cross_comma_transition(text: str, end: int, pato_id: str) -> bool:
    """Reject a value whose immediately following comma member supplies a transition."""

    suffix = text[end : min(len(text), end + 128)]
    explicit = re.match(
        r"^\s*,[^;:.!?]{0,64}(?<!\w)(?:later|eventually|becoming|becomes?|"
        r"turning|turns?|turned|taking\s+on|takes?\s+on|acquiring|acquires?|at\s+length|"
        r"then|devenant|devient|prenant|prend|acqu[ée]rant|acquiert|puis|plus\s+tard)(?!\w)",
        suffix,
        re.IGNORECASE,
    )
    if not explicit:
        explicit = re.match(
            r"^[^,;:.!?]{0,40},[^;:.!?]{0,64}(?<!\w)"
            r"(?:later|eventually|becoming|becomes?|turning|turns?|turned|"
            r"taking\s+on|takes?\s+on|acquiring|acquires?|then|devenant|devient|"
            r"prenant|prend|acqu[ée]rant|acquiert|puis|plus\s+tard)(?!\w)",
            suffix,
            re.IGNORECASE,
        )
    if explicit:
        return True
    if pato_id not in {"PATO_0000453", "PATO_0001320", "PATO_0002341"}:
        return False
    return bool(
        re.match(
            r"^[^;:.!?]{0,96}(?<!\w)(?:(?:soon|later|eventually|bient[ôo]t|"
            r"rapidement)\s+)?(?:glabrous|glabrescent(?:e|es|s)?|glabre(?:s)?)(?!\w)",
            suffix,
            re.IGNORECASE,
        )
    )


def _cross_comma_value_alternative(text: str, end: int) -> bool:
    """Catch an immediate alternative value in the next comma member."""

    return bool(
        re.match(
            r"^\s*,\s*(?:\([^)]{1,24}\)\s*)?"
            r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+"
            r"(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ'’-]+){0,3}\s+"
            r"(?:or|ou)\s+[A-Za-zÀ-ÖØ-öø-ÿ'’-]+",
            text[end : min(len(text), end + 96)],
            re.IGNORECASE,
        )
    )


def _locative_phrase_span(
    text: str,
    start: int,
    mapping: LocativeMapping,
) -> tuple[int, int] | None:
    left = max(0, mapping.clause_start)
    right = min(len(text), mapping.clause_end)
    candidates = [
        (match.start(), match.end())
        for match in re.finditer(re.escape(mapping.locative_phrase), text[left:right], re.IGNORECASE)
    ]
    if not candidates:
        return None
    local_start, local_end = min(
        candidates,
        key=lambda span: _distance(left + span[0], left + span[1], start),
    )
    return left + local_start, left + local_end


def _locative_container_span(
    text: str,
    start: int,
    mapping: LocativeMapping,
) -> tuple[int, int] | None:
    """Locate the reviewed container without widening evidence to the full clause."""

    surface = mapping.container_surface.strip()
    if not surface:
        return None
    left = max(0, mapping.clause_start)
    right = min(len(text), mapping.clause_end)
    candidates = [
        (left + match.start(), left + match.end())
        for match in re.finditer(re.escape(surface), text[left:right], re.IGNORECASE)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda span: _distance(span[0], span[1], start))


def _locative_atomic_safe(
    text: str,
    start: int,
    end: int,
    pato_id: str,
    mapping: LocativeMapping,
) -> bool:
    """Require a complete PO subregion and no unresolved value-level connective."""

    if (
        mapping.attachment_rule not in PROMOTABLE_LOCATIVE_RULES
        or mapping.normalization_scope != "locative_captured_by_atomic_po_bearer"
    ):
        return False
    phrase, phrase_left = _comma_phrase(text, start)
    if (
        TRANSITION.search(phrase)
        or DISJUNCTIVE_BRIDGE.search(phrase)
        or _compound_value(text, start, end, pato_id)
    ):
        return False
    locative = _locative_phrase_span(text, start, mapping)
    if locative is None or locative[0] < end or locative[0] - end > 64:
        return False
    between_value_and_location = text[end : locative[0]]
    # A second French ``à`` here is a value transition/range (for example ``acuminé à caudé au
    # sommet``), not the audited locative preposition.
    if re.search(r"(?<!\w)(?:or|ou|to|through|à)(?!\w)", between_value_and_location, re.I):
        return False
    prefix = phrase[: start - phrase_left]
    if re.search(
        r"(?:\b[\wÀ-ÖØ-öø-ÿ'’-]+\b\s+)(?:or|ou|to|through|à)\s*"
        r"(?:(?:très|tres|un\s+peu|longuement|courtement|largement|étroitement|"
        r"et|obtusément|brusquement)\s+){0,4}$",
        prefix,
        re.IGNORECASE,
    ):
        return False
    # Catch a value connector supported by an audited deterministic cue even if typography
    # inserts degree words around it.
    for cue in QUALITY_PATTERNS:
        for match in cue.pattern.finditer(phrase):
            other_start, other_end = phrase_left + match.start(), phrase_left + match.end()
            if other_start == start and other_end == end:
                continue
            if other_end <= start:
                connector = text[other_end:start]
            elif end <= other_start:
                connector = text[end:other_start]
            else:
                continue
            if re.fullmatch(
                r"\s*(?:(?:très|tres|un\s+peu|longuement|courtement|largement|"
                r"étroitement|obtusément|brusquement)\s+){0,4}"
                r"(?:or|ou|to|through|à|[-–—/])\s*"
                r"(?:(?:très|tres|un\s+peu|longuement|courtement|largement|"
                r"étroitement|obtusément|brusquement)\s+){0,4}",
                connector,
                re.IGNORECASE,
            ):
                return False
    return True


def load_locative_mappings(path: Path | None) -> dict[tuple[str, str, int, int, int, str], LocativeMapping]:
    """Load only curator-audited existing-PO bearer mappings; review rows are ignored."""

    if path is None:
        return {}
    mappings: dict[tuple[str, str, int, int, int, str], LocativeMapping] = {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("disposition") != "safe_existing_po":
                continue
            key = (
                row.get("source", ""),
                row.get("source_id", ""),
                int(row.get("source_segment_index", 0) or 0),
                int(row.get("span_start", 0) or 0),
                int(row.get("span_end", 0) or 0),
                row.get("proposed_pato_id", ""),
            )
            mapping = LocativeMapping(
                po_id=row.get("proposed_bearer_id", ""),
                po_label=row.get("proposed_bearer_label", ""),
                container_surface=row.get("container_surface", ""),
                locative_phrase=row.get("locative_phrase", ""),
                orientation=row.get("locative_orientation", ""),
                attachment_rule=row.get("attachment_rule", ""),
                normalization_scope=row.get("normalization_scope", ""),
                clause_start=int(row.get("clause_start", 0) or 0),
                clause_end=int(row.get("clause_end", 0) or 0),
            )
            previous = mappings.get(key)
            if previous is not None and previous != mapping:
                raise ValueError(f"conflicting reviewed locative mapping for {key!r}")
            mappings[key] = mapping
    return mappings


def _measurement_for_span(record: dict, unresolved: dict) -> Measurement | None:
    start, end = int(unresolved["start"]), int(unresolved["end"])
    pato_id = unresolved.get("candidate_pato_id", "")
    for measurement in parse_measurements(record.get("text", ""), record.get("language", "")):
        if (
            measurement.start == start
            and measurement.end == end
            and measurement.attribute_id == pato_id
        ):
            return measurement
    return None


def _assertion(
    record: dict,
    unresolved: dict,
    bearer: BearerMatch,
    *,
    context: tuple[ContextCue, int, int] | None = None,
) -> dict:
    text = record.get("text", "")
    start, end = int(unresolved["start"]), int(unresolved["end"])
    pato_id = str(unresolved.get("candidate_pato_id", "") or "")
    measurement = _measurement_for_span(record, unresolved)
    qualifier_fields, qualifier_start, qualifier_text = _modality_context(text, start)
    seasons, season_operator, season_start, season_end = _season_context(text, start, end)
    starts = [start, qualifier_start, season_start, bearer.start]
    ends = [end, season_end, bearer.end]
    context_ids: list[str] = []
    context_text = ""
    if context is not None:
        cue, context_start, context_end = context
        starts.append(context_start)
        ends.append(context_end)
        context_ids.append(cue.pato_id)
        context_text = text[context_start:context_end]
    source_start, source_end = min(starts), max(ends)
    row = {
        "po_id": bearer.po_id,
        "pato_id": pato_id,
        "negated": False,
        "organ": record.get("organ", ""),
        "source_text": text[source_start:source_end],
        "source_start": source_start,
        "source_end": source_end,
        "value_text": "",
        "value_operator": "atomic",
        "value_terms": [],
        "bearer_context_qualities": context_ids,
        "frequency_qualifier": "unspecified",
        "epistemic_modality": "asserted",
        "value_qualifier": "exact",
        "degree_qualifier": "unmodified",
        "modality_text": qualifier_text,
        "season_contexts": seasons,
        "season_operator": season_operator,
        "normalization_status": "compositional" if context_ids else "context_override",
        "mapping_provenance": [
            f"bearer:{bearer.method}",
            *(f"bearer_context:{value}" for value in context_ids),
        ],
        "raw_entity_text": bearer.surface,
        "raw_quality_text": unresolved.get("surface_form", ""),
        "extractor": "deterministic_bearer_context_recovery",
        **qualifier_fields,
    }
    if measurement is not None:
        row.update(
            {
                "value_low": measurement.value_low,
                "value_high": measurement.value_high,
                "value_low_inclusive": measurement.value_low_inclusive,
                "value_high_inclusive": measurement.value_high_inclusive,
                "unit": measurement.unit_text,
                "modifier": measurement.modifier,
                "value_qualifier": (
                    "approximately"
                    if measurement.modifier == "approximately"
                    else row["value_qualifier"]
                ),
            }
        )
        if measurement.modifier_text and not row["modality_text"]:
            row["modality_text"] = measurement.modifier_text
    if context_text:
        row["mapping_provenance"].append(f"context_text:{context_text}")
    return row


def _baseline_bearer(record: dict, unresolved: dict) -> BearerMatch | None:
    text = record.get("text", "")
    start, end = int(unresolved["start"]), int(unresolved["end"])
    if _unsupported_numeric_comparator(text, start) or _unmodelled_bearer_category(
        text, start
    ):
        return None
    pato_id = str(unresolved.get("candidate_pato_id", "") or "")
    organ_key = str(record.get("organ", "") or "").strip().casefold()
    default_po_id = _organ_to_po(record.get("organ", ""))
    if default_po_id == "PO_0009025" or organ_key in {"rachis", "rachises"}:
        # Bare ``rachis`` is ambiguous globally (leaf versus inflorescence rachis), but within a
        # leaf-scoped flora block it denotes PO's leaf rachis. Prefer that explicit local part to
        # the broad leaf heading; a global exact alias would corrupt inflorescence descriptions.
        clause, clause_left = _clause_at(text, start)
        local_start = start - clause_left
        rachis_matches = [
            match
            for match in re.finditer(r"(?<!\w)rh?achis(?!\w)", clause, re.IGNORECASE)
            if match.end() <= local_start and local_start - match.end() <= 48
        ]
        if rachis_matches:
            match = max(rachis_matches, key=lambda item: item.end())
            if not re.search(
                r"[;:.!?()]|(?<!\w)(?:and|or|et|ou)(?!\w)",
                clause[match.end() : local_start],
                re.IGNORECASE,
            ):
                return BearerMatch(
                    "PO_0020055",
                    match.group(0),
                    clause_left + match.start(),
                    clause_left + match.end(),
                    "leaf_heading_scoped_rachis",
                )
    po_id = _local_bearer(
        text,
        start,
        default_po_id,
        pato_id,
        end,
    )
    if not po_id:
        return None
    phrase, phrase_left = _comma_phrase(text, start)
    explicit: list[tuple[int, int, int, str, str]] = []
    local_position = start - phrase_left
    for candidate, pattern in LOCAL_BEARER_PATTERNS:
        if candidate != po_id:
            continue
        for match in pattern.finditer(phrase):
            explicit.append(
                (
                    _distance(match.start(), match.end(), local_position),
                    match.start(),
                    match.end(),
                    match.group(0),
                    candidate,
                )
            )
    if explicit:
        _gap, bearer_start, bearer_end, surface, candidate = min(explicit)
        if re.search(
            r"(?:\bof\b|\bde\b|\bdes\b|\bdu\b|d['’])[^,;:.!?()]{0,32}$",
            phrase[max(0, bearer_start - 48) : bearer_start],
            re.IGNORECASE,
        ):
            return None
        return BearerMatch(
            candidate,
            surface,
            phrase_left + bearer_start,
            phrase_left + bearer_end,
            "baseline_local_explicit",
        )
    # A small reviewed allowlist covers true descriptor heads that govern the next comma member.
    # Do not generalize this to every PO noun: nested parts and complements routinely occur
    # closer to a later value than the actual bearer.
    if po_id in CROSS_COMMA_HEAD_PO_IDS:
        clause, clause_left = _clause_at(text, start)
        clause_position = start - clause_left
        cross_comma: list[tuple[int, int, int, str, str]] = []
        for candidate, pattern in LOCAL_BEARER_PATTERNS:
            if candidate != po_id:
                continue
            for match in pattern.finditer(clause):
                if match.end() <= clause_position:
                    cross_comma.append(
                        (
                            clause_position - match.end(),
                            match.start(),
                            match.end(),
                            match.group(0),
                            candidate,
                        )
                    )
        if cross_comma and min(cross_comma)[0] <= 96:
            _gap, bearer_start, bearer_end, surface, candidate = min(cross_comma)
            return BearerMatch(
                candidate,
                surface,
                clause_left + bearer_start,
                clause_left + bearer_end,
                "reviewed_cross_comma_clause_head",
            )
    # A real organ heading is an admissible local prior for a terse organ-scoped flora block.
    default = _organ_to_po(record.get("organ", ""))
    if default == po_id and record.get("organ", "").strip().lower() != "description":
        return BearerMatch(po_id, record.get("organ", ""), start, end, "organ_heading")
    return None


def _lexical_bearer(
    record: dict,
    unresolved: dict,
    exact_po_forms: dict[tuple[str, ...], set[str]],
    candidate_po_forms: dict[tuple[str, ...], set[str]],
) -> BearerMatch | None:
    """Find one exact, unique PO lexical form in the same local comma phrase."""

    text = record.get("text", "")
    position = int(unresolved["start"])
    cue_end = int(unresolved["end"])
    if _unsupported_numeric_comparator(text, position) or _unmodelled_bearer_category(
        text, position
    ):
        return None
    phrase, left = _comma_phrase(text, position)
    local_position = position - left
    local_end = cue_end - left
    tokens = list(WORD.finditer(phrase))
    candidates: list[tuple[int, int, int, str, str, int, int]] = []
    blockers: list[tuple[int, int, int, str, int, int]] = []
    for start_index in range(len(tokens)):
        for width in range(1, min(6, len(tokens) - start_index) + 1):
            selected = tokens[start_index : start_index + width]
            folded = tuple(_fold(match.group(0)) for match in selected)
            exact_ids = set(exact_po_forms.get(folded, ()))
            candidate_ids = set(candidate_po_forms.get(folded, ()))
            if folded and folded[-1].endswith("s"):
                singular = (*folded[:-1], folded[-1][:-1])
                exact_ids.update(exact_po_forms.get(singular, ()))
                candidate_ids.update(candidate_po_forms.get(singular, ()))
            start, end = selected[0].start(), selected[-1].end()
            gap = _span_distance(start, end, local_position, local_end)
            if gap > 32:
                continue
            ambiguous_singleton = width == 1 and " ".join(folded) in AMBIGUOUS_SINGLETONS
            if len(exact_ids) != 1 or ambiguous_singleton:
                if candidate_ids:
                    blockers.append(
                        (gap, 0 if end <= local_position else 1, -width, phrase[start:end], start, end)
                    )
                continue
            between = phrase[min(end, local_position) : max(start, local_position)]
            if re.search(
                r"[;:.!?()]|\b(?:and|or|et|ou|with|avec|"
                r"divided\s+into|composed\s+of|divis[ée](?:e?s?)?\s+en|"
                r"compos[ée](?:e?s?)?\s+de)\b",
                between,
                re.I,
            ):
                continue
            if start >= local_end and re.search(
                r"\b(?:of|de|des|du|in|into|on|at|behind|before|beside|between|"
                r"around|near|above|below|beneath|under|sur|dans|derri[èe]re|"
                r"devant|entre|autour|pr[èe]s|sous|like|comme|"
                r"resembl(?:e|es|ing)|au\s+niveau\s+(?:de|du|des)|"
                r"r[ée]tr[ée]ci(?:e|es|s)?\s+en|se\s+prolongeant\s+en|"
                r"termin[ée](?:e|es|s)?\s+par)\b|\bd['’]",
                between,
                re.I,
            ):
                continue
            if start >= local_end and re.search(
                r"\b(?:bearing|carrying|having|presenting|portant|pr[ée]sentant)\b",
                between,
                re.IGNORECASE,
            ):
                continue
            candidates.append(
                (
                    gap,
                    0 if end <= local_position else 1,
                    -width,
                    next(iter(exact_ids)),
                    phrase[start:end],
                    start,
                    end,
                )
            )
    if not candidates:
        return None
    best = min(candidates)
    if _fold(best[4]) == "part of":
        return None
    if ADJECTIVAL_FALSE_BEARER.fullmatch(best[4]):
        return None
    if best[3] == "PO_0020105":
        organ = str(record.get("organ", "")).casefold()
        local_ligule_context = phrase[
            max(0, best[5] - 32) : min(len(phrase), best[6] + 16)
        ]
        if organ not in {
            "feuille",
            "feuilles",
            "leaf",
            "leaves",
            "lamina",
            "limbe",
        } and not re.search(
            r"(?<!\w)(?:leaf|leaves|gaines?)(?:\s+sheaths?)?\s+ligules?(?!\w)",
            local_ligule_context,
            re.IGNORECASE,
        ):
            return None
    if (
        best[3] == "PO_0030102"
        and str(record.get("language", "")).lower().startswith("fr")
        and _fold(best[4]) in {"glande", "glandes"}
    ):
        # PO's untagged EXACT ``glandes`` denotes the nut-fruit sense.  In French flora prose,
        # ``glande(s)`` overwhelmingly denotes a secretory structure, for which PO has no generic
        # class.  Keep it unresolved; English ``nut``/``nutlet`` remains eligible.
        return None
    if best[3] == "PO_0020105" and re.search(
        r"(?<!\w)floral(?:e|es|s)?(?!\w)",
        phrase[max(0, best[5] - 24) : min(len(phrase), best[6] + 24)],
        re.IGNORECASE,
    ):
        return None
    if best[3] == "PO_0009047" and _fold(best[4]) == "primary axis":
        # PO records ``primary axis`` as an exact stem synonym, but flora prose also uses it for
        # an inflorescence's primary axis.  Without the container, the bare phrase is ambiguous.
        return None
    if best[3] == "PO_0025327" and (
        _fold(best[4]) == "keels"
        or re.search(
            r"(?<!\w)(?:paleae?|palea|glumes?|lemmas?|sepals?|seeds?|callus|disc|lip)(?!\w)",
            _clause_at(text, position)[0],
            re.IGNORECASE,
        )
    ):
        # PO:0025327 is the keel petal.  These contexts instead denote an anatomical ridge.
        return None
    if best[3] == "PO_0025060" and re.search(
        r"(?<!\w)paraphyses?(?!\w)", phrase, re.IGNORECASE
    ):
        return None
    # Relative regions such as ``inner pappus`` and ``upper receptacle`` need a relational
    # class expression; mapping them to the unqualified PO whole would lose source scope.
    if REGIONAL_BEARER_MODIFIER.search(phrase[max(0, best[5] - 32) : best[5]]):
        return None
    if EXTREMAL_BEARER_MODIFIER.search(phrase[max(0, best[5] - 48) : best[5]]):
        return None
    if COORDINATED_BEARER_PREFIX.search(phrase[max(0, best[5] - 48) : best[5]]):
        return None
    if best[6] <= local_position and REGIONAL_BEARER_MODIFIER_AFTER.fullmatch(
        phrase[best[6] : local_position]
    ):
        return None
    if best[6] <= local_position and COMPOUND_HEAD_AFTER_BEARER.match(
        phrase[best[6] : local_position]
    ):
        return None
    if best[6] <= local_position and re.search(
        r"(?<!\w)(?:in|inside|on|within|dans|sur)(?!\w)",
        phrase[best[6] : local_position],
        re.IGNORECASE,
    ):
        return None
    if best[3] == "PO_0005020" and re.search(
        r"(?<!\w)(?:between|entre)\s+(?:the\s+|les\s+)?"
        r"(?:veins?|nervures?)\s*$",
        phrase[:local_position],
        re.IGNORECASE,
    ):
        # This characterizes an intervening surface region, not the vascular bundles themselves.
        return None
    if best[6] <= local_position and re.search(
        r"(?<!\w)(?:of|with|avec|à)\s+(?:c\.?\s*)?\d+"
        r"(?:\s*[-–—]\s*\d+)?\s*$",
        phrase[best[6] : local_position],
        re.IGNORECASE,
    ):
        return None
    if (
        best[6] <= local_position
        and re.search(
            r"(?<!\w)(?:of|with|avec|de|des|du|à)(?!\w)",
            phrase[best[6] : local_position],
            re.IGNORECASE,
        )
        and re.match(
            r"^\s*(?:[A-Za-zÀ-ÖØ-öø-ÿ'’-]+\s+){0,3}"
            r"(?:hairs?|trichomes?|poils?|setae?|soies?|bristles?|awns?|ar[êe]tes?|"
            r"scales?|paillettes?)\b",
            phrase[local_end:],
            re.IGNORECASE,
        )
    ):
        return None
    if best[6] <= local_position and re.search(
        r"\b(?:of|de|des|du|d['’])\s+"
        r"(?:[A-Za-zÀ-ÖØ-öø-ÿ'’-]+\s+){0,4}"
        r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+\s*$",
        phrase[best[6] : local_position],
        re.IGNORECASE,
    ):
        return None
    # In punctuation-defective prose such as ``leaflet apex acuminate costae ...``, a PO noun
    # after the value must not steal a quality explicitly headed by the preceding region.
    if REGIONAL_HEAD_BEFORE_VALUE.search(
        phrase[max(0, local_position - 32) : local_position]
    ):
        return None
    if blockers and min(blockers)[:3] <= best[:3]:
        return None
    # Equal-distance distinct PO candidates mean the local syntax is not deterministic enough.
    if any(row[0] == best[0] and row[3] != best[3] for row in candidates):
        return None
    for match in UNSCOPED_BEARER_BLOCKER.finditer(phrase):
        blocker_gap = _span_distance(
            match.start(),
            match.end(),
            local_position,
            local_end,
        )
        if blocker_gap <= best[0] and not (best[5] <= match.start() < best[6]):
            return None
    # In ``stalks of capitula 2 cm long``, the nearest noun is the complement, not the head whose
    # length is stated.  Do not reverse that attachment merely because the complement is closer.
    selected_prefix = phrase[max(0, best[5] - 48) : best[5]]
    if re.search(
        r"(?:\bof\b|\bde\b|\bdes\b|\bdu\b|d['’])[^,;:.!?()]{0,32}$",
        selected_prefix,
        re.I,
    ):
        return None
    return BearerMatch(best[3], best[4], left + best[5], left + best[6], "unique_po_lexical_form")


def recover_record(
    record: dict,
    po_forms: dict[tuple[str, ...], set[str]],
    candidate_po_forms: dict[tuple[str, ...], set[str]] | None = None,
    locative_mappings: dict[
        tuple[str, str, int, int, int, str], LocativeMapping
    ] | None = None,
) -> tuple[dict, list[dict]]:
    """Return a copied record with safe recoveries plus one audit row per scoped candidate."""

    out = dict(record)
    assertions = [dict(row) for row in record.get("assertions", []) or []]
    retained: list[dict] = []
    audit: list[dict] = []
    seen = {
        (
            row.get("po_id", ""),
            row.get("pato_id", ""),
            row.get("source_start"),
            row.get("source_end"),
            tuple(sorted(row.get("bearer_context_qualities", []) or [])),
        )
        for row in assertions
    }
    text = record.get("text", "")
    candidate_po_forms = candidate_po_forms or po_forms
    locative_mappings = locative_mappings or {}
    for unresolved in record.get("unresolved_spans", []) or []:
        reason = unresolved.get("reason", "")
        bearer: BearerMatch | None = None
        context: tuple[ContextCue, int, int] | None = None
        disposition = "retained"
        locative: LocativeMapping | None = None
        if reason == "developmental_stage_context":
            # A reviewed exact PO noun in the clause is stronger evidence than a broad FlorML
            # section heading (for example, receptacle inside an inflorescence block).
            bearer = _lexical_bearer(record, unresolved, po_forms, candidate_po_forms)
            if bearer is None:
                bearer = _baseline_bearer(record, unresolved)
            if bearer is not None:
                context = _local_context(
                    text,
                    int(unresolved["start"]),
                    int(unresolved["end"]),
                    str(unresolved.get("candidate_pato_id", "") or ""),
                    bearer,
                )
            if bearer is not None and context is not None:
                disposition = "recovered_bearer_context_quality"
        elif reason == "missing_or_unsupported_bearer":
            bearer = _lexical_bearer(record, unresolved, po_forms, candidate_po_forms)
            if bearer is not None and _candidate_atomic_safe(
                text,
                int(unresolved["start"]),
                int(unresolved["end"]),
                str(unresolved.get("candidate_pato_id", "") or ""),
            ):
                disposition = "recovered_existing_po_bearer"
        elif reason == "unsupported_alternative_or_transition":
            locative_key = (
                str(record.get("source", "") or ""),
                str(record.get("source_id", "") or ""),
                int(record.get("source_segment_index", 0) or 0),
                int(unresolved.get("start", 0) or 0),
                int(unresolved.get("end", 0) or 0),
                str(unresolved.get("candidate_pato_id", "") or ""),
            )
            locative = locative_mappings.get(locative_key)
            if locative is not None:
                locative_span = _locative_phrase_span(
                    text, int(unresolved["start"]), locative
                )
                container_span = _locative_container_span(
                    text, int(unresolved["start"]), locative
                )
                # Mapping rows retain whole-clause bounds for audit reproducibility.  Assertion
                # evidence is instead the smallest verbatim span containing the reviewed
                # container, value, and locative phrase, so an unrelated later disjunction does
                # not become part of an otherwise atomic assertion.
                evidence_end = (
                    locative_span[1]
                    if locative_span is not None
                    else int(unresolved["end"])
                )
                evidence_start = int(unresolved["start"])
                if container_span is not None and not DISJUNCTIVE_BRIDGE.search(
                    text[container_span[0] : evidence_end]
                ):
                    evidence_start = container_span[0]
                bearer = BearerMatch(
                    locative.po_id,
                    " ".join(
                        value
                        for value in (locative.container_surface, locative.locative_phrase)
                        if value
                    ),
                    evidence_start,
                    evidence_end,
                    f"reviewed_locative:{locative.attachment_rule}",
                )
                if (
                    locative.attachment_rule not in PROMOTABLE_LOCATIVE_RULES
                    or locative.normalization_scope
                    != "locative_captured_by_atomic_po_bearer"
                ):
                    disposition = "bearer_normalized_expression_pending"
                elif _locative_atomic_safe(
                    text,
                    int(unresolved["start"]),
                    int(unresolved["end"]),
                    str(unresolved.get("candidate_pato_id", "") or ""),
                    locative,
                ):
                    disposition = "recovered_existing_po_locative_subregion"
                else:
                    disposition = "bearer_normalized_logical_expression_pending"

        if disposition.startswith("recovered") and bearer is not None:
            assertion = _assertion(record, unresolved, bearer, context=context)
            if locative is not None:
                # ``normalization_status`` is a controlled schema value.  Keep the more
                # specific recovery route in ``mapping_provenance`` below rather than
                # inventing a status that downstream LinkML/Pydantic validation rejects.
                assertion["normalization_status"] = "reviewed"
                assertion["mapping_provenance"].extend(
                    [
                        f"locative_phrase:{locative.locative_phrase}",
                        f"locative_orientation:{locative.orientation}",
                        f"locative_attachment:{locative.attachment_rule}",
                        f"locative_normalization_scope:{locative.normalization_scope}",
                    ]
                )
            key = (
                assertion["po_id"],
                assertion["pato_id"],
                assertion["source_start"],
                assertion["source_end"],
                tuple(sorted(assertion.get("bearer_context_qualities", []))),
            )
            if key not in seen:
                seen.add(key)
                assertions.append(assertion)
            else:
                disposition = "duplicate_existing_assertion"
        if not disposition.startswith("recovered"):
            retained.append(unresolved)

        if reason in {"developmental_stage_context", "missing_or_unsupported_bearer"} or locative:
            clause, _left = _clause_at(text, int(unresolved.get("start", 0)))
            audit.append(
                {
                    "source": record.get("source", ""),
                    "source_id": record.get("source_id", ""),
                    "source_segment_index": record.get("source_segment_index", 0),
                    "taxon": record.get("taxon", ""),
                    "organ": record.get("organ", ""),
                    "reason": reason,
                    "surface_form": unresolved.get("surface_form", ""),
                    "candidate_pato_id": unresolved.get("candidate_pato_id", ""),
                    "bearer_po_id": bearer.po_id if bearer else "",
                    "bearer_surface": bearer.surface if bearer else "",
                    "context_quality": context[0].pato_id if context else "",
                    "context_text": (
                        text[context[1] : context[2]]
                        if context is not None
                        else (locative.locative_phrase if locative else "")
                    ),
                    "disposition": disposition,
                    "method": bearer.method if bearer else "",
                    "clause": re.sub(r"\s+", " ", clause).strip(),
                }
            )
    out["assertions"] = assertions
    out["unresolved_spans"] = retained
    # Any old FAC link is invalid once assertions have been added; the annotation-extension pass
    # will deterministically re-materialize every class link in the distinct output artifact.
    out.pop("annotation_extension_iri", None)
    return out, audit


def recover_file(
    input_path: Path,
    output_path: Path,
    audit_path: Path,
    *,
    po_obo: Path = Path("ont/plant_ontology.obo"),
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    reviewed_bearers: Path = Path("config/reviewed_local_bearers.tsv"),
    locative_mappings_path: Path | None = None,
) -> dict[str, object]:
    paths = [Path(input_path).resolve(), Path(output_path).resolve(), Path(audit_path).resolve()]
    if locative_mappings_path is not None:
        paths.append(Path(locative_mappings_path).resolve())
    if len(set(paths)) != len(paths):
        raise ValueError("recovery input, mapping, output, and audit paths must all be distinct")
    po_forms = _po_exact_forms(po_obo, reviewed_bearers)
    candidate_po_forms = _po_forms(po_lexicon, reviewed_bearers)
    locative_mappings = load_locative_mappings(locative_mappings_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    with (
        Path(input_path).open(encoding="utf-8") as source,
        Path(output_path).open("w", encoding="utf-8") as output,
        Path(audit_path).open("w", encoding="utf-8", newline="") as audit_handle,
    ):
        writer = csv.DictWriter(
            audit_handle,
            fieldnames=CONTEXT_FIELDNAMES,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            recovered, audit = recover_record(
                record,
                po_forms,
                candidate_po_forms,
                locative_mappings,
            )
            for row in audit:
                writer.writerow(row)
                counts[row["disposition"]] += 1
                if row["disposition"].startswith("recovered"):
                    sources[row["source"]] += 1
            output.write(json.dumps(recovered, ensure_ascii=False) + "\n")
            counts["records"] += 1
    return {
        **dict(counts),
        "recovered_by_source": dict(sorted(sources.items())),
        "reviewed_locative_mappings": len(locative_mappings),
        "output": str(output_path),
        "audit": str(audit_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--po-obo", type=Path, default=Path("ont/plant_ontology.obo"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument(
        "--reviewed-bearers",
        type=Path,
        default=Path("config/reviewed_local_bearers.tsv"),
    )
    parser.add_argument(
        "--locative-mappings",
        type=Path,
        help="curator-audited safe existing-PO locative bearer mappings",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            recover_file(
                args.input,
                args.output,
                args.audit,
                po_obo=args.po_obo,
                po_lexicon=args.po_lexicon,
                reviewed_bearers=args.reviewed_bearers,
                locative_mappings_path=args.locative_mappings,
            ),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
