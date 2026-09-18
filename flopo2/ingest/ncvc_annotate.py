"""Turn the NCVC Saudi native-plants guide transcription into FLOPO annotation-corpus records.

:mod:`flopo2.ingest.ncvc_guide` reads the page-by-page transcription (verbatim Arabic plus a
literal English translation, see ``local-corpora/saudi-ncvc-guide/EXTRACTION_BRIEF.md``). This
module is the deterministic, re-runnable second stage. It

* grounds every transcribed entity-quality row through exact PO labels/EXACT synonyms, exact PATO
  lexicon labels/synonyms, and the reviewed rules in ``ncvc_normalization.tsv`` (growth forms,
  life span, fruit and inflorescence types, leaf persistence, sexual system); it never mints IDs;
* applies the reviewed data-quality holds in ``ncvc_data_quality_holds.tsv`` (descriptions copied
  from another species, contradictions, unit misprints, ambiguous bearers);
* anchors each row to exact offsets in the English description (``source_en``, then quality or
  entity words) and records the Arabic source span as a source statement on the Arabic segment;
* emits gated corpus records (``source_statements``/``assertions``/``unresolved_spans``) in the
  same wire format as the machine-reviewed FLOPO materialization stages, plus side tables for
  taxon distribution, growth/cultivation traits, whole-plant FLOPO classes without an EQ
  signature, novel PO+PATO pairs, and a per-row disposition audit.

Rows that cannot be represented as a safe atomic EQ assertion (alternatives, developmental-stage
qualifiers, counts, whole-plant FLOPO classes without an EQ signature, terms with no ontology
counterpart) become ``unresolved_spans``. Data-quality holds remain assertions but are never
accepted: composition ``review``, gate ``review`` with an ``ncvc_hold:<code>`` reason, and a
``held:`` mapping-provenance entry. The schema's ``NormalizationStatus`` has no ``held`` value,
so held assertions carry ``normalization_status: proposed``.

Example::

    .venv/bin/python -m flopo2.ingest.ncvc_annotate local-corpora/saudi-ncvc-guide
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flopo2.annotation.provenance import FREQUENCY_ALIASES, stable_statement_id
from flopo2.ingest import ncvc_guide
from flopo2.owl.annotation_class import ensure_annotation_class_iri
from flopo2.verify import gates
from flopo2.verify.data_model import validate_jsonl

EXTRACTOR = "claude_opus_transcription"
ANNOTATION_EXTENSION_IRI = "https://w3id.org/flopo/annotation-extension"
PATO_PRESENT = "PATO_0000467"
PATO_ABSENT = "PATO_0000462"
WHOLE_PLANT = "PO_0000003"
LENGTH_UNITS = {"m", "cm", "mm"}
HERE = Path(__file__).resolve().parent
DEFAULT_NORMALIZATION = HERE / "ncvc_normalization.tsv"
DEFAULT_HOLDS = HERE / "ncvc_data_quality_holds.tsv"

_PAREN_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_SUFFIX_RE = re.compile(r"\s+(?:habit|growth form)$")
_OR_RE = re.compile(r"\bor\b", re.IGNORECASE)
_LOWER_CUE_RE = re.compile(r"\b(?:more than|over|at least|exceeding|above)\b|>", re.IGNORECASE)
_UNSUPPORTED_UPPER_RE = re.compile(
    r"\b(?:less than|under|below|reach(?:es|ing)?|exceed(?:s|ing)?|to)\b|<", re.IGNORECASE
)
_FREQUENCY_WORDS = {"usually", "often", "sometimes", "rarely", "mostly", "occasionally"}


def normalize_key(text: str | None) -> str:
    """Lower-case a transcribed quality/entity phrase, dropping parentheticals and habit suffixes."""

    key = _PAREN_RE.sub("", str(text or "")).strip().lower()
    key = ncvc_guide._normalize(key)
    return _SUFFIX_RE.sub("", key).strip(" ,;.")


# ---------------------------------------------------------------------------------------------
# Reviewed rule tables
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NormalizationRule:
    rule_id: str
    match_field: str
    match_key: str
    bearer_constraint: str
    kind: str
    po_id: str
    pato_id: str
    value_term: str
    flopo_class: str
    target_label: str
    evidence: str

    def bearer_ok(self, bearer_texts: Iterable[str]) -> bool:
        if not self.bearer_constraint:
            return True
        pattern = re.compile(self.bearer_constraint, re.IGNORECASE)
        return any(pattern.search(text or "") for text in bearer_texts)


RULE_KINDS = {"bearer", "pato", "flopo_value", "entity_presence", "flopo_phenotype_class", "hold"}


def load_normalization_rules(path: Path = DEFAULT_NORMALIZATION) -> list[NormalizationRule]:
    rules: list[NormalizationRule] = []
    with Path(path).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            rule = NormalizationRule(
                **{
                    name: (row.get(name) or "").strip()
                    for name in NormalizationRule.__annotations__
                }
            )
            if rule.kind not in RULE_KINDS:
                raise ValueError(f"{rule.rule_id}: unknown kind {rule.kind!r}")
            rules.append(rule)
    return rules


@dataclass(frozen=True)
class HoldRule:
    rule_id: str
    pdf_page: int
    action: str
    entity_regex: str
    quality_regex: str
    source_regex: str
    reason_code: str
    reason: str
    evidence: str

    def matches(self, page: int, phenotype: dict) -> bool:
        if page != self.pdf_page or self.action not in {"hold", "hold_all"}:
            return False
        if self.action == "hold_all":
            return True
        checks = (
            (self.entity_regex, (phenotype.get("entity_en"), phenotype.get("po_label"))),
            (self.quality_regex, (phenotype.get("quality_en"), phenotype.get("pato_label"))),
            (self.source_regex, (phenotype.get("source_en"),)),
        )
        for pattern, texts in checks:
            if pattern and not any(
                re.search(pattern, str(text or ""), re.IGNORECASE) for text in texts
            ):
                return False
        return True


def load_hold_rules(path: Path = DEFAULT_HOLDS) -> list[HoldRule]:
    rules: list[HoldRule] = []
    with Path(path).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            values = {name: (row.get(name) or "").strip() for name in HoldRule.__annotations__}
            values["pdf_page"] = int(values["pdf_page"])
            rules.append(HoldRule(**values))
    return rules


# ---------------------------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------------------------


@dataclass
class Resources:
    po_lexicon: dict[str, list[str]]
    pato_lexicon: dict[str, list[str]]
    po_labels: dict[str, str]
    pato_labels: dict[str, str]
    po_catalog: set[str]
    pato_catalog: set[str]
    flopo_catalog: set[str]
    attribute_ids: set[str]
    combos: dict
    eq_registry: dict
    signature_registry: dict
    flopo_labels: dict[str, str]
    rules: list[NormalizationRule]
    holds: list[HoldRule]

    def rule_for(self, field_name: str, key: str, bearer_texts: Iterable[str]):
        bearer_texts = list(bearer_texts)
        for rule in self.rules:
            if (
                rule.match_field == field_name
                and rule.match_key == key
                and rule.bearer_ok(bearer_texts)
            ):
                return rule
        return None


def _labels(path: Path) -> dict[str, str]:
    with Path(path).open(encoding="utf-8", newline="") as fh:
        return {row["id"]: row.get("label", "") for row in csv.DictReader(fh, delimiter="\t")}


def _flopo_labels(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with Path(path).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if row.get("deprecated", "0") != "0":
                continue
            out[row["flopo_iri"].rsplit("/", 1)[-1]] = row.get("label", "")
    return out


def load_resources(
    *,
    po_obo: Path = Path("ont/plant_ontology.obo"),
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
    flopo_registry: Path = Path("config/flopo_id_registry.tsv"),
    combinations: Path = Path("config/valid_combinations.tsv"),
    normalization: Path = DEFAULT_NORMALIZATION,
    holds: Path = DEFAULT_HOLDS,
) -> Resources:
    res = Resources(
        po_lexicon=ncvc_guide.load_obo_exact_lexicon(po_obo, "PO"),
        pato_lexicon=ncvc_guide.load_lexicon(pato_lexicon),
        po_labels=_labels(po_lexicon),
        pato_labels=_labels(pato_lexicon),
        po_catalog=gates.load_catalog_ids(po_lexicon),
        pato_catalog=gates.load_catalog_ids(pato_lexicon),
        flopo_catalog=gates.load_flopo_ids(flopo_registry),
        attribute_ids=gates.load_pato_attribute_terms(pato_lexicon),
        combos=gates.load_combinations(combinations),
        eq_registry=gates.load_eq_registry(flopo_registry),
        signature_registry=gates.load_signature_registry(flopo_registry),
        flopo_labels=_flopo_labels(flopo_registry),
        rules=load_normalization_rules(normalization),
        holds=load_hold_rules(holds),
    )
    check_rule_identifiers(res)
    return res


def check_rule_identifiers(res: Resources) -> None:
    """Refuse a rule table that names an identifier absent from the live catalogs."""

    problems: list[str] = []
    for rule in res.rules:
        if rule.po_id and rule.po_id not in res.po_catalog | res.flopo_catalog:
            problems.append(f"{rule.rule_id}: unknown bearer {rule.po_id}")
        if rule.pato_id and rule.pato_id not in res.pato_catalog:
            problems.append(f"{rule.rule_id}: unknown PATO {rule.pato_id}")
        for flopo in (rule.value_term, rule.flopo_class):
            if flopo and flopo not in res.flopo_labels:
                problems.append(f"{rule.rule_id}: unknown or deprecated FLOPO {flopo}")
    if problems:
        raise ValueError("; ".join(problems))


def _label(res: Resources, identifier: str) -> str:
    return (
        res.po_labels.get(identifier)
        or res.pato_labels.get(identifier)
        or res.flopo_labels.get(identifier)
        or ""
    )


# ---------------------------------------------------------------------------------------------
# Span location
# ---------------------------------------------------------------------------------------------


def _find_all(text: str, phrase: str, *, casefold: bool) -> list[int]:
    if not phrase:
        return []
    left = r"(?<!\w)" if phrase[0].isalnum() else ""
    right = r"(?!\w)" if phrase[-1].isalnum() else ""
    flags = re.IGNORECASE if casefold else 0
    return [m.start() for m in re.finditer(left + re.escape(phrase) + right, text, flags)]


def _pick(starts: list[int], cursor: int, used: frozenset[int] = frozenset()) -> int | None:
    """First occurrence at/after the cursor, else a unique one; spans already used lose ties."""

    fresh = [s for s in starts if s not in used]
    for pool in (fresh, starts):
        after = [s for s in pool if s >= cursor]
        if after:
            return after[0]
        if len(pool) == 1:
            return pool[0]
    return None


def _phrase_variants(phrase: str) -> list[str]:
    phrase = ncvc_guide._normalize(phrase)
    out = [phrase]
    stripped = ncvc_guide._normalize(_PAREN_RE.sub("", phrase))
    out.append(stripped)
    out.append(stripped.strip(" ,;.:"))
    return [p for p in dict.fromkeys(out) if p]


_DASHES = "-‐‑‒–—"
_TOKEN_RE = re.compile(r"[\w.%s×]+" % _DASHES)
_STOPWORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "with",
    "of",
    "in",
    "and",
    "its",
    "it",
    "their",
    "has",
    "have",
    "be",
    "being",
    "which",
    "that",
    "sic",
    "on",
    "at",
    "by",
    "as",
}
_WINDOW_BREAK = re.compile(r"[.;]\s")


def _tokens(text: str) -> list[tuple[str, int, int]]:
    out = []
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0).strip(".")
        if not token:
            continue
        start = match.start() + match.group(0).index(token)
        out.append((token.lower(), start, start + len(token)))
    return out


def _token_equal(want: str, have: str) -> bool:
    want = re.sub(f"[{_DASHES}]", "-", want)
    have = re.sub(f"[{_DASHES}]", "-", have)
    if any(ch.isdigit() for ch in want):
        return want == have
    if want == have:
        return True
    stem = want[: max(3, len(want) - 2)]
    return len(want) >= 3 and have.startswith(stem) and abs(len(have) - len(want)) <= 3


def _token_window(
    text: str, phrase: str, cursor: int, used: frozenset[int] = frozenset()
) -> tuple[int, int] | None:
    """Smallest in-order window of the phrase's content tokens within one clause."""

    wanted = [t for t, _s, _e in _tokens(_PAREN_RE.sub("", phrase)) if t not in _STOPWORDS]
    if not wanted:
        return None
    have = _tokens(text)
    limit = 3 * len(wanted) + 3
    hits: list[tuple[int, int]] = []
    for i, (token, start, _end) in enumerate(have):
        if not _token_equal(wanted[0], token):
            continue
        j, k, end = i, 1, have[i][2]
        while k < len(wanted) and j + 1 < len(have) and j + 1 - i < limit:
            j += 1
            if _WINDOW_BREAK.search(text[have[j - 1][2] : have[j][1] + 1]):
                break
            if _token_equal(wanted[k], have[j][0]):
                k += 1
                end = have[j][2]
        if k == len(wanted):
            hits.append((start, end))
    starts = [s for s, _e in hits]
    chosen = _pick(starts, cursor, used)
    if chosen is None:
        return None
    return next(h for h in hits if h[0] == chosen)


