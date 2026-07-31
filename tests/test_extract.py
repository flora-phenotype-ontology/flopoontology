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


def test_pato_attenuated_override(tmp_path):
    from flopo2.extract.ground import Lexicon

    lex = tmp_path / "pato.tsv"
    lex.write_text(
        "id\tlabel\tsynonyms\tslim\n"
        "PATO_0001982\tattenuate\t\tvalue_slim\n"
        "PATO_0002147\treduced virulence\tattenuated\tvalue_slim\n"
    )
    L = Lexicon.load(lex, {"attenuated": "PATO_0001982"})
    assert L.ground("attenuated") == "PATO_0001982"
    assert L.ground("reduced virulence") == "PATO_0002147"


def test_botanical_pubescent_override_beats_maturity_homonym(tmp_path):
    from flopo2.extract import engine
    from flopo2.extract.ground import Lexicon
    from flopo2.terminology.model import Candidate

    lex = tmp_path / "pato.tsv"
    lex.write_text(
        "id\tlabel\tsynonyms\tslim\n"
        "PATO_0000455\tpubescent\t\tvalue_slim\n"
        "PATO_0001320\tpubescent hair\t\tvalue_slim\n"
    )
    pato = Lexicon.load(
        lex,
        {
            "pubescent": "PATO_0001320",
            "downy": "PATO_0001320",
        },
    )

    class StaleGuide:
        @staticmethod
        def resolve(*args, **kwargs):
            return [
                Candidate(
                    target_id="PATO_0000455",
                    label="pubescent",
                    namespace="PATO",
                    score=1.0,
                    mapping_relation="skos:exactMatch",
                    review_status="auto",
                )
            ]

    target, status, provenance = engine._resolve(
        "pubescent", "pubescent", "PATO", "quality", pato, StaleGuide(), "leaf"
    )
    assert (target, status) == ("PATO_0001320", "auto")
    assert provenance == ("botanical_grounding_override",)
    assert pato.ground("downy") == "PATO_0001320"


def test_related_palmate_synonym_is_not_exact_grounding(tmp_path):
    from flopo2.extract.ground import Lexicon

    lex = tmp_path / "pato.tsv"
    lex.write_text("id\tlabel\tsynonyms\tslim\nPATO_digitate\tdigitate\tpalmate\tvalue_slim\n")
    assert Lexicon.load(lex, {"palmate": ""}).ground("palmate") is None


def test_lexicon_loader_enforces_all_obo_synonym_scopes(tmp_path):
    from flopo2.extract.ground import load_lexicons

    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\tnamespace\nPO_leaf\tleaf\tfoliage\tplant_anatomy\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tsynonyms\tslim\n"
        "PATO_green\tgreen\tgreenish|verdant\tvalue_slim\n"
        "PATO_greenish\tgreenish\t\tvalue_slim\n"
    )
    po_obo = tmp_path / "po.obo"
    po_obo.write_text(
        "format-version: 1.2\n\n[Term]\nid: PO:leaf\nname: leaf\n"
        'synonym: "foliage" EXACT []\n'
    )
    pato_obo = tmp_path / "pato.obo"
    pato_obo.write_text(
        "format-version: 1.2\n\n"
        "[Term]\nid: PATO:green\nname: green\n"
        'synonym: "greenish" RELATED []\n'
        'synonym: "verdant" RELATED []\n\n'
        "[Term]\nid: PATO:greenish\nname: greenish\n"
    )
    load_lexicons.cache_clear()
    po_lex, pato_lex = load_lexicons(
        str(po), str(pato), str(po_obo), str(pato_obo)
    )
    assert po_lex.ground("foliage") == "PO_leaf"
    assert pato_lex.ground("verdant") is None
    # A non-equivalent synonym must not hide a genuine primary label with the same spelling.
    assert pato_lex.ground("greenish") == "PATO_greenish"
    load_lexicons.cache_clear()


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


