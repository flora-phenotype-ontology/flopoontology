"""Correct the plant parts of records about mosses, liverworts and hornworts.

Floras describe a moss with the words of the vascular plants: "leaves", "stem", "capsule". The
annotator grounds the word alone, so a moss capsule became a fruit type (PO 'capsule fruit') and
a moss leaf the general 'leaf'. The Plant Ontology has the right classes: 'non-vascular leaf'
(phyllid), 'gametophore stem' and 'gametophore branch', 'sporangium' (spore capsule), next to
seta, peristome, costa and rhizoid, which were grounded correctly.

``config/bryophyte_families.tsv`` lists the families; ``config/po_bryophyte_terms.tsv`` says what
happens to a part in a taxon of these families:

- ``replace``: the part is exchanged for the bryophyte class (exactly this class, not its subclasses);
- ``review``: the part, or anything below it (is_a, part_of), is an organ of the seed plants
  (flower, fruit, seed, root); the record goes to review with ``bearer_outside_plant_group``.

Whether a description is one of a bryophyte is decided by ``is_bryophyte``: by the family, or,
where the family is missing or is that of a vascular plant of the same name (Girgensohnia is a
moss and an amaranth), by words that only a moss description has. Other records are left alone.
The pass is idempotent.

    python -m flopo2.verify.apply_bryophyte_terms FILES                    # count only
    python -m flopo2.verify.apply_bryophyte_terms --write-suffix .moss FILES
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
from pathlib import Path

FAMILIES = Path("config/bryophyte_families.tsv")
TERMS = Path("config/po_bryophyte_terms.tsv")
REGISTRY = Path("config/flopo_id_registry.tsv")
REASON = "bearer_outside_plant_group"
# Words of a moss or liverwort description. One of the first group is enough; of the second,
# two are needed: a pitcher plant has a peristome, a eucalypt a calyptra, a grass setae.
_ONLY = re.compile(r"\b(exostome|endostome|alar cells?|perichaetial|perigonial|autoicous|synoicous|paroicous|"
                   r"pseudoparaphyllia|paraphyllia|underleaves|amphigastria)\b", re.IGNORECASE)
_ALSO = re.compile(r"\b(setae?|peristome|calyptra|gemmae|dioicous)\b", re.IGNORECASE)
OBO = "http://purl.obolibrary.org/obo/"


def families(path: Path = FAMILIES) -> set[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["family"].lower() for row in csv.DictReader(handle, delimiter="\t")}


_FAMILIES: set[str] | None = None


def is_bryophyte(family: str, text: str) -> bool:
    """Whether a description is one of a moss, liverwort or hornwort."""

    global _FAMILIES
    if _FAMILIES is None:
        _FAMILIES = families()
    if family and family.strip().lower() in _FAMILIES:
        return True
    text = text or ""
    only = {w.lower().rstrip("s") for w in _ONLY.findall(text)}
    also = {w.lower().rstrip("e") for w in _ALSO.findall(text)}  # seta, setae
    if family and family.strip():
        # the family of a vascular plant: only a clear moss description overrides it (a fern has
        # a costa and "dioicous" gametophytes, a langsat seed a peristome-like word or two)
        return len(only | also) >= 4
    return bool(only) or len(also) >= 2


class Terms:
    def __init__(self, terms: Path = TERMS, registry: Path = REGISTRY) -> None:
        from flopo2.saudi.vocab import Vocabulary

        self.vocab = Vocabulary()
        self.families = families()
        self.replace: dict[str, tuple[str, str]] = {}
        self.review: set[str] = set()
        with terms.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row["action"] == "replace":
                    self.replace[row["po_id"]] = (row["replacement"], row["replacement_label"])
                else:
                    self.review.add(row["po_id"].replace("_", ":"))
        self.flopo: dict[str, str] = {}
        with registry.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row["deprecated"] == "0":
                    self.flopo[row["signature"]] = row["flopo_iri"]
        self._outside: dict[str, bool] = {}

    def outside(self, bearer: str) -> bool:
        """Whether the part is a seed-plant organ or part of one."""

        key = str(bearer or "").replace("_", ":")
        if key not in self._outside:
            start = key if key.startswith("PO:") else self.vocab._flopo_bearer(key) or key
            self._outside[key] = bool(self.review & set(self.vocab._ancestors(self.vocab.po, start, part_of=True)))
        return self._outside[key]

    def apply(self, assertion: dict, family: str, text: str = "") -> str:
        """'' (nothing), 'replaced' or 'review'. ``text``: the description the record is from."""

        if not is_bryophyte(family, text):
            return ""
        bearer = str(assertion.get("po_id") or "").replace(":", "_")
        if bearer in self.replace:
            self._replace(assertion, bearer, *self.replace[bearer])
            return "replaced"
        if not self.outside(bearer):
            return ""
        gate = assertion.setdefault("gate", {})
        reasons = gate.setdefault("reasons", [])
        if REASON in reasons:
            return ""
        reasons.append(REASON)
        if gate.get("status") in (None, "", "accepted", "review"):
            gate["status"] = "review"
        return "review"

    def _narrower(self, new: str, old: str) -> bool:
        return old.replace("_", ":") in set(self.vocab._ancestors(self.vocab.po, new.replace("_", ":"), part_of=False))

    def _replace(self, assertion: dict, old: str, new: str, label: str) -> None:
        from flopo2.owl.annotation_class import ensure_annotation_class_iri
        from flopo2.verify.apply_bearer_position import class_linked

        assertion["po_id"] = new
        composition = assertion.get("composition")
        if isinstance(composition, dict) and composition.get("entity_label"):
            composition["entity_label"] = label
        assertion.setdefault("mapping_provenance", []).append(
            f"bearer: {old} -> {new} ({label}) in a bryophyte family (config/po_bryophyte_terms.tsv)")
        gate = assertion.get("gate")
        if isinstance(gate, dict) and gate.get("flopo_signature"):
            parts = gate["flopo_signature"].split("|")
            signature = "|".join(new if part == old else part for part in parts)
            gate["flopo_signature"] = signature
            if signature in self.flopo:
                gate["flopo_iri"], gate["flopo_status"] = self.flopo[signature], "existing"
            elif gate.get("flopo_iri") and not self._narrower(new, old):
                # FLOPO has no class for the new part yet. Where the new part is a kind of the old
                # one (non-vascular leaf, a leaf), the class of the old part still holds and stays.
                gate["flopo_iri"], gate["flopo_status"] = "", "new_class_candidate"
        had = assertion.pop("phenotype_class_iri", None)
        if had and class_linked(assertion):
            ensure_annotation_class_iri(assertion)


def run(paths: list[Path], suffix: str | None) -> dict:
    terms = Terms()
    counts: collections.Counter = collections.Counter()
    kinds: collections.Counter = collections.Counter()
    for path in paths:
        out = open(str(path) + suffix, "w", encoding="utf-8") if suffix else None
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                family = record.get("taxon_family", "")
                only = record.get("text", "")
                for assertion in record.get("assertions", []):
                    label = (assertion.get("composition") or {}).get("entity_label", "")
                    result = terms.apply(assertion, family, only)
                    if result:
                        counts[result] += 1
                        kinds[(result, label)] += 1
                if out:
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
        if out:
            out.close()
    return {"counts": dict(counts), "kinds": [[*key, n] for key, n in kinds.most_common()]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--write-suffix", help="write each file with this suffix added; omit to count only")
    args = parser.parse_args()
    result = run(args.files, args.write_suffix)
    print(json.dumps(result["counts"], indent=1))
    for row in result["kinds"][:40]:
        print(*row, sep="\t")


if __name__ == "__main__":
    main()