def locate_span(
    text: str,
    source_phrase: str,
    fallback_words: Iterable[tuple[str, str]],
    cursor: int = 0,
    used: frozenset[int] = frozenset(),
) -> tuple[int, int, str] | None:
    """Return ``(start, end, method)`` for a transcribed phrase inside the segment text.

    The literal ``source_en`` is tried first (exact, then case-insensitive, then without
    bracketed transcriber notes), then an in-order window of its content tokens inside one
    clause; failing that, the first of ``fallback_words`` found after the cursor (or occurring
    exactly once) is used. Returns ``None`` when nothing is locatable.
    """

    for variant in _phrase_variants(source_phrase):
        for casefold, method in ((False, "source_en_exact"), (True, "source_en_casefold")):
            start = _pick(_find_all(text, variant, casefold=casefold), cursor, used)
            if start is not None:
                return start, start + len(variant), method
    window = _token_window(text, source_phrase, cursor, used)
    if window is not None:
        return window[0], window[1], "source_en_token_window"
    for word, method in fallback_words:
        word = ncvc_guide._normalize(word)
        if len(word) < 3:
            continue
        start = _pick(_find_all(text, word, casefold=True), cursor, used)
        if start is not None:
            return start, start + len(word), method
    return None


def _fallback_words(phenotype: dict) -> list[tuple[str, str]]:
    """Whole quality phrases first, then their individual words (a weaker, review-only anchor)."""

    whole: list[tuple[str, str]] = []
    parts: list[tuple[str, str]] = []
    for value in (phenotype.get("quality_en"), phenotype.get("pato_label")):
        key = normalize_key(value)
        if key:
            whole.append((key, "quality_word"))
            parts.extend(
                (part, "quality_word_partial")
                for part in re.split(r"[\s,/]+", key)
                if len(part) > 3 and part != key
            )
    return list(dict.fromkeys(whole + parts))


def _bearer_mention(text: str, start: int, end: int, phenotype: dict) -> tuple[int, int] | None:
    """Exact bearer word inside the anchored span, if the entity is named there."""

    span = text[start:end]
    candidates: list[str] = []
    for value in (phenotype.get("entity_en"), phenotype.get("po_label")):
        key = normalize_key(value)
        if not key:
            continue
        candidates.extend([key + "es", key + "s", key])
        if key.endswith("f"):
            candidates.append(key[:-1] + "ves")
        if key.endswith("y"):
            candidates.append(key[:-1] + "ies")
    for candidate in sorted(dict.fromkeys(candidates), key=len, reverse=True):
        hits = _find_all(span, candidate, casefold=True)
        if len(hits) == 1:
            return start + hits[0], start + hits[0] + len(candidate)
    return None


# ---------------------------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------------------------


