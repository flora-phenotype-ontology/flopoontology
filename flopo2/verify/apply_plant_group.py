"""Send to review the records that use a plant part of one plant group in another group.

The Plant Ontology defines some parts for one group of plants only: the spikelet "of the grasses"
and, as parts of it, glume, lemma, palea, lodicule and awn ("appendage of a glume, lemma, or
palea"). Floras use the same words for other organs elsewhere: the awns of an Asteraceae pappus,
of a Geranium fruit or of a moss leaf, the paleae on the receptacle of a daisy. The annotator
grounds the word, so such a record claims a grass spikelet in a daisy.

``config/po_plant_group_terms.tsv`` lists the root classes and the families they may be used in.
A record whose bearer is the root or below it (is_a, part_of), in a taxon of another family, gets
gate status ``review`` with the reason ``bearer_outside_plant_group``. Records without a family
are left alone.

    python -m flopo2.verify.apply_plant_group FILES                      # count only
    python -m flopo2.verify.apply_plant_group --write-suffix .group FILES
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

TABLE = Path("config/po_plant_group_terms.tsv")
REASON = "bearer_outside_plant_group"


class Guard:
    def __init__(self, table: Path = TABLE) -> None:
        from flopo2.saudi.vocab import Vocabulary

        self.vocab = Vocabulary()
        self.roots: dict[str, set[str]] = {}
        with table.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                self.roots[row["root"].replace("_", ":")] = {f.lower() for f in row["families"].split("|")}
        self._root_of: dict[str, str] = {}

    def root_of(self, bearer: str) -> str:
        key = str(bearer or "").replace("_", ":")
        if key not in self._root_of:
            start = key if key.startswith("PO:") else self.vocab._flopo_bearer(key) or key
            ancestors = set(self.vocab._ancestors(self.vocab.po, start, part_of=True))
            self._root_of[key] = next((root for root in self.roots if root in ancestors), "")
        return self._root_of[key]

    def apply(self, assertion: dict, family: str) -> bool:
        """True when the record was set to review."""

        if not family:
            return False
        root = self.root_of(assertion.get("po_id", ""))
        if not root or family.strip().lower() in self.roots[root]:
            return False
        gate = assertion.setdefault("gate", {})
        reasons = gate.setdefault("reasons", [])
        if REASON in reasons:
            return False
        reasons.append(REASON)
        if gate.get("status") in (None, "", "accepted", "review"):
            gate["status"] = "review"
        return True


def run(paths: list[Path], suffix: str | None) -> dict:
    guard = Guard()
    counts: collections.Counter = collections.Counter()
    kinds: collections.Counter = collections.Counter()
    for path in paths:
        out = open(str(path) + suffix, "w", encoding="utf-8") if suffix else None
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                family = record.get("taxon_family", "")
                for assertion in record.get("assertions", []):
                    counts["assertions"] += 1
                    if guard.apply(assertion, family):
                        counts["review"] += 1
                        kinds[((assertion.get("composition") or {}).get("entity_label", ""), family)] += 1
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
    for row in result["kinds"][:30]:
        print(*row, sep="\t")


if __name__ == "__main__":
    main()
