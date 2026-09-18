"""Read curator-reviewed bearer aliases, including provisional FLOPO-local bearers.

``config/reviewed_local_bearers.tsv`` holds three review states:

* ``reviewed_existing_po`` -- exact aliases of live PO classes (consumed by the recovery passes);
* ``reviewed_flopo_local`` -- exact aliases of curator-approved FLOPO-local support classes that PO
  lacks (e.g. leaflet apex, indumentum, calyx lobe);
* ``reviewed_contextual_po`` -- ambiguous words (scale, bristle, awn, upper surface) whose PO class
  depends on context; never used as an unconditional alias.

FLOPO-local rows are only returned once their identifier is part of the released ontology, i.e.
present in ``config/flopo_id_registry.tsv``; before the release the gate would reject the unknown
identifier, so offering the alias would only create held assertions.
"""

from __future__ import annotations

import csv
from pathlib import Path


EXISTING_PO = "reviewed_existing_po"
FLOPO_LOCAL = "reviewed_flopo_local"
CONTEXTUAL_PO = "reviewed_contextual_po"
STATUSES = frozenset({EXISTING_PO, FLOPO_LOCAL, CONTEXTUAL_PO})


def released_flopo_ids(registry: Path = Path("config/flopo_id_registry.tsv")) -> set[str]:
    """Return ``FLOPO_nnnnnnn`` identifiers of the released ontology registry."""

    ids: set[str] = set()
    if not Path(registry).exists():
        return ids
    with Path(registry).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            iri = row.get("flopo_iri", "") or ""
            local = iri.rsplit("/", 1)[-1]
            if local.startswith("FLOPO_"):
                ids.add(local)
    return ids


def load_reviewed_bearers(
    path: Path = Path("config/reviewed_local_bearers.tsv"),
    *,
    include_flopo_local: bool = True,
    released_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    """Return unconditional (non-contextual) reviewed bearer aliases.

    ``released_ids`` defaults to the identifiers in ``config/flopo_id_registry.tsv``; pass an
    explicit set to evaluate a staged (unreleased) module.
    """

    rows: list[dict[str, str]] = []
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            status = row.get("review_status", "")
            if status not in STATUSES:
                raise ValueError(f"unknown review_status {status!r} for {row.get('surface_form')!r}")
            if status == EXISTING_PO:
                rows.append(row)
            elif status == FLOPO_LOCAL and include_flopo_local:
                if released_ids is None:
                    released_ids = released_flopo_ids()
                if row.get("po_id", "") in released_ids:
                    rows.append(row)
    return rows