@dataclass
class Grounding:
    """Outcome of normalizing one transcribed phenotype row."""

    kind: str  # assertion | unresolved
    po_id: str = ""
    pato_id: str = ""
    value_terms: list[str] = field(default_factory=list)
    flopo_class: str = ""
    reason: str = ""
    provenance: list[str] = field(default_factory=list)
    normalization_status: str = "auto"
    rule_ids: list[str] = field(default_factory=list)


def ground_bearer(res: Resources, phenotype: dict) -> tuple[str, str, str]:
    """Return ``(po_id, provenance, rule_id)`` for the transcribed bearer."""

    for value in (phenotype.get("po_label"), phenotype.get("entity_en")):
        key = ncvc_guide._normalize(value).lower()
        ids = res.po_lexicon.get(key, [])
        if len(ids) == 1:
            return ids[0], f"bearer: exact PO label/EXACT synonym {key!r} -> {ids[0]}", ""
    for value in (phenotype.get("po_label"), phenotype.get("entity_en")):
        rule = res.rule_for("bearer", normalize_key(value), [])
        if rule:
            return (
                rule.po_id,
                f"bearer: reviewed rule {rule.rule_id} {normalize_key(value)!r} -> {rule.po_id} "
                f"({rule.evidence})",
                rule.rule_id,
            )
    return "", "", ""


def ground_phenotype(res: Resources, phenotype: dict) -> Grounding:
    po_id, bearer_prov, bearer_rule = ground_bearer(res, phenotype)
    provenance = [bearer_prov] if bearer_prov else []
    rule_ids = [bearer_rule] if bearer_rule else []
    status = "proposed" if bearer_rule else "auto"
    bearer_texts = [
        phenotype.get("entity_en", ""),
        phenotype.get("po_label", ""),
        res.po_labels.get(po_id, ""),
    ]

    pato_id = ""
    pato_label = ncvc_guide._normalize(phenotype.get("pato_label")).lower()
    ids = res.pato_lexicon.get(pato_label, []) if pato_label else []
    if len(ids) == 1:
        pato_id = ids[0]
        provenance.append(f"quality: exact PATO lexicon label/synonym {pato_label!r} -> {pato_id}")
    elif len(ids) > 1:
        return Grounding("unresolved", reason="pato_label_collision", po_id=po_id)

    if not pato_id:
        key = normalize_key(phenotype.get("quality_en"))
        rule = res.rule_for("quality", key, bearer_texts)
        if rule is None:
            direct = res.pato_lexicon.get(key, [])
            if len(direct) == 1:
                pato_id = direct[0]
                provenance.append(
                    f"quality: quality_en {key!r} is an exact PATO lexicon label/synonym -> "
                    f"{pato_id}"
                )
            else:
                return Grounding(
                    "unresolved",
                    po_id=po_id,
                    reason="no_ontology_term_for_quality",
                    provenance=provenance,
                )
        else:
            rule_ids.append(rule.rule_id)
            rule_prov = f"quality: reviewed rule {rule.rule_id} {key!r} -> {rule.target_label} ({rule.evidence})"
            if rule.kind == "hold":
                return Grounding(
                    "unresolved",
                    po_id=po_id,
                    reason=f"no_ontology_term:{rule.target_label}",
                    provenance=[*provenance, rule_prov],
                    rule_ids=rule_ids,
                )
            if rule.kind == "flopo_phenotype_class":
                return Grounding(
                    "unresolved",
                    po_id=po_id or WHOLE_PLANT,
                    flopo_class=rule.flopo_class,
                    reason="flopo_phenotype_class_without_eq_signature",
                    provenance=[*provenance, rule_prov],
                    rule_ids=rule_ids,
                )
            status = "proposed"
            provenance.append(rule_prov)
            pato_id = rule.pato_id
            if rule.kind == "entity_presence":
                po_id = rule.po_id
            elif rule.kind == "flopo_value":
                return Grounding(
                    "assertion",
                    po_id=po_id,
                    pato_id=rule.pato_id,
                    value_terms=[rule.value_term],
                    provenance=provenance,
                    normalization_status=status,
                    rule_ids=rule_ids,
                )
    if not po_id:
        return Grounding(
            "unresolved",
            pato_id=pato_id,
            reason="missing_or_unsupported_bearer",
            provenance=provenance,
            rule_ids=rule_ids,
        )
    if po_id not in res.po_catalog and po_id not in res.flopo_catalog:
        return Grounding("unresolved", pato_id=pato_id, reason="bearer_not_in_catalog")
    return Grounding(
        "assertion",
        po_id=po_id,
        pato_id=pato_id,
        provenance=provenance,
        normalization_status=status,
        rule_ids=rule_ids,
    )


# ---------------------------------------------------------------------------------------------
# Measurement bounds
# ---------------------------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_bounds(
    low: Any, high: Any, cue_text: str
) -> tuple[float | None, float | None, str, str]:
    """Return ``(low, high, bound_type, problem)`` for one printed value or range.

    A single printed value stored only as an upper (or lower) bound becomes ``low == high``
    unless the text carries an explicit comparator. ``problem`` is non-empty when the
    comparator is one the gate/validator cannot represent (e.g. *less than*, *reaching*).
    """

    low, high = _num(low), _num(high)
    if low is not None and high is not None:
        if low > high:
            low, high = high, low
        return low, high, ("single" if low == high else "range"), ""
    if low is None and high is None:
        return None, None, "none", ""
    if high is not None:
        if gates.UPPER_BOUND_EVIDENCE.search(cue_text):
            return None, high, "upper", ""
        if _UNSUPPORTED_UPPER_RE.search(cue_text):
            return None, high, "upper", "upper_bound_cue_not_supported"
        return high, high, "single", ""
    if _LOWER_CUE_RE.search(cue_text):
        return low, None, "lower", ""
    return low, low, "single", ""


# ---------------------------------------------------------------------------------------------
# Record annotation
# ---------------------------------------------------------------------------------------------


@dataclass
class Disposition:
    row: dict
    status: str  # accepted | review | held | unresolved | unanchored
    reason: str
    assertion: dict | None = None


def _hold_for(res: Resources, page: int, phenotype: dict) -> HoldRule | None:
    for rule in res.holds:
        if rule.matches(page, phenotype):
            return rule
    return None


def _page_provenance(rec: dict) -> str:
    printed = rec.get("printed_pages") or []
    printed_text = "-".join(str(p) for p in printed)
    return (
        f"source: {ncvc_guide.SOURCE} pdf_page={int(rec['pdf_page'])}"
        + (f" printed_pages={printed_text}" if printed_text else "")
        + f" phenotype_row={{row}}; transcription {EXTRACTOR}"
    )


def _arabic_statement(
    ar_record: dict | None, source_ar: str, cursor: int
) -> tuple[dict | None, int]:
    if ar_record is None or not source_ar:
        return None, cursor
    text = ar_record["text"]
    phrase = ncvc_guide._normalize(source_ar)
    start = _pick(_find_all(text, phrase, casefold=False), cursor)
    if start is None:
        return None, cursor
    end = start + len(phrase)
    statement_id = stable_statement_id(ar_record, start, end, phrase)
    return (
        {
            "statement_id": statement_id,
            "verbatim_text": phrase,
            "start": start,
            "end": end,
            "language": "ar",
            "document_start": ar_record["char_start"] + start,
            "document_end": ar_record["char_start"] + end,
        },
        end,
    )


def _base_assertion(organ: str) -> dict[str, Any]:
    return {
        "po_id": "",
        "pato_id": "",
        "negated": False,
        "negation_scope": "",
        "organ": organ,
        "source_text": "",
        "source_start": None,
        "source_end": None,
        "bearer_start": None,
        "bearer_end": None,
        "modality_start": None,
        "modality_end": None,
        "extractor": EXTRACTOR,
        "value_low": None,
        "value_high": None,
        "value_low_inclusive": True,
        "value_high_inclusive": True,
        "unit": "",
        "value_text": "",
        "trait": "",
        "modifier": "",
        "cardinality": "",
        "confidence": None,
        "raw_entity_text": "",
        "raw_quality_text": "",
        "entity_mention_id": "",
        "quality_mention_ids": [],
        "value_operator": "atomic",
        "bearer_context_qualities": [],
        "developmental_stage_contexts": [],
        "developmental_stage_operator": "atomic",
        "normalization_status": "auto",
        "mapping_provenance": [],
        "source_statement_id": "",
        "frequency_qualifier": "unspecified",
        "epistemic_modality": "asserted",
        "value_qualifier": "exact",
        "degree_qualifier": "unmodified",
        "modality_text": "",
        "season_contexts": [],
        "season_operator": "atomic",
        "value_terms": [],
    }


