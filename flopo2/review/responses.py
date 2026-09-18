"""Structured-output schemas and strict ingestion for external LLM runners."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from flopo2.review.io import atomic_write_text, write_jsonl
from flopo2.review.models import (
    AdversarialBatchResponse,
    ReviewBatchResponse,
)


def strict_provider_schema(schema: dict) -> dict:
    """Recursively adapt Pydantic JSON Schema to strict provider requirements.

    Claude and OpenAI strict output modes require every declared object property to appear in
    ``required`` and prohibit additional properties, including inside ``$defs``. Defaults remain
    present, so this wire constraint does not alter Pydantic's internal default behaviour.
    """

    def normalize(node):
        if isinstance(node, dict):
            result = {key: normalize(value) for key, value in node.items()}
            if result.get("type") == "object" or "properties" in result:
                properties = result.get("properties", {})
                if isinstance(properties, dict):
                    result["required"] = list(properties)
                    result["additionalProperties"] = False
            return result
        if isinstance(node, list):
            return [normalize(value) for value in node]
        return node

    return normalize(schema)


def response_schema(role: str) -> dict:
    if role == "reviewer":
        model = ReviewBatchResponse
    elif role == "adjudicator":
        model = AdversarialBatchResponse
    else:
        raise ValueError("role must be reviewer or adjudicator")
    return strict_provider_schema(model.model_json_schema())


def write_response_schemas(review_path: Path, adversarial_path: Path) -> None:
    atomic_write_text(
        review_path,
        json.dumps(response_schema("reviewer"), indent=2, sort_keys=True) + "\n",
    )
    atomic_write_text(
        adversarial_path,
        json.dumps(response_schema("adjudicator"), indent=2, sort_keys=True) + "\n",
    )


def ingest_response(response_path: Path, output_path: Path, *, role: str) -> int:
    """Validate one provider response and atomically materialize normalized decision JSONL."""

    try:
        payload = response_path.read_text(encoding="utf-8")
        if role == "reviewer":
            response = ReviewBatchResponse.model_validate_json(payload)
        elif role == "adjudicator":
            response = AdversarialBatchResponse.model_validate_json(payload)
        else:
            raise ValueError("role must be reviewer or adjudicator")
    except (OSError, ValidationError, ValueError) as exc:
        raise ValueError(f"invalid {role} response {response_path}: {exc}") from exc
    write_jsonl(output_path, response.decisions)
    return len(response.decisions)
