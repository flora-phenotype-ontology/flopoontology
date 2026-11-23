"""Passes over existing records: the position of the bearer, and parts of one plant group."""

from __future__ import annotations

from flopo2.verify import apply_bearer_position as position
from flopo2.verify import apply_plant_group as group


def _assertion(text: str, bearer: str, po: str, pato: str = "PATO_0000956") -> dict:
    from flopo2.owl.annotation_class import ensure_annotation_class_iri

    start = text.index(bearer)
    assertion = {"po_id": po, "pato_id": pato, "value_terms": [], "value_operator": "atomic", "negated": False,
                 "source_text": text, "bearer_start": start, "bearer_end": start + len(bearer),
                 "raw_entity_text": bearer, "gate": {"status": "accepted", "reasons": []},
                 "composition": {"entity_label": bearer, "quality_label": "x"}}
    ensure_annotation_class_iri(assertion)
    return assertion


def test_the_position_before_the_bearer_is_recorded():
    words = position.load()
    pattern = position._pattern(words)
    text = "the lateral umbels usually sterile"
    a = _assertion(text, "umbels", "PO_0030129")
    before = a["phenotype_class_iri"]
    assert position.apply(a, text, words, pattern) == "added"
    assert a["bearer_context_qualities"] == [words["lateral"][0]] and a["phenotype_class_iri"] != before
    assert position.apply(a, text, words, pattern) == ""  # idempotent

    text = "Basal leaves spatulate"
    a = _assertion(text, "leaves", "PO_0025034", "PATO_0000052")
    assert position.apply(a, text, words, pattern) == "added"
    assert a["bearer_context_qualities"] == [words["basal"][0]]


def test_a_record_that_is_not_linked_to_a_class_gets_the_position_but_no_class_identifier():
    # "5-7 on each side" is written in the record only; the formal builder refuses a class on it
    words = position.load()
    pattern = position._pattern(words)
    text = "lateral veins 5-7 on each side"
    a = _assertion(text, "veins", "PO_0005020", "PATO_0000070")
    a.pop("phenotype_class_iri")
    a["count_position"] = {"kind": "each_side", "position_text": "on each side"}
    assert position.apply(a, text, words, pattern) == "added"
    assert a["bearer_context_qualities"] == [words["lateral"][0]] and "phenotype_class_iri" not in a


def test_a_position_without_a_class_or_two_positions_go_to_review():
    words = position.load()
    pattern = position._pattern(words)
    for text in ("the axillary umbels mostly sterile", "the terminal and uppermost umbels mostly small and sterile"):
        a = _assertion(text, "umbels", "PO_0030129")
        before = a["phenotype_class_iri"]
        assert position.apply(a, text, words, pattern) == "review"
        assert a["gate"] == {"status": "review", "reasons": [position.REASON]} and a["phenotype_class_iri"] == before
        assert position.apply(a, text, words, pattern) == ""
    text = "umbels sterile"
    assert position.apply(_assertion(text, "umbels", "PO_0030129"), text, words, pattern) == ""


def test_a_grass_part_in_another_family_goes_to_review():
    guard = group.Guard()
    awn = {"po_id": "PO_0025349", "gate": {"status": "accepted", "reasons": []}}
    assert not guard.apply(dict(awn, gate={"status": "accepted", "reasons": []}), "Poaceae")
    assert not guard.apply(dict(awn, gate={"status": "accepted", "reasons": []}), "Cyperaceae")
    assert not guard.apply(dict(awn, gate={"status": "accepted", "reasons": []}), "")
    assert guard.apply(awn, "Asteraceae") and awn["gate"] == {"status": "review", "reasons": [group.REASON]}
    assert not guard.apply(awn, "Asteraceae")  # once
    lemma_awn = {"po_id": "PO_0006032", "gate": {"status": "accepted", "reasons": []}}
    assert guard.apply(lemma_awn, "Geraniaceae")
    leaf = {"po_id": "PO_0025034", "gate": {"status": "accepted", "reasons": []}}
    assert not guard.apply(leaf, "Asteraceae")


def test_grass_spikelet_parts_are_one_browse_group():
    from flopo2.saudi.vocab import Vocabulary

    vocab = Vocabulary()
    assert {vocab.organ_group(t) for t in ("PO:0025349", "PO:0006032", "PO:0009037", "PO:0009039")} == {"spikelet"}
    assert vocab.organ_group("PO:0009046") == "flower"
    assert "shrub habit" in vocab.other_names("FLOPO:0987002")
