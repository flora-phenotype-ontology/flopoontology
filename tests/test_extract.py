"""Offline tests for Phase 5 extraction (router parsing, grounding, engine with a stub client)."""

from __future__ import annotations

import pytest

from flopo2.extract.router import Usage, parse_json


def test_parse_json_variants():
    assert parse_json('{"a": 1}') == {"a": 1}
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure!\n{"assertions": []}\ndone') == {"assertions": []}
    assert parse_json("not json") is None
    assert parse_json("") is None


def test_usage_cost_accounting():
    u = Usage()
    u.add("openai/gpt-oss-120b", 1_000_000, 1_000_000)  # $0.03 + $0.15
    assert round(u.cost_usd, 4) == 0.18
    assert u.calls == 1


def test_lexicon_grounding(tmp_path):
    from flopo2.extract.ground import Lexicon

    lex = tmp_path / "po.tsv"
    lex.write_text(
        "id\tlabel\tsynonyms\tnamespace\n"
        "PO_0009046\tflower\tbloom\tplant_anatomy\n"
        "PO_0009025\tleaf\tleaves|foliage leaf\tplant_anatomy\n"
    )
    L = Lexicon.load(lex)
    assert L.ground("flower") == "PO_0009046"
    assert L.ground("Flower") == "PO_0009046"          # case-insensitive
    assert L.ground("bloom") == "PO_0009046"            # synonym
    assert L.ground("leaves") == "PO_0009025"           # synonym
    assert L.ground("leafs") == "PO_0009025"            # plural/fuzzy fallback
    assert L.ground("xyzzy") is None
    cands = L.candidates("flowr")
    assert any(cid == "PO_0009046" for cid, _ in cands)


class StubClient:
    """Stub OpenRouterClient returning a canned extraction for any call."""

    def __init__(self, assertions):
        self._a = assertions
        self.usage = Usage()

    def chat_json_tiered(self, models, system, user, temperature=0.0, ok=None):
        return {"assertions": self._a}

    def chat_json(self, *a, **k):
        return {"id": ""}


def test_extract_segment_grounds(monkeypatch, tmp_path):
    from flopo2.extract import engine
    from flopo2.extract.ground import Lexicon

    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\tnamespace\nPO_0009046\tflower\t\tplant_anatomy\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\tsynonyms\tslim\nPATO_0000322\tred\t\t\n")
    # Point the cached loader at our tiny lexicons.
    engine.load_lexicons.cache_clear()
    monkeypatch.setattr(engine, "load_lexicons",
                        lambda *a, **k: (Lexicon.load(po), Lexicon.load(pato)))

    client = StubClient([
        {"entity_label": "flower", "quality_label": "red", "negated": False,
         "source_text": "flowers red"},
        {"entity_label": "unknownpart", "quality_label": "red", "source_text": "x"},  # ungroundable -> dropped
    ])
    cfg = engine.EngineConfig(models=["m"], grounding="spires", samples=1)
    out = engine.extract_segment(client, cfg, {"taxon": "T", "organ": "flower",
                                               "language": "en", "text": "flowers red"})
    assert len(out) == 1
    assert out[0].po_id == "PO_0009046" and out[0].pato_id == "PATO_0000322"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