def _modality(text: str, start: int, end: int, frequency: str) -> tuple[str, int, int] | None:
    """Locate a frequency cue inside the clause holding the anchor (unique occurrence only)."""

    word = frequency.strip().lower()
    if word not in _FREQUENCY_WORDS:
        return None
    left = max(text.rfind(";", 0, start), text.rfind(".", 0, start)) + 1
    right_candidates = [p for p in (text.find(";", end), text.find(".", end)) if p != -1]
    right = min(right_candidates) if right_candidates else len(text)
    hits = _find_all(text[left:right], word, casefold=True)
    if len(hits) != 1:
        return None
    cue_start = left + hits[0]
    return text[cue_start : cue_start + len(word)], cue_start, cue_start + len(word)


def annotate_record(rec: dict, res: Resources) -> tuple[list[dict], list[Disposition]]:
    """Return the corpus segment rows (Arabic/English description and habitat) for one species."""

    segments = [seg.to_row() for seg in ncvc_guide.iter_segments_from_records([rec])]
    for seg in segments:
        seg.update(
            {
                "source_statements": [],
                "term_mentions": [],
                "unresolved_spans": [],
                "assertions": [],
                "annotation_extension_iri": ANNOTATION_EXTENSION_IRI,
            }
        )
    en = next((s for s in segments if s["organ"] == "description" and s["language"] == "en"), None)
    ar = next((s for s in segments if s["organ"] == "description" and s["language"] == "ar"), None)
    page = int(rec["pdf_page"])
    page_prov = _page_provenance(rec)
    dispositions: list[Disposition] = []
    en_cursor = ar_cursor = 0
    used_starts: set[int] = set()
    pending: list[tuple[dict, Disposition]] = []

    for index, phenotype in enumerate(rec.get("phenotypes") or []):
        row = {"pdf_page": page, "row": index, **phenotype}
        grounding = ground_phenotype(res, phenotype)
        hold = _hold_for(res, page, phenotype)
        qualifiers = phenotype.get("qualifiers") or {}
        if en is None:
            dispositions.append(Disposition(row, "unanchored", "no_english_description"))
            continue
        text = en["text"]
        has_value = (
            phenotype.get("value_low") is not None or phenotype.get("value_high") is not None
        )
        # A measurement must be anchored on its printed numbers, never on a bare quality word.
        fallback = [] if has_value else _fallback_words(phenotype)
        located = locate_span(
            text, phenotype.get("source_en", ""), fallback, en_cursor, frozenset(used_starts)
        )
        ar_statement, ar_cursor_next = _arabic_statement(
            ar, phenotype.get("source_ar", ""), ar_cursor
        )
        if ar_statement is not None:
            ar_cursor = ar_cursor_next
            if all(
                s["statement_id"] != ar_statement["statement_id"] for s in ar["source_statements"]
            ):
                ar["source_statements"].append(ar_statement)
        if located is None:
            row["hold_rule"] = hold.rule_id if hold else ""
            dispositions.append(
                Disposition(row, "unanchored", "source_span_not_found_in_description_en")
            )
            continue
        start, end, method = located
        en_cursor = start
        used_starts.add(start)
        span_text = text[start:end]

        reason = grounding.reason if grounding.kind == "unresolved" else ""
        alternatives = [a for a in qualifiers.get("alternatives") or [] if str(a).strip()]
        low = high = None
        unit = ncvc_guide._normalize(phenotype.get("unit"))
        if not reason and alternatives:
            reason = "taxon_level_alternatives_or_continuum"
        if not reason and _OR_RE.search(span_text):
            reason = "explicit_disjunction"
        if not reason and str(qualifiers.get("stage") or "").strip():
            reason = "developmental_stage_context"
        if not reason and has_value:
            if unit not in LENGTH_UNITS:
                reason = "count_or_non_length_measurement" if unit else "measurement_missing_unit"
            elif grounding.pato_id not in res.attribute_ids:
                reason = "numeric_quality_not_pato_attribute"
            else:
                low, high, _bound, problem = normalize_bounds(
                    phenotype.get("value_low"), phenotype.get("value_high"), span_text
                )
                reason = problem
        negated = bool(qualifiers.get("negated"))
        if not reason and negated and grounding.pato_id == PATO_ABSENT:
            negated = False
            grounding.provenance.append("negation: PATO absent already expresses the negation")
        if not reason and negated and not gates.NEGATION_EVIDENCE.search(span_text):
            reason = "negation_cue_not_in_source_span"

        if reason:
            candidate = grounding.pato_id if grounding.pato_id in res.pato_catalog else ""
            unresolved = {
                "start": start,
                "end": end,
                "surface_form": span_text,
                "reason": reason,
                "candidate_pato_id": candidate,
                "extractor": EXTRACTOR,
            }
            if reason == "missing_or_unsupported_bearer":
                unresolved["pending_bearer"] = ncvc_guide._normalize(
                    phenotype.get("po_label") or phenotype.get("entity_en")
                )
            en["unresolved_spans"].append(unresolved)
            row.update(
                {
                    "po_id": grounding.po_id,
                    "pato_id": grounding.pato_id,
                    "flopo_class": grounding.flopo_class,
                    "hold_rule": hold.rule_id if hold else "",
                    "anchor_method": method,
                    "rules": "|".join(grounding.rule_ids),
                }
            )
            dispositions.append(Disposition(row, "unresolved", reason))
            continue

        assertion = _base_assertion(en["organ"])
        assertion.update(
            {
                "po_id": grounding.po_id,
                "pato_id": grounding.pato_id,
                "value_terms": list(grounding.value_terms),
                "source_text": span_text,
                "source_start": start,
                "source_end": end,
                "normalization_status": grounding.normalization_status,
                "raw_quality_text": ncvc_guide._normalize(phenotype.get("quality_en")),
            }
        )
        if has_value:
            assertion.update({"value_low": low, "value_high": high, "unit": unit})
        if negated:
            assertion.update({"negated": True, "negation_scope": "quality"})
        bearer = _bearer_mention(text, start, end, phenotype)
        if bearer is not None:
            assertion.update(
                {
                    "raw_entity_text": text[bearer[0] : bearer[1]],
                    "bearer_start": bearer[0],
                    "bearer_end": bearer[1],
                }
            )
        cue = _modality(text, start, end, str(qualifiers.get("frequency") or ""))
        if cue is not None:
            assertion.update(
                {
                    "modality_text": cue[0],
                    "modality_start": cue[1],
                    "modality_end": cue[2],
                    "frequency_qualifier": FREQUENCY_ALIASES.get(cue[0].lower(), "unspecified"),
                }
            )
        provenance = [page_prov.format(row=index), f"anchor: {method}", *grounding.provenance]
        if ar_statement is not None:
            provenance.append(
                f"source_ar: {ar_statement['statement_id']} description_ar"
                f"[{ar_statement['start']}:{ar_statement['end']}]"
            )
        elif phenotype.get("source_ar"):
            provenance.append("source_ar: not located verbatim in description_ar")
        if has_value and (low, high) != (
            _num(phenotype.get("value_low")),
            _num(phenotype.get("value_high")),
        ):
            provenance.append("value: single printed value normalized to low=high")
        if hold is not None:
            provenance.append(f"held: {hold.reason_code} ({hold.rule_id}: {hold.reason})")
            assertion["normalization_status"] = "proposed"
        assertion["mapping_provenance"] = provenance
        entity_label = _label(res, grounding.po_id)
        quality_label = _label(res, (grounding.value_terms or [grounding.pato_id])[0])
        comp_reasons = [f"ncvc_hold:{hold.reason_code}"] if hold else []
        if method == "quality_word_partial":
            comp_reasons.append("anchor_partial_quality_word")
        assertion["composition"] = {
            "status": "review" if comp_reasons else "accept",
            "confidence": 0.5 if comp_reasons else 1.0,
            "reasons": comp_reasons,
            "entity_label": entity_label,
            "quality_label": quality_label,
            "clause": span_text,
        }
        en["assertions"].append(assertion)
        row.update(
            {
                "po_id": grounding.po_id,
                "pato_id": grounding.pato_id,
                "value_terms": "|".join(grounding.value_terms),
                "hold_rule": hold.rule_id if hold else "",
                "anchor_method": method,
                "rules": "|".join(grounding.rule_ids),
            }
        )
        disposition = Disposition(
            row, "held" if hold else "pending", hold.reason_code if hold else ""
        )
        pending.append((assertion, disposition))
        dispositions.append(disposition)

    if en is not None and en["assertions"]:
        gated = gates.gate_segment(
            en,
            res.combos,
            res.eq_registry,
            res.signature_registry,
            res.attribute_ids,
            pato_catalog_ids=res.pato_catalog,
            flopo_catalog_ids=res.flopo_catalog,
            po_catalog_ids=res.po_catalog,
        )
        en.clear()
        en.update(gated)
        for (_old, disposition), assertion in zip(pending, en["assertions"], strict=True):
            hold_code = disposition.reason
            gate = assertion["gate"]
            if hold_code:
                gate["reasons"] = [*gate["reasons"], f"ncvc_hold:{hold_code}"]
                if gate["status"] == "accepted":
                    gate["status"] = "review"
            if assertion.get(
                "frequency_qualifier", "unspecified"
            ) != "unspecified" and not assertion.get("modality_text"):
                assertion["frequency_qualifier"] = "unspecified"
            ensure_annotation_class_iri(assertion)
            disposition.assertion = assertion
            if not hold_code:
                disposition.status = gate["status"]
                disposition.reason = ";".join(gate["reasons"])
    return segments, dispositions