def test_extract_segment_preserves_supplied_offsets_for_repeated_source(monkeypatch, tmp_path):
    from flopo2.extract import engine
    from flopo2.extract.ground import Lexicon

    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\tnamespace\n"
        "PO_0009046\tflower\tflowers\tplant_anatomy\n"
    )
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\tsynonyms\tslim\nPATO_0000322\tred\t\t\n")
    monkeypatch.setattr(
        engine,
        "load_lexicons",
        lambda *args, **kwargs: (Lexicon.load(po), Lexicon.load(pato)),
    )
    text = "flowers usually red; flowers usually red"
    source_start = text.rindex("red")
    bearer_start = text.rindex("flowers")
    modality_start = text.rindex("usually")
    client = StubClient(
        [
            {
                "entity_label": "flower",
                "quality_label": "red",
                "entity_text": "flowers",
                "quality_text": "red",
                "source_text": "red",
                "source_start": source_start,
                "source_end": source_start + len("red"),
                "bearer_start": bearer_start,
                "bearer_end": bearer_start + len("flowers"),
                "frequency_qualifier": "usually",
                "modality_text": "usually",
                "modality_start": modality_start,
                "modality_end": modality_start + len("usually"),
            }
        ]
    )

    out = engine.extract_segment(
        client,
        engine.EngineConfig(models=["m"], grounding="spires", samples=1),
        {"taxon": "T", "organ": "flower", "language": "en", "text": text},
    )

    assert len(out) == 1
    assert (
        out[0].source_start,
        out[0].source_end,
        out[0].bearer_start,
        out[0].bearer_end,
        out[0].modality_start,
        out[0].modality_end,
    ) == (
        source_start,
        source_start + len("red"),
        bearer_start,
        bearer_start + len("flowers"),
        modality_start,
        modality_start + len("usually"),
    )


def test_extract_segment_uses_deterministic_measurement_prior_and_repairs_value(
    monkeypatch, tmp_path
):
    from flopo2.extract import engine
    from flopo2.extract.ground import Lexicon

    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\tnamespace\nPO_flower\tflower\tflowers\tplant_anatomy\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\tsynonyms\tslim\nPATO_0000921\twidth\t\tattribute_slim\n")
    monkeypatch.setattr(
        engine,
        "load_lexicons",
        lambda *args, **kwargs: (Lexicon.load(po), Lexicon.load(pato)),
    )

    class CapturingClient(StubClient):
        user_prompt = ""

        def chat_json_tiered(self, models, system, user, temperature=0.0, ok=None):
            self.user_prompt = user
            return {"assertions": self._a}

    client = CapturingClient(
        [
            {
                "entity_label": "flower",
                "quality_label": "width",
                "entity_text": "flowers",
                "quality_text": "wide",
                "source_text": "flowers 1.2 cm wide",
                "value_low": 12,
                "value_high": 12,
                "unit": "mm",
            }
        ]
    )
    out = engine.extract_segment(
        client,
        engine.EngineConfig(models=["m"], terminology_mode="off"),
        {
            "text": "flowers 1.2 cm wide",
            "organ": "description",
            "language": "en",
        },
    )
    assert len(out) == 1
    assert (out[0].value_low, out[0].value_high, out[0].unit) == (1.2, 1.2, "cm")
    assert "deterministic_measurement_parse" in out[0].mapping_provenance
    assert "UO:0000015" in out[0].mapping_provenance
    assert '"1.2 cm wide" -> PATO_0000921 width' in client.user_prompt


