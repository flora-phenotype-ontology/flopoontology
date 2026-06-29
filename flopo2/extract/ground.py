"""Deterministic grounding of free-text entity/quality labels to PO/PATO ids (Phase 5).

The extraction engine has the LLM emit English entity/quality *labels* (it translates French in
context); this module maps those labels to ontology ids against the PO/PATO lexicons:
exact label/synonym match first, then a conservative fuzzy fallback. Grounding here is
deterministic and reproducible, which is exactly what we want as the baseline ("SPIRES-style")
grounding strategy — the Graph-RAG strategy (LLM picks from retrieved candidates) is evaluated
against it. ``candidates()`` also exposes top-k matches for that strategy.
"""

from __future__ import annotations

import csv
import difflib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass
class Lexicon:
    label_to_id: dict[str, str]       # lowercased label/synonym -> id
    id_to_label: dict[str, str]       # id -> primary label
    all_labels: list[str]             # lowercased labels for fuzzy matching

    @classmethod
    def load(cls, path: Path) -> "Lexicon":
        label_to_id: dict[str, str] = {}
        id_to_label: dict[str, str] = {}
        with Path(path).open(newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                tid, label = row["id"], row["label"]
                id_to_label[tid] = label
                label_to_id.setdefault(label.lower(), tid)
                for syn in (row.get("synonyms") or "").split("|"):
                    if syn:
                        label_to_id.setdefault(syn.lower(), tid)
        return cls(label_to_id, id_to_label, list(label_to_id))

    def ground(self, label: str, fuzzy_cutoff: float = 0.92) -> str | None:
        """Return the id for a label: exact (label/synonym) then conservative fuzzy fallback."""
        if not label:
            return None
        key = label.strip().lower()
        if key in self.label_to_id:
            return self.label_to_id[key]
        # Try singular/plural and hyphen variants cheaply before fuzzy.
        for variant in (key.rstrip("s"), key.replace("-", " "), key.replace(" ", "-")):
            if variant in self.label_to_id:
                return self.label_to_id[variant]
        match = difflib.get_close_matches(key, self.all_labels, n=1, cutoff=fuzzy_cutoff)
        return self.label_to_id[match[0]] if match else None

    def candidates(self, label: str, k: int = 8) -> list[tuple[str, str]]:
        """Top-k (id, label) candidates for a label (for the Graph-RAG grounding strategy)."""
        key = (label or "").strip().lower()
        names = difflib.get_close_matches(key, self.all_labels, n=k, cutoff=0.5)
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for nm in names:
            tid = self.label_to_id[nm]
            if tid not in seen:
                seen.add(tid)
                out.append((tid, self.id_to_label.get(tid, nm)))
        return out


@lru_cache(maxsize=4)
def load_lexicons(po_path: str = "config/po_lexicon.tsv",
                  pato_path: str = "config/pato_lexicon.tsv") -> tuple[Lexicon, Lexicon]:
    return Lexicon.load(Path(po_path)), Lexicon.load(Path(pato_path))
