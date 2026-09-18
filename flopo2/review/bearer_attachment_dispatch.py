"""Batches, reviewer dispatch and review collection for the bearer-attachment campaign.

Three reviewer backends answer the same closed question per item (one candidate ``bearer_id``
or ``hold``):

* ``claude`` -- headless ``claude -p`` (Opus, Sonnet) with ``--json-schema`` structured output,
  no tools, no session persistence and no user/project settings;
* ``vllm`` -- an OpenAI-compatible chat endpoint (the curator's Qwen server) with guided
  ``json_schema`` output whose per-item ``bearer_id`` enumeration is exactly the item's closed
  candidate list.  The bearer key is read from a file at call time and never logged.

Every batch is checkpointed (one JSON file per reviewer and batch, bound to the batch and prompt
SHA-256), so interrupted runs resume.  Responses are validated strictly: every item exactly once,
``bearer_id`` from the item's candidate list or ``hold``; an invalid response is retried and
finally recorded as ``invalid`` (never a vote).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from flopo2.review.bearer_attachment_inventory import HOLD

REVIEW_SCHEMA_VERSION = "flopo-bearer-attachment-review-v1"
PROMPT_ID = "flopo_bearer_attachment_reviewer_v2"
DEFAULT_PROMPT = Path(f"config/review_prompts/{PROMPT_ID}.md")

REVIEWERS: dict[str, dict[str, str]] = {
    "claude-opus": {"backend": "claude", "model": "opus", "model_family": "claude-opus"},
    "claude-sonnet": {"backend": "claude", "model": "sonnet", "model_family": "claude-sonnet"},
    "qwen": {
        "backend": "vllm",
        "model": "qwen3.8-27b",
        "model_family": "qwen-3.8",
        "base_url": "http://unimatrix01.kaust.edu.sa:8000/v1",
        "key_file": "~/.config/borg-llm/api-key",
    },
}

PACKET_FIELDS = ("item_id", "language", "taxon_family", "record_heading", "clause", "context")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def packet_item(item: dict[str, Any]) -> dict[str, Any]:
    """Reviewer-facing view of an inventory item (no gate or diagnostic fields)."""

    quality = item["quality"]
    if quality["value_operator"] == "one_of":
        described = {
            "value_operator": "one_of",
            "attribute": f"{quality['attribute_label']} ({quality['attribute_id']})",
            "values": [
                f"{label} ({term})"
                for label, term in zip(quality["value_labels"], quality["value_terms"])
            ],
        }
    else:
        described = {
            "value_operator": "atomic",
            "quality": f"{quality['attribute_label']} ({quality['attribute_id']})",
        }
    return {
        **{name: item.get(name, "") for name in PACKET_FIELDS},
        "marked_value_text": item["value_text"],
        "quality": described,
        "candidates": [
            {
                "bearer_id": row["bearer_id"],
                "label": row["label"],
                "evidence": [
                    f"{e['basis']}: {e['surface']!r}"
                    + (f" at [{e['start']},{e['end']})" if e.get("start") is not None else "")
                    for e in row["evidence"]
                ],
            }
            for row in item["candidates"]
        ],
    }


def make_batches(
    inventory: Path, out_dir: Path, *, size: int, item_ids: set[str] | None = None
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    items = [
        json.loads(line)
        for line in inventory.open(encoding="utf-8")
        if line.strip()
    ]
    if item_ids is not None:
        items = [item for item in items if item["item_id"] in item_ids]
    paths = []
    for index in range(0, len(items), size):
        chunk = [packet_item(item) for item in items[index : index + size]]
        path = out_dir / f"batch-{index // size + 1:05d}.json"
        path.write_text(json.dumps({"items": chunk}, ensure_ascii=False, indent=1) + "\n")
        paths.append(path)
    return paths


def response_schema(items: list[dict[str, Any]], *, per_item_enum: bool) -> dict[str, Any]:
    """Batch response schema; with ``per_item_enum`` each position is bound to its item."""

    def decision(item: dict[str, Any] | None) -> dict[str, Any]:
        bearer: dict[str, Any] = {"type": "string"}
        item_id: dict[str, Any] = {"type": "string"}
        if item is not None:
            bearer = {"type": "string", "enum": [c["bearer_id"] for c in item["candidates"]] + [HOLD]}
            item_id = {"type": "string", "enum": [item["item_id"]]}
        return {
            "type": "object",
            "properties": {"item_id": item_id, "bearer_id": bearer, "reason": {"type": "string"}},
            "required": ["item_id", "bearer_id", "reason"],
            "additionalProperties": False,
        }

    if per_item_enum:
        array: dict[str, Any] = {
            "type": "array",
            "prefixItems": [decision(item) for item in items],
            "items": False,
            "minItems": len(items),
            "maxItems": len(items),
        }
    else:
        array = {"type": "array", "items": decision(None)}
    return {
        "type": "object",
        "properties": {"decisions": array},
        "required": ["decisions"],
        "additionalProperties": False,
    }


def validate_decisions(items: list[dict[str, Any]], decisions: Any) -> list[dict[str, Any]]:
    if not isinstance(decisions, list):
        raise ValueError("decisions is not a list")
    by_id: dict[str, dict[str, Any]] = {}
    for row in decisions:
        if not isinstance(row, dict) or set(row) - {"item_id", "bearer_id", "reason"}:
            raise ValueError(f"malformed decision: {row!r}")
        if row.get("item_id") in by_id:
            raise ValueError(f"duplicate decision for {row.get('item_id')}")
        by_id[str(row.get("item_id"))] = row
    wanted = [item["item_id"] for item in items]
    if set(by_id) != set(wanted):
        raise ValueError(
            f"decision ids differ from batch: missing {sorted(set(wanted) - set(by_id))[:3]}, "
            f"extra {sorted(set(by_id) - set(wanted))[:3]}"
        )
    out = []
    for item in items:
        row = by_id[item["item_id"]]
        allowed = {c["bearer_id"] for c in item["candidates"]} | {HOLD}
        bearer = str(row.get("bearer_id", "")).strip()
        if bearer not in allowed:
            raise ValueError(f"{item['item_id']}: bearer {bearer!r} not in candidate list")
        out.append({"item_id": item["item_id"], "bearer_id": bearer, "reason": str(row.get("reason", ""))})
    return out


def _user_message(items: list[dict[str, Any]]) -> str:
    return (
        "Review every item below and return one decision per item, in the same order, as "
        '{"decisions": [{"item_id", "bearer_id", "reason"}, ...]}. `bearer_id` must be copied '
        "exactly from that item's candidates, or be `hold`.\n\n"
        + json.dumps({"items": items}, ensure_ascii=False, indent=1)
    )


# ------------------------------------------------------------------------------ backends
def call_claude(
    spec: dict[str, str], prompt: str, items: list[dict[str, Any]], timeout: int = 1800
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    schema = response_schema(items, per_item_enum=False)
    command = [
        "claude", "-p",
        "--model", spec["model"],
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--tools", "",
        "--no-session-persistence",
        "--setting-sources", "",
        "--system-prompt", prompt,
    ]
    completed = subprocess.run(
        command,
        input=_user_message(items),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd="/tmp",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"claude exited {completed.returncode}: {completed.stderr[-500:]}")
    envelope = json.loads(completed.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude error: {str(envelope.get('result'))[:500]}")
    output = envelope.get("structured_output")
    if output is None:
        output = json.loads(envelope.get("result") or "{}")
    usage = envelope.get("modelUsage") or {}
    served = max(usage, key=lambda name: usage[name].get("outputTokens", 0)) if usage else ""
    meta = {
        "served_model": served,
        "provider_request_id": envelope.get("session_id", ""),
        "cost_usd": envelope.get("total_cost_usd"),
        "duration_ms": envelope.get("duration_ms"),
    }
    return validate_decisions(items, output.get("decisions")), meta


def call_vllm(
    spec: dict[str, str], prompt: str, items: list[dict[str, Any]], timeout: int = 1800
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    key = Path(os.path.expanduser(spec["key_file"])).read_text(encoding="utf-8").strip()
    body = {
        "model": spec["model"],
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": _user_message(items)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "bearer_decisions",
                "schema": response_schema(items, per_item_enum=True),
                "strict": True,
            },
        },
        "temperature": 0,
        "max_tokens": 24000,
    }
    request = urllib.request.Request(
        spec["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as handle:
        payload = json.loads(handle.read())
    choice = payload["choices"][0]
    if choice.get("finish_reason") not in {"stop", None}:
        raise RuntimeError(f"vllm finish_reason {choice.get('finish_reason')}")
    content = choice["message"].get("content")
    if not content:
        raise RuntimeError("vllm returned no content (reasoning only or truncated)")
    output = json.loads(content)
    meta = {
        "served_model": payload.get("model", ""),
        "system_fingerprint": payload.get("system_fingerprint", ""),
        "provider_request_id": payload.get("id", ""),
        "usage": payload.get("usage", {}),
    }
    return validate_decisions(items, output.get("decisions")), meta


BACKENDS: dict[str, Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]]] = {
    "claude": call_claude,
    "vllm": call_vllm,
}


# ------------------------------------------------------------------------------ runner
def review_batch(
    reviewer: str,
    batch_path: Path,
    checkpoint_dir: Path,
    prompt_path: Path,
    *,
    attempts: int = 3,
    backend: Callable[..., Any] | None = None,
) -> Path:
    spec = REVIEWERS[reviewer]
    prompt = prompt_path.read_text(encoding="utf-8")
    batch_text = batch_path.read_text(encoding="utf-8")
    binding = {"batch_sha256": sha256_text(batch_text), "prompt_sha256": sha256_text(prompt)}
    target = checkpoint_dir / batch_path.name
    if target.exists():
        existing = json.loads(target.read_text())
        if all(existing.get(k) == v for k, v in binding.items()):
            return target
    items = json.loads(batch_text)["items"]
    call = backend or BACKENDS[spec["backend"]]
    errors: list[str] = []
    decisions: list[dict[str, Any]] | None = None
    meta: dict[str, Any] = {}
    for attempt in range(attempts):
        try:
            decisions, meta = call(spec, prompt, items)
            break
        except (RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError,
                subprocess.TimeoutExpired, urllib.error.URLError, TimeoutError, OSError) as error:
            errors.append(f"attempt {attempt + 1}: {type(error).__name__}: {str(error)[:300]}")
            time.sleep(5 * (attempt + 1))
    if decisions is None:
        decisions = [{"item_id": item["item_id"], "bearer_id": "invalid", "reason": "; ".join(errors)}
                     for item in items]
    checkpoint = {
        **binding,
        "reviewer_id": reviewer,
        "backend": spec["backend"],
        "requested_model": spec["model"],
        "model_family": spec["model_family"],
        "batch": batch_path.name,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "errors": errors,
        "meta": meta,
        "decisions": decisions,
    }
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=1) + "\n")
    temporary.replace(target)
    return target


def run_reviewer(
    reviewer: str,
    batches_dir: Path,
    campaign_dir: Path,
    *,
    prompt_path: Path = DEFAULT_PROMPT,
    workers: int = 4,
) -> dict[str, Any]:
    checkpoint_dir = campaign_dir / "checkpoints" / reviewer
    batches = sorted(batches_dir.glob("batch-*.json"))
    lock = threading.Lock()
    done = 0
    with ThreadPoolExecutor(max_workers=min(workers, 4)) as pool:
        futures = {
            pool.submit(review_batch, reviewer, path, checkpoint_dir, prompt_path): path
            for path in batches
        }
        for future in as_completed(futures):
            future.result()
            with lock:
                done += 1
                print(f"{reviewer}: {done}/{len(batches)} {futures[future].name}", flush=True)
    return collect(reviewer, batches_dir, campaign_dir, prompt_path=prompt_path)


def collect(
    reviewer: str, batches_dir: Path, campaign_dir: Path, *, prompt_path: Path = DEFAULT_PROMPT
) -> dict[str, Any]:
    """Write ``reviews-<reviewer>.jsonl`` from checkpoints bound to the current batches."""

    spec = REVIEWERS[reviewer]
    prompt_sha = sha256_text(prompt_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    counts = {"batches": 0, "missing_batches": 0, "invalid": 0, "hold": 0, "bearer": 0}
    served: dict[str, int] = {}
    for path in sorted(batches_dir.glob("batch-*.json")):
        counts["batches"] += 1
        checkpoint_path = campaign_dir / "checkpoints" / reviewer / path.name
        if not checkpoint_path.exists():
            counts["missing_batches"] += 1
            continue
        checkpoint = json.loads(checkpoint_path.read_text())
        if checkpoint["batch_sha256"] != sha256_text(path.read_text(encoding="utf-8")) or (
            checkpoint["prompt_sha256"] != prompt_sha
        ):
            counts["missing_batches"] += 1
            continue
        model = checkpoint.get("meta", {}).get("served_model", "")
        served[model] = served.get(model, 0) + len(checkpoint["decisions"])
        for decision in checkpoint["decisions"]:
            kind = (
                "invalid" if decision["bearer_id"] == "invalid"
                else "hold" if decision["bearer_id"] == HOLD else "bearer"
            )
            counts[kind] += 1
            rows.append(
                {
                    "schema_version": REVIEW_SCHEMA_VERSION,
                    "reviewer_id": reviewer,
                    "backend": spec["backend"],
                    "requested_model": spec["model"],
                    "model": model,
                    "model_family": spec["model_family"],
                    "prompt_id": PROMPT_ID,
                    "prompt_sha256": prompt_sha,
                    "batch": path.name,
                    "batch_sha256": checkpoint["batch_sha256"],
                    "item_id": decision["item_id"],
                    "bearer_id": decision["bearer_id"],
                    "reason": decision["reason"],
                    "validation_passed": kind != "invalid",
                }
            )
    out = campaign_dir / f"reviews-{reviewer}.jsonl"
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {"reviewer": reviewer, "counts": counts, "served_models": served, "path": str(out)}
    (campaign_dir / f"reviews-{reviewer}-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    batch = sub.add_parser("batches")
    batch.add_argument("inventory", type=Path)
    batch.add_argument("out_dir", type=Path)
    batch.add_argument("--size", type=int, default=20)
    batch.add_argument("--item-ids", type=Path, help="optional file with one item id per line")
    run = sub.add_parser("run")
    run.add_argument("reviewer", choices=sorted(REVIEWERS))
    run.add_argument("batches_dir", type=Path)
    run.add_argument("campaign_dir", type=Path)
    run.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    run.add_argument("--workers", type=int, default=4)
    col = sub.add_parser("collect")
    col.add_argument("reviewer", choices=sorted(REVIEWERS))
    col.add_argument("batches_dir", type=Path)
    col.add_argument("campaign_dir", type=Path)
    col.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    args = parser.parse_args(argv)
    if args.command == "batches":
        ids = None
        if args.item_ids:
            ids = {line.strip() for line in args.item_ids.open() if line.strip()}
        paths = make_batches(args.inventory, args.out_dir, size=args.size, item_ids=ids)
        print(json.dumps({"batches": len(paths)}))
    elif args.command == "run":
        print(json.dumps(run_reviewer(args.reviewer, args.batches_dir, args.campaign_dir,
                                      prompt_path=args.prompt, workers=args.workers), indent=2))
    else:
        print(json.dumps(collect(args.reviewer, args.batches_dir, args.campaign_dir,
                                 prompt_path=args.prompt), indent=2))


if __name__ == "__main__":
    main()
