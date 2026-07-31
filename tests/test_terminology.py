from __future__ import annotations

import csv

import pytest

from flopo2.terminology.catalog import OntologyCatalog, OntologyTerm
from flopo2.terminology.model import RegistryEntry


def _catalog() -> OntologyCatalog:
    return OntologyCatalog(
        {
            "PO_leaf": OntologyTerm("PO_leaf", "leaf", "PO", ("foliage leaf",)),
            "PO_petal": OntologyTerm("PO_petal", "petal", "PO"),
            "PO_flower": OntologyTerm("PO_flower", "flower", "PO"),
            "PATO_color": OntologyTerm("PATO_color", "color", "PATO"),
            "PATO_red": OntologyTerm("PATO_red", "red", "PATO", ("crimson",)),
            "PATO_digitate": OntologyTerm(
                "PATO_digitate",
                "digitate",
                "PATO",
                ("palmate",),
                (("palmate", "RELATED"),),
            ),
            "FLOPO_greenish": OntologyTerm("FLOPO_greenish", "greenish", "FLOPO"),
            "FLOPO_pinkish": OntologyTerm("FLOPO_pinkish", "pinkish", "FLOPO"),
            "FLOPO_union": OntologyTerm(
                "FLOPO_union", "greenish or pinkish", "FLOPO"
            ),
        }
    )


def test_registry_build_uses_roles_translation_and_scoped_synonyms(tmp_path):
    from flopo2.terminology.registry import build_registry

    fna = tmp_path / "fna.csv"
    fna.write_text(
        '#Version: 1\n\n"term","category","hasSyn","sourceDataset","termID"\n'
        '"leaf","structure","0","x","1"\n'
        '"crimson","coloration","0","x","2"\n'
        '"palmate","shape","0","x","3"\n'
    )
    bilingual = tmp_path / "bilingual.tsv"
    bilingual.write_text(
        "ID\tEnglish\tFrench\tPrettyFrench\tType\tEtymology\tDefinition\n"
        "7\tpetal\tpétale\tpetale\tn.f.\t\tsecret copyrighted definition\n"
    )
    manifest = tmp_path / "sources.tsv"
    manifest.write_text(
        "source_id\tparser\tpath\tlanguage\tversion\tsource_url\tlicense\tlicense_status\t"
        "redistributable\tdefinition_policy\tenabled\tnotes\n"
        "fna\tfna_category_csv\tfna.csv\ten\t1\t\tunknown\tunknown\t0\texclude\t1\t\n"
        "bi\tbilingual_tsv\tbilingual.tsv\ten|fr\t1\t\tunknown\tunknown\t0\texclude\t1\t\n"
    )
    output = tmp_path / "registry.tsv"
    entries = build_registry(manifest, output, root=tmp_path, catalog=_catalog())
    by_surface = {(entry.surface_form, entry.language): entry for entry in entries}

    assert by_surface[("leaf", "en")].target_id == "PO_leaf"
    assert by_surface[("crimson", "en")].target_id == "PATO_red"
    assert by_surface[("palmate", "en")].mapping_relation == "skos:relatedMatch"
    assert by_surface[("palmate", "en")].review_status == "proposed"
    assert by_surface[("pétale", "fr")].target_id == "PO_petal"
    assert by_surface[("pétale", "fr")].mapping_method == "parallel_glossary_transfer"
    assert by_surface[("pétale", "fr")].definition == ""
    assert "definition_excluded" in by_surface[("pétale", "fr")].notes