# ---------------------------------------------------------------------------------------------
# Side tables
# ---------------------------------------------------------------------------------------------

GROWTH_FIELDS = [
    "source_id",
    "pdf_page",
    "taxon",
    "taxon_family",
    "table",
    "trait",
    "value_en",
    "value_ar",
    "low",
    "high",
    "unit",
    "bound_type",
    "months",
    "ontology_hint",
    "note",
]
TRAIT_UNITS = {"soil_salinity_ppm": "ppm", "temperature_c": "°C", "elevation_m": "m"}
TRAIT_HINTS = {
    "flowering": "TO:0002616 flowering time; PO:0007616 flowering stage (season/month context)",
    "growth_rate": "PATO:0001492 growth rate (whole plant)",
    "drought": "TO:0000276 drought tolerance",
    "waterlogging": "TO:0000114 flooding related trait / TO:0000524 submergence tolerance",
    "soil_salinity_ppm": "TO:0006001 salt tolerance; PATO:0085001 salinity (of the soil, ENVO context)",
    "temperature_c": "PATO:0000146 temperature (environmental tolerance range); TO:0000259 heat tolerance",
    "frost": "TO:0000303 cold tolerance (nearest; no frost-specific TO term in ont/trait.obo)",
    "elevation_m": "PATO:0001687 elevation (occurrence context, not a phenotype)",
    "planting_time": "cultivation practice (no ontology target)",
}


def iter_growth_rows(records: Iterable[dict]) -> Iterable[dict]:
    for rec in records:
        base = {
            "source_id": ncvc_guide._source_id(rec),
            "pdf_page": int(rec["pdf_page"]),
            "taxon": ncvc_guide.taxon_from_record(rec).name_string,
            "taxon_family": ncvc_guide._normalize(rec.get("family")),
        }
        for table in ("growth_adaptation", "cultivation"):
            for trait, cell in sorted((rec.get(table) or {}).items()):
                if not isinstance(cell, dict):
                    continue
                value_en = ncvc_guide._normalize(cell.get("en"))
                note = ""
                low = high = None
                bound = "categorical"
                if "low" in cell or "high" in cell:
                    low, high, bound, problem = normalize_bounds(
                        cell.get("low"),
                        cell.get("high"),
                        value_en + " " + str(cell.get("ar") or ""),
                    )
                    if problem:
                        note = "explicit comparator (strict/open bound)"
                    if (low, high) != (_num(cell.get("low")), _num(cell.get("high"))):
                        note = "single printed value normalized to low=high"
                    if bound == "none":
                        bound = "unparsed"
                yield {
                    **base,
                    "table": table,
                    "trait": trait,
                    "value_en": value_en,
                    "value_ar": ncvc_guide._normalize(cell.get("ar")),
                    "low": "" if low is None else low,
                    "high": "" if high is None else high,
                    "unit": TRAIT_UNITS.get(trait, ""),
                    "bound_type": bound,
                    "months": "|".join(str(m) for m in cell.get("months") or []),
                    "ontology_hint": TRAIT_HINTS.get(trait, ""),
                    "note": note,
                }


def _read_optional_tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def join_distribution(
    rows: list[dict], gazetteer: list[dict], taxa: list[dict]
) -> tuple[list[dict], list[str]]:
    """Left-join optional gazetteer (by Arabic or English place name) and taxa (by page/name)."""

    extra_fields: list[str] = []
    gaz_index: dict[str, dict] = {}
    if gazetteer:
        gaz_keys = [
            k
            for k in ("verbatim_ar", "name_ar", "locality_verbatim_ar", "name_en", "locality_name")
            if k in gazetteer[0]
        ]
        for g in gazetteer:
            for key in gaz_keys:
                value = ncvc_guide._normalize(g.get(key))
                if value:
                    gaz_index.setdefault(value.lower(), g)
        extra_fields += [f"gaz_{k}" for k in gazetteer[0]]
    taxa_index: dict[str, dict] = {}
    if taxa:
        for t in taxa:
            for key in ("source_id", "pdf_page", "scientific_name", "taxon"):
                value = ncvc_guide._normalize(t.get(key))
                if value:
                    taxa_index.setdefault(f"{key}={value.lower()}", t)
        extra_fields += [f"taxa_{k}" for k in taxa[0]]
    out = []
    for row in rows:
        row = dict(row)
        if gazetteer:
            hit = None
            for value in (row.get("verbatim_ar"), row.get("locality_name")):
                value = ncvc_guide._normalize(value).lower()
                if value and value in gaz_index:
                    hit = gaz_index[value]
                    break
            for k in gazetteer[0]:
                row[f"gaz_{k}"] = (hit or {}).get(k, "")
        if taxa:
            page = row["source_id"].rsplit("page-", 1)[-1].lstrip("0")
            hit = (
                taxa_index.get(f"source_id={row['source_id'].lower()}")
                or taxa_index.get(f"pdf_page={page}")
                or taxa_index.get(f"scientific_name={row['taxon'].lower()}")
            )
            for k in taxa[0]:
                row[f"taxa_{k}"] = (hit or {}).get(k, "")
        out.append(row)
    return out, extra_fields


TAXA_FIELDS = [
    "source_id",
    "pdf_page",
    "printed_pages",
    "scientific_name",
    "authority",
    "name_as_printed",
    "family",
    "family_ar",
    "arabic_names",
    "synonyms",
    "abundance_en",
    "native_range_en",
    "ksa_regions_all",
    "data_quality_flags",
]


