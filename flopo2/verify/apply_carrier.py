"""Give existing annotation records the carrier of pattern 16 (quality of a whole towards its parts).

    python -m flopo2.verify.apply_carrier local-corpora/*/derived/*-annotated.jsonl            # count only
    python -m flopo2.verify.apply_carrier --write-suffix .carrier <files>                     # write copies

A record such as "leaves alternate" keeps its part (leaf); it gains ``carrier`` (the shoot axis)
and the class identifier that follows from it (flopo2.owl.carrier). Without ``--write-suffix``
nothing is written: the counts say how many records of each part and value would change.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from flopo2.owl import carrier


def run(paths: list[Path], suffix: str | None) -> dict:
    counts: collections.Counter = collections.Counter()
    pairs: collections.Counter = collections.Counter()
    for path in paths:
        out = open(str(path) + suffix, "w", encoding="utf-8") if suffix else None
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                for assertion in record.get("assertions", []):
                    counts["assertions"] += 1
                    before = assertion.get("phenotype_class_iri")
                    if carrier.apply(assertion):
                        slot = assertion["carrier"]
                        counts[slot["kind"]] += 1
                        counts["class identifier changed"] += before != assertion.get("phenotype_class_iri")
                        pairs[(slot["kind"], assertion["po_id"], carrier.value_of(assertion), slot["carrier_term"])] += 1
                if out:
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
        if out:
            out.close()
    return {"counts": dict(counts), "pairs": [[*key, n] for key, n in pairs.most_common()]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--write-suffix", help="write each file with this suffix added; omit to count only")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = run(args.files, args.write_suffix)
    if args.report:
        args.report.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result["counts"], indent=1))
    for row in result["pairs"][:40]:
        print(*row, sep="\t")


if __name__ == "__main__":
    main()
