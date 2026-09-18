#!/usr/bin/env python3
"""Build the FLOPO ISCC-NBS colour backbone module (curator decisions of 2026-09-18).

Only ISCC-NBS level-1, level-2 and level-3 categories become colour classes.  Munsell ranges
and Kelly (1958) centroids are cited annotations, never logical axioms.  Vernacular colour
words are ``botanical_colour_name`` synonyms with an honest OBO scope.  The superseded FLOPO
colour classes are obsoleted, and every FLOPO class whose logical axioms used a colour that
now has a backbone reading is redefined in this module with its colour re-pointed.

Subcommands:

``import-design``
    One-off translation of the reviewed design tables (placeholder identifiers) into the
    committed configuration tables with real identifiers.  New FLOPO identifiers come from
    the reserved block FLOPO:0988000-0988999; an existing allocation is never changed.

``build``
    Read the configuration tables and the current ``ontology/flopo.owl`` and write
    ``ontology/flopo-colour-backbone.ttl``, the pipeline crosswalk
    ``config/colour_backbone_crosswalk.tsv`` and the change list
    ``curation/flopo_colour_backbone_eq_changes.tsv``.  Re-running the build on a release
    that already embeds the module reproduces the same module.

Re-pointing rules (source colour -> backbone):

* A PATO colour whose word is an EXACT backbone name is replaced by the backbone class; the
  class keeps its EquivalentTo axiom.
* A superseded FLOPO colour class, or one of the nine PATO requests withdrawn upstream
  (PATO issue 617), is replaced by its backbone target: EXACT keeps EquivalentTo; NARROW
  uses the covering backbone class in a SubClassOf axiom; RELATED falls back to
  PATO:0000014 color in a SubClassOf axiom, because no backbone class below color covers it.
* Any other PATO colour (NARROW or RELATED word, e.g. ochre, maroon, lilac) stays as it is:
  the PATO class is live and its EquivalentTo axiom remains accurate.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import itertools
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flopo2.ids.registry import _signature_of  # noqa: E402


OBO = Namespace("http://purl.obolibrary.org/obo/")
OBO_IN_OWL = Namespace("http://www.geneontology.org/formats/oboInOwl#")
MODULE = URIRef(OBO + "flopo-colour-backbone.owl")

# owl:Axiom reification nodes (one per annotated range/centroid/dbxref/synonym; there are
# thousands) are skolemized to stable, sequentially-numbered IRIs in this module's own namespace
# rather than left as rdflib BNodes. Two things make that safe: (1) axiom-annotation reification
# is pure metadata that no reasoner or downstream tool treats as a named class or individual, so
# giving it a persistent name changes nothing semantically; (2) it sidesteps two performance
# cliffs that blank nodes would otherwise force here -- full graph-isomorphism canonicalization
# (``rdflib.compare.to_canonical_graph``) at serialization time, and again at release-embedding
# time, since the embedding step re-parses the committed Turtle file and rdflib's parser assigns
# a *fresh random* blank-node identity on every parse (so blank nodes could never be reproducible
# across separate build/embed invocations anyway). Every genuine anonymous OWL class expression
# (unionOf/intersectionOf/restriction, built in ``_Rewriter``) stays a real BNode: the release
# tooling tells a named class from an anonymous expression by ``isinstance(x, URIRef)``, and an
# expression skolemized this way would be miscounted as a declared class.
_AXIOM_NODE_COUNTER = itertools.count()


def _new_axiom_node() -> URIRef:
    return URIRef(f"{MODULE}#axiom_{next(_AXIOM_NODE_COUNTER):06d}")


# Anonymous OWL class-expression nodes (unionOf/intersectionOf/restriction, and the rdf:List
# cells that carry their members) built while re-pointing a redefined EQ class's colour filler
# are skolemized the same way and for the same reason (see the note above): as real rdflib
# BNodes they would need full graph canonicalization at release-embedding time, and with roughly
# four such nodes for each of the ~1,400 redefined EQ classes that is prohibitively slow. They
# use their own IRI shape (``#expr_...``) so that ``_logical_iris`` and the release tooling can
# tell an anonymous expression from a genuine named class purely from the IRI, without needing
# ``isinstance(x, BNode)``.
_EXPR_NODE_COUNTER = itertools.count()
EXPR_NODE_PREFIX = f"{MODULE}#expr_"


def _new_expr_node() -> URIRef:
    return URIRef(f"{EXPR_NODE_PREFIX}{next(_EXPR_NODE_COUNTER):06d}")


def _is_expr_node(node) -> bool:
    return isinstance(node, URIRef) and str(node).startswith(EXPR_NODE_PREFIX)


def _build_rdf_list(graph: Graph, members: list) -> URIRef:
    """Build an rdf:List of ``members`` using skolemized cells, never ``rdflib.collection.
    Collection`` (which allocates a fresh random ``BNode`` per continuation cell)."""

    if not members:
        return RDF.nil
    head = _new_expr_node()
    node = head
    last = len(members) - 1
    for index, member in enumerate(members):
        graph.add((node, RDF.first, member))
        if index == last:
            graph.add((node, RDF.rest, RDF.nil))
        else:
            nxt = _new_expr_node()
            graph.add((node, RDF.rest, nxt))
            node = nxt
    return head


def _reset_axiom_node_counter() -> None:
    global _AXIOM_NODE_COUNTER, _EXPR_NODE_COUNTER
    _AXIOM_NODE_COUNTER = itertools.count()
    _EXPR_NODE_COUNTER = itertools.count()


COLOR = OBO.PATO_0000014
IAO_DEF = OBO.IAO_0000115
IAO_EDITOR_NOTE = OBO.IAO_0000116
IAO_REPLACED_BY = OBO.IAO_0100001
CONSIDER = OBO_IN_OWL.consider
HAS_DBXREF = OBO_IN_OWL.hasDbXref
HAS_SYNONYM_TYPE = OBO_IN_OWL.hasSynonymType
SYNONYM_TYPE = URIRef(OBO + "flopo#botanical_colour_name")
SCOPE_PROPERTY = {
    "EXACT": OBO_IN_OWL.hasExactSynonym,
    "NARROW": OBO_IN_OWL.hasNarrowSynonym,
    "BROAD": OBO_IN_OWL.hasBroadSynonym,
    "RELATED": OBO_IN_OWL.hasRelatedSynonym,
}
SYNONYM_PROPERTIES = set(SCOPE_PROPERTY.values())
CURATOR = URIRef("https://orcid.org/0000-0001-8149-5890")
DECISION_DATE = "2026-09-18"
SP440_DOI = "DOI:10.6028/NBS.SP.440"
KELLY_DOI = "DOI:10.6028/jres.061.035"
SP440_URL = URIRef("https://doi.org/10.6028/NBS.SP.440")
KELLY_URL = URIRef("https://doi.org/10.6028/jres.061.035")

BLOCK_FIRST = 988000
BLOCK_LAST = 988999
PROPERTY_FIRST = 988900

# FLOPO-local annotation properties (key, number, label, definition).
ANNOTATION_PROPERTIES = (
    ("iscc_nbs_level", 988900, "ISCC-NBS level",
     "The Universal Color Language level (1, 2 or 3; NBS SP 440) at which the colour class is a "
     "named ISCC-NBS category. A class whose extension is the same at several levels carries one "
     "value per level."),
    ("iscc_nbs_block_number", 988901, "ISCC-NBS block number",
     "The number (1-267) of the ISCC-NBS level-3 colour-name block that the class denotes (NBS SP 440)."),
    ("iscc_nbs_abbreviation", 988902, "ISCC-NBS abbreviation",
     "The standard ISCC-NBS abbreviation of the colour name, as printed in NBS SP 440."),
    ("iscc_nbs_level3_blocks", 988903, "ISCC-NBS level-3 blocks",
     "Space-separated numbers of the ISCC-NBS level-3 blocks whose union is the extension of the class."),
    ("munsell_range", 988904, "Munsell range",
     "One closed Munsell hue/value/chroma box of an ISCC-NBS block, measured from the NBS SP 440 "
     "hue-range charts (pp. 16-31). Several values describe a non-convex block. A boundary point "
     "takes the names of all touching blocks (SP 440 p. 15). Descriptive annotation, not a logical axiom."),
    ("munsell_centroid", 988905, "Munsell centroid",
     "The central notation (Munsell renotation) of an ISCC-NBS block as published by Kelly (1958), Table 1."),
    ("munsell_centroid_location", 988906, "Munsell centroid location",
     "Whether Kelly (1958) marks the central notation of the block as peripheral or interior."),
)
PROPERTY_IRIS = {key: OBO[f"FLOPO_{number:07d}"] for key, number, _label, _definition in ANNOTATION_PROPERTIES}

# PATO requests withdrawn upstream (PATO issue 617 closed; curator decision B2 of 2026-09-18).
WITHDRAWN_PATO = frozenset(
    {
        "PATO:0104314",  # crimson
        "PATO:0104317",  # scarlet
        "PATO:0104321",  # lemon yellow
        "PATO:0104324",  # mahogany red
        "PATO:0104326",  # salmon colour
        "PATO:0104329",  # chestnut colour
        "PATO:0104333",  # chocolate brown
        "PATO:0104336",  # olive colour
        "PATO:0104343",  # straw yellow
    }
)

PATHS = {
    "registry": Path("config/flopo_colour_backbone_id_registry.tsv"),
    "backbone": Path("config/iscc_nbs_backbone.tsv"),
    "synonyms": Path("config/botanical_colour_synonyms.tsv"),
    "migration": Path("config/flopo_colour_backbone_migration.tsv"),
    "eq_plan": Path("config/flopo_colour_eq_repointing.tsv"),
    "sssom": Path("ontology/flopo-colour-backbone.sssom.tsv"),
    "crosswalk": Path("config/colour_backbone_crosswalk.tsv"),
    "module": Path("ontology/flopo-colour-backbone.ttl"),
    "changes": Path("curation/flopo_colour_backbone_eq_changes.tsv"),
    "release": Path("ontology/flopo.owl"),
}

REGISTRY_FIELDS = (
    "proposal_key",
    "ontology_id",
    "label",
    "kind",
    "iscc_nbs_level",
    "iscc_nbs_number",
    "status",
    "canonical_key",
)
CROSSWALK_FIELDS = (
    "source_id",
    "source_label",
    "source_status",
    "word_scope",
    "backbone_id",
    "backbone_label",
    "canonical_id",
    "eq_axiom",
)
CHANGE_FIELDS = (
    "flopo_id",
    "label",
    "change",
    "old_colours",
    "new_colours",
    "note",
)
B3_NOTE = (
    "Curator decision B3 (2026-09-18): 'pale X' is EXACT only where ISCC-NBS itself names the "
    "block that way; otherwise NARROW."
)


# --------------------------------------------------------------------------- helpers


def read_tsv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        lines = [line for line in handle if not line.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def tsv_text(fields: tuple[str, ...] | list[str], rows: list[dict[str, str]], header: str = "") -> str:
    buffer = io.StringIO()
    buffer.write(header)
    writer = csv.DictWriter(
        buffer, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore"
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def iri(curie: str) -> URIRef:
    prefix, local = curie.replace("_", ":", 1).split(":", 1)
    return OBO[f"{prefix}_{local}"]


def curie(node: URIRef) -> str:
    value = str(node)
    if not value.startswith(str(OBO)):
        return value
    local = value[len(str(OBO)):]
    return local.replace("_", ":", 1) if re.fullmatch(r"[A-Za-z]+_\d+", local) else value


def underscore(curie_or_id: str) -> str:
    return curie_or_id.replace(":", "_", 1)


def design_key(placeholder: str) -> str:
    return "ISCCNBS:" + placeholder.split(":", 1)[1]


# --------------------------------------------------------------------------- import-design


def _canonical_placeholders(pd_rows: list[dict[str, str]]) -> dict[str, str]:
    blocksets = {
        row["backbone_id"]: frozenset(int(x) for x in row["level3_blocks"].split()) for row in pd_rows
    }
    extension: dict[frozenset[int], str] = {}
    for row in sorted(pd_rows, key=lambda r: int(r["level"])):
        extension.setdefault(blocksets[row["backbone_id"]], row["backbone_id"])
    return {bid: extension[blockset] for bid, blockset in blocksets.items()}


def import_design(design: Path, root: Path = ROOT) -> dict[str, int]:
    """Translate the reviewed design tables to committed tables with real identifiers."""

    pd_rows = read_tsv(design / "iscc_nbs_backbone_pd.tsv")
    reuse = json.loads((design / "work" / "pato_reuse.json").read_text(encoding="utf-8"))
    by_placeholder = {row["backbone_id"]: row for row in pd_rows}
    canonical = _canonical_placeholders(pd_rows)
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in pd_rows:
        groups[canonical[row["backbone_id"]]].append(row)
    ordered = sorted(
        groups,
        key=lambda bid: (int(by_placeholder[bid]["level"]), int(by_placeholder[bid]["iscc_nbs_number"])),
    )
    homonyms: dict[str, set[str]] = defaultdict(set)
    for row in pd_rows:
        homonyms[row["name"]].add(canonical[row["backbone_id"]])

    registry_path = root / PATHS["registry"]
    previous = {row["proposal_key"]: row for row in read_tsv(registry_path)} if registry_path.exists() else {}
    used_numbers = {
        int(row["ontology_id"].split(":")[1])
        for row in previous.values()
        if row["ontology_id"].startswith("FLOPO:")
    }

    def next_number() -> int:
        number = BLOCK_FIRST
        while number in used_numbers:
            number += 1
        if number >= PROPERTY_FIRST:
            raise ValueError("colour backbone class block FLOPO:0988000-0988899 is exhausted")
        used_numbers.add(number)
        return number

    ontology_id: dict[str, str] = {}
    labels: dict[str, str] = {}
    for bid in ordered:
        key = design_key(bid)
        if key in previous:
            ontology_id[bid] = previous[key]["ontology_id"]
        elif bid in reuse:
            ontology_id[bid] = reuse[bid]
        else:
            ontology_id[bid] = f"FLOPO:{next_number():07d}"
        representative = max(groups[bid], key=lambda r: int(r["level"]))
        label = representative["name"]
        if len(homonyms[label]) > 1 and representative["level"] != "1":
            label = f"{label} (ISCC-NBS level {representative['level']})"
        labels[bid] = label

    registry_rows: list[dict[str, str]] = []
    for bid in ordered:
        levels = sorted({row["level"] for row in groups[bid]})
        representative = max(groups[bid], key=lambda r: int(r["level"]))
        for row in sorted(groups[bid], key=lambda r: int(r["level"])):
            is_canonical = row["backbone_id"] == bid
            status = (
                "existing_pato_reused"
                if ontology_id[bid].startswith("PATO:")
                else "new_flopo_local"
            )
            registry_rows.append(
                {
                    "proposal_key": design_key(row["backbone_id"]),
                    "ontology_id": ontology_id[bid],
                    "label": labels[bid] if is_canonical else row["name"],
                    "kind": "backbone_class",
                    "iscc_nbs_level": ",".join(levels) if is_canonical else row["level"],
                    "iscc_nbs_number": representative["iscc_nbs_number"] if representative["level"] == "3" else "",
                    "status": status if is_canonical else "merged_into_canonical",
                    "canonical_key": design_key(bid),
                }
            )
    for key, number, label, _definition in ANNOTATION_PROPERTIES:
        registry_rows.append(
            {
                "proposal_key": f"ISCCNBS:property_{key}",
                "ontology_id": f"FLOPO:{number:07d}",
                "label": label,
                "kind": "annotation_property",
                "iscc_nbs_level": "",
                "iscc_nbs_number": "",
                "status": "new_flopo_local",
                "canonical_key": "",
            }
        )
    registry_rows.append(
        {
            "proposal_key": "ISCCNBS:synonym_type_botanical_colour_name",
            "ontology_id": str(SYNONYM_TYPE),
            "label": "botanical colour name",
            "kind": "synonym_type",
            "iscc_nbs_level": "",
            "iscc_nbs_number": "",
            "status": "new_flopo_local",
            "canonical_key": "",
        }
    )
    for key, row in previous.items():
        if key not in {r["proposal_key"] for r in registry_rows}:
            raise ValueError(f"registry row disappeared from the design: {key}")
        new = next(r for r in registry_rows if r["proposal_key"] == key)
        if new["ontology_id"] != row["ontology_id"]:
            raise ValueError(f"registry allocation changed for {key}")
    (root / PATHS["registry"]).write_text(tsv_text(REGISTRY_FIELDS, registry_rows), encoding="utf-8")

    def real(placeholder: str) -> str:
        if not placeholder.startswith("ISCCNBS_PLACEHOLDER:"):
            return placeholder
        return ontology_id[canonical[placeholder]]

    # normative backbone table
    backbone_fields = ["ontology_id", "canonical_ontology_id", "design_key"] + [
        field for field in pd_rows[0] if field != "backbone_id"
    ] + ["parent_ontology_id"]
    backbone_rows = []
    for row in pd_rows:
        out = {field: row[field] for field in row if field != "backbone_id"}
        out["ontology_id"] = real(row["backbone_id"])
        out["canonical_ontology_id"] = real(row["backbone_id"])
        out["design_key"] = design_key(row["backbone_id"])
        out["parent_id"] = design_key(row["parent_id"]) if row["parent_id"].startswith("ISCCNBS_") else row["parent_id"]
        out["parent_ontology_id"] = real(row["parent_id"])
        backbone_rows.append(out)
    (root / PATHS["backbone"]).write_text(
        tsv_text(backbone_fields, backbone_rows), encoding="utf-8"
    )

    # synonyms, with B3 applied
    synonym_rows = read_tsv(design / "botanical_colour_synonyms.tsv")
    synonym_fields = ["word", "language", "ontology_id"] + [
        field for field in synonym_rows[0] if field not in {"word", "language", "backbone_id"}
    ] + ["design_key"]
    b3 = 0
    for row in synonym_rows:
        row["design_key"] = design_key(row["backbone_id"])
        row["ontology_id"] = real(row["backbone_id"])
        row["backbone_label"] = labels[canonical[row["backbone_id"]]]
        flags = [flag for flag in row["flags"].split("|") if flag]
        if "gloss_equivalent_candidate_exact" in flags:
            b3 += 1
            row["scope"] = "NARROW"
            flags = [flag for flag in flags if flag != "gloss_equivalent_candidate_exact"]
            flags.append("b3_pale_gloss_narrow")
            row["flags"] = "|".join(flags)
            row["rationale"] = (
                row["rationale"].replace(" Kept RELATED under the literal-only EXACT rule.", "")
                + " " + B3_NOTE
            )
    (root / PATHS["synonyms"]).write_text(tsv_text(synonym_fields, synonym_rows), encoding="utf-8")

    migration_rows = read_tsv(design / "flopo_colour_class_migration.tsv")
    for row in migration_rows:
        if row["target"]:
            placeholder = row["target"]
            row["target"] = real(placeholder)
            row["target_label"] = labels[canonical[placeholder]] if placeholder.startswith("ISCCNBS_") else row["target_label"]
    (root / PATHS["migration"]).write_text(
        tsv_text(list(migration_rows[0].keys()), migration_rows), encoding="utf-8"
    )

    eq_rows = read_tsv(design / "eq_filler_repointing.tsv")
    for row in eq_rows:
        placeholder = row["new_filler"]
        row["new_filler"] = real(placeholder)
        if placeholder.startswith("ISCCNBS_"):
            row["new_filler_label"] = labels[canonical[placeholder]]
    (root / PATHS["eq_plan"]).write_text(tsv_text(list(eq_rows[0].keys()), eq_rows), encoding="utf-8")

    sssom_rows = read_tsv(design / "colour_mappings.sssom.tsv")
    kept = []
    for row in sssom_rows:
        placeholder = row["object_id"]
        row["object_id"] = real(placeholder)
        if placeholder.startswith("ISCCNBS_"):
            row["object_label"] = labels[canonical[placeholder]]
        if row["object_id"] == row["subject_id"]:
            continue  # a reused PATO class is itself the backbone class
        kept.append(row)
    header = (
        "# curie_map:\n"
        "#   PATO: http://purl.obolibrary.org/obo/PATO_\n"
        "#   FLOPO: http://purl.obolibrary.org/obo/FLOPO_\n"
        "#   skos: http://www.w3.org/2004/02/skos/core#\n"
        "#   semapv: https://w3id.org/semapv/vocab/\n"
        "#   sssom: https://w3id.org/sssom/\n"
        "# mapping_set_id: http://purl.obolibrary.org/obo/flopo/mappings/flopo-colour-backbone.sssom.tsv\n"
        "# mapping_set_description: Mappings of PATO colour classes and superseded FLOPO colour classes "
        "onto the FLOPO ISCC-NBS colour backbone (curator decision 2026-09-18). The predicate follows the "
        "OBO scope of the word: EXACT -> skos:exactMatch (skos:closeMatch when the source class is not "
        "ISCC-NBS defined), NARROW -> skos:broadMatch, RELATED -> skos:relatedMatch. The 27 reused PATO "
        "classes are backbone classes themselves and are not listed.\n"
        "# license: https://creativecommons.org/publicdomain/zero/1.0/\n"
        f"# mapping_date: {DECISION_DATE}\n"
    )
    (root / PATHS["sssom"]).write_text(
        tsv_text(list(sssom_rows[0].keys()), kept, header=header), encoding="utf-8"
    )
    return {
        "registry_rows": len(registry_rows),
        "new_flopo_classes": sum(1 for v in set(ontology_id.values()) if v.startswith("FLOPO:")),
        "reused_pato_classes": sum(1 for v in set(ontology_id.values()) if v.startswith("PATO:")),
        "synonyms": len(synonym_rows),
        "b3_narrowed": b3,
        "migration_rows": len(migration_rows),
        "eq_plan_rows": len(eq_rows),
        "mappings": len(kept),
    }


# --------------------------------------------------------------------------- build


@dataclass(frozen=True)
class Mapping:
    source: URIRef
    source_label: str
    source_status: str  # pato_live | pato_withdrawn | flopo_obsolete
    scope: str  # EXACT | NARROW | RELATED | ""
    backbone: URIRef | None
    backbone_label: str

    @property
    def canonical(self) -> URIRef:
        """The colour that replaces the source in FLOPO logical axioms."""

        if self.source_status == "pato_live":
            if self.scope == "EXACT" and self.backbone is not None:
                return self.backbone
            return self.source
        if self.scope in {"EXACT", "NARROW"} and self.backbone is not None:
            return self.backbone
        return COLOR

    @property
    def exact(self) -> bool:
        return self.canonical == self.source or self.scope == "EXACT"


@dataclass
class Inputs:
    registry: list[dict[str, str]]
    backbone: list[dict[str, str]]
    synonyms: list[dict[str, str]]
    migration: list[dict[str, str]]
    sssom: list[dict[str, str]]


def load_inputs(root: Path = ROOT) -> Inputs:
    return Inputs(
        registry=read_tsv(root / PATHS["registry"]),
        backbone=read_tsv(root / PATHS["backbone"]),
        synonyms=read_tsv(root / PATHS["synonyms"]),
        migration=read_tsv(root / PATHS["migration"]),
        sssom=read_tsv(root / PATHS["sssom"]),
    )


def build_mappings(inputs: Inputs) -> dict[URIRef, Mapping]:
    obsolete = {row["flopo_id"]: row for row in inputs.migration if row["action"] == "obsolete"}
    mappings: dict[URIRef, Mapping] = {}
    for row in inputs.sssom:
        subject = row["subject_id"]
        if subject.startswith("FLOPO:") and subject not in obsolete:
            continue  # compositions keep their IDs and are rewritten through their operands
        if subject.startswith("FLOPO:"):
            status = "flopo_obsolete"
            migration = obsolete[subject]
            scope = "EXACT" if migration["replacement_property"] == "IAO:0100001" else row["synonym_scope"]
            target = migration["target"]
            target_label = migration["target_label"]
        else:
            status = "pato_withdrawn" if subject in WITHDRAWN_PATO else "pato_live"
            scope = row["synonym_scope"]
            target = row["object_id"] if row["predicate_id"] != "sssom:NoTermFound" else ""
            target_label = row["object_label"]
        mappings[iri(subject)] = Mapping(
            source=iri(subject),
            source_label=row["subject_label"],
            source_status=status,
            scope=scope,
            backbone=iri(target) if target else None,
            backbone_label=target_label,
        )
    for flopo_id, row in obsolete.items():
        if iri(flopo_id) not in mappings:
            raise ValueError(f"obsoleted FLOPO colour class lacks a mapping: {flopo_id}")
    for pato_id in WITHDRAWN_PATO:
        if iri(pato_id) not in mappings:
            raise ValueError(f"withdrawn PATO colour lacks a mapping: {pato_id}")
    return mappings


def _add_axiom(graph: Graph, source, prop, target, annotations: list[tuple[URIRef, object]]) -> None:
    axiom = _new_axiom_node()
    graph.add((axiom, RDF.type, OWL.Axiom))
    graph.add((axiom, OWL.annotatedSource, source))
    graph.add((axiom, OWL.annotatedProperty, prop))
    graph.add((axiom, OWL.annotatedTarget, target))
    for annotation_property, value in annotations:
        graph.add((axiom, annotation_property, value))


def _canonical_classes(inputs: Inputs) -> list[dict[str, str]]:
    registry = {row["proposal_key"]: row for row in inputs.registry}
    canonical_rows = []
    by_key = {row["design_key"]: row for row in inputs.backbone}
    for row in inputs.registry:
        if row["kind"] != "backbone_class" or row["status"] == "merged_into_canonical":
            continue
        members = [
            by_key[r["proposal_key"]]
            for r in inputs.registry
            if r["kind"] == "backbone_class" and r["canonical_key"] == row["proposal_key"]
        ]
        representative = max(members, key=lambda r: int(r["level"]))
        canonical_rows.append(
            {
                "ontology_id": row["ontology_id"],
                "label": row["label"],
                "status": row["status"],
                "levels": row["iscc_nbs_level"].split(","),
                "row": representative,
                "canonical_key": row["proposal_key"],
                "registry": registry[row["proposal_key"]],
            }
        )
    return canonical_rows


def _declare_vocabulary(graph: Graph) -> None:
    graph.add((MODULE, RDF.type, OWL.Ontology))
    graph.add((MODULE, DCTERMS.title, Literal("FLOPO ISCC-NBS colour backbone", lang="en")))
    graph.add(
        (
            MODULE,
            DCTERMS.description,
            Literal(
                "ISCC-NBS Universal Color Language levels 1-3 as FLOPO colour classes under "
                "PATO:0000014 color, with public-domain Munsell ranges (NBS SP 440 charts) and "
                "centroids (Kelly 1958) as cited annotations, botanical colour words as "
                "botanical_colour_name synonyms, the obsoleted FLOPO colour classes and the FLOPO "
                "classes whose colour was re-pointed. Curator decision 2026-09-18.",
                lang="en",
            ),
        )
    )
    graph.add((MODULE, DCTERMS.license, URIRef("https://creativecommons.org/publicdomain/zero/1.0/")))
    for key, _number, label, definition in ANNOTATION_PROPERTIES:
        prop = PROPERTY_IRIS[key]
        graph.add((prop, RDF.type, OWL.AnnotationProperty))
        graph.add((prop, RDFS.label, Literal(label, lang="en")))
        graph.add((prop, IAO_DEF, Literal(definition, lang="en")))
        graph.add((prop, DCTERMS.source, SP440_URL))
    graph.add((SYNONYM_TYPE, RDF.type, OWL.AnnotationProperty))
    graph.add((SYNONYM_TYPE, RDFS.subPropertyOf, OBO_IN_OWL.SynonymTypeProperty))
    graph.add((SYNONYM_TYPE, RDFS.label, Literal("botanical colour name", lang="en")))
    graph.add(
        (
            SYNONYM_TYPE,
            RDFS.comment,
            Literal(
                "Synonym type for a flora colour word attached to an ISCC-NBS backbone class. "
                "EXACT only for a literal ISCC-NBS name or its spelling or translation variant; "
                "a vernacular word attaches NARROW to the lowest class covering its documented "
                "senses, or RELATED when those senses cross level-1 categories.",
                lang="en",
            ),
        )
    )
    for prop in (
        OBO_IN_OWL.SynonymTypeProperty,
        HAS_SYNONYM_TYPE,
        HAS_DBXREF,
        CONSIDER,
        IAO_REPLACED_BY,
        DCTERMS.bibliographicCitation,
        *SYNONYM_PROPERTIES,
    ):
        graph.add((prop, RDF.type, OWL.AnnotationProperty))


def _backbone_classes(graph: Graph, inputs: Inputs) -> dict[URIRef, str]:
    labels: dict[URIRef, str] = {}
    for entry in _canonical_classes(inputs):
        cls = iri(entry["ontology_id"])
        row = entry["row"]
        level = row["level"]
        new = entry["status"] == "new_flopo_local"
        labels[cls] = entry["label"]
        if new:
            graph.add((cls, RDF.type, OWL.Class))
        if new:
            graph.add((cls, RDFS.label, Literal(entry["label"], lang="en")))
            if level == "3":
                definition = (
                    "A color whose Munsell hue, value, and chroma fall within ISCC-NBS color-name "
                    f"block {row['iscc_nbs_number']} ({row['name']}), for which the published "
                    f"central notation is {row['centroid_munsell']}."
                )
                xrefs = [SP440_DOI, KELLY_DOI]
            else:
                definition = (
                    "A color whose Munsell coordinates fall within the ISCC-NBS level-"
                    f"{level} category {row['name']}, the union of color-name blocks "
                    f"{row['level3_blocks']}."
                )
                xrefs = [SP440_DOI]
            graph.add((cls, IAO_DEF, Literal(definition, lang="en")))
            _add_axiom(
                graph, cls, IAO_DEF, Literal(definition, lang="en"),
                [(HAS_DBXREF, Literal(x)) for x in xrefs],
            )
            graph.add((cls, DCTERMS.contributor, CURATOR))
            graph.add((cls, DCTERMS.created, Literal(DECISION_DATE, datatype=XSD.date)))
        graph.add((cls, DCTERMS.source, SP440_URL))
        if level == "3":
            graph.add((cls, DCTERMS.source, KELLY_URL))
        for value in entry["levels"]:
            graph.add((cls, PROPERTY_IRIS["iscc_nbs_level"], Literal(value)))
        if level == "3":
            graph.add((cls, PROPERTY_IRIS["iscc_nbs_block_number"], Literal(row["iscc_nbs_number"])))
        graph.add((cls, PROPERTY_IRIS["iscc_nbs_abbreviation"], Literal(row["abbreviation"])))
        blocks = Literal(row["level3_blocks"])
        graph.add((cls, PROPERTY_IRIS["iscc_nbs_level3_blocks"], blocks))
        _add_axiom(
            graph, cls, PROPERTY_IRIS["iscc_nbs_level3_blocks"], blocks,
            [(HAS_DBXREF, Literal(SP440_DOI)), (DCTERMS.bibliographicCitation, Literal(row["range_source"]))],
        )
        if level == "3":
            for box in row["munsell_ranges"].split(" || "):
                value = Literal(box)
                graph.add((cls, PROPERTY_IRIS["munsell_range"], value))
                _add_axiom(
                    graph, cls, PROPERTY_IRIS["munsell_range"], value,
                    [(HAS_DBXREF, Literal(SP440_DOI)), (DCTERMS.bibliographicCitation, Literal(row["range_source"]))],
                )
            if row["centroid_munsell"]:
                value = Literal(row["centroid_munsell"])
                graph.add((cls, PROPERTY_IRIS["munsell_centroid"], value))
                _add_axiom(
                    graph, cls, PROPERTY_IRIS["munsell_centroid"], value,
                    [(HAS_DBXREF, Literal(KELLY_DOI)), (DCTERMS.bibliographicCitation, Literal(row["centroid_source"]))],
                )
            if row["centroid_location"]:
                graph.add((cls, PROPERTY_IRIS["munsell_centroid_location"], Literal(row["centroid_location"])))
        parent = iri(row["parent_ontology_id"]) if row["parent_ontology_id"] else COLOR
        if level == "1" or parent == cls:
            parent = COLOR
        graph.add((cls, RDFS.subClassOf, parent))
    return labels


def _logical_iris(graph: Graph, node, seen: set | None = None) -> set[URIRef]:
    """Every named class or individual referenced (directly or through an anonymous class
    expression) by ``node``. A skolemized expression node (``_is_expr_node``) is transparent, just
    like a real BNode class expression would be; any other URIRef is a genuine named reference
    and is returned as a leaf, without recursing into it."""

    seen = seen if seen is not None else set()
    if isinstance(node, URIRef) and not _is_expr_node(node):
        return {node}
    if not (isinstance(node, BNode) or _is_expr_node(node)) or node in seen:
        return set()
    seen.add(node)
    found: set[URIRef] = set()
    for predicate, obj in graph.predicate_objects(node):
        if predicate == RDF.type:
            continue
        found |= _logical_iris(graph, obj, seen)
    return found


class _Rewriter:
    def __init__(self, source: Graph, target: Graph, mappings: dict[URIRef, Mapping]):
        self.source = source
        self.target = target
        self.mappings = mappings

    def rewrite(self, node, used: list[Mapping]):
        if isinstance(node, URIRef):
            mapping = self.mappings.get(node)
            if mapping is None or mapping.canonical == node:
                return node
            used.append(mapping)
            return mapping.canonical
        if not isinstance(node, BNode):
            return node
        union_head = self.source.value(node, OWL.unionOf)
        if union_head is not None:
            members = []
            for member in Collection(self.source, union_head):
                rewritten = self.rewrite(member, used)
                if rewritten not in members:
                    members.append(rewritten)
            if COLOR in members:
                return COLOR
            if len(members) == 1:
                return members[0]
            # Skolemized, not a real BNode: see the ``_new_expr_node`` note above its definition.
            new = _new_expr_node()
            self.target.add((new, RDF.type, OWL.Class))
            head = _build_rdf_list(self.target, members)
            self.target.add((new, OWL.unionOf, head))
            return new
        intersection_head = self.source.value(node, OWL.intersectionOf)
        new = _new_expr_node()
        for predicate, obj in self.source.predicate_objects(node):
            if predicate == OWL.intersectionOf:
                members = [self.rewrite(member, used) for member in Collection(self.source, obj)]
                head = _build_rdf_list(self.target, members)
                self.target.add((new, predicate, head))
            elif predicate in {RDF.first, RDF.rest}:
                raise ValueError("unexpected bare RDF list in a class expression")
            else:
                self.target.add((new, predicate, self.rewrite(obj, used)))
        del intersection_head
        return new


def _label(graph: Graph, node: URIRef) -> str:
    return str(next(graph.objects(node, RDFS.label), ""))


def _transform_class(
    release: Graph,
    module: Graph,
    cls: URIRef,
    mappings: dict[URIRef, Mapping],
    labels: dict[URIRef, str],
) -> dict[str, str]:
    rewriter = _Rewriter(release, module, mappings)
    converted: list[Mapping] = []
    all_used: list[Mapping] = []
    for predicate, obj in release.predicate_objects(cls):
        if predicate == OWL.equivalentClass:
            used: list[Mapping] = []
            rewritten = rewriter.rewrite(obj, used)
            all_used.extend(used)
            if all(mapping.exact for mapping in used):
                module.add((cls, OWL.equivalentClass, rewritten))
            else:
                converted.extend(mapping for mapping in used if not mapping.exact)
                if rewritten != cls:
                    module.add((cls, RDFS.subClassOf, rewritten))
        elif predicate == RDFS.subClassOf:
            used = []
            rewritten = rewriter.rewrite(obj, used)
            all_used.extend(used)
            if rewritten != cls:
                module.add((cls, RDFS.subClassOf, rewritten))
        elif isinstance(obj, BNode):
            raise ValueError(f"unexpected anonymous annotation value on {cls}")
        else:
            module.add((cls, predicate, obj))
    if converted:
        described = sorted(
            {f"'{m.source_label}' ({curie(m.source)})" for m in converted}
        )
        targets = sorted(
            {f"'{labels.get(m.canonical, 'color' if m.canonical == COLOR else m.backbone_label)}' ({curie(m.canonical)})" for m in converted}
        )
        note = (
            "ISCC-NBS colour backbone migration (curator decision 2026-09-18): the former logical "
            f"definition used {', '.join(described)}, which has no exact backbone class. The "
            "EquivalentTo axiom was replaced by SubClassOf with the covering colour "
            f"{', '.join(targets)}; the class keeps its identifier."
        )
        module.add((cls, IAO_EDITOR_NOTE, Literal(note, lang="en")))
    old = sorted({curie(m.source) for m in all_used})
    new = sorted({curie(m.canonical) for m in all_used})
    return {
        "flopo_id": curie(cls),
        "label": _label(release, cls),
        "change": "equivalence_to_subclass" if converted else "filler_repointed",
        "old_colours": "|".join(old),
        "new_colours": "|".join(new),
        "note": "",
    }


def _obsolete_stub(
    release: Graph, module: Graph, cls: URIRef, migration: dict[str, str], target_label: str
) -> None:
    label = _label(release, cls)
    module.add((cls, RDF.type, OWL.Class))
    module.add((cls, RDFS.label, Literal(f"obsolete {label}", lang="en")))
    for predicate, obj in release.predicate_objects(cls):
        if predicate in {RDF.type, RDFS.label, RDFS.subClassOf, OWL.equivalentClass, OWL.deprecated}:
            continue
        if predicate in SYNONYM_PROPERTIES or isinstance(obj, BNode):
            continue
        if predicate == IAO_DEF:
            text = str(obj)
            obj = Literal(text if text.startswith("OBSOLETE.") else f"OBSOLETE. {text}", lang="en")
        module.add((cls, predicate, obj))
    target = iri(migration["target"])
    replaced = migration["replacement_property"] == "IAO:0100001"
    module.add((cls, IAO_REPLACED_BY if replaced else CONSIDER, target))
    module.add((cls, OWL.deprecated, Literal(True)))
    module.add((cls, DCTERMS.modified, Literal(DECISION_DATE, datatype=XSD.date)))
    reason = (
        "Obsoleted by the ISCC-NBS colour backbone (curator decision 2026-09-18): FLOPO keeps only "
        "ISCC-NBS level-1 to level-3 colour classes, and colour words become botanical_colour_name "
        f"synonyms. {'Replaced by' if replaced else 'Consider'} '{target_label}' ({migration['target']}); "
        "the former label is now a synonym of that class."
    )
    module.add((cls, IAO_EDITOR_NOTE, Literal(reason, lang="en")))


def _norm(text: str) -> str:
    return re.sub(r"[\s-]+", " ", text.strip().lower())


def _synonyms(
    release: Graph,
    module: Graph,
    inputs: Inputs,
    labels: dict[URIRef, str],
    obsolete: dict[str, dict[str, str]],
    mappings: dict[URIRef, Mapping],
) -> dict[str, int]:
    entries: dict[tuple[URIRef, str, str, str], set[str]] = {}
    word_index: dict[tuple[str, str], list[tuple[URIRef, str, str, str]]] = defaultdict(list)
    for row in inputs.synonyms:
        cls = iri(row["ontology_id"])
        if _norm(row["word"]) == _norm(labels.get(cls, _label(release, cls))):
            continue
        key = (cls, row["scope"], row["word"], row["language"])
        entries.setdefault(key, set()).update(e for e in row["evidence"].split("|") if e)
        word_index[(_norm(row["word"]), row["language"])].append(key)
    moved = Counter()
    for flopo_id, migration in sorted(obsolete.items()):
        cls = iri(flopo_id)
        mapping = mappings[cls]
        texts = [(_label(release, cls), "en")]
        for predicate in SYNONYM_PROPERTIES:
            for value in release.objects(cls, predicate):
                texts.append((str(value), getattr(value, "language", None) or "en"))
        target = iri(migration["target"])
        scope = mapping.scope if mapping.scope in SCOPE_PROPERTY else "RELATED"
        for text, language in texts:
            if not text:
                continue
            existing = word_index.get((_norm(text), language))
            if existing:
                for key in existing:
                    entries[key].add(flopo_id)
                moved["xref_on_existing_synonym"] += 1
                continue
            if _norm(text) == _norm(labels.get(target, "")):
                moved["equal_to_target_label"] += 1
                continue
            key = (target, scope, text, language)
            entries.setdefault(key, set()).add(flopo_id)
            word_index[(_norm(text), language)].append(key)
            moved["new_synonym"] += 1
    for (cls, scope, text, language), xrefs in sorted(entries.items(), key=lambda kv: (str(kv[0][0]), kv[0][1], kv[0][2], kv[0][3])):
        value = Literal(text, lang=language)
        prop = SCOPE_PROPERTY[scope]
        module.add((cls, prop, value))
        _add_axiom(
            module, cls, prop, value,
            [(HAS_SYNONYM_TYPE, SYNONYM_TYPE)] + [(HAS_DBXREF, Literal(x)) for x in sorted(xrefs)],
        )
    moved["synonyms_total"] = len(entries)
    return dict(moved)


def _live_flopo_classes(graph: Graph) -> set[URIRef]:
    return {
        cls
        for cls in graph.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef)
        and str(cls).startswith(str(OBO) + "FLOPO_")
        and not any(str(v).lower() == "true" for v in graph.objects(cls, OWL.deprecated))
    }


def _signature_duplicates(graph: Graph, classes: set[URIRef]) -> dict[str, list[str]]:
    by_signature: dict[str, list[str]] = defaultdict(list)
    for cls in classes:
        signature = _signature_of(graph, cls)
        if signature != "OTHER":
            by_signature[signature].append(curie(cls))
    return {sig: sorted(ids) for sig, ids in by_signature.items() if len(ids) > 1}


def build(root: Path = ROOT, release_path: Path | None = None) -> dict:
    _reset_axiom_node_counter()
    inputs = load_inputs(root)
    release_path = release_path or root / PATHS["release"]
    release = Graph().parse(release_path.as_posix())
    mappings = build_mappings(inputs)
    obsolete = {row["flopo_id"]: row for row in inputs.migration if row["action"] == "obsolete"}
    obsolete_iris = {iri(k) for k in obsolete}

    module = Graph()
    _declare_vocabulary(module)
    labels = _backbone_classes(module, inputs)
    backbone = set(labels)

    # FLOPO classes whose logical axioms use a colour with a different canonical reading.
    changing = {source for source, mapping in mappings.items() if mapping.canonical != source}
    affected: set[URIRef] = set()
    for cls in _live_flopo_classes(release) - obsolete_iris - backbone:
        for predicate in (OWL.equivalentClass, RDFS.subClassOf):
            for obj in release.objects(cls, predicate):
                if _logical_iris(release, obj) & changing:
                    affected.add(cls)
    changes = []
    for cls in sorted(affected, key=str):
        changes.append(_transform_class(release, module, cls, mappings, labels))
    for flopo_id, migration in sorted(obsolete.items()):
        _obsolete_stub(release, module, iri(flopo_id), migration, migration["target_label"])
        changes.append(
            {
                "flopo_id": flopo_id,
                "label": _label(release, iri(flopo_id)),
                "change": "obsoleted",
                "old_colours": "",
                "new_colours": migration["target"],
                "note": migration["replacement_property"],
            }
        )
    synonym_counts = _synonyms(release, module, inputs, labels, obsolete, mappings)

    # No live FLOPO class may still reference an obsoleted colour or a withdrawn PATO request.
    forbidden = obsolete_iris | {iri(p) for p in WITHDRAWN_PATO}
    for cls in _live_flopo_classes(module):
        for predicate in (OWL.equivalentClass, RDFS.subClassOf):
            for obj in module.objects(cls, predicate):
                leaked = _logical_iris(module, obj) & forbidden
                if leaked:
                    raise ValueError(f"{curie(cls)} still uses {sorted(map(curie, leaked))}")

    # Duplicate check: signatures of live classes before and after the change.
    replaced = affected | obsolete_iris
    merged = Graph()
    for triple in release:
        if triple[0] not in replaced:
            merged.add(triple)
    for triple in module:
        merged.add(triple)
    before = _signature_duplicates(release, _live_flopo_classes(release))
    after = _signature_duplicates(merged, _live_flopo_classes(merged))
    new_duplicates = {sig: ids for sig, ids in after.items() if before.get(sig) != ids}

    module_path = root / PATHS["module"]
    module_text = _serialize_module(module)
    module_path.write_text(module_text, encoding="utf-8")

    crosswalk_rows = []
    for source, mapping in sorted(mappings.items(), key=lambda kv: str(kv[0])):
        crosswalk_rows.append(
            {
                "source_id": underscore(curie(source)),
                "source_label": mapping.source_label,
                "source_status": mapping.source_status,
                "word_scope": mapping.scope,
                "backbone_id": underscore(curie(mapping.backbone)) if mapping.backbone else "",
                "backbone_label": mapping.backbone_label,
                "canonical_id": underscore(curie(mapping.canonical)),
                "eq_axiom": "EquivalentTo" if mapping.exact else "SubClassOf",
            }
        )
    for cls, label in sorted(labels.items(), key=lambda kv: str(kv[0])):
        crosswalk_rows.append(
            {
                "source_id": underscore(curie(cls)),
                "source_label": label,
                "source_status": "backbone",
                "word_scope": "EXACT",
                "backbone_id": underscore(curie(cls)),
                "backbone_label": label,
                "canonical_id": underscore(curie(cls)),
                "eq_axiom": "EquivalentTo",
            }
        )
    header = (
        "# Colour crosswalk for the extraction pipeline (generated by "
        "tools/build_flopo_colour_backbone.py; do not edit).\n"
        "# canonical_id is the colour FLOPO uses in logical axioms for source_id; rows with "
        "eq_axiom=SubClassOf generalise the source and never define an EquivalentTo class.\n"
    )
    (root / PATHS["crosswalk"]).write_text(
        tsv_text(CROSSWALK_FIELDS, crosswalk_rows, header=header), encoding="utf-8"
    )
    (root / PATHS["changes"]).write_text(tsv_text(CHANGE_FIELDS, changes), encoding="utf-8")

    change_counts = Counter(row["change"] for row in changes)
    return {
        "backbone_classes": len(labels),
        "new_flopo_backbone_classes": sum(1 for c in labels if str(c).startswith(str(OBO) + "FLOPO_")),
        "reused_pato_backbone_classes": sum(1 for c in labels if str(c).startswith(str(OBO) + "PATO_")),
        "obsoleted": len(obsolete),
        "redefined_classes": len(affected),
        "changes": dict(change_counts),
        "synonyms": synonym_counts,
        "new_signature_duplicates": new_duplicates,
        "module_sha256": hashlib.sha256(module_text.encode("utf-8")).hexdigest(),
    }


def _serialize_module(module: Graph) -> str:
    # A plain copy is enough here: the graph is serialized once, directly from the in-memory
    # object built by this process, so cross-references between a blank node and its uses (e.g. an
    # rdf:List head and its owl:intersectionOf/unionOf subject) are already consistent by Python
    # object identity. Full isomorphism canonicalization (``rdflib.compare.to_canonical_graph``)
    # would additionally make the blank-node *labels* stable across separate builds, but for a
    # graph with thousands of blank nodes (the class-expression trees of ~1,400 redefined EQ
    # classes) it is prohibitively slow, and is not needed for correctness: tests compare modules
    # with ``rdflib.compare.isomorphic``, which never depends on blank-node identity. The
    # owl:Axiom reification nodes, which dominate the blank-node count, are already skolemized to
    # stable IRIs by ``_new_axiom_node`` and so are unaffected either way.
    out = Graph()
    for triple in module:
        out.add(triple)
    out.bind("obo", OBO)
    out.bind("oboInOwl", OBO_IN_OWL)
    out.bind("owl", OWL)
    out.bind("rdfs", RDFS)
    out.bind("dcterms", DCTERMS)
    out.bind("xsd", XSD)
    text = out.serialize(format="turtle")
    return (
        "# FLOPO ISCC-NBS colour backbone module. Generated by tools/build_flopo_colour_backbone.py;\n"
        "# embedded in ontology/flopo.owl by tools/update_flopo_colour_backbone_release.py.\n"
        + text
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-design", help="translate reviewed design tables to config tables")
    imp.add_argument("--design", type=Path, default=Path("scratchpad/colour-backbone-20260918"))
    bld = sub.add_parser("build", help="write the backbone module, crosswalk and change list")
    bld.add_argument("--release", type=Path, default=PATHS["release"])
    args = parser.parse_args()
    if args.command == "import-design":
        print(json.dumps(import_design(args.design), indent=2))
    else:
        print(json.dumps(build(ROOT, args.release), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
