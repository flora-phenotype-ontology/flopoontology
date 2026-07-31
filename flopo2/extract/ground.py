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

from flopo2.terminology.catalog import load_obo_metadata


@dataclass
class Lexicon:
    label_to_id: dict[str, str]       # lowercased label/synonym -> id
    id_to_label: dict[str, str]       # id -> primary label
    all_labels: list[str]             # lowercased labels for fuzzy matching
    label_overrides: dict[str, str] | None = None

    @classmethod
    def load(cls, path: Path, label_overrides: dict[str, str] | None = None) -> "Lexicon":
        label_to_id: dict[str, str] = {}
        id_to_label: dict[str, str] = {}
        primary_labels: set[str] = set()
        with Path(path).open(newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                tid, label = row["id"], row["label"]
                id_to_label[tid] = label
                # A preferred label must outrank the same string used as another class's synonym.
                label_to_id[label.lower()] = tid
                primary_labels.add(label.lower())
                for syn in (row.get("synonyms") or "").split("|"):
                    if syn:
                        label_to_id.setdefault(syn.lower(), tid)
        overrides: dict[str, str] = {}
        for label, target_id in (label_overrides or {}).items():
            key = label.strip().lower()
            if target_id and target_id in id_to_label:
                label_to_id[key] = target_id
                overrides[key] = target_id
            elif key not in primary_labels:
                label_to_id.pop(key, None)
                overrides[key] = ""
        return cls(label_to_id, id_to_label, list(label_to_id), overrides)

    def ground(self, label: str, fuzzy_cutoff: float = 0.92) -> str | None:
        """Return the id for a label: exact (label/synonym) then conservative fuzzy fallback."""
        if not label:
            return None
        key = label.strip().lower()
        if key in (self.label_overrides or {}):
            override = (self.label_overrides or {}).get(key)
            return override if override and override in self.id_to_label else None
        if key in self.label_to_id:
            return self.label_to_id[key]
        # Try singular/plural and hyphen variants cheaply before fuzzy.
        for variant in (key.rstrip("s"), key.replace("-", " "), key.replace(" ", "-")):
            if variant in (self.label_overrides or {}):
                override = (self.label_overrides or {}).get(variant)
                return override if override and override in self.id_to_label else None
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


def _scoped_synonym_overrides(obo_path: str) -> dict[str, str]:
    """Block non-equivalent OBO synonyms unless the same form is also explicitly EXACT."""
    scopes: dict[str, set[str]] = {}
    path = Path(obo_path)
    if not path.exists():
        return {}
    for metadata in load_obo_metadata(path).values():
        for synonym, scope in metadata.get("synonym_scopes", ()):
            scopes.setdefault(synonym.strip().lower(), set()).add(scope)
    return {
        synonym: ""
        for synonym, synonym_scopes in scopes.items()
        if "EXACT" not in synonym_scopes
    }


@lru_cache(maxsize=4)
def load_lexicons(
    po_path: str = "config/po_lexicon.tsv",
    pato_path: str = "config/pato_lexicon.tsv",
    po_obo_path: str = "ont/plant_ontology.obo",
    pato_obo_path: str = "ont/quality.obo",
) -> tuple[Lexicon, Lexicon]:
    po_overrides = _scoped_synonym_overrides(po_obo_path)
    pato_overrides = _scoped_synonym_overrides(pato_obo_path)
    pato_overrides.update({
        # In plant morphology, attenuated/atténué means tapering to a slender point
        # (PATO:attenuate), not pathogen reduced virulence. PATO has "attenuated" as
        # a synonym for reduced virulence, so deterministic grounding needs this guard.
        "attenuated": "PATO_0001982",
        "attenuate": "PATO_0001982",
        "attenué": "PATO_0001982",
        "atténuée": "PATO_0001982",
        "atténués": "PATO_0001982",
        "atténuées": "PATO_0001982",
        # PATO explicitly marks palmate as a RELATED synonym of digitate.  Do not collapse the
        # broader leaf term to digitate during deterministic exact grounding.
        "palmate": "",
        # PATO:0000455 has the preferred label ``pubescent`` but denotes the onset of sexual
        # puberty. Botanical pubescence is the pilosity quality PATO:0001320, whose definition is
        # coverage by short hairs or soft down. Never let the lexical homonym ground a plant trait
        # to a maturity quality.
        "pubescent": "PATO_0001320",
        "pubescence": "PATO_0001320",
        "downy": "PATO_0001320",
    })
    return Lexicon.load(Path(po_path), po_overrides), Lexicon.load(Path(pato_path), pato_overrides)
