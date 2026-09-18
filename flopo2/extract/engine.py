"""Trait extraction engine: terminology-guided flora text -> grounded EQ assertions.

The terminology layer supplies reviewed mappings and retrieval candidates as *soft* evidence.  The
model still resolves senses and entity-quality bindings in context, and every accepted assertion
retains its source span.  Logical alternatives are represented explicitly as ``one_of`` values;
they are never flattened into conjunctive PATO parents.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace

from flopo2.eval.scoring import Assertion, assertion_vote_key
from flopo2.extract.ground import load_lexicons
from flopo2.extract.measurement import Measurement, parse_measurements
from flopo2.extract.router import OpenRouterClient
from flopo2.terminology.annotate import (
    TerminologyIndex,
    load_ontology_index,
    load_terminology_index,
)
from flopo2.terminology.normalize import fold

SYSTEM = (
    "You are an expert botanist extracting plant phenotype traits from flora descriptions for the "
    "Flora Phenotype Ontology. Extract every entity-quality assertion: an anatomical structure and "
    "a quality/attribute asserted of it. Translate non-English text to English anatomical/quality "
    "terms. Botanical terminology annotations are evidence, not mandatory answers: use context, "
    "and emit no assertion rather than force an incompatible term. Preserve 'A or B' as one_of and "
    "never turn it into a conjunction. Scope explicit negation as quality or absence and retain "
    "developmental-stage cues on the phenotype they qualify. Return STRICT JSON only."
)

USER_TMPL = """Taxon: {taxon}
Organ hint: {organ}
Language: {language}
Description: "{text}"

Prior botanical terminology annotations (soft evidence; candidates may be rejected):
{terminology_context}

Deterministically parsed measurements (exact source spans; bind each to the correct bearer):
{measurement_context}

Extract all entity-quality trait assertions. Return JSON:
{{"assertions": [
  {{"entity_label": "<English anatomical structure, e.g. leaf, petal, stem>",
    "quality_label": "<English quality or attribute, e.g. red, shape, glabrous, length>",
    "entity_text": "<verbatim entity expression>",
    "quality_text": "<verbatim quality/value expression>",
    "value_operator": "<atomic, all_of, or one_of>",
    "value_labels": ["<English categorical value; include every alternative>"],
    "negated": <true only for an explicit negative assertion>,
    "negation_scope": "<quality, absence, or empty when not negated>",
    "developmental_stage_contexts": [{{"stage_term": "<PO id if grounded>",
      "stage_text": "<exact cue>"}}],
    "value_low": <number or null>, "value_high": <number or null>,
    "value_low_inclusive": <true unless the lower comparator is strict>,
    "value_high_inclusive": <true unless the upper comparator is strict>,
    "unit": "<e.g. cm, mm or empty>",
    "value_text": "<verbatim categorical state or empty>",
    "source_text": "<exact verbatim substring of the description justifying this>"}}
]}}
Only include assertions supported by the text. Copy source_text verbatim, including any negation
cue that changes its meaning. For "greenish or
pinkish flowers", emit one flower/color assertion with value_operator one_of and both values."""

PICK_TMPL = """Source phrase: "{phrase}"
Candidate {kind} terms (id : label):
{cands}
Pick the single best-matching id for the {kind} in the source phrase. Return JSON {{"id": "<id or empty>"}}."""


@dataclass
class EngineConfig:
    models: list[str]
    grounding: str = "spires"
    samples: int = 1
    temperature: float = 0.3
    use_terminology: bool = True
    terminology_mode: str = "full"  # off | ontology | registry | full
    terminology_registry: str = "config/botanical_terminology.tsv"
    terminology_limit: int = 30


_MEASUREMENT_LABELS = {
    "PATO_0000122": "length",
    "PATO_0000921": "width",
    "PATO_0000119": "height",
    "PATO_0000915": "thickness",
    "PATO_0001334": "diameter",
}

_UNSAFE_BOTANICAL_PATO_IDS = {
    "PATO_0000389",  # acute process duration, not acute organ shape
    "PATO_0000455",  # onset-of-puberty maturity, not botanical pubescence
    "PATO_0002147",  # reduced virulence, not botanical attenuation
}


