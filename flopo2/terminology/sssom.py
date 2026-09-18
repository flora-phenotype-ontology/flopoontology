"""SSSOM projection of reviewed one-to-one botanical terminology mappings."""

from __future__ import annotations

import csv
from pathlib import Path

from flopo2.terminology.model import RegistryEntry

_FIELDS = (
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "mapping_justification",
    "mapping_date",
    "author_id",
    "confidence",
    "mapping_tool",
    "mapping_source",
    "comment",
)


def write_sssom(entries: list[RegistryEntry], output: Path, include_auto: bool = False) -> int:
    allowed = {"reviewed", "accepted"} | ({"auto"} if include_auto else set())
    rows = []
    for entry in entries:
        compositional = entry.logical_operator in {"one_of", "all_of"} and entry.components
        if entry.review_status not in allowed or (not entry.target_id and not compositional):
            continue
        targets = entry.components if compositional else (entry.target_id,)
        for target in targets:
            target_label = entry.target_label if target == entry.target_id else ""
            predicate = entry.mapping_relation
            comment = entry.notes
            if compositional:
                predicate = "skos:relatedMatch"
                expression = entry.target_id or entry.term_id
                comment = (
                    f"component_of_{entry.logical_operator}:{expression}; {comment}"
                ).strip("; ")
            rows.append(
                {
                    "subject_id": entry.term_id,
                    "subject_label": entry.surface_form,
                    "predicate_id": predicate,
                    "object_id": target,
                    "object_label": target_label,
                    "mapping_justification": (
                        "semapv:ManualMappingCuration"
                        if entry.review_status in {"reviewed", "accepted"}
                        else "semapv:LexicalMatching"
                    ),
                    "mapping_date": entry.mapping_date,
                    "author_id": f"orcid:{entry.curator_orcid}" if entry.curator_orcid else "",
                    "confidence": entry.mapping_confidence,
                    "mapping_tool": entry.mapping_method,
                    "mapping_source": entry.source_url or entry.source_id,
                    "comment": comment,
                }
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# curie_map:\n")
        handle.write("#   BTERM: https://w3id.org/flopo/botanical-term/\n")
        handle.write("#   PO: http://purl.obolibrary.org/obo/PO_\n")
        handle.write("#   PATO: http://purl.obolibrary.org/obo/PATO_\n")
        handle.write("#   FLOPO: http://purl.obolibrary.org/obo/FLOPO_\n")
        writer = csv.DictWriter(handle, fieldnames=_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
