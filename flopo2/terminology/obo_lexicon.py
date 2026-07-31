"""Generate deterministic grounding lexicons directly from pinned OBO sources."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from flopo2.terminology.catalog import load_obo_metadata


# PATO marks these aliases EXACT because they name the intended colour region once the source is
# known to be describing colour.  The accompanying OBO comments nevertheless require explicit
# colour context because the naked words are also botanical entities, shapes, or materials.  The
# generic grounding TSV has no context channel, so it must not expose these aliases
# unconditionally.  Compound colour forms (for example ``olive-green``) and preferred labels stay
# available; a context-aware extractor may separately opt into the naked forms.
CONTEXT_GATED_PATO_SYNONYMS: dict[str, frozenset[str]] = {
    "PATO_0104321": frozenset({"lemon"}),
    "PATO_0104329": frozenset({"chestnut"}),
    "PATO_0104333": frozenset({"chocolate"}),
    "PATO_0104336": frozenset({"olive"}),
}


def write_obo_lexicon(obo_path: Path, output: Path, ontology: str) -> int:
    """Write the TSV consumed by deterministic grounding and return its live-term count."""

    ontology = ontology.upper()
    if ontology not in {"PO", "PATO"}:
        raise ValueError("ontology must be PO or PATO")
    category_field = "namespace" if ontology == "PO" else "slim"
    fields = ("id", "label", "synonyms", category_field)
    rows = []
    for curie, metadata in load_obo_metadata(obo_path).items():
        if not curie.startswith(f"{ontology}_"):
            continue
        if metadata.get("deprecated") or not metadata.get("label"):
            continue
        synonyms = []
        exact_synonyms = {
            synonym
            for synonym, scope in metadata.get("synonym_scopes", ())
            if scope == "EXACT"
        }
        for synonym in metadata.get("synonyms", ()):
            # This TSV is consumed as an exact-grounding index.  PATO's BROAD, NARROW, and
            # RELATED synonyms are retrieval metadata, not interchangeable quality names.  In
            # particular, botanical colour terms such as ``blackish`` must not be collapsed to
            # ``black``.  PO retains its historical all-scope export for now; its contextual
            # grounding layer separately blocks non-exact forms using the OBO scope metadata.
            if ontology == "PATO" and synonym not in exact_synonyms:
                continue
            if (
                ontology == "PATO"
                and synonym.casefold()
                in CONTEXT_GATED_PATO_SYNONYMS.get(curie, frozenset())
            ):
                continue
            synonym = synonym.replace("|", "/").strip()
            if synonym and synonym not in synonyms:
                synonyms.append(synonym)
        category = (
            metadata.get("namespace", "")
            if ontology == "PO"
            else "|".join(metadata.get("subsets", ()))
        )
        rows.append(
            {
                "id": curie,
                "label": metadata["label"],
                "synonyms": "|".join(synonyms),
                category_field: category,
            }
        )

    rows.sort(key=lambda row: row["id"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("obo", type=Path)
    parser.add_argument("--ontology", required=True, choices=("PO", "PATO"))
    parser.add_argument("-o", "--out", type=Path, required=True)
    args = parser.parse_args()
    count = write_obo_lexicon(args.obo, args.out, args.ontology)
    print(f"{args.ontology} live terms: {count}; wrote {args.out}")


if __name__ == "__main__":
    main()
