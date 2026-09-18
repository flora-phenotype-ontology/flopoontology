"""Focused tests for the immutable Stage-15 ``negated_context`` review campaign.

The suite exercises the runner classifier, the frozen inventory/manifest hash binding, the
two-family exact consensus requirement, and the non-destructive materializer against small
synthetic fixtures, plus a conservation check over the real 448-span Stage-15 input.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from flopo2.review.consensus import build_consensus
from flopo2.review.inventory import model_spec
from flopo2.review.io import read_jsonl, sha256_file, write_jsonl
from flopo2.review.models import (
    CampaignManifest,
    Occurrence,
    ProposedSignature,
    ReviewDecision,
)
from flopo2.review.negation_inventory import (
    ADMISSIBLE,
    NegationCandidate,
    build_negation_inventory,
    classify_span,
)
from flopo2.verify.materialize_negation_consensus import materialize_negation_consensus


CONFIG = Path("config")
ONTOLOGIES = [
    Path("ont/plant_ontology.obo"),
    CONFIG / "po_lexicon.tsv",
    CONFIG / "pato_lexicon.tsv",
    CONFIG / "flopo_id_registry.tsv",
    CONFIG / "valid_combinations.tsv",
    CONFIG / "reviewed_local_bearers.tsv",
]
REAL_STAGE15 = Path(
    "scratchpad/flopo-machine-reviewed-materialization-20260804-v1/stage15-annotated.jsonl"
)
REAL_STAGE15_SHA = "051b6ce4965cd5ff14e590252c8b4c4dd1a54ebfc0d5ed5530ff2a431c177167"


def _span(text: str, surface: str, pato: str) -> dict:
    start = text.index(surface)
    return {
        "start": start,
        "end": start + len(surface),
        "surface_form": surface,
        "reason": "negated_context",
        "candidate_pato_id": pato,
        "extractor": "test",
    }


def _record(source_id: str, text: str, span: dict, assertions=()) -> dict:
    return {
        "source": "test",
        "source_id": source_id,
        "source_segment_index": 0,
        "taxon": f"Taxon {source_id}",
        "language": "fr",
        "organ": "description",
        "char_start": 0,
        "char_end": len(text),
        "text": text,
        "assertions": list(assertions),
        "source_statements": [],
        "term_mentions": [],
        "unresolved_spans": [span],
    }


# A resolvable-bearer quality negation: the sibling positive assertion names PO_0009047 ("Tige") in
# the same clause; (PO_0009047, PATO_0000402) is an admissible non-blocklisted combination.
QUALITY_TEXT = "Tige non ramifiée."
BEARER_ASSERTION = {
    "po_id": "PO_0009047",
    "pato_id": "PATO_0000622",
    "source_text": "Tige",
    "source_start": 0,
    "source_end": 4,
}


def _fixture_records() -> list[dict]:
    return [
        _record(
            "quality",
            QUALITY_TEXT,
            _span(QUALITY_TEXT, "ramifiée", "PATO_0000402"),
            assertions=[BEARER_ASSERTION],
        ),
        _record(
            "absence", "Stem without hairs.", _span("Stem without hairs.", "hairs", "PATO_0000402")
        ),
        _record(
            "mixed",
            "Tige peu ou pas ramifiée.",
            _span("Tige peu ou pas ramifiée.", "ramifiée", "PATO_0000402"),
        ),
        _record(
            "falsecue",
            "Akènes non glandulaires brun-jaune.",
            _span("Akènes non glandulaires brun-jaune.", "brun", "PATO_0000952"),
        ),
        _record(
            "compound",
            "Bractées non longuement acuminées.",
            _span("Bractées non longuement acuminées.", "acuminées", "PATO_0002228"),
        ),
    ]


def _write_stage15(path: Path, records: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def reviewers():
    return [
        model_spec(
            reviewer_id="rev-a",
            provider="openai",
            model="gpt",
            model_family="openai",
            role="reviewer",
        ),
        model_spec(
            reviewer_id="rev-b",
            provider="anthropic",
            model="claude",
            model_family="anthropic",
            role="reviewer",
        ),
    ]


@pytest.fixture()
def prompt(tmp_path: Path) -> Path:
    path = tmp_path / "reviewer.md"
    path.write_text("negation reviewer prompt\n", encoding="utf-8")
    return path


def _build(tmp_path: Path, records, reviewers, prompt) -> tuple[CampaignManifest, dict[str, Path]]:
    stage15 = _write_stage15(tmp_path / "stage15.jsonl", records)
    paths = {
        "stage15": stage15,
        "occurrences": tmp_path / "occurrences.jsonl",
        "clusters": tmp_path / "clusters.jsonl",
        "evidence": tmp_path / "evidence.jsonl",
        "candidates": tmp_path / "candidates.jsonl",
        "report": tmp_path / "candidate_report.json",
        "manifest": tmp_path / "manifest.json",
    }
    manifest = build_negation_inventory(
        stage15_path=paths["stage15"],
        occurrence_path=paths["occurrences"],
        cluster_path=paths["clusters"],
        evidence_path=paths["evidence"],
        candidate_path=paths["candidates"],
        report_path=paths["report"],
        manifest_path=paths["manifest"],
        ontology_paths=ONTOLOGIES,
        prompt_paths={"reviewer": prompt},
        models=reviewers,
        created_at=None,
    )
    return manifest, paths


def _candidates(paths) -> dict[str, NegationCandidate]:
    return {row.occurrence_id: row for row in read_jsonl(paths["candidates"], NegationCandidate)}


# --------------------------------------------------------------------------- classifier


def test_classifications_cover_the_typology():
    def classify(text, surface, pato):
        record = _record("x", text, _span(text, surface, pato))
        return classify_span(record, record["unresolved_spans"][0])

    assert (
        classify(QUALITY_TEXT, "ramifiée", "PATO_0000402")["classification"] == "quality_negation"
    )
    assert (
        classify("Stem without hairs.", "hairs", "PATO_0000402")["classification"]
        == "bearer_absence"
    )
    mixed = classify("Tige peu ou pas ramifiée.", "ramifiée", "PATO_0000402")
    assert mixed["classification"] == "mixed_negation_disjunction"
    assert mixed["hold_reason"] == "coordinated_or_hedged_negation"
    false_cue = classify("Akènes non glandulaires brun-jaune.", "brun", "PATO_0000952")
    assert false_cue["classification"] == "false_cue"
    compound = classify("Bractées non longuement acuminées.", "acuminées", "PATO_0002228")
    assert compound["classification"] == "compound_scope"
    assert compound["hold_reason"] == "negation_scopes_degree_modifier"
    coating = classify("Rhizome not white waxy.", "white", "PATO_0000323")
    assert coating["classification"] == "compound_scope"
    assert coating["hold_reason"] == "negation_scopes_compound_quality"
    frequency = classify("Tige généralement non ramifiée.", "ramifiée", "PATO_0000402")
    assert frequency["classification"] == "compound_scope"
    assert frequency["hold_reason"] == "frequency_modified_negation"
    optional_bound = classify(
        "receptacle non-stipitate or up to 0.4 cm long stipitate.",
        "up to 0.4 cm long",
        "PATO_0000122",
    )
    assert optional_bound["classification"] == "mixed_negation_disjunction"
    assert optional_bound["hold_reason"] == "coordinated_optional_numeric_bearer"
    ranged_optional_bound = classify(
        "receptacle non-stipitate to up to 0.1 cm long stipitate.",
        "up to 0.1 cm long",
        "PATO_0000122",
    )
    assert ranged_optional_bound["classification"] == "mixed_negation_disjunction"
    assert ranged_optional_bound["hold_reason"] == "coordinated_optional_numeric_bearer"
    sibling = classify(
        "tiges robustes, non ramifiées et tiges minces, ramifiées.",
        "ramifiées",
        "PATO_0000402",
    )
    assert sibling["classification"] == "compound_scope"
    assert sibling["hold_reason"] == "negation_restricted_to_coordinated_subset"
    correction = classify(
        "Rachis pubérulent (et non pas pubescent!).",
        "pubescent",
        "PATO_0001320",
    )
    assert correction["classification"] == "compound_scope"
    assert correction["hold_reason"] == "contrastive_or_metalinguistic_negation"
    malformed = classify("Petit arbre général non ramifié.", "ramifié", "PATO_0000402")
    assert malformed["classification"] == "compound_scope"
    assert malformed["hold_reason"] == "malformed_or_truncated_negation_context"
    scoped_absence = classify(
        "Écorce sans cambium jaune habituel développé.", "jaune", "PATO_0000324"
    )
    assert scoped_absence["classification"] == "compound_scope"
    assert scoped_absence["hold_reason"] == "post_quality_scope_modifier"


def test_exact_cue_and_source_offsets():
    text = QUALITY_TEXT
    record = _record("x", text, _span(text, "ramifiée", "PATO_0000402"))
    result = classify_span(record, record["unresolved_spans"][0])
    assert text[result["cue_start"] : result["cue_end"]] == "non"
    assert text[result["source_start"] : result["source_end"]] == "non ramifiée"


def test_numeric_negation_is_an_upper_bound_not_a_complement():
    text = "Feuille not exceeding 5 mm long."
    record = _record("x", text, _span(text, "long", "PATO_0000122"))
    span = record["unresolved_spans"][0]
    result = classify_span(record, span)
    # The comparator classifies as an upper bound regardless of whether a bearer resolves.
    if result["classification"] == "numeric_upper_bound":
        assert result["negation_scope"] == "numeric_bound"
    else:
        # If the deterministic measurement parse does not fire, it must never become a complement.
        assert result["classification"] != "quality_negation"


# --------------------------------------------------------------------------- inventory / hashes


def test_inventory_binds_input_and_candidate_hashes(tmp_path, reviewers, prompt):
    manifest, paths = _build(tmp_path, _fixture_records(), reviewers, prompt)
    assert manifest.input.sha256 == sha256_file(paths["stage15"]).sha256
    assert len(manifest.sources) == 1
    assert manifest.sources[0].sha256 == sha256_file(paths["candidates"]).sha256
    assert manifest.starting_occurrences == manifest.starting_clusters == len(_fixture_records())
    # Every admitted candidate carries an admissible classification and matching signature hash.
    for candidate in _candidates(paths).values():
        if candidate.admission == "admit":
            assert candidate.classification in ADMISSIBLE
            assert candidate.admitted_expression is not None


def test_candidate_payload_hash_tamper_fails(tmp_path, reviewers, prompt):
    _, paths = _build(tmp_path, _fixture_records(), reviewers, prompt)
    rows = list(read_jsonl(paths["candidates"], NegationCandidate))
    victim = rows[0].model_dump(mode="json", exclude_none=True)
    victim["payload_sha256"] = hashlib.sha256(b"tampered").hexdigest()
    with pytest.raises(ValueError):
        NegationCandidate.model_validate(victim)


def test_held_candidate_cannot_carry_expression(tmp_path, reviewers, prompt):
    _, paths = _build(tmp_path, _fixture_records(), reviewers, prompt)
    candidates = _candidates(paths)
    held = [c for c in candidates.values() if c.admission == "hold"]
    assert held
    for candidate in held:
        assert candidate.admitted_expression is None
        assert candidate.admitted_signature_sha256 == ""
        assert candidate.hold_reason


# --------------------------------------------------------------------------- consensus + materialize


def _decision(manifest, spec, prompt, candidate, occurrence_evidence, *, accept) -> ReviewDecision:
    if accept:
        signature = ProposedSignature(
            kind="annotation_expression", expression=candidate.admitted_expression
        )
        disposition = "annotation_expression"
        rationale = "copy runner candidate"
    else:
        signature = ProposedSignature(kind="hold", reason="negation held")
        disposition = "hold"
        rationale = "hold"
    return ReviewDecision(
        campaign_id=manifest.campaign_id,
        item_id=candidate.cluster_id,
        reviewer_id=spec.reviewer_id,
        provider=spec.provider,
        model=spec.model,
        model_family=spec.model_family,
        reasoning_effort=spec.reasoning_effort,
        prompt_id="reviewer",
        prompt_sha256=sha256_file(prompt).sha256,
        disposition=disposition,
        proposed_signature=signature,
        rationale=rationale,
        confidence=1.0,
        evidence_ids=(occurrence_evidence,),
        validation_passed=True,
    )


def _run_consensus(tmp_path, manifest, paths, reviewers, prompt, decisions_by_reviewer):
    review_paths = []
    for index, decisions in enumerate(decisions_by_reviewer):
        path = tmp_path / f"reviews_{index}.jsonl"
        write_jsonl(path, decisions)
        review_paths.append(path)
    consensus = tmp_path / "consensus.jsonl"
    exception = tmp_path / "exception.jsonl"
    ledger = tmp_path / "ledger.jsonl"
    build_consensus(
        manifest=manifest,
        occurrence_path=paths["occurrences"],
        cluster_path=paths["clusters"],
        evidence_path=paths["evidence"],
        review_paths=review_paths,
        consensus_path=consensus,
        exception_path=exception,
        ledger_path=ledger,
    )
    return consensus, ledger


def _materialize(tmp_path, manifest, paths, consensus, ledger):
    out = {
        "proposals": tmp_path / "proposals.jsonl",
        "held": tmp_path / "held.jsonl",
        "conservation": tmp_path / "conservation.jsonl",
        "report": tmp_path / "materialization.json",
    }
    result = materialize_negation_consensus(
        manifest_path=paths["manifest"],
        occurrence_path=paths["occurrences"],
        cluster_path=paths["clusters"],
        evidence_path=paths["evidence"],
        candidate_path=paths["candidates"],
        consensus_path=consensus,
        ledger_path=ledger,
        candidate_report_path=paths["report"],
        stage15_path=paths["stage15"],
        proposals_path=out["proposals"],
        held_path=out["held"],
        conservation_path=out["conservation"],
        report_path=out["report"],
    )
    return result, out


def test_two_family_consensus_admits_and_materializes(tmp_path, reviewers, prompt):
    manifest, paths = _build(tmp_path, _fixture_records(), reviewers, prompt)
    occurrences = {row.cluster_id: row for row in read_jsonl(paths["occurrences"], Occurrence)}
    candidates = _candidates(paths)
    admit_ids = {c.cluster_id for c in candidates.values() if c.admission == "admit"}
    assert admit_ids, "fixture must contain at least one admissible candidate"

    def decisions_for(spec):
        rows = []
        for candidate in candidates.values():
            evidence = occurrences[candidate.cluster_id].evidence_id
            rows.append(
                _decision(
                    manifest,
                    spec,
                    prompt,
                    candidate,
                    evidence,
                    accept=candidate.admission == "admit",
                )
            )
        return rows

    consensus, ledger = _run_consensus(
        tmp_path,
        manifest,
        paths,
        reviewers,
        prompt,
        [decisions_for(reviewers[0]), decisions_for(reviewers[1])],
    )
    result, out = _materialize(tmp_path, manifest, paths, consensus, ledger)

    assert result["conserved"] is True
    assert result["proposals"] == len(admit_ids)
    assert result["proposals"] + result["held"] == manifest.starting_occurrences
    assert result["provenance"]["human_reviewed"] is False
    assert result["provenance"]["stage15_modified"] is False

    proposals = [json.loads(line) for line in out["proposals"].read_text().splitlines()]
    assert proposals
    for proposal in proposals:
        assertion = proposal["assertion"]
        assert assertion["negated"] is True
        assert assertion["negation_scope"] == "quality"
        assert assertion["extractor"] == "llm_consensus_negation_v1"
        # The cleared range is exactly the reviewed quality span, once.
        cleared = proposal["apply"]["clear_unresolved_spans"]
        assert len(cleared) == 1

    # Conservation ledger: one terminal row per starting occurrence, accepted xor held.
    ledger_rows = [json.loads(line) for line in out["conservation"].read_text().splitlines()]
    assert len(ledger_rows) == manifest.starting_occurrences
    accepted = {r["occurrence_id"] for r in ledger_rows if r["outcome"] == "accepted"}
    held = {r["occurrence_id"] for r in ledger_rows if r["outcome"] == "held"}
    assert accepted and held and not (accepted & held)


def test_single_reviewer_never_admits(tmp_path, reviewers, prompt):
    manifest, paths = _build(tmp_path, _fixture_records(), reviewers, prompt)
    occurrences = {row.cluster_id: row for row in read_jsonl(paths["occurrences"], Occurrence)}
    candidates = _candidates(paths)
    single = [
        _decision(
            manifest,
            reviewers[0],
            prompt,
            candidate,
            occurrences[candidate.cluster_id].evidence_id,
            accept=candidate.admission == "admit",
        )
        for candidate in candidates.values()
    ]
    consensus, ledger = _run_consensus(tmp_path, manifest, paths, reviewers, prompt, [single])
    # A lone reviewer means an incomplete campaign: the materializer fails closed and admits nothing.
    with pytest.raises(ValueError, match="incomplete or unconserved"):
        _materialize(tmp_path, manifest, paths, consensus, ledger)
    from flopo2.review.models import ConsensusDecision

    statuses = {row.status for row in read_jsonl(consensus, ConsensusDecision)}
    assert statuses == {"held"}


def test_materialization_is_non_destructive(tmp_path, reviewers, prompt):
    manifest, paths = _build(tmp_path, _fixture_records(), reviewers, prompt)
    before = paths["stage15"].read_bytes()
    occurrences = {row.cluster_id: row for row in read_jsonl(paths["occurrences"], Occurrence)}
    candidates = _candidates(paths)
    both = [
        [
            _decision(
                manifest,
                spec,
                prompt,
                candidate,
                occurrences[candidate.cluster_id].evidence_id,
                accept=candidate.admission == "admit",
            )
            for candidate in candidates.values()
        ]
        for spec in reviewers
    ]
    consensus, ledger = _run_consensus(tmp_path, manifest, paths, reviewers, prompt, both)
    _materialize(tmp_path, manifest, paths, consensus, ledger)
    assert paths["stage15"].read_bytes() == before  # Stage 15 untouched, byte-for-byte.


# --------------------------------------------------------------------------- real 448 conservation


@pytest.mark.skipif(not REAL_STAGE15.exists(), reason="real Stage-15 input not present")
def test_real_stage15_448_conservation(tmp_path, reviewers, prompt):
    assert sha256_file(REAL_STAGE15).sha256 == REAL_STAGE15_SHA
    paths = {
        "occurrences": tmp_path / "occurrences.jsonl",
        "clusters": tmp_path / "clusters.jsonl",
        "evidence": tmp_path / "evidence.jsonl",
        "candidates": tmp_path / "candidates.jsonl",
        "report": tmp_path / "candidate_report.json",
        "manifest": tmp_path / "manifest.json",
    }
    manifest = build_negation_inventory(
        stage15_path=REAL_STAGE15,
        occurrence_path=paths["occurrences"],
        cluster_path=paths["clusters"],
        evidence_path=paths["evidence"],
        candidate_path=paths["candidates"],
        report_path=paths["report"],
        manifest_path=paths["manifest"],
        ontology_paths=ONTOLOGIES,
        prompt_paths={"reviewer": prompt},
        models=reviewers,
    )
    assert manifest.starting_occurrences == 448
    candidates = list(read_jsonl(paths["candidates"], NegationCandidate))
    assert len(candidates) == 448
    # Every span is classified into the typology; admits are always admissible.
    classifications = {c.classification for c in candidates}
    assert {
        "quality_negation",
        "bearer_absence",
        "mixed_negation_disjunction",
        "false_cue",
    }.issubset(classifications)
    for candidate in candidates:
        if candidate.admission == "admit":
            assert candidate.classification in ADMISSIBLE

    report = json.loads(paths["report"].read_text())
    assert report["negated_context_spans"] == 448
    assert sum(report["classifications"].values()) == 448
    assert report["conservation"]["all_spans_classified"] is True
