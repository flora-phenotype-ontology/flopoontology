"""Seed the PO×PATO validity table (whitelist / blocklist) from the FLOPO registry.

The 2016 ontology is our prior knowledge of which entity-quality combinations make sense:
  * A live (non-deprecated) ``EQ`` class is evidence the (PO, PATO) combination is *allowed*.
  * A deprecated ``EQ`` class is a combination judged *nonsensical* — it becomes a *blocklist*
    entry so the rebuild never recreates it (the proactive replacement for create-then-deprecate).

If a (PO, PATO) pair appears both live and deprecated across the registry, the blocklist wins
(conservative: a human cleared it once). Output columns: ``po_id``, ``pato_id``, ``status``
(allowed/blocked), ``source`` (2016_seed), ``example_label``.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from flopo2.ids.registry import load_registry


def seed_combinations(registry_tsv: Path, out_path: Path) -> dict:
    entries = load_registry(registry_tsv)
    allowed: dict[tuple[str, str], str] = {}
    blocked: dict[tuple[str, str], str] = {}
    # Deprecated classes whose defining axiom was stripped on deprecation (DeprecateDumbClasses.groovy
    # removed the equivalentClass), so their (PO, PATO) combination is not recoverable from flopo.owl.
    # We keep their IRIs+labels here to re-ground in Phase 8 and rebuild the full blocklist.
    unrecoverable_deprecated: list[tuple[str, str]] = []
    for e in entries:
        if e.signature.startswith("EQ|"):
            _, po, pato = e.signature.split("|", 2)
            key = (po, pato)
            if e.deprecated:
                blocked.setdefault(key, e.label)
            else:
                allowed.setdefault(key, e.label)
        elif e.deprecated:
            unrecoverable_deprecated.append((e.iri, e.label))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["po_id", "pato_id", "status", "source", "example_label"])
        for (po, pato), label in sorted(blocked.items()):
            w.writerow([po, pato, "blocked", "2016_seed", label])
        for (po, pato), label in sorted(allowed.items()):
            if (po, pato) in blocked:  # blocklist wins
                continue
            w.writerow([po, pato, "allowed", "2016_seed", label])

    # Companion file: deprecated classes needing label-grounding to recover their blocked combo.
    companion = out_path.parent / "deprecated_to_reground.tsv"
    with companion.open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["flopo_iri", "label"])
        for iri, label in sorted(unrecoverable_deprecated, key=lambda x: x[1]):
            w.writerow([iri, label])

    return {
        "allowed": len(allowed) - len(set(allowed) & set(blocked)),
        "blocked": len(blocked),
        "unrecoverable_deprecated": len(unrecoverable_deprecated),
        "out": str(out_path),
        "companion": str(companion),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed config/valid_combinations.tsv from the registry.")
    ap.add_argument(
        "registry", type=Path, nargs="?", default=Path("config/flopo_id_registry.tsv"),
        help="Registry TSV (default: config/flopo_id_registry.tsv)",
    )
    ap.add_argument("-o", "--out", type=Path, default=Path("config/valid_combinations.tsv"))
    args = ap.parse_args()
    s = seed_combinations(args.registry, args.out)
    print(f"Wrote {args.out}: {s['allowed']} allowed, {s['blocked']} blocked combinations")
    print(
        f"Wrote {s['companion']}: {s['unrecoverable_deprecated']} deprecated classes "
        f"needing label-grounding (axiom stripped on deprecation) to recover their blocked combo"
    )


if __name__ == "__main__":
    main()