def _measurement_context(measurements: list[Measurement]) -> str:
    if not measurements:
        return "(none found)"
    lines = []
    for item in measurements:
        values = (
            f"upper_bound={item.value_high:g}"
            if item.value_low is None
            else f"value={item.value_low:g}"
            if item.value_low == item.value_high
            else f"range={item.value_low:g}..{item.value_high:g}"
        )
        lines.append(
            f'- [{item.start}:{item.end}] "{item.source_text}" -> '
            f"{item.attribute_id} {_MEASUREMENT_LABELS[item.attribute_id]}; "
            f"{values} {item.unit_text}; unit={item.unit_id}"
        )
    return "\n".join(lines)


def _repair_measurement(assertion: Assertion, measurements: list[Measurement]) -> Assertion:
    """Replace model-copied scalar data with a matching deterministic parse."""

    source = assertion.source_text
    support = next(
        (
            item
            for item in measurements
            if item.attribute_id == assertion.pato_id
            and source
            and (item.source_text in source or source in item.source_text)
        ),
        None,
    )
    if support is None:
        return assertion
    # Never downgrade a recognized open bound. If the model marked exactly one side open (an upper
    # or lower bound) but the matching deterministic parse is bounded on both sides — an exact
    # scalar (low == high) or an explicit range — the parser simply missed the comparator. Keep the
    # model's bound structure rather than collapsing "n'atteignant pas 0,5 mm" to an exact 0.5 or a
    # range; only when the support is itself an open bound is its full parse (including its
    # inclusivity) adopted.
    assertion_is_open_bound = (assertion.value_low is None) != (assertion.value_high is None)
    support_is_open_bound = (support.value_low is None) != (support.value_high is None)
    if assertion_is_open_bound and not support_is_open_bound:
        return assertion
    return replace(
        assertion,
        value_low=support.value_low,
        value_high=support.value_high,
        value_low_inclusive=support.value_low_inclusive,
        value_high_inclusive=support.value_high_inclusive,
        unit=support.unit_text,
        modifier=support.modifier,
        mapping_provenance=tuple(
            sorted(
                set(assertion.mapping_provenance)
                | {"deterministic_measurement_parse", support.unit_id}
            )
        ),
    )


def _resolve(
    label: str,
    raw_text: str,
    namespace: str,
    role: str,
    lexicon,
    guide: TerminologyIndex | None,
    organ: str,
) -> tuple[str | None, str, tuple[str, ...]]:
    direct = lexicon.ground(label)
    override_keys = {
        fold(value)
        for value in (label, raw_text)
        if value and fold(value) in (lexicon.label_overrides or {})
    }
    if override_keys:
        # Explicit domain overrides exist precisely where a preferred label or synonym is unsafe
        # in botanical context. They must outrank even an old auto mapping in the registry.
        override_target = next(
            (
                (lexicon.label_overrides or {}).get(key)
                for key in sorted(override_keys)
                if (lexicon.label_overrides or {}).get(key)
            ),
            "",
        )
        if override_target and override_target in lexicon.id_to_label:
            return override_target, "auto", ("botanical_grounding_override",)
        if not override_target:
            return None, "nil", ("blocked_non_equivalent_ontology_synonym",)
    candidates = []
    if guide:
        for surface in dict.fromkeys(filter(None, (raw_text, label))):
            candidates.extend(guide.resolve(surface, namespace, role, organ_context=organ, k=5))
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.target_id))
    trusted = next(
        (
            candidate
            for candidate in candidates
            if candidate.mapping_status in {"reviewed", "accepted", "auto"}
            and candidate.score >= 0.95
            and candidate.mapping_relation in {"", "skos:exactMatch", "skos:closeMatch"}
            and candidate.target_id in lexicon.id_to_label
        ),
        None,
    )
    if trusted:
        provenance = tuple(sorted(set(trusted.registry_term_ids) | set(trusted.evidence)))
        return trusted.target_id, trusted.mapping_status, provenance
    if direct:
        return direct, "auto", ("ontology_label_or_synonym",)
    retrieved = next(
        (
            candidate
            for candidate in candidates
            if candidate.score >= 0.72
            and candidate.target_id in lexicon.id_to_label
            and candidate.mapping_relation in {"", "skos:exactMatch", "skos:closeMatch"}
        ),
        None,
    )
    if retrieved:
        provenance = tuple(sorted(set(retrieved.registry_term_ids) | set(retrieved.evidence)))
        return retrieved.target_id, "retrieved", provenance
    return None, "nil", ()


