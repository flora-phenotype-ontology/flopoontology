"""Descriptions held by two sources: the copy is left out of the atlas."""

from __future__ import annotations

import json

from tools import atlas_duplicates as dup

TEXT = ("Shrubs to 2 m tall, with erect glabrous branches throughout. Leaves alternate, the blade ovate and "
        "entire at the margin. Flowers white, in terminal racemes of ten to twenty. Fruit a capsule, "
        "opening by four valves when ripe.")


def _corpus(path, source, text, classes):
    record = {"source": source, "source_id": f"{source}:1", "taxon": "A b", "text": text,
              "assertions": [{"phenotype_class_iri": c, "gate": {"status": "accepted"}} for c in classes]}
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return path


def test_sentences_ignore_case_and_punctuation():
    assert dup.sentences(TEXT) == dup.sentences(TEXT.upper().replace(",", " ,"))
    assert len(dup.sentences(TEXT)) == 4


def test_the_aggregator_copy_is_left_out_and_agreement_counted(tmp_path, monkeypatch):
    files = {"eflora-foc": _corpus(tmp_path / "a.jsonl", "eflora-foc", TEXT, ["c1", "c2", "c3"]),
             "wfo": _corpus(tmp_path / "b.jsonl", "wfo", TEXT + " Native of China.", ["c1", "c2", "c4"])}
    monkeypatch.setattr(dup, "corpora", lambda: files)
    rows, agreement, worst = dup.find()
    assert [(r["source"], r["primary_source"]) for r in rows] == [("wfo", "eflora-foc")]
    pair = agreement[("wfo", "eflora-foc")]
    assert (pair["accepted_both"], pair["accepted_copy_only"], pair["accepted_primary_only"]) == (2, 1, 1)
    dup.write(rows, agreement, worst, tmp_path)
    copies = dup.load(tmp_path / "duplicates.tsv")
    assert ("wfo", "wfo:1", dup.text_key(TEXT + " Native of China.")) in copies

    from flopo2.saudi.build import Builder

    builder = Builder.__new__(Builder)
    builder.copies, builder._text_key = copies, dup.text_key
    assert builder.is_copy("wfo", {"source_id": "wfo:1", "text": TEXT + " Native of China."})
    assert not builder.is_copy("eflora-foc", {"source_id": "eflora-foc:1", "text": TEXT})