def test_extract_segment_preserves_reviewed_disjunction(monkeypatch, tmp_path):
    from flopo2.extract import engine
    from flopo2.extract.ground import Lexicon
    from flopo2.terminology.annotate import TerminologyIndex
    from flopo2.terminology.catalog import OntologyCatalog, OntologyTerm
    from flopo2.terminology.model import RegistryEntry

    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\tnamespace\nPO_flower\tflower\tflowers\tplant_anatomy\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\tsynonyms\tslim\nPATO_color\tcolor\t\tattribute_slim\n")
    po_lex, pato_lex = Lexicon.load(po), Lexicon.load(pato)
    catalog = OntologyCatalog(
        {
            "PO_flower": OntologyTerm("PO_flower", "flower", "PO", ("flowers",)),
            "PATO_color": OntologyTerm("PATO_color", "color", "PATO"),
            "FLOPO_greenish": OntologyTerm("FLOPO_greenish", "greenish", "FLOPO"),
            "FLOPO_pinkish": OntologyTerm("FLOPO_pinkish", "pinkish", "FLOPO"),
            "FLOPO_union": OntologyTerm("FLOPO_union", "greenish or pinkish", "FLOPO"),
        }
    )
    entries = [
        RegistryEntry(
            term_id="union",
            surface_form="greenish or pinkish",
            normalized_form="greenish or pinkish",
            language="en",
            semantic_role="value",
            target_id="FLOPO_union",
            target_label="greenish or pinkish",
            target_namespace="FLOPO",
            mapping_relation="skos:exactMatch",
            mapping_confidence=1.0,
            review_status="reviewed",
            component_ids="FLOPO_greenish|FLOPO_pinkish",
            logical_operator="one_of",
            attribute_id="PATO_color",
        ),
        RegistryEntry(
            term_id="flower",
            surface_form="flower",
            normalized_form="flower",
            language="en",
            semantic_role="entity",
            target_id="PO_flower",
            target_label="flower",
            target_namespace="PO",
            mapping_relation="skos:exactMatch",
            mapping_confidence=1.0,
            review_status="reviewed",
        ),
    ]
    guide = TerminologyIndex(entries, catalog)
    monkeypatch.setattr(engine, "load_lexicons", lambda: (po_lex, pato_lex))
    monkeypatch.setattr(engine, "load_terminology_index", lambda path: guide)
    client = StubClient(
        [
            {
                "entity_label": "flower",
                "quality_label": "color",
                "entity_text": "flowers",
                "quality_text": "greenish or pinkish",
                "value_operator": "one_of",
                "value_labels": ["greenish", "pinkish"],
                "source_text": "greenish or pinkish flowers",
            }
        ]
    )
    result = engine.extract_segment(
        client,
        engine.EngineConfig(models=["m"]),
        {"text": "greenish or pinkish flowers", "organ": "flower", "language": "en"},
    )
    assert len(result) == 1
    assert result[0].pato_id == "PATO_color"
    assert result[0].value_operator == "one_of"
    assert result[0].value_term_ids == ("FLOPO_greenish", "FLOPO_pinkish")
    assert result[0].normalization_status == "compositional"


def test_atomic_flopo_value_does_not_inherit_a_related_pato_colour(monkeypatch, tmp_path):
    from flopo2.extract import engine
    from flopo2.extract.ground import Lexicon
    from flopo2.terminology.annotate import TerminologyIndex
    from flopo2.terminology.catalog import OntologyCatalog, OntologyTerm
    from flopo2.terminology.model import RegistryEntry

    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\tnamespace\nPO_flower\tflower\tflowers\tplant_anatomy\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tsynonyms\tslim\n"
        "PATO_color\tcolor\t\tattribute_slim\n"
        "PATO_green\tgreen\t\tvalue_slim\n"
    )
    po_lex, pato_lex = Lexicon.load(po), Lexicon.load(pato)
    catalog = OntologyCatalog(
        {
            "PO_flower": OntologyTerm("PO_flower", "flower", "PO", ("flowers",)),
            "PATO_color": OntologyTerm("PATO_color", "color", "PATO"),
            "PATO_green": OntologyTerm("PATO_green", "green", "PATO", ("greenish",)),
            "FLOPO_greenish": OntologyTerm("FLOPO_greenish", "greenish", "FLOPO"),
        }
    )
    entries = [
        RegistryEntry(
            term_id="greenish-value",
            surface_form="greenish",
            normalized_form="greenish",
            language="en",
            semantic_role="value",
            target_id="FLOPO_greenish",
            target_label="greenish",
            target_namespace="FLOPO",
            mapping_relation="skos:exactMatch",
            mapping_confidence=1.0,
            review_status="reviewed",
            logical_operator="atomic",
            attribute_id="PATO_color",
        ),
        RegistryEntry(
            term_id="greenish-related",
            surface_form="greenish",
            normalized_form="greenish",
            language="en",
            semantic_role="quality",
            target_id="PATO_green",
            target_label="green",
            target_namespace="PATO",
            mapping_relation="skos:relatedMatch",
            mapping_confidence=0.9,
            review_status="proposed",
        ),
        RegistryEntry(
            term_id="flower",
            surface_form="flower",
            normalized_form="flower",
            language="en",
            semantic_role="entity",
            target_id="PO_flower",
            target_label="flower",
            target_namespace="PO",
            mapping_relation="skos:exactMatch",
            mapping_confidence=1.0,
            review_status="reviewed",
        ),
    ]
    guide = TerminologyIndex(entries, catalog)
    monkeypatch.setattr(engine, "load_lexicons", lambda: (po_lex, pato_lex))
    monkeypatch.setattr(engine, "load_terminology_index", lambda path: guide)
    client = StubClient(
        [
            {
                "entity_label": "flower",
                "quality_label": "color",
                "entity_text": "flowers",
                "quality_text": "greenish",
                "value_operator": "atomic",
                "value_labels": ["greenish"],
                "source_text": "greenish flowers",
            }
        ]
    )
    result = engine.extract_segment(
        client,
        engine.EngineConfig(models=["m"]),
        {"text": "greenish flowers", "organ": "flower", "language": "en"},
    )
    assert len(result) == 1
    assert result[0].pato_id == "PATO_color"
    assert result[0].value_operator == "atomic"
    assert result[0].value_term_ids == ("FLOPO_greenish",)