def test_annotator_preserves_longest_union_and_overlaps():
    from flopo2.terminology.annotate import TerminologyIndex

    entries = [
        RegistryEntry(
            term_id="g",
            surface_form="greenish",
            normalized_form="greenish",
            language="en",
            semantic_role="value",
            target_id="FLOPO_greenish",
            target_label="greenish",
            target_namespace="FLOPO",
            mapping_relation="skos:exactMatch",
            mapping_confidence=1.0,
            review_status="reviewed",
        ),
        RegistryEntry(
            term_id="p",
            surface_form="pinkish",
            normalized_form="pinkish",
            language="en",
            semantic_role="value",
            target_id="FLOPO_pinkish",
            target_label="pinkish",
            target_namespace="FLOPO",
            mapping_relation="skos:exactMatch",
            mapping_confidence=1.0,
            review_status="reviewed",
        ),
        RegistryEntry(
            term_id="u",
            surface_form="greenish or pinkish",
            normalized_form="greenish or pinkish",
            language="en",
            semantic_role="value",
            target_id="FLOPO_union",
            target_label="greenish or pinkish",
            target_namespace="FLOPO",
            mapping_relation="skos:exactMatch",
            mapping_confidence=1.0,
            review_status="reviewed",
            component_ids="FLOPO_greenish|FLOPO_pinkish",
            logical_operator="one_of",
            attribute_id="PATO_color",
        ),
        RegistryEntry(
            term_id="flower",
            surface_form="flower",
            normalized_form="flower",
            language="en",
            semantic_role="entity",
            target_id="PO_flower",
            target_label="flower",
            target_namespace="PO",
            mapping_relation="skos:exactMatch",
            mapping_confidence=1.0,
            review_status="reviewed",
        ),
        RegistryEntry(
            term_id="leaf",
            surface_form="leaf",
            normalized_form="leaf",
            language="en",
            semantic_role="entity",
            target_id="PO_leaf",
            target_label="leaf",
            target_namespace="PO",
            mapping_relation="skos:exactMatch",
            mapping_confidence=1.0,
            review_status="reviewed",
        ),
        RegistryEntry(
            term_id="leaves-unmapped",
            surface_form="leaves",
            normalized_form="leaves",
            language="en",
            semantic_role="entity",
            mapping_relation="flopo:unmapped",
            review_status="unreviewed",
        ),
    ]
    index = TerminologyIndex(entries, _catalog())
    mentions = index.annotate("greenish or pinkish flowers and leaves", "en", "flower")
    union = next(mention for mention in mentions if mention.surface_form == "greenish or pinkish")
    greenish = next(mention for mention in mentions if mention.surface_form == "greenish")
    flower = next(mention for mention in mentions if mention.surface_form == "flowers")
    leaf = next(mention for mention in mentions if mention.surface_form == "leaves")
    assert union.longest_match and not greenish.longest_match
    assert union.logical_operator == "one_of"
    assert union.component_ids == ("FLOPO_greenish", "FLOPO_pinkish")
    assert union.attribute_id == "PATO_color"
    assert flower.match_type == "inflection" and flower.candidates[0].target_id == "PO_flower"
    assert leaf.match_type == "exact" and leaf.candidates[0].target_id == "PO_leaf"


def test_prompt_withholds_non_equivalent_and_low_confidence_candidates():
    from flopo2.terminology.annotate import TerminologyIndex

    entries = [
        RegistryEntry(
            term_id="palmate",
            surface_form="palmate",
            normalized_form="palmate",
            language="en",
            semantic_role="quality",
            target_id="PATO_digitate",
            target_label="digitate",
            target_namespace="PATO",
            mapping_relation="skos:relatedMatch",
            mapping_confidence=0.9,
            review_status="proposed",
        ),
        RegistryEntry(
            term_id="unknown",
            surface_form="blossomy",
            normalized_form="blossomy",
            language="en",
            semantic_role="entity",
            mapping_relation="flopo:unmapped",
            review_status="proposed",
            candidate_ids="PO_flower|PO_leaf",
            candidate_labels="flower|leaf",
            candidate_scores="0.80|0.60",
        ),
    ]
    index = TerminologyIndex(entries, _catalog())
    mentions = index.annotate("palmate blossomy", "en")
    prompt = index.prompt_context(mentions)
    assert '"palmate" roles=quality -> NIL' in prompt
    assert "PATO_digitate" not in prompt
    assert "PO_flower flower (0.80" in prompt
    assert "PO_leaf" not in prompt
    blossomy = next(mention for mention in mentions if mention.surface_form == "blossomy")
    assert blossomy.candidates[0].mapping_relation == ""


def test_annotation_respects_source_language():
    from flopo2.terminology.annotate import TerminologyIndex

    french_only = RegistryEntry(
        term_id="fr-feuille",
        surface_form="feuille",
        normalized_form="feuille",
        language="fr",
        semantic_role="entity",
        target_id="PO_leaf",
        target_label="leaf",
        target_namespace="PO",
        mapping_relation="skos:closeMatch",
        mapping_confidence=0.98,
        review_status="reviewed",
    )
    index = TerminologyIndex([french_only], _catalog())
    assert index.annotate("feuille", "en") == []
    assert index.annotate("feuille", "fr")[0].candidates[0].target_id == "PO_leaf"


