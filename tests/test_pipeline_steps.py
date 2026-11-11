"""The flora pipeline's step markers and its CPU/LLM step split (tools/orix_flora_lane.py)."""

import json
from pathlib import Path

import pytest

import flopo2.ingest.pipeline as pipeline


@pytest.fixture
def fake_flora(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []
    raw = Path("local-corpora/demo/raw")
    derived = Path("local-corpora/demo/derived")
    raw.mkdir(parents=True)
    derived.mkdir(parents=True)
    segments = raw / "demo-segments.jsonl"
    segments.write_text("".join(json.dumps({"source_id": f"s{i}"}) + "\n" for i in range(3)))
    qwen = raw / "demo-qwen.jsonl"

    def append(path: Path, text: str) -> None:
        with path.open("a") as handle:
            handle.write(text + "\n")

    def transcribe(argv):
        calls.append("transcribe")
        for i in range(3):
            append(qwen, json.dumps({"source_id": f"s{i}", "transcription": "x"}))

    def annotate(source, qwen_path, derived_dir):
        calls.append("annotate")
        append(derived / "demo-annotated.jsonl", f"pass {len(calls)}")
        (derived / "demo-dispositions.tsv").write_text("d\n")
        (derived / "demo-summary.json").write_text(json.dumps({"assertions": 1}))
        return {"assertions": 1}

    def llm(name, out_flag):
        def run(argv):
            calls.append(name)
            append(Path(argv[argv.index(out_flag) + 1]), name)
        return run

    monkeypatch.setattr(pipeline, "FLORA_SOURCES", {"demo": {}})
    monkeypatch.setattr(pipeline, "dump_segments", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.flora_llm, "main", transcribe)
    monkeypatch.setattr(pipeline.flora_annotate, "run", annotate)
    monkeypatch.setattr(pipeline.llm_reread, "main", llm("reread", "--out"))
    monkeypatch.setattr(pipeline.llm_term_rules, "main", llm("term-rules", "--out"))
    monkeypatch.setattr(pipeline.llm_relations, "main", llm("relations", "--out"))
    monkeypatch.setattr(pipeline, "validate_jsonl", lambda *a, **k: calls.append("validate") or {"errors": 0})
    monkeypatch.setattr(pipeline.flora_candidates, "extract_for_source",
                        lambda *a, **k: calls.append("candidates") or {"n": 0})
    return calls


def test_steps_alternate_between_cpu_and_llm(fake_flora):
    calls = fake_flora
    run = lambda steps: pipeline.run_flora_pipeline("demo", steps=steps)  # noqa: E731

    assert run("cpu")["status"] == "needs-llm" and calls == []          # transcription first
    assert run("llm") == {"source": "demo", "status": "needs-cpu", "next_step": "annotate-initial"}
    assert calls == ["transcribe"]
    assert run("cpu")["next_step"] == "reread"
    assert run("llm")["next_step"] == "annotate-reread"
    assert run("cpu")["next_step"] == "term-rules"
    assert run("llm")["next_step"] == "annotate-final"
    assert run("cpu")["status"] == "done"
    assert calls == ["transcribe", "annotate", "reread", "annotate", "term-rules", "relations",
                     "annotate", "validate", "candidates"]


def test_rerun_skips_completed_steps_until_a_cache_changes(fake_flora):
    calls = fake_flora
    assert pipeline.run_flora_pipeline("demo")["status"] == "done"
    calls.clear()
    assert pipeline.run_flora_pipeline("demo")["status"] == "done"
    assert calls == []                                    # everything was complete
    with open("local-corpora/demo/llm-relations.jsonl", "a") as handle:
        handle.write("new answer\n")                      # new relation answers (another run)
    pipeline.run_flora_pipeline("demo")
    assert calls == ["annotate", "validate", "candidates"]  # only the steps downstream of it


def test_redo_ignores_markers(fake_flora):
    calls = fake_flora
    pipeline.run_flora_pipeline("demo")
    calls.clear()
    pipeline.run_flora_pipeline("demo", redo=True)
    assert "annotate" in calls and "transcribe" not in calls  # transcription is cache-driven


def test_segments_failing_every_retry_do_not_block_the_cpu_steps(fake_flora, monkeypatch):
    calls = fake_flora
    qwen = Path("local-corpora/demo/raw/demo-qwen.jsonl")

    def transcribe_with_failure(argv):
        calls.append("transcribe")
        with qwen.open("a") as handle:
            handle.write(json.dumps({"source_id": "s0", "transcription": "x"}) + "\n")
            handle.write(json.dumps({"source_id": "s1", "transcription": "x"}) + "\n")
            handle.write(json.dumps({"source_id": "s2", "error": "JSONDecodeError"}) + "\n")

    monkeypatch.setattr(pipeline.flora_llm, "main", transcribe_with_failure)
    assert pipeline.run_flora_pipeline("demo", steps="llm")["next_step"] == "annotate-initial"
    assert pipeline.run_flora_pipeline("demo", steps="cpu")["next_step"] == "reread"
    assert calls.count("transcribe") == 1
