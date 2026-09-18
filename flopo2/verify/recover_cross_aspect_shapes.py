"""Recover safe outline qualities suppressed by broad shape-family conflict detection.

``same_attribute_composite_or_transition`` is intentionally conservative, but PATO's broad
``shape`` attribute groups compatible aspects together.  Consequently a flora phrase such as
``leaves oblong, acuminate`` currently withholds *both* values even though the organ's oblong
outline is asserted independently of its tapered termination.

This pass promotes only the gross-outline component when it is directly coordinated with a
different, compatible taper/termination component.  It does not promote the terminal component,
which can characterize an apex or base requiring a more specific bearer.  Same-aspect lists,
alternatives, transitions, slash/hyphen compounds, and locative attachments stay unresolved.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from flopo2.extract import baseline
from flopo2.verify.recover_exact_pato_compounds import BearerResolver


TARGET_REASON = "same_attribute_composite_or_transition"

# The cited PATO definitions characterize an organ's outline/whole shape: elliptic, oblong,
# linear, lanceolate, ovate, spherical, and subspherical.  The second group characterizes
# tapering or roundness at a termination and is compatible with any of these gross outlines.
OUTLINE_QUALITIES = frozenset(
    {
        "PATO_0000946",  # oblong
        "PATO_0000947",  # elliptic
        "PATO_0001199",  # linear
        "PATO_0001499",  # spherical / globose
        "PATO_0001877",  # lanceolate
        "PATO_0001891",  # ovate
        "PATO_0005014",  # subspherical / subglobose
    }
)
TERMINATION_QUALITIES = frozenset(
    {
        "PATO_0001935",  # obtuse
        "PATO_0001982",  # attenuate
        "PATO_0002228",  # acuminate
    }
)

_COORDINATION = re.compile(
    r"\s*(?:,\s*)?(?:(?:and|et)\s+)?"
    r"(?:(?:shortly|briefly|finely|narrowly|broadly|"
    r"courtement|brièvement|brievement|finement|étroitement|etroitement|largement)\s+)?",
    re.IGNORECASE,
)
_LOCATIVE = re.compile(
    r"\b(?:at|towards?|vers|au|aux|à)\b|\b(?:apex|base|tip|sommet|extrémité|extremite)\b",
    re.IGNORECASE,
)
_UNSUPPORTED_SUBPART = re.compile(
    r"\b(?:lobes?|teeth|dents?|segments?|parts?|parties?|branches?|ramifications?|"
    r"valves?|rays?|ray\s+florets?|rayons?|ligules?|bractéoles?|sheaths?|"
    r"connective[- ]appendages?|appendages?|appendices?|stipels?|stipelles?|"
    r"staminodes?|étamines?|etamines?|filaments?|filets?|"
    r"apex|base|tips?|summits?|sommets?|acumens?|bords?|marges?|"
    r"blades?|limbes?|wings?|ailes?|keels?|carènes?|carenes?|"
    r"standards?|étendards?|etendards?|lips?|lèvres?|levres?|"
    r"laterals?|latéraux|lateraux|intérieurs?|interieurs?|extérieurs?|exterieurs?|"
    r"lemmas?|lemmes?|glumes?|spikelets?|épillets?|epillets?|scales?|écailles?|ecailles?|"
    r"pinnae?|pinnules?|rachillae?|rachillas?|"
    r"swellings?|renflements?)\b"
    r"[^;:]{0,120}$",
    re.IGNORECASE,
)
_PREPOSITIONAL_BEARER = re.compile(
    r"\b(?:adpressed|appressed|attached|appliqu[ée]s?)\s+"
    r"(?:to|against|sur|contre)\s+(?:the\s+|le\s+|la\s+|les\s+)?"
    r"[^,;:.]{1,28},\s*$|"
    r"\b(?:on|upon|sur|dans)\s+(?:the\s+|le\s+|la\s+|les\s+)?"
    r"[^,;:.]{1,40},\s*$|"
    r"\b(?:with|bearing|having|avec|à)\s+(?:an?\s+|un\s+|une\s+)?"
    r"(?:pedicels?|pédicelles?|pedicelles?|stipes?|stalks?)\b[^,;:.]{0,40},\s*$",
    re.IGNORECASE,
)
_ATTACHMENT_OBJECT_CONTEXT = re.compile(
    r"\b(?:adpressed|appressed|attached|clasping|covering|concealing|surrounding|"
    r"enclosing|overtopping|appliqu[\u00e9e]s?|accol[\u00e9e]s?|couvrant)\b"
    r"[^;:.]{0,100}\b(?:stem|tige|pedicels?|p[\u00e9e]dicelles?|flowers?|fleurs?)\b"
    r"[^;:.]{0,80}$",
    re.IGNORECASE,
)
_LOCATIVE_STEM_CONTEXT = re.compile(
    r"\b(?:on|upon|sur)\s+(?:the\s+|le\s+|la\s+|les\s+)?"
    r"(?:(?:fertile|sterile|st[\u00e9e]rile|florif[\u00e8e]re|caulinaire)\s+)?"
    r"(?:stem|tige)\b[^;:.]{0,100}$",
    re.IGNORECASE,
)
_PETIOLE_TRANSITION_CONTEXT = re.compile(
    r"\b(?:en|into)\s+(?:an?\s+|un\s+|une\s+)?p[\u00e9e]tiole\b[^;:.]{0,80}$",
    re.IGNORECASE,
)
_NESTED_PETIOLE_CONTEXT = re.compile(
    r"\b(?:leaves?|feuilles?)\b[^;:.]{0,120}\b(?:with|à)\s+"
    r"(?:an?\s+|un\s+|une\s+)?p[ée]tioles?\b[^;:.]{0,80},\s*$",
    re.IGNORECASE,
)
_QUANTIFIED_SUBJECT_CONTEXT = re.compile(
    r"\b(?:most|some|many|few|a\s+few|the\s+majority\s+of|"
    r"la\s+plupart\s+des|certains?|certaines?|quelques)\b"
    r"[^;:.]{0,72}\b(?:are|is|sont|est)?\s*$",
    re.IGNORECASE,
)
_RELATIONAL_SEX_CONTEXT = re.compile(
    r"\b(?:in|for)\s+(?:the\s+)?(?:male|female)\s*:.{0,240}$",
    re.IGNORECASE,
)
_RELATIONAL_FLOWER_CATEGORY_CONTEXT = re.compile(
    r"(?:\(\?\s*flowers?|"
    r"(?:male|female|hermaphrodite|staminate|pistillate|short[- ]styled|long[- ]styled)\s+"
    r"flowers?|"
    r"fleurs?\s+(?:m[âa]les?|femelles?|hermaphrodites?|stamin[ée]es?|pistill[ée]es?))"
    r"\b[^;:.]{0,96}$",
    re.IGNORECASE,
)
_ALTERNATIVE_OR_TRANSITION = re.compile(
    r"\b(?:or|ou|to|through|à|au)\b",
    re.IGNORECASE,
)
_MODAL_OUTLINE_CONNECTOR = re.compile(
    r"\b(?:sometimes|occasionally|rarely|usually|often|"
    r"parfois|rarement|souvent|g[ée]n[ée]ralement)\b",
    re.IGNORECASE,
)
_QUALIFIED_TRANSITION_BEFORE = re.compile(
    r"\b(?:to|through|à|au|vers)\s+"
    r"(?:(?:broadly|narrowly|widely|largement|étroitement|etroitement)\s+)?$",
    re.IGNORECASE,
)
_QUALIFIED_HYPHEN_BEFORE = re.compile(
    r"\b[^\s,;:.]+[-–—]\s*"
    r"(?:(?:broadly|narrowly|widely|largement|étroitement|etroitement)\s+)?$",
    re.IGNORECASE,
)
_PRECEDING_HYPHENATED_SHAPE = re.compile(
    r"\b(?:oblong|ovate|ovale|ov[\u00e9e]|elliptic|lanceolate|linear|triangular|"
    r"orbicular|obovate)[-\u2013\u2014][^\s,;:.]+\s*,\s*$",
    re.IGNORECASE,
)
_COMPOSITE_OUTLINE_SEPARATOR = re.compile(
    r"\s*(?:(?:narrowly|broadly|obliquely|almost|nearly|"
    r"étroitement|etroitement|largement|obliquement|presque)\s+)?",
    re.IGNORECASE,
)
_POSTPOSED_SUBPART = re.compile(
    r"^[^;:.]{0,120}\b(?:lobes?|teeth|dents?|segments?|valves?|rays?|rayons?|"
    r"ligules?|bractéoles?|sheaths?|appendages?|appendices?|stipels?|stipelles?|wings?|ailes?|keels?|"
    r"carènes?|carenes?|scales?|écailles?|ecailles?|pinnae?|pinnules?|"
    r"lemmas?|lemmes?|glumes?|swellings?|renflements?)\b",
    re.IGNORECASE,
)
_COORDINATED_BEARER_CONNECTOR = re.compile(r"\s*(?:and|et)\s*", re.IGNORECASE)
_COORDINATED_BEARER_TAIL = re.compile(
    r"\s*(?:(?:narrowly|broadly|shortly|briefly|finely|"
    r"étroitement|etroitement|largement|courtement|bri[\u00e8e]vement|finement)\s+)?$",
    re.IGNORECASE,
)
_POSTPOSED_BEARER_BRIDGE = re.compile(
    r"\s*(?:,\s*)?(?:(?:flat|narrow|broad|short|long|"
    r"plat(?:e|es|s)?|étroit(?:e|es|s)?|etroit(?:e|es|s)?)\s+)*$",
    re.IGNORECASE,
)
_POSTPOSED_NAMED_STRUCTURE = re.compile(
    r"^[^;:.]{0,140}\b(?:rhizome[- ]scales?|root[- ]scales?)\b",
    re.IGNORECASE,
)
_LEXICAL_COMPOSITE_OUTLINE_BEFORE = re.compile(
    r"\b(?:ovate|ovales?|ov[ée]es?|oblongs?|oblongues?|elliptic(?:al)?|elliptiques?|"
    r"lanceolate|lanc[ée]ol[ée]es?|linear|lin[ée]aires?)"
    r"(?:\s+(?:narrowly|broadly|obliquely|étroitement|etroitement|largement|"
    r"obliquement))?\s+$",
    re.IGNORECASE,
)


def _quality_matches(record: dict, bearers: BearerResolver):
    text = str(record.get("text", ""))
    return [
        (
            cue,
            match,
            bearers.resolve(
                record,
                match.start(),
                match.end(),
                cue.pato_id,
            ),
        )
        for cue in baseline.QUALITY_PATTERNS
        for match in cue.pattern.finditer(text)
    ]


def _coordinated_subject_bearers(
    record: dict, outline_match: re.Match[str]
) -> tuple[str, ...]:
    """Return two explicit bearers in a direct ``X and Y quality`` subject phrase.

    Nearest-bearer selection alone loses one universally characterized subject in statements
    such as ``bracts and bracteoles linear, acuminate``.  Keep this deliberately narrow: exactly
    the last two explicit local bearers, a bare conjunction between them, and only an optional
    degree modifier before the quality.
    """

    text = str(record.get("text", ""))
    clause, clause_start = baseline._clause_at(text, outline_match.start())
    local_start = outline_match.start() - clause_start
    candidates: set[tuple[int, int, str]] = set()
    for po_id, pattern in baseline.LOCAL_BEARER_PATTERNS:
        for match in pattern.finditer(clause[:local_start]):
            if local_start - match.end() <= 96:
                candidates.add((match.start(), match.end(), po_id))
    ordered = sorted(candidates)
    if len(ordered) < 2:
        return ()
    first, second = ordered[-2:]
    if not _COORDINATED_BEARER_CONNECTOR.fullmatch(clause[first[1] : second[0]]):
        return ()
    if not _COORDINATED_BEARER_TAIL.fullmatch(clause[second[1] : local_start]):
        return ()
    return tuple(dict.fromkeys((first[2], second[2])))


def _postposed_subject_bearer(
    record: dict, outline_match: re.Match[str], terminal_match: re.Match[str]
) -> str:
    """Resolve the explicit noun closing ``oblong, obtuse, flat tepals``."""

    text = str(record.get("text", ""))
    clause, clause_start = baseline._clause_at(text, outline_match.start())
    right = max(outline_match.end(), terminal_match.end()) - clause_start
    candidates: list[tuple[int, str]] = []
    for po_id, pattern in baseline.LOCAL_BEARER_PATTERNS:
        for match in pattern.finditer(clause, right):
            if match.start() - right > 48:
                continue
            if _POSTPOSED_BEARER_BRIDGE.fullmatch(clause[right : match.start()]):
                candidates.append((match.start(), po_id))
    return min(candidates)[1] if candidates else ""


def _has_competing_logical_outline(text: str, outline, matches) -> bool:
    """Detect an outline that is itself one endpoint of an alternative/transition.

    The broad baseline reason can contain a safe outline-plus-termination pair *and* a separate
    outline alternation, for example ``oblong to narrowly elliptic, acuminate``.  The terminal
    adjective does not make ``elliptic`` independently assertable in that case.  Compare nearby
    differently grounded outline cues on the same bearer and reject when the text between them
    carries a logical connector, or when the competing cue is itself directly disjunctive.
    """

    outline_cue, outline_match, outline_bearer = outline
    clause, clause_start = baseline._clause_at(text, outline_match.start())
    clause_end = clause_start + len(clause)
    for other_cue, other_match, other_bearer in matches:
        if (
            other_match is outline_match
            or other_cue.pato_id not in OUTLINE_QUALITIES
            or not outline_bearer.po_id
            or other_bearer.po_id != outline_bearer.po_id
            or not (clause_start <= other_match.start() < clause_end)
        ):
            continue
        left, right = sorted((outline_match, other_match), key=lambda match: match.start())
        if right.start() - left.end() > 56:
            continue
        between = text[left.end() : right.start()]
        if (
            _ALTERNATIVE_OR_TRANSITION.search(between)
            or _MODAL_OUTLINE_CONNECTOR.search(between)
            or _COMPOSITE_OUTLINE_SEPARATOR.fullmatch(between)
            or baseline._adjacent_disjunction(text, other_match.start(), other_match.end())
            or baseline._adjacent_transition(text, other_match)
        ):
            return True
    return False


def _compatible_outline_pair(text: str, outline, terminal, matches) -> bool:
    outline_cue, outline_match, outline_bearer = outline
    terminal_cue, terminal_match, terminal_bearer = terminal
    if outline_cue.pato_id not in OUTLINE_QUALITIES:
        return False
    if terminal_cue.pato_id not in TERMINATION_QUALITIES:
        return False
    if not outline_bearer.po_id or outline_bearer.po_id != terminal_bearer.po_id:
        return False
    if outline_bearer.method == "organ_heading":
        return False
    if _has_competing_logical_outline(text, outline, matches):
        return False
    outline_clause, outline_clause_start = baseline._clause_at(text, outline_match.start())
    _terminal_clause, terminal_clause_start = baseline._clause_at(text, terminal_match.start())
    if outline_clause_start != terminal_clause_start:
        return False
    left, right = sorted((outline_match, terminal_match), key=lambda match: match.start())
    connector = text[left.end() : right.start()]
    if not _COORDINATION.fullmatch(connector) or _LOCATIVE.search(connector):
        return False
    if baseline._negated_or_hedged(text, outline_match.start()):
        return False
    transition_before = text[max(0, outline_match.start() - 56) : outline_match.start()]
    if _QUALIFIED_TRANSITION_BEFORE.search(transition_before) or _QUALIFIED_HYPHEN_BEFORE.search(
        transition_before
    ) or _PRECEDING_HYPHENATED_SHAPE.search(transition_before):
        return False
    if baseline._compound_edge(text, outline_match):
        return False
    if baseline._adjacent_disjunction(text, outline_match.start(), outline_match.end()):
        return False
    if baseline._adjacent_transition(text, outline_match):
        return False
    local_start = outline_match.start() - outline_clause_start
    preceding = outline_clause[max(0, local_start - 200) : local_start]
    global_preceding = text[max(0, outline_match.start() - 260) : outline_match.start()]
    # The closed baseline bearer list does not yet distinguish a petal/calyx lobe, style branch,
    # or other named subpart from the enclosing organ.  Do not create a broad whole-organ EQ in
    # those cases; route them to bearer curation instead.
    if (
        _UNSUPPORTED_SUBPART.search(preceding)
        or _PREPOSITIONAL_BEARER.search(preceding)
        or _ATTACHMENT_OBJECT_CONTEXT.search(preceding)
        or _LOCATIVE_STEM_CONTEXT.search(preceding)
        or _PETIOLE_TRANSITION_CONTEXT.search(preceding)
        or _NESTED_PETIOLE_CONTEXT.search(preceding)
        or _RELATIONAL_FLOWER_CATEGORY_CONTEXT.search(preceding)
        or _QUANTIFIED_SUBJECT_CONTEXT.search(preceding)
        or _RELATIONAL_SEX_CONTEXT.search(preceding)
        or _RELATIONAL_SEX_CONTEXT.search(global_preceding)
        or _LEXICAL_COMPOSITE_OUTLINE_BEFORE.search(preceding)
    ):
        return False
    rightmost_end = max(outline_match.end(), terminal_match.end()) - outline_clause_start
    after_pair = outline_clause[rightmost_end : min(len(outline_clause), rightmost_end + 96)]
    if _POSTPOSED_SUBPART.match(after_pair) or _POSTPOSED_NAMED_STRUCTURE.match(after_pair):
        return False
    # A local qualifier after the outline but before punctuation can scope it to an apex/base.
    local_end = outline_match.end() - outline_clause_start
    following = outline_clause[local_end : min(len(outline_clause), local_end + 32)]
    if _LOCATIVE.match(following):
        return False
    return True


def recover_record(record: dict, bearers: BearerResolver) -> tuple[dict, Counter[str]]:
    result = dict(record)
    text = str(record.get("text", ""))
    assertions = [dict(row) for row in record.get("assertions", []) or []]
    unresolved = [dict(row) for row in record.get("unresolved_spans", []) or []]
    matches = _quality_matches(record, bearers)
    outcomes: Counter[str] = Counter()
    removed: set[int] = set()
    seen = {
        (
            row.get("po_id", ""),
            row.get("pato_id", ""),
            row.get("source_start"),
            row.get("source_end"),
        )
        for row in assertions
    }

    for index, span in enumerate(unresolved):
        if span.get("reason") != TARGET_REASON:
            continue
        start = int(span.get("start", -1))
        pato_id = str(span.get("candidate_pato_id", ""))
        if pato_id not in OUTLINE_QUALITIES:
            continue
        outline = next(
            (
                row
                for row in matches
                if row[0].pato_id == pato_id and row[1].start() == start
            ),
            None,
        )
        if outline is None:
            continue
        terminals = [
            row for row in matches if _compatible_outline_pair(text, outline, row, matches)
        ]
        if not terminals:
            continue
        # Multiple compatible direct neighbours do not change the independently asserted outline.
        match = outline[1]
        bearer = outline[2]
        postposed_po_id = _postposed_subject_bearer(record, match, terminals[0][1])
        po_ids = (
            _coordinated_subject_bearers(record, match)
            or ((postposed_po_id,) if postposed_po_id else ())
            or (bearer.po_id,)
        )
        qualifier_fields, qualifier_start, qualifier_text = baseline._modality_context(
            text, match.start()
        )
        seasons, season_operator, season_start, season_end = baseline._season_context(
            text, match.start(), match.end()
        )
        source_start = min(match.start(), qualifier_start, season_start)
        source_end = max(match.end(), season_end)
        for po_id in po_ids:
            key = (po_id, pato_id, source_start, source_end)
            if key in seen:
                outcomes["already_asserted"] += 1
                continue
            assertions.append(
                {
                    "po_id": po_id,
                    "pato_id": pato_id,
                    "negated": False,
                    "organ": record.get("organ", ""),
                    "source_text": text[source_start:source_end],
                    "source_start": source_start,
                    "source_end": source_end,
                    "modality_text": qualifier_text,
                    "season_contexts": seasons,
                    "season_operator": season_operator,
                    "normalization_status": "auto",
                    "mapping_provenance": [
                        "cross-aspect shape recovery: independently asserted gross outline",
                        *(
                            ["directly coordinated explicit source bearers"]
                            if len(po_ids) > 1
                            else []
                        ),
                    ],
                    "extractor": "deterministic_cross_aspect_shape_recovery",
                    **qualifier_fields,
                }
            )
            seen.add(key)
            outcomes[f"promoted:{pato_id}"] += 1
            outcomes[f"promoted_bearer_method:{bearer.method}"] += 1
            outcomes[f"promoted_po:{po_id}"] += 1
        removed.add(index)
        outcomes["resolved_evidence_spans"] += 1

    result["assertions"] = assertions
    result["unresolved_spans"] = [
        row for index, row in enumerate(unresolved) if index not in removed
    ]
    return result, outcomes


def recover_file(
    input_path: Path,
    output_path: Path,
    *,
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
) -> dict[str, object]:
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("recovery output must be distinct from its input")
    bearers = BearerResolver(po_lexicon)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = 0
    outcomes: Counter[str] = Counter()
    promoted_by_source: Counter[str] = Counter()
    with Path(input_path).open(encoding="utf-8") as source, output_path.open(
        "w", encoding="utf-8"
    ) as output:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            recovered, record_outcomes = recover_record(record, bearers)
            output.write(json.dumps(recovered, ensure_ascii=False) + "\n")
            records += 1
            outcomes.update(record_outcomes)
            promoted = sum(
                count
                for outcome, count in record_outcomes.items()
                if outcome.startswith("promoted:")
            )
            if promoted:
                promoted_by_source[str(record.get("source", ""))] += promoted
    return {
        "input": str(input_path),
        "output": str(output_path),
        "records": records,
        "promoted_by_source": dict(sorted(promoted_by_source.items())),
        "outcomes": dict(sorted(outcomes.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = recover_file(args.input, args.output, po_lexicon=args.po_lexicon)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