def test_loaded_registry_is_layered_over_po_and_pato_catalog_forms(tmp_path):
    from flopo2.terminology.annotate import TerminologyIndex
    from flopo2.terminology.registry import write_registry

    registry = tmp_path / "registry.tsv"
    write_registry([], registry)
    index = TerminologyIndex.load(registry, catalog=_catalog())
    red = index.annotate("red", "en")[0]
    assert red.candidates[0].target_id == "PATO_red"
    assert red.registry_term_ids[0].startswith("ONTOFORM:PATO_red:")
    prompt = index.prompt_context(index.annotate("palmate", "en"))
    assert "PATO_digitate" not in prompt


def test_operational_index_blocks_biomedical_botanical_homonyms():
    from flopo2.terminology.annotate import TerminologyIndex

    entries = [
        RegistryEntry(
            term_id=f"unsafe-{target}",
            surface_form=surface,
            normalized_form=surface,
            language="en",
            semantic_role="quality",
            target_id=target,
            target_label=surface,
            target_namespace="PATO",
            mapping_relation="skos:exactMatch",
            mapping_confidence=1.0,
            review_status="auto",
        )
        for surface, target in (
            ("acute", "PATO_0000389"),
            ("pubescent", "PATO_0000455"),
            ("attenuated", "PATO_0002147"),
        )
    ]
    index = TerminologyIndex(entries, _catalog())
    for surface, target in (
        ("acute", "PATO_0000389"),
        ("pubescent", "PATO_0000455"),
        ("attenuated", "PATO_0002147"),
    ):
        assert all(
            candidate.target_id != target
            for candidate in index.resolve(surface, "PATO", "quality")
        )


def test_gold_sampler_balances_source_language_slices(tmp_path):
    from flopo2.terminology.workflows import sample_alignment_gold

    entries = []
    for source, language in (("english", "en"), ("french", "fr")):
        for number in range(20):
            entries.append(
                RegistryEntry(
                    term_id=f"{source}-{number}",
                    surface_form=f"term {source} {number}",
                    language=language,
                    semantic_role="quality",
                    source_id=source,
                    corpus_frequency=1 if number < 10 else 0,
                )
            )
    output = tmp_path / "gold.tsv"
    assert sample_alignment_gold(entries, output, n=20, corpus_n=10, seed=7) == 20
    with output.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert sum(row["language"] == "en" for row in rows) == 10
    assert sum(row["language"] == "fr" for row in rows) == 10
    assert sum(int(row["corpus_frequency"]) > 0 for row in rows) == 10
    assert {row["split"] for row in rows} <= {"train", "dev", "test"}
    assert all(row["split_group"] for row in rows)


def test_gold_sampler_keeps_mapped_synonyms_and_translations_in_one_split(tmp_path):
    from flopo2.terminology.workflows import sample_alignment_gold

    entries = [
        RegistryEntry(
            term_id="leaf",
            surface_form="leaf",
            normalized_form="leaf",
            language="en",
            target_id="PO_leaf",
            corpus_frequency=1,
        ),
        RegistryEntry(
            term_id="foliage-leaf",
            surface_form="foliage leaf",
            normalized_form="foliage leaf",
            language="en",
            target_id="PO_leaf",
            corpus_frequency=1,
        ),
        RegistryEntry(
            term_id="petal-en",
            surface_form="petal",
            normalized_form="petal",
            language="en",
            translation_group="row-7",
        ),
        RegistryEntry(
            term_id="petal-fr",
            surface_form="pétale",
            normalized_form="petale",
            language="fr",
            translation_group="row-7",
        ),
    ]
    output = tmp_path / "gold.tsv"
    assert sample_alignment_gold(entries, output, n=4, corpus_n=4, seed=17) == 4
    with output.open(newline="", encoding="utf-8") as handle:
        rows = {row["term_id"]: row for row in csv.DictReader(handle, delimiter="\t")}

    assert rows["leaf"]["split_group"] == "concept:PO_leaf"
    assert rows["leaf"]["split"] == rows["foliage-leaf"]["split"]
    assert rows["petal-en"]["split_group"] == "translation:row-7"
    assert rows["petal-en"]["split"] == rows["petal-fr"]["split"]