def _relevant_mentions(assertion: dict, mentions) -> list:
    labels = assertion.get("value_labels") or []
    if isinstance(labels, str):
        labels = [labels]
    raw = " ".join(
        filter(
            None,
            (
                fold(assertion.get("source_text", "")),
                fold(assertion.get("entity_text", "")),
                fold(assertion.get("quality_text", "")),
                fold(" ".join(map(str, labels))),
            ),
        )
    )
    return [mention for mention in mentions if mention.normalized_form in raw]


def _value_logic(assertion: dict, guide: TerminologyIndex | None, mentions, pato_lex):
    operator = assertion.get("value_operator", "atomic")
    if operator not in {"atomic", "all_of", "one_of"}:
        operator = "atomic"
    values: list[str] = []
    attribute_id = ""
    authoritative_expression = False
    provenance: set[str] = set()
    relevant = _relevant_mentions(assertion, mentions)
    value_mentions = [
        mention
        for mention in relevant
        if "value" in mention.semantic_roles or mention.logical_operator in {"one_of", "all_of"}
    ]
    value_mentions.sort(
        key=lambda mention: (
            mention.logical_operator not in {"one_of", "all_of"},
            -(mention.end - mention.start),
        )
    )
    if value_mentions:
        mention = value_mentions[0]
        operator = mention.logical_operator or operator
        attribute_id = mention.attribute_id
        values.extend(mention.component_ids)
        authoritative_expression = bool(mention.component_ids)
        if not values:
            value_candidate = next(
                (
                    candidate
                    for candidate in mention.candidates
                    if candidate.namespace in {"PATO", "FLOPO"}
                    and candidate.score >= 0.90
                    and candidate.mapping_relation
                    in {"", "skos:exactMatch", "skos:closeMatch"}
                ),
                None,
            )
            if value_candidate:
                values.append(value_candidate.target_id)
                provenance.update(value_candidate.registry_term_ids)
        provenance.update(mention.registry_term_ids)

    labels = assertion.get("value_labels") or []
    if isinstance(labels, str):
        labels = [labels]
    if guide and not authoritative_expression and (operator != "atomic" or not values):
        for label in labels:
            candidates = guide.resolve(str(label), "PATO", "value", k=3)
            candidate = next(
                (
                    item
                    for item in candidates
                    if item.score >= 0.72
                    and item.mapping_relation in {"", "skos:exactMatch", "skos:closeMatch"}
                ),
                None,
            )
            if candidate is None:
                candidates = guide.resolve(str(label), "FLOPO", "value", k=3)
                candidate = next(
                    (
                        item
                        for item in candidates
                        if item.score >= 0.72
                        and item.mapping_relation in {"", "skos:exactMatch", "skos:closeMatch"}
                    ),
                    None,
                )
            if candidate:
                values.append(candidate.target_id)
                provenance.update(candidate.registry_term_ids)
    elif not guide:
        for label in labels:
            target_id = pato_lex.ground(str(label))
            if target_id:
                values.append(target_id)
                provenance.add("ontology_label_or_synonym")
    values = list(dict.fromkeys(
        value for value in values if value and value not in _UNSAFE_BOTANICAL_PATO_IDS
    ))
    if len(values) >= 2 and re.search(r"\bor\b", fold(assertion.get("source_text", ""))):
        operator = "one_of"
    if attribute_id and attribute_id not in pato_lex.id_to_label:
        attribute_id = ""
    return operator, tuple(values), attribute_id, tuple(sorted(provenance)), relevant


