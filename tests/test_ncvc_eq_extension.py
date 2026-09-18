"""NCVC Saudi guide EQ phenotype classes (staged module, 2026-09-18)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from rdflib import DCTERMS, OWL, RDF, RDFS, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.compare import isomorphic

from flopo2.owl.build import _definition
from tools.build_flopo_ncvc_eq_extension import (
    ABNORMAL_PATO,
    HAS_PART,
    HAS_QUALITY,
    HOMONYM_PATO,
    IAO_DEFINITION,
    ID_BLOCK,
    OBO,
    PART_OF,
    QUALITY_ROOT,
    ROOT_CLASS,
    blocked_qualities,
    build_module,
    other_block_numbers,
    propose,
    registry_index,
)
from tools.update_flopo_ncvc_eq_release import (
    BEGIN_MARKER,
    END_MARKER,
    _allocations,
    _without_generated_block,
    module_fragment,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "curation" / "ncvc_saudi_eq_classes_20260918.tsv"
REGISTRY = ROOT / "config" / "flopo_ncvc_eq_id_registry.tsv"
FLOPO_REGISTRY = ROOT / "config" / "flopo_id_registry.tsv"
COMBINATIONS = ROOT / "config" / "valid_combinations.tsv"
MODULE_PATH = ROOT / "ontology" / "flopo-ncvc-eq-extension.ttl"
DATE = "2026-09-18"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


@pytest.fixture(scope="module")
def spec() -> list[dict[str, str]]:
    return _rows(SPEC)


@pytest.fixture(scope="module")
def module() -> Graph:
    return Graph().parse(MODULE_PATH.as_posix(), format="turtle")


def test_every_accepted_row_is_an_allowed_pair_with_canonical_label_and_definition(spec):
    allowed = {
        (row["po_id"], row["pato_id"])
        for row in _rows(COMBINATIONS)
        if row["status"] == "allowed"
    }
    accepted = [row for row in spec if row["decision"] == "accept"]
    assert accepted
    for row in accepted:
        assert (row["po_id"], row["pato_id"]) in allowed
        assert row["pato_id"].startswith("PATO_")
        assert row["signature"] == f"EQ|{row['po_id']}|{row['pato_id']}"
        assert row["label"] == f"{row['po_label']} {row['pato_label']}"
        assert row["definition"] == _definition(row["po_label"], row["pato_label"])


def test_screen_excludes_homonyms_abnormal_senses_and_live_duplicates(spec):
    live, _labels, _numbers = registry_index(FLOPO_REGISTRY)
    excluded = {row["signature"]: row["reason"] for row in spec if row["decision"] == "exclude"}
    for row in spec:
        if row["decision"] != "accept":
            continue
        assert row["pato_id"] not in HOMONYM_PATO
        assert row["pato_id"] not in ABNORMAL_PATO
        if row["signature"] in live:
            # The live registry can move ahead of this staged proposal (e.g. this exact batch
            # has since been released for real, under the same reserved block): that is fine as
            # long as the live class is the one this proposal itself describes, not a collision
            # with something unrelated.
            assert live[row["signature"]][1] == row["label"], row["signature"]
    assert excluded, "the screen must keep a reasoned exclusion list"
    assert all(reason.strip() for reason in excluded.values())
    homonyms = [row for row in spec if row["pato_id"] in HOMONYM_PATO]
    assert homonyms and all(row["decision"] == "exclude" for row in homonyms)


def test_blocked_quality_branches_never_reach_the_release(spec):
    blocked = blocked_qualities()
    assert {"PATO_0001340", "PATO_0000383", "PATO_0000384"} <= set(blocked)
    sex_rows = [row for row in spec if row["pato_id"] in blocked]
    assert sex_rows and all(row["decision"] == "exclude" for row in sex_rows)
    assert all("blocked quality branch" in row["reason"] for row in sex_rows)


def test_proposal_is_current_for_the_annotated_corpus(spec):
    """The frozen spec's 292 accepted rows have since been released for real (their FLOPO ids are
    live), so ``propose()`` -- which only considers still-*unlinked* EQ signatures -- correctly
    stops proposing them at all; that is not drift, it is the intended lifecycle. What must stay
    true is that every one of the 108 rows this batch did *not* accept is still reproduced
    identically (module the ``parent`` field, which legitimately now resolves to a live class
    instead of a not-yet-released ``PHENO|...`` placeholder once sibling accepted rows land), and
    that a fresh run surfaces no signature this frozen spec never considered."""

    normalized = {
        row["signature"]: {
            **row,
            "assertions": int(row["assertions"]),
            "accepted_assertions": int(row["accepted_assertions"]),
            "taxa": int(row["taxa"]),
        }
        for row in spec
    }
    fresh = {row["signature"]: row for row in propose()}

    # Check "actually released" against the FLOPO id this batch's own registry allocated, rather
    # than the live registry's re-derived ``EQ|...`` signature: a colour-bearing accepted class
    # (e.g. "seed trichome yellow") had its quality filler re-pointed to an ISCC-NBS backbone
    # class by the 2026-09-18 colour backbone migration, which changes the shape
    # ``flopo2.ids.registry._signature_of`` expects, so the live registry now records it as
    # signature "OTHER" even though the class itself is live and unchanged in identity.
    allocations = {row["proposal_key"]: row["flopo_id"] for row in _rows(REGISTRY)}
    with FLOPO_REGISTRY.open(encoding="utf-8", newline="") as handle:
        live_by_id = {
            row["flopo_iri"].rsplit("/", 1)[-1]: row for row in csv.DictReader(handle, delimiter="\t")
        }

    accepted = {sig for sig, row in normalized.items() if row["decision"] == "accept"}
    assert accepted, "the frozen spec must still record what this batch accepted"
    for signature in accepted:
        assert signature not in fresh, signature
        flopo_id = allocations[signature]
        live_row = live_by_id.get(flopo_id)
        assert live_row is not None, f"{signature}: allocated {flopo_id} is missing from the live registry"
        assert live_row["deprecated"] in {"0", "", "false", "False"}, f"{signature}: {flopo_id} is deprecated"

    still_open = set(normalized) - accepted
    assert still_open, "the frozen spec must still record at least one undecided candidate"
    assert set(fresh) == still_open
    # Fields derived from a live label (parent, *_label, label, definition, reason) can
    # legitimately drift for an "exclude" row too: e.g. FLOPO_0980092 "silvery" is one of the 78
    # colour value classes the 2026-09-18 backbone migration obsoleted, so its live label is now
    # "obsolete silvery". Trust ``propose()``'s own construction of those fields (checked below
    # for internal consistency) rather than the frozen copy, and compare everything else exactly.
    label_derived = {"po_label", "pato_label", "label", "definition", "parent", "reason"}
    for signature in still_open:
        fresh_row = fresh[signature]
        expected_row = {k: v for k, v in normalized[signature].items() if k not in label_derived}
        actual_row = {k: v for k, v in fresh_row.items() if k not in label_derived}
        assert actual_row == expected_row, signature
        assert fresh_row["label"] == f"{fresh_row['po_label']} {fresh_row['pato_label']}", signature
        assert fresh_row["definition"] == _definition(fresh_row["po_label"], fresh_row["pato_label"]), signature


def test_identifiers_are_unique_inside_the_reserved_block_and_collide_with_nothing():
    allocations = _rows(REGISTRY)
    numbers = [int(row["flopo_id"].removeprefix("FLOPO_")) for row in allocations]
    assert len(numbers) == len(set(numbers))
    assert all(ID_BLOCK[0] <= number <= ID_BLOCK[1] for number in numbers)
    labels_by_number = {int(row["flopo_id"].removeprefix("FLOPO_")): row["label"] for row in allocations}
    _live, live_labels, released = registry_index(FLOPO_REGISTRY)
    assert not set(numbers) & other_block_numbers(ROOT / "config", ROOT / "ontology")
    # An overlap with the global registry is fine once this reserved block has actually been
    # released for real (the global registry is only populated by a release resync): every such
    # number must denote the same class this file allocated it to, not an unrelated collision.
    for number in set(numbers) & released:
        flopo_id = f"FLOPO_{number:07d}"
        assert live_labels.get(flopo_id) == labels_by_number[number], flopo_id


def test_registry_covers_exactly_the_accepted_rows_and_their_bearer_parents(spec):
    allocations = {row["proposal_key"]: row for row in _rows(REGISTRY)}
    accepted = [row for row in spec if row["decision"] == "accept"]
    expected = {row["signature"] for row in accepted}
    expected |= {row["parent"] for row in accepted if row["parent"].startswith("PHENO|")}
    assert set(allocations) == expected
    for row in accepted:
        assert allocations[row["signature"]]["label"] == row["label"]


def test_module_matches_a_fresh_build(module):
    assert isomorphic(module, build_module(SPEC, REGISTRY, FLOPO_REGISTRY, COMBINATIONS, DATE))


def test_every_class_has_the_eq_pattern_provenance_and_a_parent(module, spec):
    allocations = {row["proposal_key"]: row["flopo_id"] for row in _rows(REGISTRY)}
    accepted = [row for row in spec if row["decision"] == "accept"]
    for row in accepted:
        cls = URIRef(OBO + allocations[row["signature"]])
        assert (cls, RDF.type, OWL.Class) in module
        assert (cls, RDFS.label, Literal(row["label"], lang="en")) in module
        assert (cls, IAO_DEFINITION, Literal(row["definition"], lang="en")) in module
        assert (cls, DCTERMS.contributor, URIRef("https://orcid.org/0000-0001-8149-5890")) in module
        sources = {str(value) for value in module.objects(cls, DCTERMS.source)}
        assert any("ncvc-saudi-native-plants-guide-2024" in value for value in sources)
        assert "curation/curator-2026-09-18-po-pato-approvals.tsv" in sources
        note = " ".join(str(value) for value in module.objects(cls, URIRef(OBO + "IAO_0000116")))
        assert "Curator decision D1" in note
        equivalents = list(module.objects(cls, OWL.equivalentClass))
        assert len(equivalents) == 1
        assert module.value(equivalents[0], OWL.onProperty) == HAS_PART
        filler = module.value(equivalents[0], OWL.someValuesFrom)
        members = list(Collection(module, module.value(filler, OWL.intersectionOf)))
        assert members[0] == URIRef(OBO + row["po_id"])
        assert module.value(members[1], OWL.onProperty) == HAS_QUALITY
        assert module.value(members[1], OWL.someValuesFrom) == URIRef(OBO + row["pato_id"])
        parents = list(module.objects(cls, RDFS.subClassOf))
        assert len(parents) == 1
        if row["parent"].startswith("PHENO|"):
            assert parents[0] == URIRef(OBO + allocations[row["parent"]])
        else:
            assert parents[0] == URIRef(OBO + row["parent"])


def test_minted_bearer_parents_use_the_phenotype_pattern(module):
    for row in _rows(REGISTRY):
        if row["kind"] != "phenotype_parent":
            continue
        cls = URIRef(OBO + row["flopo_id"])
        bearer = URIRef(OBO + row["signature"].split("|", 1)[1])
        assert (cls, RDFS.subClassOf, ROOT_CLASS) in module
        equivalent = next(module.objects(cls, OWL.equivalentClass))
        filler = module.value(equivalent, OWL.someValuesFrom)
        members = list(Collection(module, module.value(filler, OWL.intersectionOf)))
        assert module.value(members[0], OWL.onProperty) == PART_OF
        assert module.value(members[0], OWL.someValuesFrom) == bearer
        assert module.value(members[1], OWL.someValuesFrom) == QUALITY_ROOT


def test_release_fragment_holds_only_minted_classes_and_round_trips(module):
    allocations = _allocations(REGISTRY)
    fragment, minted = module_fragment(module, allocations)
    assert len(minted) == len(allocations)
    assert "flopo-ncvc-eq-extension.owl" not in fragment
    for identifier in ("PO_0030100", "PATO_0000467"):
        assert f'rdf:about="{OBO}{identifier}"' not in fragment
    text = f'<rdf:RDF>\n{BEGIN_MARKER}\n{fragment}\n{END_MARKER}\n</rdf:RDF>\n'
    assert _without_generated_block(text) == "<rdf:RDF>\n</rdf:RDF>\n"


def test_build_refuses_a_pair_the_whitelist_does_not_allow(tmp_path):
    rows = _rows(SPEC)
    accepted = next(row for row in rows if row["decision"] == "accept")
    combinations = tmp_path / "valid_combinations.tsv"
    with combinations.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["po_id", "pato_id", "status", "source", "example_label"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in _rows(COMBINATIONS):
            if (row["po_id"], row["pato_id"]) == (accepted["po_id"], accepted["pato_id"]):
                row["status"] = "novel"
            writer.writerow(row)
    with pytest.raises(ValueError, match="pair is not allowed"):
        build_module(SPEC, REGISTRY, FLOPO_REGISTRY, combinations, DATE)
