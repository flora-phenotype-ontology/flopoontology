from flopo2.ingest.ncvc_annotate import apply_rereads

SOURCE_ID = "collenette-saudi:page-001:1"


def _row(entity, quality, source):
    return {"entity_en": entity, "quality_en": quality, "source_en": source, "value_low": None,
            "value_high": None, "unit": "", "qualifiers": {"negated": False, "stage": "", "frequency": "", "alternatives": []}}


def _answer(row, phenotype, rows):
    return {(SOURCE_ID, row): {"source_id": SOURCE_ID, "row": row, "entity": phenotype["entity_en"],
                               "quality": phenotype["quality_en"], "phrase": phenotype["source_en"], "rows": rows}}


def _rec(*phenotypes):
    return {"source_id": SOURCE_ID, "pdf_page": 1,
            "description_en": "A medium tree with bark longitudinally fissured; the tree flowers before the leaves appear. A shrub.",
            "phenotypes": list(phenotypes)}


def test_split_row_replaces_original_and_keeps_indices():
    original = _row("whole plant", "medium tree growth form", "A medium tree")
    rec = _rec(original)
    apply_rereads(rec, _answer(0, original, [
        {"part": "whole plant", "quality": "tree", "kind": "quality", "alternatives": [], "modifier": "", "evidence": "A medium tree"},
        {"part": "whole plant", "quality": "medium-sized", "kind": "quality", "alternatives": [], "modifier": "", "evidence": "not in the text"},
    ]))
    first, tree, medium = rec["phenotypes"]
    assert first["merged_into"] == "llm re-read"
    assert (tree["quality_en"], tree["reread_from"], tree["pato_label"]) == ("tree", 0, "tree")
    assert medium["source_en"] == "A medium tree"  # evidence not verbatim: the original span


def test_process_keeps_row_with_precise_reason():
    original = _row("whole plant", "flowering before leaf emergence", "the tree flowers before the leaves appear")
    rec = _rec(original)
    apply_rereads(rec, _answer(0, original, [
        {"part": "whole plant", "quality": "flowering before leaf emergence", "kind": "process",
         "alternatives": [], "modifier": "", "evidence": "the tree flowers before the leaves appear"},
    ]))
    assert len(rec["phenotypes"]) == 1
    assert rec["phenotypes"][0]["reread_reason"] == "process_or_event"
    assert "merged_into" not in rec["phenotypes"][0]


def test_duplicate_of_another_row_and_stale_answer():
    shrub = _row("whole plant", "shrub", "A shrub")
    odd = _row("whole plant", "a shrub plant", "A shrub")
    rec = _rec(shrub, odd)
    reading = [{"part": "whole plant", "quality": "shrub", "kind": "quality", "alternatives": [], "modifier": "", "evidence": "A shrub"}]
    apply_rereads(rec, _answer(1, odd, reading))
    assert len(rec["phenotypes"]) == 2 and rec["phenotypes"][1]["merged_into"] == "llm re-read"

    # An answer for a row whose transcription changed is ignored.
    rec = _rec(shrub, _row("whole plant", "bush", "A shrub"))
    apply_rereads(rec, _answer(1, odd, reading))
    assert len(rec["phenotypes"]) == 2 and "merged_into" not in rec["phenotypes"][1]


def test_structure_and_alternatives():
    head = _row("inflorescence", "head", "flowers before")
    fissured = _row("bark", "longitudinally fissured", "bark longitudinally fissured")
    rec = _rec(head, fissured)
    answers = _answer(0, head, [{"part": "inflorescence", "quality": "head", "kind": "structure",
                                 "alternatives": [], "modifier": "", "evidence": ""}])
    answers |= _answer(1, fissured, [{"part": "bark", "quality": "fissured", "kind": "alternatives",
                                      "alternatives": ["cracked"], "modifier": "longitudinally", "evidence": "bark longitudinally fissured"}])
    apply_rereads(rec, answers)
    structure, alternatives = rec["phenotypes"][2:]
    assert (structure["entity_en"], structure["quality_en"]) == ("head", "present")
    assert alternatives["qualifiers"]["alternatives"] == ["cracked"]
