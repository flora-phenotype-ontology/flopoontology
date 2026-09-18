"""Hashing and strict JSONL I/O helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Iterator, TypeVar

from pydantic import BaseModel, ValidationError

from flopo2.review.models import ArtifactHash


ModelT = TypeVar("ModelT", bound=BaseModel)


def sha256_file(path: Path) -> ArtifactHash:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return ArtifactHash(path=str(path), sha256=digest.hexdigest(), bytes=size)


def stable_id(prefix: str, value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}_{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


def read_jsonl(path: Path, model: type[ModelT]) -> Iterator[ModelT]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield model.model_validate_json(line)
            except (ValidationError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: invalid {model.__name__}: {exc}") from exc


def write_jsonl(path: Path, records: Iterable[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary_path = Path(temporary.name)
    try:
        with temporary as handle:
            for record in records:
                handle.write(record.model_dump_json(exclude_none=True) + "\n")
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, payload: str) -> None:
    """Durably replace a text artifact without exposing a partial checkpoint."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary_path = Path(temporary.name)
    try:
        with temporary as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def write_immutable_json(path: Path, model: BaseModel) -> None:
    payload = model.model_dump_json(indent=2, exclude_none=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace immutable manifest: {path}")
    atomic_write_text(path, payload)