def _mk(
    assertion: dict,
    po: str,
    pato: str,
    organ: str,
    pato_lex,
    guide: TerminologyIndex | None = None,
    mentions=(),
    normalization_status: str = "auto",
    mapping_provenance: tuple[str, ...] = (),
) -> Assertion:
    operator, value_ids, attribute_id, value_provenance, relevant = _value_logic(
        assertion, guide, mentions, pato_lex
    )
    if attribute_id:
        pato = attribute_id
    entity_mention = next(
        (
            mention.mention_id
            for mention in relevant
            if "entity" in mention.semantic_roles
            and any(candidate.target_id == po for candidate in mention.candidates)
        ),
        "",
    )
    quality_mentions = tuple(
        mention.mention_id
        for mention in relevant
        if {"quality", "value"}.intersection(mention.semantic_roles)
    )
    return Assertion(
        po_id=po,
        pato_id=pato,
        negated=bool(assertion.get("negated", False)),
        negation_scope=assertion.get("negation_scope", "") or "",
        organ=organ,
        source_text=assertion.get("source_text", ""),
        source_start=assertion.get("source_start"),
        source_end=assertion.get("source_end"),
        bearer_start=assertion.get("bearer_start"),
        bearer_end=assertion.get("bearer_end"),
        modality_start=assertion.get("modality_start"),
        modality_end=assertion.get("modality_end"),
        value_low=assertion.get("value_low"),
        value_high=assertion.get("value_high"),
        value_low_inclusive=assertion.get("value_low_inclusive", True),
        value_high_inclusive=assertion.get("value_high_inclusive", True),
        unit=assertion.get("unit", "") or "",
        value_text=assertion.get("value_text", "") or "",
        trait=assertion.get("trait", "") or assertion.get("trait_id", "") or "",
        modifier=assertion.get("modifier", "") or "",
        source_statement_id=assertion.get("source_statement_id", "") or "",
        frequency_qualifier=assertion.get("frequency_qualifier", "unspecified") or "unspecified",
        epistemic_modality=assertion.get("epistemic_modality", "asserted") or "asserted",
        value_qualifier=assertion.get("value_qualifier", "exact") or "exact",
        degree_qualifier=assertion.get("degree_qualifier", "unmodified") or "unmodified",
        modality_text=assertion.get("modality_text", "") or "",
        season_contexts=tuple(assertion.get("season_contexts", []) or []),
        season_operator=assertion.get("season_operator", "atomic") or "atomic",
        cardinality=str(assertion.get("cardinality", "") or ""),
        confidence=assertion.get("confidence"),
        raw_entity_text=assertion.get("entity_text", "") or assertion.get("entity_label", ""),
        raw_quality_text=assertion.get("quality_text", "") or assertion.get("quality_label", ""),
        entity_mention_id=entity_mention,
        quality_mention_ids=quality_mentions,
        value_operator=operator,
        value_term_ids=value_ids,
        bearer_context_qualities=tuple(assertion.get("bearer_context_qualities", []) or []),
        developmental_stage_contexts=tuple(
            assertion.get("developmental_stage_contexts", []) or []
        ),
        developmental_stage_operator=(
            assertion.get("developmental_stage_operator", "atomic") or "atomic"
        ),
        normalization_status="compositional" if operator != "atomic" else normalization_status,
        mapping_provenance=tuple(sorted(set(mapping_provenance) | set(value_provenance))),
    )


def _ground_assertion(
    assertion: dict,
    po_lex,
    pato_lex,
    organ: str,
    guide: TerminologyIndex | None = None,
    mentions=(),
) -> Assertion | None:
    po, po_status, po_provenance = _resolve(
        assertion.get("entity_label", ""),
        assertion.get("entity_text", ""),
        "PO",
        "entity",
        po_lex,
        guide,
        organ,
    )
    pato, pato_status, pato_provenance = _resolve(
        assertion.get("quality_label", ""),
        assertion.get("quality_text", ""),
        "PATO",
        "quality",
        pato_lex,
        guide,
        organ,
    )
    _, _, attribute_id, _, _ = _value_logic(assertion, guide, mentions, pato_lex)
    pato = attribute_id or pato
    if not po or not pato:
        return None
    statuses = (po_status, pato_status)
    if all(status in {"reviewed", "accepted"} for status in statuses):
        status = "reviewed"
    elif all(status in {"reviewed", "accepted", "auto"} for status in statuses):
        status = "auto"
    else:
        status = "retrieved"
    return _mk(
        assertion,
        po,
        pato,
        organ,
        pato_lex,
        guide,
        mentions,
        normalization_status=status,
        mapping_provenance=tuple(sorted(set(po_provenance) | set(pato_provenance))),
    )


