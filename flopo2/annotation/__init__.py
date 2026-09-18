"""FLOPO source-assertion, modality, and context helpers."""

from __future__ import annotations

from typing import Any


__all__ = ["ensure_source_statements", "stable_statement_id", "upgrade_jsonl"]


def __getattr__(name: str) -> Any:
    """Load provenance helpers lazily so ``python -m ...provenance`` stays warning-free."""

    if name in __all__:
        from . import provenance

        return getattr(provenance, name)
    raise AttributeError(name)