def test_sssom_exports_reviewed_union_components(tmp_path):
    from flopo2.terminology.sssom import write_sssom

    entry = RegistryEntry(
        term_id="BTERM:u",
        surface_form="red or yellow",
        target_id="FLOPO_union",
        target_label="red or yellow",
        mapping_relation="skos:exactMatch",
        mapping_confidence=1.0,
        review_status="reviewed",
        component_ids="PATO_red|PATO_yellow",
        logical_operator="one_of",
        curator_orcid="0000-0001-8149-5890",
    )
    output = tmp_path / "mappings.sssom.tsv"
    assert write_sssom([entry], output) == 2
    text = output.read_text()
    assert "component_of_one_of:FLOPO_union" in text
    assert "PATO_red" in text and "PATO_yellow" in text


def test_sssom_exports_reviewed_uncoined_composition(tmp_path):
    from flopo2.terminology.sssom import write_sssom

    entry = RegistryEntry(
        term_id="BTERM:compound",
        surface_form="papery yellow",
        mapping_relation="flopo:compositionalMatch",
        mapping_confidence=1.0,
        review_status="reviewed",
        component_ids="PATO_papery|PATO_yellow",
        logical_operator="all_of",
    )
    output = tmp_path / "mappings.sssom.tsv"
    assert write_sssom([entry], output) == 2
    assert "component_of_all_of:BTERM:compound" in output.read_text()


