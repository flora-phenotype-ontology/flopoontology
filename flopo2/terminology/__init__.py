"""Botanical terminology alignment and text pre-annotation.

The terminology registry is the durable, reviewable artifact.  Runtime indexes are built from
that registry and pinned PO/PATO/FLOPO releases; no generated search index is a source of truth.
"""

from flopo2.terminology.annotate import TerminologyIndex
from flopo2.terminology.model import Candidate, RegistryEntry, TermMention

__all__ = ["Candidate", "RegistryEntry", "TermMention", "TerminologyIndex"]
