"""Trait extraction engine (Phase 5): segment text -> grounded EQ assertions.

The LLM extracts entity-quality assertions as English labels (translating French in context),
which are then grounded to PO/PATO ids. Two grounding strategies are supported so the pilot can
A/B them (the user's hybrid choice):

* ``"spires"`` — deterministic lexicon grounding of the emitted labels (baseline).
* ``"graphrag"`` — for each emitted label, retrieve top-k lexicon candidates and let the model
  pick the id from that constrained list in a second pass (combined recognition+normalization).

Self-consistency: run the extraction N times and keep assertions agreed by a majority, which both
suppresses the ~16.7% rerun flip-rate and yields a confidence signal. Output assertions are
``flopo2.eval.scoring.Assertion`` so they score directly against the silver/gold standard.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from flopo2.eval.scoring import Assertion
from flopo2.extract.ground import load_lexicons
from flopo2.extract.router import OpenRouterClient

SYSTEM = (
    "You are an expert botanist extracting plant phenotype traits from flora descriptions for the "
    "Flora Phenotype Ontology. Extract every entity-quality assertion: an anatomical structure and "
    "a quality/attribute asserted of it. Translate non-English text to English anatomical/quality "
    "terms. Return STRICT JSON only."
)

USER_TMPL = """Taxon: {taxon}
Organ hint: {organ}
Language: {language}
Description: "{text}"

Extract all entity-quality trait assertions. Return JSON:
{{"assertions": [
  {{"entity_label": "<English anatomical structure, e.g. leaf, petal, stem>",
    "quality_label": "<English quality/attribute, e.g. red, ovate, glabrous, length>",
    "negated": <true if the quality is asserted ABSENT>,
    "value_low": <number or null>, "value_high": <number or null>, "unit": "<e.g. cm, mm or empty>",
    "value_text": "<categorical state or empty>",
    "source_text": "<exact verbatim substring of the description justifying this>"}}
]}}
Only include assertions supported by the text. Copy source_text verbatim."""

PICK_TMPL = """Source phrase: "{phrase}"
Candidate {kind} terms (id : label):
{cands}
Pick the single best-matching id for the {kind} in the source phrase. Return JSON {{"id": "<id or empty>"}}."""


@dataclass
class EngineConfig:
    models: list[str]            # tiered model list (workhorse first, escalation after)
    grounding: str = "spires"    # "spires" | "graphrag"
    samples: int = 1             # self-consistency runs
    temperature: float = 0.3     # >0 so self-consistency samples diverge


def _ground_assertion(a: dict, po_lex, pato_lex, organ: str) -> Assertion | None:
    po = po_lex.ground(a.get("entity_label", ""))
    pato = pato_lex.ground(a.get("quality_label", ""))
    if not po or not pato:
        return None
    return _mk(a, po, pato, organ)


def _mk(a: dict, po: str, pato: str, organ: str) -> Assertion:
    return Assertion(
        po_id=po, pato_id=pato,
        negated=bool(a.get("negated", False)),
        organ=organ,
        source_text=a.get("source_text", ""),
        value_low=a.get("value_low"), value_high=a.get("value_high"),
        unit=a.get("unit", "") or "", value_text=a.get("value_text", "") or "",
    )


def _graphrag_ground(client, model, a, po_lex, pato_lex, organ):
    po_cands = po_lex.candidates(a.get("entity_label", ""))
    pato_cands = pato_lex.candidates(a.get("quality_label", ""))
    if not po_cands or not pato_cands:
        return _ground_assertion(a, po_lex, pato_lex, organ)  # fall back to deterministic
    phrase = a.get("source_text") or f"{a.get('entity_label')} {a.get('quality_label')}"

    def pick(kind, cands):
        listing = "\n".join(f"{cid} : {lbl}" for cid, lbl in cands)
        r = client.chat_json(model, "Return STRICT JSON only.",
                             PICK_TMPL.format(phrase=phrase, kind=kind, cands=listing))
        return (r or {}).get("id") or (cands[0][0] if cands else None)

    po = pick("anatomical entity (PO)", po_cands)
    pato = pick("quality (PATO)", pato_cands)
    if po in po_lex.id_to_label and pato in pato_lex.id_to_label:
        return _mk(a, po, pato, organ)
    return None


def _extract_once(client, cfg, seg, po_lex, pato_lex) -> list[Assertion]:
    user = USER_TMPL.format(
        taxon=seg.get("taxon", ""), organ=seg.get("organ", ""),
        language=seg.get("language", ""), text=seg.get("text", "")[:4000],
    )
    result = client.chat_json_tiered(cfg.models, SYSTEM, user, temperature=cfg.temperature)
    out: list[Assertion] = []
    for a in (result or {}).get("assertions", []) or []:
        if cfg.grounding == "graphrag":
            g = _graphrag_ground(client, cfg.models[0], a, po_lex, pato_lex, seg.get("organ", ""))
        else:
            g = _ground_assertion(a, po_lex, pato_lex, seg.get("organ", ""))
        if g:
            out.append(g)
    return out


def extract_segment(client: OpenRouterClient, cfg: EngineConfig, seg: dict) -> list[Assertion]:
    """Extract grounded assertions for one segment, with N-sample self-consistency voting."""
    po_lex, pato_lex = load_lexicons()
    if cfg.samples <= 1:
        return _extract_once(client, cfg, seg, po_lex, pato_lex)

    votes: Counter[tuple] = Counter()
    rep: dict[tuple, Assertion] = {}
    for _ in range(cfg.samples):
        for a in _extract_once(client, cfg, seg, po_lex, pato_lex):
            k = (a.po_id, a.pato_id, a.negated)
            votes[k] += 1
            rep.setdefault(k, a)
    threshold = cfg.samples / 2  # majority
    return [rep[k] for k, v in votes.items() if v >= threshold]