def test_alignment_evaluation_reports_candidate_and_auto_precision(tmp_path):
    from flopo2.terminology.evaluate import evaluate_alignment
    from flopo2.terminology.registry import write_registry

    registry = tmp_path / "registry.tsv"
    write_registry(
        [
            RegistryEntry(
                term_id="one",
                surface_form="leaf",
                target_id="PO_leaf",
                mapping_relation="skos:exactMatch",
                mapping_confidence=0.99,
                review_status="auto",
                candidate_ids="PO_leaf|PO_petal",
            ),
            RegistryEntry(
                term_id="nil",
                surface_form="unknown",
                review_status="unreviewed",
            ),
        ],
        registry,
    )
    gold = tmp_path / "gold.tsv"
    with gold.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["term_id", "gold_target_ids", "gold_relation", "gold_is_nil"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerow(
            {
                "term_id": "one",
                "gold_target_ids": "PO_leaf",
                "gold_relation": "skos:exactMatch",
                "gold_is_nil": "false",
            }
        )
        writer.writerow(
            {"term_id": "nil", "gold_target_ids": "", "gold_relation": "", "gold_is_nil": "true"}
        )
    report = evaluate_alignment(gold, registry)
    assert report["candidate_recall_at_10"] == 1.0
    assert report["candidate_recall_at_1"] == 1.0
    assert report["auto_accept_precision"] == 1.0
    assert report["nil_f1"] == 1.0
    assert report["relation_macro_f1"] == 1.0
    assert report["slices"]["composition"]["atomic"]["evaluated"] == 2


def test_alignment_evaluation_handles_compositions_splits_and_selective_metrics(tmp_path):
    from flopo2.terminology.evaluate import evaluate_alignment
    from flopo2.terminology.registry import write_registry

    registry = tmp_path / "registry.tsv"
    write_registry(
        [
            RegistryEntry(
                term_id="atomic",
                surface_form="leaf",
                target_id="PO_leaf",
                mapping_relation="skos:exactMatch",
                mapping_confidence=0.99,
                review_status="auto",
                candidate_ids="PO_leaf|PO_petal",
            ),
            RegistryEntry(
                term_id="wrong-train",
                surface_form="wrong",
                target_id="PO_petal",
                mapping_relation="skos:closeMatch",
                mapping_confidence=0.9,
                review_status="proposed",
                candidate_ids="PO_petal|PO_leaf",
            ),
            RegistryEntry(
                term_id="nil",
                surface_form="habitat word",
                mapping_relation="flopo:unmapped",
                mapping_confidence=1.0,
                review_status="reviewed",
            ),
            RegistryEntry(
                term_id="composition",
                surface_form="red and yellow",
                mapping_relation="flopo:compositionalMatch",
                mapping_confidence=0.8,
                review_status="proposed",
                component_ids="PATO_red|PATO_yellow",
                logical_operator="all_of",
                candidate_ids="PATO_red|PATO_yellow|PATO_color",
            ),
        ],
        registry,
    )
    gold = tmp_path / "gold.tsv"
    fields = [
        "term_id",
        "split",
        "gold_target_ids",
        "gold_relation",
        "gold_is_nil",
        "gold_logical_operator",
    ]
    with gold.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(
            [
                {
                    "term_id": "atomic",
                    "split": "test",
                    "gold_target_ids": "PO_leaf",
                    "gold_relation": "skos:exactMatch",
                    "gold_is_nil": "false",
                },
                {
                    "term_id": "wrong-train",
                    "split": "train",
                    "gold_target_ids": "PO_other",
                    "gold_relation": "skos:exactMatch",
                    "gold_is_nil": "false",
                },
                {
                    "term_id": "nil",
                    "split": "test",
                    "gold_target_ids": "",
                    "gold_relation": "flopo:unmapped",
                    "gold_is_nil": "true",
                },
                {
                    "term_id": "composition",
                    "split": "test",
                    "gold_target_ids": "PATO_red|PATO_yellow",
                    "gold_relation": "flopo:compositionalMatch",
                    "gold_is_nil": "false",
                    "gold_logical_operator": "all_of",
                },
            ]
        )

    report = evaluate_alignment(gold, registry, split="test")

    assert report["evaluated"] == 3
    assert report["skipped_other_split"] == 1
    assert report["mapped_gold"] == 2
    assert report["top1_accuracy"] == 1.0
    assert report["candidate_recall_at_1"] == 0.5
    assert report["candidate_recall_at_5"] == 1.0
    assert report["nil_f1"] == 1.0
    assert report["relation_macro_f1"] == 1.0
    assert report["slices"]["composition"]["compositional"]["evaluated"] == 1
    assert report["selective_accuracy"]["0.95"]["selected"] == 2


def test_alignment_evaluation_rejects_gold_target_leakage_across_splits(tmp_path):
    from flopo2.terminology.evaluate import evaluate_alignment
    from flopo2.terminology.registry import write_registry
    from flopo2.terminology.workflows import resplit_alignment_gold

    registry = tmp_path / "registry.tsv"
    write_registry(
        [
            RegistryEntry(term_id="leaf", target_id="PO_leaf"),
            RegistryEntry(term_id="foliage", target_id="PO_leaf"),
        ],
        registry,
    )
    gold = tmp_path / "gold.tsv"
    with gold.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["term_id", "surface_form", "language", "split", "gold_target_ids", "gold_is_nil"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerow(
            {
                "term_id": "leaf",
                "surface_form": "leaf",
                "language": "en",
                "split": "train",
                "gold_target_ids": "PO_leaf",
                "gold_is_nil": "false",
            }
        )
        writer.writerow(
            {
                "term_id": "foliage",
                "surface_form": "foliage leaf",
                "language": "en",
                "split": "test",
                "gold_target_ids": "PO_leaf",
                "gold_is_nil": "false",
            }
        )

    with pytest.raises(ValueError, match="split leakage"):
        evaluate_alignment(gold, registry, split="test")

    repaired = tmp_path / "gold-resplit.tsv"
    summary = resplit_alignment_gold(gold, repaired, seed=23)
    assert summary["components"] == 1
    with repaired.open(newline="", encoding="utf-8") as handle:
        repaired_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert repaired_rows[0]["split"] == repaired_rows[1]["split"]
    assert repaired_rows[0]["split_group"].startswith("gold-component:")
    assert evaluate_alignment(repaired, registry)["split_validation"]["leaking_groups"] == 0


def test_dense_retrieval_can_add_a_semantic_candidate_without_lexical_overlap():
    from flopo2.terminology.retrieve import HybridRetriever

    class FakeEncoder:
        def encode(self, texts):
            return [
                [1.0, 0.0] if "flower" in text or text == "blossom" else [0.0, 1.0]
                for text in texts
            ]

    retriever = HybridRetriever(_catalog(), dense_encoder=FakeEncoder())
    candidates = retriever.retrieve("blossom", role="entity", k=2)
    assert candidates[0].target_id == "PO_flower"
    assert candidates[0].dense_score == 1.0
    assert "dense_similarity" in candidates[0].evidence


def test_reviewed_nil_is_not_replaced_by_retrieval_or_surface_propagation(tmp_path):
    from flopo2.terminology.annotate import TerminologyIndex
    from flopo2.terminology.registry import build_registry, write_registry

    fna = tmp_path / "fna.csv"
    fna.write_text(
        '"term","category","hasSyn","sourceDataset","termID"\n'
        '"leaf","structure","0","x","1"\n'
        '"leaf","structure","0","x","2"\n'
    )
    manifest = tmp_path / "sources.tsv"
    manifest.write_text(
        "source_id\tparser\tpath\tlanguage\tversion\tsource_url\tlicense\tlicense_status\t"
        "redistributable\tdefinition_policy\tenabled\tnotes\n"
        "fna\tfna_category_csv\tfna.csv\ten\t1\t\tCC0\tverified\t1\tinclude\t1\t\n"
    )
    registry = tmp_path / "registry.tsv"
    entries = build_registry(manifest, registry, root=tmp_path, catalog=_catalog())
    entries[0].review_status = "reviewed"
    entries[0].curator_orcid = "0000-0001-8149-5890"
    entries[1].target_id = ""
    entries[1].target_label = ""
    entries[1].target_namespace = ""
    entries[1].mapping_relation = "flopo:unmapped"
    entries[1].review_status = "reviewed"
    entries[1].curator_orcid = "0000-0001-8149-5890"
    write_registry(entries, registry)

    rebuilt = build_registry(manifest, registry, root=tmp_path, catalog=_catalog())
    reviewed_nil = next(entry for entry in rebuilt if entry.source_record_id == "2")
    assert reviewed_nil.review_status == "reviewed"
    assert reviewed_nil.target_id == ""

    index = TerminologyIndex([reviewed_nil], _catalog())
    mention = index.annotate("leaf", "en")[0]
    assert mention.candidates == ()


def test_apply_review_supports_compositional_mapping_and_provenance(tmp_path):
    from flopo2.terminology.workflows import apply_review_queue

    entry = RegistryEntry(
        term_id="BTERM:union",
        surface_form="greenish or pinkish",
        review_status="proposed",
    )
    review = tmp_path / "review.tsv"
    with review.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "term_id",
                "curator_decision",
                "target_id",
                "component_ids",
                "logical_operator",
                "mapping_relation",
                "mapping_confidence",
                "curator_notes",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerow(
            {
                "term_id": entry.term_id,
                "curator_decision": "accept",
                "target_id": "FLOPO_union",
                "component_ids": "FLOPO_greenish|FLOPO_pinkish",
                "logical_operator": "one_of",
                "mapping_relation": "flopo:compositionalMatch",
                "mapping_confidence": "1",
                "curator_notes": "alternatives belong in FLOPO",
            }
        )
    result = apply_review_queue(
        [entry], review, _catalog(), "0000-0001-8149-5890", "2026-07-14"
    )
    assert result["accepted"] == 1
    assert entry.target_label == "greenish or pinkish"
    assert entry.target_namespace == "FLOPO"
    assert entry.logical_operator == "one_of"
    assert entry.mapping_relation == "flopo:compositionalMatch"
    assert entry.curator_orcid == "0000-0001-8149-5890"


def test_ablation_acceptance_requires_gain_without_regressions():
    from flopo2.terminology.ablation import assess_acceptance

    results = {
        "off": {
            "overall": {
                "exact": {"f1": 0.60},
                "lenient": {"f1": 0.70},
                "hallucination_rate": 0.10,
            },
            "by_language": {"en": {"f1": 0.60}, "fr": {"f1": 0.55}},
        },
        "full": {
            "overall": {
                "exact": {"f1": 0.66},
                "lenient": {"f1": 0.74},
                "hallucination_rate": 0.09,
            },
            "by_language": {"en": {"f1": 0.67}, "fr": {"f1": 0.54}},
        },
    }
    assessment = assess_acceptance(results)
    assert assessment["passed"]
    assert assessment["exact_f1_delta"] == 0.06