def iter_taxa_rows(records: Iterable[dict], holds: list[HoldRule]) -> Iterable[dict]:
    for rec in records:
        page = int(rec["pdf_page"])
        flags = [h for h in holds if h.pdf_page == page]
        synonyms = rec.get("synonyms") or []
        if any(h.action == "drop_synonyms" for h in flags):
            synonyms = []
        yield {
            "source_id": ncvc_guide._source_id(rec),
            "pdf_page": page,
            "printed_pages": "|".join(str(p) for p in rec.get("printed_pages") or []),
            "scientific_name": ncvc_guide._normalize(rec.get("scientific_name")),
            "authority": ncvc_guide._normalize(rec.get("authority")),
            "name_as_printed": ncvc_guide._normalize(rec.get("name_as_printed")),
            "family": ncvc_guide._normalize(rec.get("family")),
            "family_ar": ncvc_guide._normalize(rec.get("family_ar")),
            "arabic_names": "|".join(rec.get("arabic_names") or []),
            "synonyms": "|".join(ncvc_guide._normalize(s) for s in synonyms),
            "abundance_en": ncvc_guide._normalize(rec.get("abundance_en")),
            "native_range_en": ncvc_guide._normalize(rec.get("native_range_en")),
            "ksa_regions_all": bool(rec.get("ksa_regions_all")),
            "data_quality_flags": "|".join(f"{h.rule_id}:{h.reason_code}" for h in flags),
        }


DISPOSITION_FIELDS = [
    "source_id",
    "pdf_page",
    "taxon",
    "row",
    "status",
    "reason",
    "entity_en",
    "quality_en",
    "po_label",
    "pato_label",
    "po_id",
    "pato_id",
    "value_terms",
    "flopo_class",
    "flopo_signature",
    "flopo_iri",
    "po_pato_status",
    "hold_rule",
    "rules",
    "anchor_method",
    "source_en",
]


def holds_from_taxa(taxa: list[dict], existing: list[HoldRule]) -> list[HoldRule]:
    """Hold every phenotype of a page the taxon review marked ``unreliable_description``."""

    covered = {h.pdf_page for h in existing if h.action == "hold_all"}
    out = []
    for row in taxa:
        page = ncvc_guide._normalize(row.get("pdf_page"))
        if row.get("reliability") != "unreliable_description" or not page.isdigit():
            continue
        if int(page) in covered:
            continue
        out.append(
            HoldRule(
                rule_id=f"T{int(page):03d}",
                pdf_page=int(page),
                action="hold_all",
                entity_regex="",
                quality_regex="",
                source_regex="",
                reason_code="description_unreliable_taxa_review",
                reason=ncvc_guide._normalize(row.get("notes"))[:200],
                evidence="taxa.tsv reliability=unreliable_description",
            )
        )
    return out


def join_taxa(rows: list[dict], taxa: list[dict]) -> tuple[list[dict], list[str]]:
    """Attach the taxon-review columns (accepted name/family, WFO/POWO id) by PDF page."""

    if not taxa:
        return rows, []
    by_page = {ncvc_guide._normalize(t.get("pdf_page")): t for t in taxa}
    fields = [f"taxa_{k}" for k in taxa[0] if k != "pdf_page"]
    out = []
    for row in rows:
        hit = by_page.get(str(row["pdf_page"]), {})
        out.append({**row, **{f"taxa_{k}": hit.get(k, "") for k in taxa[0] if k != "pdf_page"}})
    return out, fields


def _novel_candidates(dispositions: list[Disposition], res: Resources) -> list[dict]:
    groups: dict[str, dict] = {}
    for d in dispositions:
        a = d.assertion
        if a is None:
            continue
        gate = a["gate"]
        if gate["po_pato_status"] != "novel" or gate["flopo_status"] != "new_class_candidate":
            continue
        signature = gate["flopo_signature"]
        g = groups.setdefault(
            signature,
            {
                "signature": signature,
                "po_id": a["po_id"],
                "pato_id": a["pato_id"],
                "count": 0,
                "taxa": set(),
                "examples": [],
                "held": 0,
                "numeric": 0,
            },
        )
        g["count"] += 1
        g["taxa"].add(d.row.get("taxon", ""))
        g["held"] += d.status == "held"
        g["numeric"] += a.get("value_low") is not None or a.get("value_high") is not None
        if len(g["examples"]) < 3:
            g["examples"].append(
                f"{d.row.get('taxon', '')} (p{d.row['pdf_page']}): {a['source_text']}"
            )
    out = []
    for g in sorted(groups.values(), key=lambda g: (-g["count"], g["signature"])):
        quality = g["signature"].rsplit("|", 1)[-1]
        out.append(
            {
                "signature": g["signature"],
                "po_id": g["po_id"],
                "po_label": _label(res, g["po_id"]),
                "quality_id": quality,
                "quality_label": _label(res, quality),
                "proposed_label": f"{_label(res, g['po_id'])} {_label(res, quality)}".strip(),
                "pato_is_attribute": g["pato_id"] in res.attribute_ids,
                "count": g["count"],
                "taxon_count": len(g["taxa"]),
                "held_count": g["held"],
                "numeric_count": g["numeric"],
                "example_1": g["examples"][0] if g["examples"] else "",
                "example_2": g["examples"][1] if len(g["examples"]) > 1 else "",
                "example_3": g["examples"][2] if len(g["examples"]) > 2 else "",
                "review_status": "pending",
            }
        )
    return out


def _write_tsv(path: Path, fields: list[str], rows: Iterable[dict]) -> int:
    return ncvc_guide._write_tsv(path, fields, rows)


# ---------------------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------------------


def page_coverage(raw: Path, first: int = 15, last: int = 317) -> dict[str, Any]:
    pages: Counter[int] = Counter()
    dividers: list[int] = []
    files = sorted(raw.glob("*.jsonl")) if raw.is_dir() else [raw]
    for file in files:
        with file.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    pages[int(rec.get("pdf_page", 0))] += 1
                    if rec.get("non_species_page"):
                        dividers.append(int(rec["pdf_page"]))
    expected = set(range(first, last + 1))
    return {
        "expected": f"{first}-{last}",
        "present": len(expected & set(pages)),
        "missing": sorted(expected - set(pages)),
        "duplicates": sorted(p for p, n in pages.items() if n > 1),
        "non_species_pages": sorted(dividers),
    }