def test_chat_json_never_raises(monkeypatch):
    """A network/HTTP failure must return None, not propagate (so the pool can't be crashed)."""
    from flopo2.extract.router import OpenRouterClient

    c = OpenRouterClient(api_key="x", client=object())  # dummy transport; _post is overridden

    def boom(payload):
        raise RuntimeError("network down")

    monkeypatch.setattr(c, "_post", boom)
    assert c.chat_json("m", "s", "u") is None
    assert c.usage.calls == 0  # failed calls are not counted


def test_baseline_extracts_organ_measurement_and_quality():
    from flopo2.extract.baseline import extract_segment

    seg = {
        "organ": "fruits",
        "language": "fr",
        "text": "Fruit subglobuleux, 2-2,5 cm de diamètre, lisse, glabre, jaune à rouge.",
    }
    out = extract_segment(seg)
    pairs = {(a["po_id"], a["pato_id"]) for a in out}
    assert ("PO_0009001", "PATO_0001334") in pairs
    assert ("PO_0009001", "PATO_0005014") in pairs
    assert ("PO_0009001", "PATO_0000453") in pairs
    assert all(a["source_text"] in seg["text"] for a in out)
    diameter = next(a for a in out if a["pato_id"] == "PATO_0001334")
    assert diameter["value_low"] == 2.0
    assert diameter["value_high"] == 2.5
    assert diameter["unit"] == "cm"


def test_run_pilot_survives_segment_failure(monkeypatch, tmp_path):
    """One segment raising inside extraction must not abort the run; all segments still score."""
    import json as _json

    from flopo2.extract import engine, pilot

    segs = [
        {"text": "a", "language": "en", "organ": "leaf",
         "assertions": [{"po_id": "PO_1", "pato_id": "PATO_1", "source_text": "a"}]},
        {"text": "b", "language": "en", "organ": "leaf", "assertions": []},   # will raise
        {"text": "c", "language": "fr", "organ": "stem", "assertions": []},
    ]
    silver = tmp_path / "silver.jsonl"
    silver.write_text("\n".join(_json.dumps(s) for s in segs))

    def flaky_extract(client, cfg, seg):
        if seg["text"] == "b":
            raise RuntimeError("boom")
        return []

    monkeypatch.setattr(pilot, "extract_segment", flaky_extract)
    cfg = engine.EngineConfig(models=["m"], grounding="spires", samples=1)
    res = pilot.run_pilot(silver, cfg, limit=None, client=StubClient([]), concurrency=2)
    assert res["segments"] == 3  # completed without crashing despite the middle failure


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
