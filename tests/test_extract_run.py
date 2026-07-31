from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

from flopo2.eval.scoring import Assertion


def test_run_assertion_serializer_preserves_all_provenance_offsets():
    from flopo2.extract.run import _assertion_to_json

    assertion = Assertion(
        po_id="PO_0009046",
        pato_id="PATO_0000322",
        source_text="red",
        source_start=16,
        source_end=19,
        raw_entity_text="flowers",
        bearer_start=0,
        bearer_end=7,
        frequency_qualifier="usually",
        modality_text="usually",
        modality_start=8,
        modality_end=15,
    )

    serialized = _assertion_to_json(assertion, {}, {})
    assert {
        key: serialized[key]
        for key in (
            "source_start",
            "source_end",
            "bearer_start",
            "bearer_end",
            "modality_start",
            "modality_end",
        )
    } == {
        "source_start": 16,
        "source_end": 19,
        "bearer_start": 0,
        "bearer_end": 7,
        "modality_start": 8,
        "modality_end": 15,
    }


def test_max_seconds_closes_client_and_unwinds_workers(monkeypatch, tmp_path):
    from flopo2.extract import run
    from flopo2.extract.engine import EngineConfig

    source = tmp_path / "segments.jsonl"
    source.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "1",
                "taxon": "Planta alpha",
                "organ": "leaf",
                "language": "en",
                "text": "Leaves green.",
            }
        )
        + "\n"
    )
    closed = threading.Event()

    class FakeClient:
        def __init__(self, **kwargs):
            self.usage = SimpleNamespace(
                calls=0,
                cost_usd=0.0,
                escalations=0,
                by_model={},
            )

        def close(self):
            closed.set()

    def blocked_extract(client, cfg, row):
        assert closed.wait(5), "client.close() did not release the worker"
        return []

    lexicon = SimpleNamespace(id_to_label={})
    monkeypatch.setattr(run, "OpenRouterClient", FakeClient)
    monkeypatch.setattr(run, "extract_segment", blocked_extract)
    monkeypatch.setattr(run, "load_lexicons", lambda: (lexicon, lexicon))

    started = time.monotonic()
    result = run.run_file(
        source,
        tmp_path / "out.jsonl",
        EngineConfig(models=["test"], use_terminology=False),
        concurrency=1,
        resume=False,
        max_seconds=0.01,
    )
    elapsed = time.monotonic() - started

    assert result["timed_out"] is True
    assert result["rows_written"] == 0
    assert closed.is_set()
    assert elapsed < 1