def run(
    corpus_dir: Path,
    out_dir: Path | None = None,
    res: Resources | None = None,
    catalog_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Build every derived artifact, validate the corpus JSONL, and write ``REPORT.md``.

    ``catalog_paths`` (``po_lexicon``/``pato_lexicon``/``flopo_registry``) must match ``res``
    when custom resources are supplied; the defaults are the repository config tables.
    """
    raw = corpus_dir / "raw"
    out_dir = out_dir or corpus_dir / "derived"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = res or load_resources()
    records = list(ncvc_guide.iter_records(raw))
    gazetteer = _read_optional_tsv(corpus_dir / "gazetteer.tsv")
    taxa_extra = _read_optional_tsv(corpus_dir / "taxa.tsv")
    res.holds = [*res.holds, *holds_from_taxa(taxa_extra, res.holds)]
    all_dispositions: list[Disposition] = []
    whole_plant_rows: list[dict] = []
    counts: Counter[str] = Counter()
    with (out_dir / "ncvc-saudi-annotated.jsonl").open("w", encoding="utf-8") as fh:
        for rec in records:
            segments, dispositions = annotate_record(rec, res)
            taxon = ncvc_guide.taxon_from_record(rec).name_string
            source_id = ncvc_guide._source_id(rec)
            for d in dispositions:
                d.row.update({"taxon": taxon, "source_id": source_id})
                if d.row.get("flopo_class"):
                    whole_plant_rows.append(
                        {
                            "source_id": source_id,
                            "pdf_page": d.row["pdf_page"],
                            "taxon": taxon,
                            "taxon_family": ncvc_guide._normalize(rec.get("family")),
                            "flopo_class": d.row["flopo_class"],
                            "flopo_label": res.flopo_labels.get(d.row["flopo_class"], ""),
                            "quality_en": d.row.get("quality_en", ""),
                            "source_en": d.row.get("source_en", ""),
                            "rule": d.row.get("rules", ""),
                            "hold_rule": d.row.get("hold_rule", ""),
                        }
                    )
            all_dispositions.extend(dispositions)
            for seg in segments:
                counts["segments"] += 1
                counts[f"segments_{seg['language']}"] += 1
                counts["source_statements"] += len(seg["source_statements"])
                counts["unresolved_spans"] += len(seg["unresolved_spans"])
                fh.write(json.dumps(seg, ensure_ascii=False) + "\n")

    disposition_rows = []
    for d in all_dispositions:
        a = d.assertion or {}
        gate = a.get("gate") or {}
        disposition_rows.append(
            {
                **{k: d.row.get(k, "") for k in DISPOSITION_FIELDS},
                "status": d.status,
                "reason": d.reason,
                "value_terms": "|".join(a.get("value_terms") or []) or d.row.get("value_terms", ""),
                "flopo_signature": gate.get("flopo_signature", ""),
                "flopo_iri": gate.get("flopo_iri", ""),
                "po_pato_status": gate.get("po_pato_status", ""),
            }
        )
    _write_tsv(
        out_dir / "ncvc-saudi-phenotype-dispositions.tsv", DISPOSITION_FIELDS, disposition_rows
    )
    whole_fields = [
        "source_id",
        "pdf_page",
        "taxon",
        "taxon_family",
        "flopo_class",
        "flopo_label",
        "quality_en",
        "source_en",
        "rule",
        "hold_rule",
    ]
    _write_tsv(out_dir / "ncvc-saudi-whole-plant-classes.tsv", whole_fields, whole_plant_rows)
    novel = _novel_candidates(all_dispositions, res)
    novel_fields = list(novel[0]) if novel else ["signature"]
    _write_tsv(out_dir / "ncvc-saudi-novel-eq-candidates.tsv", novel_fields, novel)

    distribution = list(ncvc_guide.iter_distribution_rows(records))
    distribution, extra = join_distribution(distribution, gazetteer, taxa_extra)
    _write_tsv(
        out_dir / "ncvc-saudi-distribution.tsv",
        ncvc_guide.DISTRIBUTION_FIELDS + extra,
        distribution,
    )
    growth = list(iter_growth_rows(records))
    _write_tsv(out_dir / "ncvc-saudi-growth-traits.tsv", GROWTH_FIELDS, growth)
    taxa_rows = list(iter_taxa_rows(records, res.holds))
    taxa_rows, taxa_fields = join_taxa(taxa_rows, taxa_extra)
    _write_tsv(out_dir / "ncvc-saudi-taxa.tsv", TAXA_FIELDS + taxa_fields, taxa_rows)

    status_counts = Counter(d.status for d in all_dispositions)
    reason_counts = Counter(
        d.reason for d in all_dispositions if d.status in {"unresolved", "unanchored", "held"}
    )
    assertions = [d.assertion for d in all_dispositions if d.assertion is not None]
    region_counts = Counter(r["iso_3166_2"] for r in distribution if r["level"] == "region")
    hold_rule_hits = Counter(
        d.row.get("hold_rule") for d in all_dispositions if d.row.get("hold_rule")
    )
    summary = {
        "species_records": len(records),
        "distinct_taxa": len({ncvc_guide.taxon_from_record(r).name_string for r in records}),
        "page_coverage": page_coverage(raw),
        **dict(counts),
        "phenotype_rows": len(all_dispositions),
        "dispositions": dict(sorted(status_counts.items())),
        "assertions": len(assertions),
        "assertions_linked_to_existing_flopo": sum(
            1 for a in assertions if a["gate"]["flopo_status"] == "existing"
        ),
        "assertions_novel_pair": sum(
            1 for a in assertions if a["gate"]["po_pato_status"] == "novel"
        ),
        "novel_eq_candidates": len(novel),
        "whole_plant_class_rows": len(whole_plant_rows),
        "reasons": dict(reason_counts.most_common()),
        "hold_rule_hits": dict(sorted(hold_rule_hits.items())),
        "hold_rules_without_hits": sorted(
            h.rule_id
            for h in res.holds
            if h.action in {"hold", "hold_all"} and h.rule_id not in hold_rule_hits
        ),
        "distribution_rows": len(distribution),
        "region_taxon_counts": dict(sorted(region_counts.items())),
        "distribution_joined": {"gazetteer": bool(gazetteer), "taxa": bool(taxa_extra)},
        "growth_trait_rows": len(growth),
        "assertions_by_gate": dict(
            sorted(Counter(a["gate"]["status"] for a in assertions).items())
        ),
        "assertions_by_normalization": dict(
            sorted(Counter(a["normalization_status"] for a in assertions).items())
        ),
        "assertions_via_reviewed_rules": sum(
            1 for d in all_dispositions if d.assertion is not None and d.row.get("rules")
        ),
        "whole_plant_classes": dict(
            Counter(r["flopo_label"] for r in whole_plant_rows).most_common()
        ),
        "locality_rows": sum(1 for r in distribution if r["level"] == "locality"),
        "locality_rows_with_region": sum(
            1 for r in distribution if r["level"] == "locality" and r["iso_3166_2"]
        ),
        "taxa_without_region": sorted(
            ncvc_guide._source_id(r)
            for r in records
            if not r.get("ksa_regions") and not r.get("ksa_regions_all")
        ),
        "taxa_family_corrections": sum(
            1
            for t in taxa_rows
            if t.get("taxa_accepted_family") and t["taxa_accepted_family"] != t["family"]
        ),
        "duplicate_taxa": sorted(
            name
            for name, n in Counter(
                ncvc_guide.taxon_from_record(r).name_string for r in records
            ).items()
            if n > 1
        ),
    }
    validation = validate_jsonl(
        out_dir / "ncvc-saudi-annotated.jsonl",
        stage="gated",
        require_annotation_class=True,
        strict_source_statements=True,
        **(catalog_paths or {}),
    )
    (out_dir / "validation.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    summary["validation"] = {
        k: validation[k] for k in ("errors", "errors_by_code", "gate_statuses", "ok")
    }
    write_report(out_dir / "REPORT.md", summary, novel)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def _table(headers: list[str], rows: Iterable[Iterable[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |")
    return "\n".join(lines)


def write_report(path: Path, summary: dict[str, Any], novel: list[dict]) -> None:
    cov = summary["page_coverage"]
    disp = summary["dispositions"]
    gate = summary["assertions_by_gate"]
    held = disp.get("held", 0)
    region_rows = [
        (code, ncvc_guide.SAUDI_REGIONS[code], n)
        for code, n in sorted(summary["region_taxon_counts"].items())
    ]
    reasons = list(summary["reasons"].items())
    val = summary["validation"]
    text = f"""# NCVC Saudi native-plants guide: FLOPO annotation corpus

Generated by `flopo2.ingest.ncvc_annotate` (deterministic; rerun with
`.venv/bin/python -m flopo2.ingest.ncvc_annotate local-corpora/saudi-ncvc-guide`). All numbers
below are recomputed on every run from `raw/*.jsonl`; see `summary.json` for the full breakdown.

## Coverage

* PDF pages {cov["expected"]}: {cov["present"]} present, missing {cov["missing"] or "none"},
  duplicated {cov["duplicates"] or "none"}; non-species divider pages {cov["non_species_pages"]}.
* Species records: {summary["species_records"]} ({summary["distinct_taxa"]} distinct names;
  printed twice: {", ".join(summary["duplicate_taxa"]) or "none"}).
* Segments: {summary["segments"]} ({summary["segments_en"]} English, {summary["segments_ar"]}
  Arabic; description and habitat per language). Source statements: {summary["source_statements"]}
  (English assertion evidence plus Arabic `source_ar` spans on the Arabic description segment).

## Outputs (`derived/`)

| File | Content |
|---|---|
| `ncvc-saudi-annotated.jsonl` | corpus records (stage-22 wire format): segments, `source_statements`, gated `assertions` with FAC class IRIs, `unresolved_spans` |
| `ncvc-saudi-phenotype-dispositions.tsv` | every transcribed phenotype row with its status, reason, grounding, rule and hold IDs |
| `ncvc-saudi-whole-plant-classes.tsv` | taxon to existing FLOPO whole-plant class (life span/growth form) that has no EQ signature |
| `ncvc-saudi-novel-eq-candidates.tsv` | novel PO+PATO pairs (pair, count, examples); candidates only, nothing minted |
| `ncvc-saudi-distribution.tsv` | taxon occurrence by ISO 3166-2 region and named locality (+ joined `taxa.tsv`/`gazetteer.tsv` columns when present) |
| `ncvc-saudi-growth-traits.tsv` | growth/ecological-adaptation and cultivation table cells per taxon (long format) |
| `ncvc-saudi-taxa.tsv` | taxon list with synonyms (dropped where flagged), data-quality flags, joined taxon review |
| `validation.json`, `summary.json` | data-model validation report and run summary |

## Phenotype statements

Transcribed rows: {summary["phenotype_rows"]}.

{_table(["disposition", "rows"], sorted(disp.items()))}

* Assertions (PO/FLOPO bearer + PATO quality or FLOPO value, anchored by exact offsets in
  `description_en`): **{summary["assertions"]}**; gate {gate}. Linked to an existing FLOPO EQ class (any gate
  status): **{summary["assertions_linked_to_existing_flopo"]}**. Novel PO+PATO pair (gate
  `po_pato_novel`, review): {summary["assertions_novel_pair"]}. Normalized through reviewed
  rules (`flopo2/ingest/ncvc_normalization.tsv`): {summary["assertions_via_reviewed_rules"]}.
* Held for data quality (`flopo2/ingest/ncvc_data_quality_holds.tsv` and `taxa.tsv`
  `unreliable_description`): {held} assertions stay in the corpus with composition/gate `review`,
  gate reason `ncvc_hold:<code>` and a `held:` mapping-provenance entry. The schema's
  `NormalizationStatus` enum has no `held` value, so they carry `normalization_status: proposed`.
  Rule hits: {summary["hold_rule_hits"]}; rules matching no anchored row:
  {summary["hold_rules_without_hits"] or "none"}.
* Unresolved spans (verbatim, first-class audit evidence, never asserted): {disp.get("unresolved", 0)};
  unanchored rows (no locatable English span; kept only in the dispositions TSV):
  {disp.get("unanchored", 0)}.

Top unresolved/held reasons:

{_table(["reason", "rows"], reasons[:20])}

### Habit, life span, fruit and inflorescence types

The transcription's rows without a PATO label were normalized with the reviewed table
`flopo2/ingest/ncvc_normalization.tsv` (every rule cites its evidence; no identifiers minted):

* Life span and growth form map to existing FLOPO whole-plant classes (`whole plant perennial`,
  `annual`, `biennial`, `arborescent` = tree, `frutescent` = shrub, `lianescent` = climber,
  `shoot axis suffruticose` = subshrub). These classes have registry signature `OTHER` (no EQ
  definition), so they cannot be EQ assertions; they are recorded as unresolved spans with reason
  `flopo_phenotype_class_without_eq_signature` and listed per taxon in
  `ncvc-saudi-whole-plant-classes.tsv`: {summary["whole_plant_classes"]}.
* `evergreen`/`deciduous`/`semi-deciduous` map to PATO `evergreen (plant)`, `deciduous (plant)`
  (whole plant) or `deciduous (generic)` (caducous organs); `herb` to PATO `herbaceous`
  (existing FLOPO `whole plant herbaceous`); `woody` to PATO `ligneous`; `bisexual` to PATO
  `hermaphrodite`.
* Fruit types (capsule, legume/pod, drupe, berry, achene, follicle, nut/nutlet, silique,
  mericarp, schizocarp, samara) and inflorescence types (raceme/racemose, spike, umbel, panicle,
  cyme, corymb, capitulum) are entities: PO fruit/inflorescence class + PATO `present`.
  `petiolate` leaves become PO `petiole` + `present`.
* No ontology counterpart (held as unresolved): dioecious/monoecious/unisexual, axillary,
  solitary, subsessile, leaf-opposed, winged (non-fruit), counts such as many-flowered.

## Novel PO+PATO pair candidates

{len(novel)} distinct novel pairs (checked against `config/valid_combinations.tsv`; the gate marks
them `po_pato_novel`, and `flopo2.verify.novel_combinations` can build the curator sheet from the
annotated JSONL). They remain assertions carrying their EQ signature. Top 25:

{_table(["signature", "label", "count", "taxa", "example"], [(r["signature"], r["proposed_label"], r["count"], r["taxon_count"], r["example_1"]) for r in novel[:25]])}

## Geography

The trait data model has no place for taxon occurrence: `SeasonContext.geographic_context`
qualifies a season, not a taxon, and segments carry only `taxon`/`source_id`. Distribution is
therefore a separate table, `ncvc-saudi-distribution.tsv` ({summary["distribution_rows"]} rows;
{summary["locality_rows"]} locality rows, {summary["locality_rows_with_region"]} with a region
code). Joined inputs: gazetteer.tsv = {summary["distribution_joined"]["gazetteer"]},
taxa.tsv = {summary["distribution_joined"]["taxa"]} (accepted names, WFO/POWO IDs, family
corrections: {summary["taxa_family_corrections"]} taxa whose accepted family differs from the
printed one). Taxa with no administrative region stated: {len(summary["taxa_without_region"])}.

{_table(["ISO 3166-2", "region", "taxa"], region_rows)}

## Growth and cultivation traits

`ncvc-saudi-growth-traits.tsv` ({summary["growth_trait_rows"]} rows) keeps flowering months,
growth rate, drought/waterlogging/frost tolerance, soil salinity (ppm), temperature (°C),
elevation (m), propagation, planting time, irrigation, fertilization, care, toxicity, pests and
stresses. These are ecological or horticultural traits, not PATO phenotypes of a plant part, and
are not asserted in the corpus. Single printed values stored only as an upper bound become
low = high; explicit comparators (*less than*, *up to*, *>*) keep an open bound.

Possible ontology targets (column `ontology_hint`): flowering months as TO:0002616 *flowering
time* or a PO:0007616 *flowering stage* context with month bounds (the model's `SeasonContext`
already supports month ranges); drought TO:0000276, salinity TO:0006001 (with PATO:0085001
*salinity* for the soil value), frost TO:0000303 *cold tolerance* (nearest), waterlogging
TO:0000114 / TO:0000524, heat TO:0000259, growth rate PATO:0001492. Elevation (PATO:0001687) is
occurrence context, not a trait.

## Validation

`python -m flopo2.verify.data_model derived/ncvc-saudi-annotated.jsonl --stage gated
--strict-source-statements --require-annotation-class`: errors = {val["errors"]}, ok =
{val["ok"]}, gate statuses {val["gate_statuses"]}.

## Open issues

* `held` is not a schema `NormalizationStatus`; holds are expressed through composition/gate
  `review`, `ncvc_hold:` gate reasons and `held:` provenance. Adding the enum value would make
  them first-class.
* Whole-plant life span and growth-form classes (perennial, tree, shrub, climber) have no EQ
  definitions in FLOPO, so {summary["whole_plant_class_rows"]} habit statements live only as
  unresolved spans plus the side table.
* Sexual system (dioecious, monoecious, unisexual) and position terms (axillary, solitary,
  subsessile) have no PATO/FLOPO term in the lexicon.
* Alternatives (`X or Y`, `X to Y`) are held as unresolved rather than converted into
  `one_of` or qualitative relations; a follow-up could reuse `recover_llm_one_of_expressions`
  or the qualitative-relation recovery.
* Counts (numbers of flowers, seeds, leaflets) are not representable as length measurements.
* The bearer `leaf` grounds to PO:0025034 (exact label), while much of the existing corpus uses
  PO:0009025 *vascular leaf*; some "novel" leaf pairs exist in FLOPO under vascular leaf.
* Taxon occurrence has no slot in the trait schema (see Geography).
* The English text is a literal translation; offsets anchor the translation, and the Arabic
  evidence is linked only through `source_ar` statements on the Arabic segment.
"""
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("corpus_dir", type=Path, help="local-corpora/saudi-ncvc-guide")
    ap.add_argument("-o", "--out-dir", type=Path, default=None)
    args = ap.parse_args(argv)
    summary = run(args.corpus_dir, args.out_dir)
    json.dump(summary, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
