"""Group unresolved anatomical bearers for PO reuse or FLOPO-local extension review.

The grouping is deliberately evidence-first.  Existing PO candidates retain their published
definition, superclass, and parthood axioms.  A genuinely missing bearer is only labelled a local
extension *candidate*; it is never ready to mint until a curator supplies and approves all three
semantic fields.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from flopo2.extract.baseline import _clause_at, _organ_to_po


@dataclass(frozen=True)
class PoTerm:
    po_id: str
    label: str
    definition: str
    parents: tuple[str, ...]
    part_of: tuple[str, ...]


@dataclass(frozen=True)
class BearerHint:
    key: str
    label: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class LocalProposal:
    proposal_id: str
    preferred_label: str
    definition: str
    definition_sources: tuple[str, ...]
    parents: tuple[str, ...]
    part_of: tuple[str, ...]
    recommendation: str
    caveat: str


HINTS = (
    BearerHint("leaf_blade", "leaf blade", re.compile(r"\bleaf\s+blades?\b", re.I)),
    BearerHint(
        "vein",
        "vein or vascular bundle",
        re.compile(r"\b(?:veins?|nerves?|nervures?)\b", re.I),
    ),
    BearerHint(
        "margin",
        "organ margin",
        re.compile(r"\b(?:margins?|borders?|edges?|fringes?|frang[ée](?:e?s?)?)\b", re.I),
    ),
    BearerHint(
        "throat",
        "floral-organ throat",
        re.compile(r"\b(?:throats?|gorges?)\b", re.I),
    ),
    BearerHint(
        "central_region",
        "central region",
        re.compile(r"\b(?:cent(?:er|re)s?)\b", re.I),
    ),
    BearerHint(
        "abaxial_surface",
        "abaxial or lower surface",
        re.compile(r"\b(?:lower\s+(?:surfaces?|faces?)|faces?\s+inf[ée]rieures?)\b", re.I),
    ),
    BearerHint(
        "adaxial_surface",
        "adaxial or upper surface",
        re.compile(r"\b(?:upper\s+(?:surfaces?|faces?)|faces?\s+sup[ée]rieures?)\b", re.I),
    ),
    BearerHint(
        "indumentum",
        "indumentum",
        re.compile(r"\b(?:tomentum|pubescence|velours|indumentum)\b", re.I),
    ),
    BearerHint(
        "pattern_region",
        "patterned region",
        re.compile(
            r"\b(?:spots?|patch(?:es)?|blotches?|streaks?|bands?|mottl(?:e|ed|es|ing)|"
            r"taches?|bandes?|stries?|mouchet[ée](?:e?s?)?)\b",
            re.I,
        ),
    ),
    BearerHint("trichome", "trichome or hair", re.compile(r"\b(?:hairs?|trichomes?|poils?)\b", re.I)),
    BearerHint("hilum", "hilum", re.compile(r"\b(?:hilum|hila|hiles?)\b", re.I)),
    BearerHint("keel", "keel", re.compile(r"\b(?:keels?|car[èe]nes?)\b", re.I)),
)


FIELDNAMES = (
    "rank",
    "group_key",
    "bearer_label",
    "disposition",
    "candidate_po_id",
    "candidate_po_label",
    "evidence_count",
    "source_count",
    "source_collections",
    "document_count",
    "taxon_count",
    "organ_headings",
    "quality_pato_ids",
    "curation_proposal_id",
    "definition_source_ids",
    "candidate_flopo_iri",
    "definition",
    "superclass_ids",
    "part_of_ids",
    "semantics_complete",
    "review_status",
    "examples",
    "notes",
)


# These headings add sex, position, or developmental qualifiers to a bearer that PO already
# supplies.  The broad bearer is safe for grouping; the qualifier remains in the source evidence.
BROAD_HEADING_PO = {
    "male flowers": "PO_0009046",
    "female flowers": "PO_0009046",
    "basal flowers": "PO_0009046",
    "apical flowers": "PO_0009046",
    "axillary flowers": "PO_0009046",
    "central flowers": "PO_0009046",
    "lower flowers": "PO_0009046",
    "terminal flowers": "PO_0009046",
    "male inflorescences": "PO_0009049",
    "female inflorescences": "PO_0009049",
    "flower arrangement": "PO_0009049",
    "male racemes": "PO_0030115",
    "female racemes": "PO_0030115",
    "paniculated inflorescences": "PO_0030123",
    "lower pitchers": "PO_0009025",
    "upper pitchers": "PO_0009025",
    "fertile fronds": "PO_0009025",
    "sterile fronds": "PO_0009025",
    "fronds": "PO_0009025",
    "basal pinnae": "PO_0020049",
    "lateral pinnae": "PO_0020049",
    "lower pinnae": "PO_0020049",
    "middle pinnae": "PO_0020049",
    "terminal pinnae": "PO_0020049",
    "pinnae": "PO_0020049",
    "stipes": "PO_0025066",
    "pods": "PO_0030100",
    "legume pods": "PO_0030100",
    "berries": "PO_0030108",
    "internodes": "PO_0005005",
    "first internode": "PO_0005005",
    "spores": "PO_0025017",
    "thyrses": "PO_0009049",
    "sessile spikelets": "PO_0009051",
    "pedicelled spikelets": "PO_0009051",
    "pedicellate spikelets": "PO_0009051",
    "female spikelets": "PO_0009051",
    "fertile spikelets": "PO_0009051",
    "sterile spikelets": "PO_0009051",
    "pedicel spikelets": "PO_0009051",
    "median veins": "PO_0020139",
    "midveins": "PO_0020139",
    "ovules": "PO_0020003",
    "integument": "PO_0020021",
    "floral scapes": "PO_0009047",
    "shoots": "PO_0009006",
    "generative shoots": "PO_0009006",
    "juvenile shoots": "PO_0009006",
    "mature stems": "PO_0009047",
    "mature fruits": "PO_0009001",
    "male strobili": "PO_0005031",
    "female strobili": "PO_0005032",
    "long stamens": "PO_0009029",
    "outer stamens": "PO_0009029",
    "inner stamens": "PO_0009029",
    "fertile stamens": "PO_0009029",
    "outer petals": "PO_0009032",
    "first leaves": "PO_0009025",
    "humus collecting fronds": "PO_0009025",
    "pinnatifid fronds": "PO_0009025",
    "ovarian follicles": "PO_0030105",
    "liana habit": "PO_0000003",
    "female inflorescence rachises": "PO_0020122",
    "male inflorescence rachises": "PO_0020122",
}

# A heading in this set is meaningful but cannot select one PO sense without its attachment or
# taxonomic context.  It must not be misreported as proof that PO lacks a class.
AMBIGUOUS_HEADINGS = {
    "apex",
    "axes",
    "basal scales",
    "branching",
    "column",
    "crown",
    "colour",
    "dimensions",
    "final bifurcations",
    "fruiting axes",
    "germination",
    "lobes",
    "lower half of leaves",
    "note",
    "number of flowers",
    "perennial organs",
    "pinna axes",
    "pistil",
    "rachis articles",
    "rachises",
    "ridges",
    "scales",
    "sheaths",
    "stones",
    "surfaces",
    "tendrils",
    "texture",
    "ultimate segments",
    "upper surfaces",
    "veinlets",
    "vegetative parts",
}


# These are evidence links, not automatic mappings.  In particular, a generic ``tube`` heading
# must first be shown to denote fused petals, and ``labellum`` must have the Orchidaceae sense
# required by the reviewed definition.  The FLOPO identifier is deliberately allocated only after
# this source-sense review has been approved.
LOCAL_PROPOSAL_BY_GROUP = {
    "heading:labellum": "PO-CAND:orchid_labellum",
    "heading:tube": "PO-CAND:corolla_tube",
    "throat": "PO-CAND:corolla_throat",
}


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


@lru_cache(maxsize=None)
def _cached_organ_to_po(organ: str) -> str:
    return _organ_to_po(organ)


def _obo_id(value: str) -> str:
    return value.replace("PO:", "PO_")


def _proposal_ids(value: str) -> tuple[str, ...]:
    return tuple(
        token.replace("PO:", "PO_")
        for token in (value or "").replace(";", "|").split("|")
        if token
    )


def load_local_proposals(path: Path) -> dict[str, LocalProposal]:
    """Load source-backed candidate semantics without treating a proposal as an approval."""

    if not Path(path).exists():
        return {}
    proposals: dict[str, LocalProposal] = {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            proposal_id = row.get("proposal_id", "")
            if proposal_id not in set(LOCAL_PROPOSAL_BY_GROUP.values()):
                continue
            proposals[proposal_id] = LocalProposal(
                proposal_id=proposal_id,
                preferred_label=row.get("preferred_label", ""),
                definition=row.get("definition", ""),
                definition_sources=tuple(
                    token
                    for token in (row.get("definition_sources", "") or "").split("|")
                    if token
                ),
                parents=_proposal_ids(row.get("direct_parent_ids", "")),
                part_of=_proposal_ids(row.get("part_of_ids", "")),
                recommendation=row.get("recommendation", ""),
                caveat=row.get("counterexample_or_caveat", ""),
            )
    return proposals


def load_po_terms(path: Path) -> dict[str, PoTerm]:
    """Load the PO semantics needed to judge whether a candidate is already defined."""

    terms: dict[str, PoTerm] = {}
    stanza: dict[str, object] = {}

    def finish() -> None:
        raw_id = str(stanza.get("id", ""))
        if not raw_id.startswith("PO:"):
            return
        po_id = _obo_id(raw_id)
        terms[po_id] = PoTerm(
            po_id=po_id,
            label=str(stanza.get("name", "")),
            definition=str(stanza.get("definition", "")),
            parents=tuple(stanza.get("parents", ())),
            part_of=tuple(stanza.get("part_of", ())),
        )

    with Path(path).open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line == "[Term]":
                finish()
                stanza = {"parents": [], "part_of": []}
            elif line.startswith("id: "):
                stanza["id"] = line[4:].strip()
            elif line.startswith("name: "):
                stanza["name"] = line[6:].strip()
            elif line.startswith("def: "):
                match = re.match(r'def: "(.*)"\s+\[', line)
                stanza["definition"] = match.group(1) if match else line[5:].strip()
            elif line.startswith("is_a: PO:"):
                cast = stanza.setdefault("parents", [])
                assert isinstance(cast, list)
                cast.append(_obo_id(line[6:].split()[0]))
            elif line.startswith("relationship: part_of PO:"):
                cast = stanza.setdefault("part_of", [])
                assert isinstance(cast, list)
                cast.append(_obo_id(line[22:].split()[0]))
    finish()
    return terms


def _po_forms(
    path: Path,
    reviewed_bearers: Path = Path("config/reviewed_local_bearers.tsv"),
) -> dict[tuple[str, ...], set[str]]:
    """Return exact PO forms, including the small curator-reviewed flora alias table."""

    forms: dict[tuple[str, ...], set[str]] = defaultdict(set)
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("namespace") != "plant_anatomy":
                continue
            po_id = row.get("id", "")
            for form in (row.get("label", ""), *(row.get("synonyms", "") or "").split("|")):
                if _fold(form):
                    forms[tuple(_fold(form).split())].add(po_id)
    _merge_reviewed_bearer_forms(forms, reviewed_bearers)
    return forms


def _merge_reviewed_bearer_forms(
    forms: dict[tuple[str, ...], set[str]],
    reviewed_bearers: Path,
) -> None:
    if not Path(reviewed_bearers).exists():
        return
    with Path(reviewed_bearers).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("review_status") != "reviewed_existing_po":
                continue
            form = _fold(row.get("surface_form", ""))
            po_id = row.get("po_id", "")
            if form and po_id.startswith("PO_"):
                forms[tuple(form.split())].add(po_id)


def _po_exact_forms(
    path: Path = Path("ont/plant_ontology.obo"),
    reviewed_bearers: Path = Path("config/reviewed_local_bearers.tsv"),
) -> dict[tuple[str, ...], set[str]]:
    """Return PO labels and EXACT synonyms safe for automatic bearer normalization."""

    forms: dict[tuple[str, ...], set[str]] = defaultdict(set)
    current_id = ""
    namespace = ""
    current_forms: list[str] = []

    def finish() -> None:
        if current_id and namespace == "plant_anatomy":
            for value in current_forms:
                # The pinned PO export redundantly embeds scope/language metadata in many synonym
                # strings (for example ``vexillum (exact)``) as well as in the OBO scope token.
                value = re.sub(
                    r"\s+\([^()]*\bexact\b[^()]*\)\s*$",
                    "",
                    value,
                    flags=re.IGNORECASE,
                )
                form = _fold(html.unescape(value))
                if form:
                    forms[tuple(form.split())].add(current_id)

    with Path(path).open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            # Any stanza boundary closes the preceding term.  In particular, do not let the
            # final PO term leak into a following ``[Typedef]`` stanza: that previously made
            # relation labels such as ``part_of`` look like exact synonyms of PO_0030136.
            if line.startswith("["):
                finish()
                current_id = ""
                namespace = ""
                current_forms = []
            elif line.startswith("id: PO:"):
                current_id = _obo_id(line[4:].strip())
            elif line.startswith("namespace: "):
                namespace = line[11:].strip()
            elif current_id and line.startswith("name: "):
                current_forms.append(line[6:].strip())
            elif current_id and line.startswith("synonym: "):
                match = re.match(r'^synonym: "(.*)"\s+EXACT(?P<tail>.*)$', line)
                tail = match.group("tail").strip() if match else ""
                # Language-tagged exact synonyms are exact within that language, not unscoped
                # lexical aliases.  French flora aliases require explicit review in the local
                # table; PO's untagged/English synonym forms remain eligible automatically.
                language_tagged = bool(
                    tail
                    and not tail.startswith("[")
                    and not tail.startswith("OMO:")
                )
                if match and not language_tagged:
                    current_forms.append(match.group(1))
    finish()
    _merge_reviewed_bearer_forms(forms, reviewed_bearers)
    return forms


def _form_candidates(value: str, po_forms: dict[tuple[str, ...], set[str]]) -> set[str]:
    tokens = tuple(_fold(value).split())
    candidates = set(po_forms.get(tokens, ()))
    if tokens and tokens[-1].endswith("s"):
        candidates.update(po_forms.get((*tokens[:-1], tokens[-1][:-1]), ()))
    return candidates


def _nearest_po_form(
    clause: str,
    local_position: int,
    po_forms: dict[tuple[str, ...], set[str]],
) -> tuple[str, str] | None:
    """Find a unique nearby exact PO lexical form for grouping, never auto-acceptance."""

    tokens = list(re.finditer(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]*", clause))
    candidates: list[tuple[int, int, int, str, str]] = []
    max_words = min(6, len(tokens))
    ambiguous_singletons = {
        "apex",
        "base",
        "body",
        "branch",
        "center",
        "centre",
        "part",
        "region",
        "side",
        "surface",
        "tip",
    }
    for start_index in range(len(tokens)):
        for width in range(1, min(max_words, len(tokens) - start_index) + 1):
            selected = tokens[start_index : start_index + width]
            phrase = " ".join(_fold(match.group(0)) for match in selected)
            if width == 1 and phrase in ambiguous_singletons:
                continue
            ids = _form_candidates(phrase, po_forms)
            if len(ids) != 1:
                continue
            start, end = selected[0].start(), selected[-1].end()
            gap = _distance(start, end, local_position)
            side = 0 if end <= local_position else 1
            candidates.append((gap, side, -width, next(iter(ids)), clause[start:end]))
    if not candidates:
        return None
    _gap, _side, _width, po_id, surface = min(candidates)
    return po_id, surface


def _distance(start: int, end: int, position: int) -> int:
    if end <= position:
        return position - end
    if start >= position:
        return start - position
    return 0


def _nearest_hint(clause: str, local_position: int) -> tuple[BearerHint, str] | None:
    candidates: list[tuple[int, int, BearerHint, str]] = []
    for order, hint in enumerate(HINTS):
        for match in hint.pattern.finditer(clause):
            candidates.append(
                (_distance(match.start(), match.end(), local_position), order, hint, match.group(0))
            )
    if not candidates:
        return None
    _gap, _order, hint, surface = min(candidates)
    return hint, surface


def _context_contains(value: str, pattern: str) -> bool:
    return re.search(pattern, value, re.I) is not None


def _contextual_po_id(key: str, context: str) -> tuple[str, str]:
    """Return an existing PO candidate and the caution attached to that lexical use."""

    leaf = _context_contains(context, r"\b(?:leaf|leaves|leaflet|folioles?|feuilles?|limb(?:e|es))\b")
    if key == "leaf_blade":
        return "PO_0020039", "PO records 'leaf blade' only as a RELATED synonym of leaf lamina."
    if key == "vein" and leaf:
        return "PO_0020138", "Use only when the vein is part of a leaf lamina."
    if key == "margin":
        margin_map = (
            (r"\b(?:leaflets?|folioles?)\b", "PO_0006034"),
            (r"\b(?:leaves?|feuilles?|limb(?:e|es))\b", "PO_0020128"),
            (r"\b(?:petals?|p[ée]tales?)\b", "PO_0025008"),
            (r"\b(?:sepals?|s[ée]pales?)\b", "PO_0005021"),
            (r"\b(?:tepals?|t[ée]pales?)\b", "PO_0025015"),
            (r"\b(?:bracts?|bract[ée]es?)\b", "PO_0025011"),
            (r"\b(?:petioles?|p[ée]tioles?)\b", "PO_0025010"),
            (r"\bcarpels?\b", "PO_0025019"),
            (r"\bstamens?\b", "PO_0025020"),
        )
        for pattern, po_id in margin_map:
            if _context_contains(context, pattern):
                return po_id, "Context selects an existing organ-specific margin."
        return "PO_0025005", "Generic plant-organ margin; container attachment still requires review."
    if key == "abaxial_surface" and leaf:
        return "PO_0000049", "Interprets a leaf-lamina lower surface as its abaxial epidermis."
    if key == "adaxial_surface" and leaf:
        return "PO_0000050", "Interprets a leaf-lamina upper surface as its adaxial epidermis."
    if key == "trichome":
        return "PO_0000282", "PO treats 'hair' as NARROW under trichome; sense review is mandatory."
    if key == "hilum":
        return "PO_0020063", "Existing seed hilum class."
    if key == "keel" and _context_contains(context, r"\b(?:corolla|petals?|p[ée]tales?)\b"):
        return "PO_0025327", "PO keel is specifically the two lowest petals of a papilionaceous corolla."
    return "", ""


def _classify(
    organ: str,
    clause: str,
    local_position: int,
    po_forms: dict[tuple[str, ...], set[str]],
) -> tuple[str, str, str, str, str]:
    hint_hit = _nearest_hint(clause, local_position)
    context = f"{organ} {clause}"
    if hint_hit:
        hint, surface = hint_hit
        po_id, note = _contextual_po_id(hint.key, context)
        if po_id:
            disposition = "existing_po_context_review"
        elif hint.key in {"throat", "indumentum"}:
            disposition = "flopo_extension_candidate"
        else:
            disposition = "attachment_or_region_review"
        return hint.key, hint.label, disposition, po_id, f"Observed bearer form: {surface}. {note}".strip()

    normalized_organ = _fold(organ)
    if normalized_organ in BROAD_HEADING_PO:
        po_id = BROAD_HEADING_PO[normalized_organ]
        return (
            f"heading:{normalized_organ}",
            organ,
            "existing_po_context_review",
            po_id,
            "The heading qualifier is retained in evidence; grouping uses the broader existing PO bearer.",
        )
    if normalized_organ in AMBIGUOUS_HEADINGS:
        return (
            f"heading:{normalized_organ}",
            organ,
            "attachment_or_region_review",
            "",
            "Multiple bearer senses are possible; resolve context before selecting PO or proposing a class.",
        )
    if normalized_organ == "indumentum":
        return (
            "indumentum",
            organ,
            "flopo_extension_candidate",
            "",
            "A covering-quality noun may denote either the bearer or its pilosity; resolve that distinction before proposing a local entity.",
        )
    po_id = _cached_organ_to_po(organ)
    if not po_id:
        candidates = _form_candidates(normalized_organ, po_forms)
        if len(candidates) == 1:
            po_id = next(iter(candidates))
    if po_id:
        return (
            f"heading:{normalized_organ}",
            organ or "source heading bearer",
            "existing_po_context_review",
            po_id,
            "Candidate derived from the source organ heading; verify pronoun and nested-part attachment.",
        )
    lexical = _nearest_po_form(clause, local_position, po_forms)
    if lexical:
        po_id, surface = lexical
        return (
            f"lexical:{po_id}",
            surface,
            "existing_po_context_review",
            po_id,
            "Unique nearby PO label or synonym; verify that it is the grammatical bearer and that synonym scope is appropriate.",
        )
    if normalized_organ and normalized_organ != "description":
        return (
            f"heading:{normalized_organ}",
            organ,
            "flopo_extension_candidate",
            "",
            "No unique existing PO mapping for the source organ heading.",
        )
    return (
        "unresolved_attachment",
        "unresolved contextual bearer",
        "attachment_or_region_review",
        "",
        "No explicit reusable bearer was identified; resolve syntax/coreference before proposing anatomy.",
    )


def group_missing_bearers(
    input_jsonl: Path,
    output_tsv: Path,
    *,
    po_obo: Path = Path("ont/plant_ontology.obo"),
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    concept_proposals: Path = Path("curation/botanical_concept_proposals.tsv"),
) -> dict[str, int | str]:
    po_terms = load_po_terms(po_obo)
    po_forms = _po_forms(po_lexicon)
    local_proposals = load_local_proposals(concept_proposals)
    groups: dict[tuple[str, str], dict[str, object]] = {}
    evidence = 0

    with Path(input_jsonl).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            text = str(record.get("text", "") or "")
            for unresolved in record.get("unresolved_spans", []) or []:
                if unresolved.get("reason") != "missing_or_unsupported_bearer":
                    continue
                evidence += 1
                position = int(unresolved.get("start", 0) or 0)
                clause, clause_start = _clause_at(text, position)
                key, label, disposition, po_id, note = _classify(
                    str(record.get("organ", "") or ""),
                    clause,
                    position - clause_start,
                    po_forms,
                )
                group_id = (key, po_id)
                row = groups.setdefault(
                    group_id,
                    {
                        "group_key": key,
                        "bearer_label": label,
                        "disposition": disposition,
                        "candidate_po_id": po_id,
                        "sources": Counter(),
                        "documents": set(),
                        "taxa": set(),
                        "organs": Counter(),
                        "qualities": Counter(),
                        "examples": [],
                        "notes": note,
                        "evidence_count": 0,
                    },
                )
                row["evidence_count"] = int(row["evidence_count"]) + 1
                row["sources"][str(record.get("source", "") or "")] += 1
                row["documents"].add(
                    (str(record.get("source", "") or ""), str(record.get("source_id", "") or ""))
                )
                row["taxa"].add(str(record.get("taxon", "") or ""))
                row["organs"][str(record.get("organ", "") or "")] += 1
                row["qualities"][str(unresolved.get("candidate_pato_id", "") or "")] += 1
                examples = row["examples"]
                if len(examples) < 5:
                    compact_clause = re.sub(r"\s+", " ", clause).strip()
                    examples.append(
                        f"{record.get('source', '')}:{record.get('source_id', '')} | "
                        f"{record.get('taxon', '')} | {record.get('organ', '')} | "
                        f"{unresolved.get('surface_form', '')} | {compact_clause[:300]}"
                    )

    ordered = sorted(
        groups.values(),
        key=lambda row: (-int(row["evidence_count"]), str(row["group_key"]), str(row["candidate_po_id"])),
    )
    output_tsv.parent.mkdir(parents=True, exist_ok=True)
    with Path(output_tsv).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, delimiter="\t")
        writer.writeheader()
        for rank, row in enumerate(ordered, 1):
            po_id = str(row["candidate_po_id"])
            term = po_terms.get(po_id)
            proposal_id = LOCAL_PROPOSAL_BY_GROUP.get(str(row["group_key"]), "")
            proposal = local_proposals.get(proposal_id)
            # A proposal may supply complete candidate semantics, but it never reserves a FLOPO
            # IRI or authorizes ingestion.  Scope/sense review remains an independent gate.
            candidate_definition = proposal.definition if proposal else ""
            candidate_parents = proposal.parents if proposal else ()
            candidate_part_of = proposal.part_of if proposal else ()
            semantics_complete = bool(
                (term and term.definition and term.parents)
                or (proposal and candidate_definition and candidate_parents)
            )
            if term:
                review_status = "pending_existing_po_mapping"
            elif proposal and proposal.recommendation == "accept_proposal":
                review_status = "ready_for_scope_and_curator_review"
            elif proposal:
                review_status = "needs_definition_superclass_and_parthood_review"
            else:
                review_status = "needs_definition_superclass_and_parthood_review"
            notes = str(row["notes"])
            if proposal:
                notes = (
                    f"{notes} Linked evidence proposal {proposal.proposal_id} is not an approval. "
                    f"{proposal.caveat}"
                ).strip()
            writer.writerow(
                {
                    "rank": rank,
                    "group_key": row["group_key"],
                    "bearer_label": row["bearer_label"],
                    "disposition": row["disposition"],
                    "candidate_po_id": po_id,
                    "candidate_po_label": term.label if term else "",
                    "evidence_count": row["evidence_count"],
                    "source_count": len(row["sources"]),
                    "source_collections": "|".join(sorted(row["sources"])),
                    "document_count": len(row["documents"]),
                    "taxon_count": len({value for value in row["taxa"] if value}),
                    "organ_headings": "|".join(value for value, _count in row["organs"].most_common(20)),
                    "quality_pato_ids": "|".join(value for value, _count in row["qualities"].most_common() if value),
                    "curation_proposal_id": proposal.proposal_id if proposal else "",
                    "definition_source_ids": (
                        "|".join(proposal.definition_sources) if proposal else ""
                    ),
                    "candidate_flopo_iri": "",
                    "definition": term.definition if term else candidate_definition,
                    "superclass_ids": (
                        "|".join(term.parents) if term else "|".join(candidate_parents)
                    ),
                    "part_of_ids": (
                        "|".join(term.part_of) if term else "|".join(candidate_part_of)
                    ),
                    "semantics_complete": str(semantics_complete).lower(),
                    "review_status": review_status,
                    "examples": " || ".join(row["examples"]),
                    "notes": notes,
                }
            )

    return {
        "evidence": evidence,
        "groups": len(ordered),
        "existing_po_groups": sum(bool(row["candidate_po_id"]) for row in ordered),
        "extension_candidate_groups": sum(
            row["disposition"] == "flopo_extension_candidate" for row in ordered
        ),
        "output": str(output_tsv),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--po-obo", type=Path, default=Path("ont/plant_ontology.obo"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument(
        "--concept-proposals",
        type=Path,
        default=Path("curation/botanical_concept_proposals.tsv"),
    )
    args = parser.parse_args()
    print(
        json.dumps(
            group_missing_bearers(
                args.input,
                args.output,
                po_obo=args.po_obo,
                po_lexicon=args.po_lexicon,
                concept_proposals=args.concept_proposals,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