def _graphrag_ground(client, model, assertion, po_lex, pato_lex, organ, guide=None, mentions=()):
    po_cands = po_lex.candidates(assertion.get("entity_label", ""))
    pato_cands = pato_lex.candidates(assertion.get("quality_label", ""))
    if not po_cands or not pato_cands:
        return _ground_assertion(assertion, po_lex, pato_lex, organ, guide, mentions)
    phrase = assertion.get("source_text") or (
        f"{assertion.get('entity_label')} {assertion.get('quality_label')}"
    )

    def pick(kind, candidates):
        listing = "\n".join(f"{curie} : {label}" for curie, label in candidates)
        result = client.chat_json(
            model,
            "Return STRICT JSON only.",
            PICK_TMPL.format(phrase=phrase, kind=kind, cands=listing),
        )
        return (result or {}).get("id") or (candidates[0][0] if candidates else None)

    po = pick("anatomical entity (PO)", po_cands)
    pato = pick("quality (PATO)", pato_cands)
    safe_pato, _, _ = _resolve(
        assertion.get("quality_label", ""),
        assertion.get("quality_text", ""),
        "PATO",
        "quality",
        pato_lex,
        None,
        organ,
    )
    override_keys = {
        fold(value)
        for value in (assertion.get("quality_label", ""), assertion.get("quality_text", ""))
        if value and fold(value) in (pato_lex.label_overrides or {})
    }
    if override_keys:
        if not safe_pato:
            return None
        pato = safe_pato
    if po in po_lex.id_to_label and pato in pato_lex.id_to_label:
        return _mk(
            assertion,
            po,
            pato,
            organ,
            pato_lex,
            guide,
            mentions,
            normalization_status="retrieved",
            mapping_provenance=("llm_constrained_candidate_pick",),
        )
    return None


def _extract_once(client, cfg, segment, po_lex, pato_lex, guide=None) -> list[Assertion]:
    text = segment.get("text", "")[:4000]
    measurements = parse_measurements(text, segment.get("language", ""))
    mentions = (
        guide.annotate(
            text,
            language=segment.get("language", ""),
            organ_context=segment.get("organ", ""),
            keep_overlaps=True,
        )
        if guide
        else []
    )
    terminology_context = (
        guide.prompt_context(mentions, limit=cfg.terminology_limit)
        if guide and mentions and cfg.terminology_mode in {"ontology", "full"}
        else "(none found; extraction may still identify novel or compositional terms)"
    )
    user = USER_TMPL.format(
        taxon=segment.get("taxon", ""),
        organ=segment.get("organ", ""),
        language=segment.get("language", ""),
        text=text,
        terminology_context=terminology_context,
        measurement_context=_measurement_context(measurements),
    )
    result = client.chat_json_tiered(cfg.models, SYSTEM, user, temperature=cfg.temperature)
    out: list[Assertion] = []
    for assertion in (result or {}).get("assertions", []) or []:
        if cfg.grounding == "graphrag":
            grounded = _graphrag_ground(
                client,
                cfg.models[0],
                assertion,
                po_lex,
                pato_lex,
                segment.get("organ", ""),
                guide,
                mentions,
            )
        else:
            grounded = _ground_assertion(
                assertion,
                po_lex,
                pato_lex,
                segment.get("organ", ""),
                guide,
                mentions,
            )
        if grounded:
            grounded = _repair_measurement(grounded, measurements)
            source = grounded.source_text
            starts = [match.start() for match in re.finditer(re.escape(source), text)] if source else []
            if len(starts) == 1:
                grounded = replace(
                    grounded,
                    source_start=starts[0],
                    source_end=starts[0] + len(source),
                    extractor="openrouter",
                )
            else:
                grounded = replace(grounded, extractor="openrouter")
            out.append(grounded)
    return out


def extract_segment(client: OpenRouterClient, cfg: EngineConfig, segment: dict) -> list[Assertion]:
    """Extract grounded assertions with optional N-run majority self-consistency."""
    po_lex, pato_lex = load_lexicons()
    mode = cfg.terminology_mode if cfg.use_terminology else "off"
    if mode not in {"off", "ontology", "registry", "full"}:
        raise ValueError(f"unknown terminology mode: {mode}")
    guide = (
        load_ontology_index()
        if mode == "ontology"
        else load_terminology_index(cfg.terminology_registry)
        if mode in {"registry", "full"}
        else None
    )
    if cfg.samples <= 1:
        return _extract_once(client, cfg, segment, po_lex, pato_lex, guide)

    votes: Counter[tuple] = Counter()
    representative: dict[tuple, Assertion] = {}
    for _ in range(cfg.samples):
        for assertion in _extract_once(client, cfg, segment, po_lex, pato_lex, guide):
            key = assertion_vote_key(assertion)
            votes[key] += 1
            representative.setdefault(key, assertion)
    threshold = cfg.samples / 2
    return [representative[key] for key, count in votes.items() if count >= threshold]
