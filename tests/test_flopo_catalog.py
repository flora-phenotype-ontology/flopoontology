from __future__ import annotations

from flopo2.terminology.annotate import TerminologyIndex
from flopo2.terminology.catalog import (
    OntologyCatalog,
    OntologyTerm,
    _load_flopo_registry,
    load_catalog_from_ontology_files,
)


def test_flopo_registry_is_enriched_from_released_owl(tmp_path):
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0900034\t900034\twhole plant shrub\tOTHER\t0\n",
        encoding="utf-8",
    )
    owl = tmp_path / "flopo.owl"
    owl.write_text(
        """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:owl="http://www.w3.org/2002/07/owl#"
 xmlns:obo="http://purl.obolibrary.org/obo/"
 xmlns:oboInOwl="http://www.geneontology.org/formats/oboInOwl#">
 <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0900034">
  <rdfs:subClassOf rdf:resource="http://purl.obolibrary.org/obo/FLOPO_0000000"/>
  <rdfs:label>whole plant shrub phenotype</rdfs:label>
  <obo:IAO_0000115>A phenotype of a whole plant with shrub growth form.</obo:IAO_0000115>
  <oboInOwl:hasExactSynonym>shrub</oboInOwl:hasExactSynonym>
  <oboInOwl:hasRelatedSynonym>frutex</oboInOwl:hasRelatedSynonym>
 </owl:Class>
</rdf:RDF>
""",
        encoding="utf-8",
    )

    term = _load_flopo_registry(registry, owl)["FLOPO_0900034"]

    assert term.label == "whole plant shrub phenotype"
    assert term.definition.startswith("A phenotype")
    assert term.parents == ("FLOPO_0000000",)
    assert term.synonyms == ("shrub", "frutex")
    assert term.synonym_scopes == (("shrub", "EXACT"), ("frutex", "RELATED"))


def test_runtime_catalog_forms_include_flopo_with_synonym_scope():
    catalog = OntologyCatalog(
        {
            "FLOPO_0900034": OntologyTerm(
                "FLOPO_0900034",
                "whole plant shrub",
                "FLOPO",
                synonyms=("shrub", "frutex"),
                synonym_scopes=(("shrub", "EXACT"), ("frutex", "RELATED")),
            )
        }
    )
    index = TerminologyIndex.from_catalog(catalog)

    shrub = index.annotate("shrub", "en")[0]
    frutex = index.annotate("frutex", "en")[0]

    assert shrub.semantic_roles == ("phenotype",)
    assert shrub.candidates[0].target_id == "FLOPO_0900034"
    assert shrub.candidates[0].mapping_relation == "skos:exactMatch"
    assert frutex.candidates[0].mapping_relation == "skos:relatedMatch"


def test_released_owl_can_supply_flopo_terms_without_registry(tmp_path):
    missing_registry = tmp_path / "missing.tsv"
    owl = tmp_path / "flopo.owl"
    owl.write_text(
        """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:owl="http://www.w3.org/2002/07/owl#">
 <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0900005">
  <rdfs:label>inflorescence type head</rdfs:label>
 </owl:Class>
</rdf:RDF>
""",
        encoding="utf-8",
    )

    terms = _load_flopo_registry(missing_registry, owl)

    assert terms["FLOPO_0900005"].label == "inflorescence type head"


def test_registry_requires_a_released_class_declaration(tmp_path):
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0980106\t980106\tcrimson\tOTHER\t0\n"
        "http://purl.obolibrary.org/obo/FLOPO_0980092\t980092\tsilvery\tOTHER\t0\n",
        encoding="utf-8",
    )
    owl = tmp_path / "flopo.owl"
    owl.write_text(
        """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:owl="http://www.w3.org/2002/07/owl#">
 <rdf:Description rdf:about="http://purl.obolibrary.org/obo/FLOPO_0980106">
  <rdfs:label>crimson</rdfs:label>
 </rdf:Description>
 <rdf:Description rdf:about="http://purl.obolibrary.org/obo/FLOPO_0980092">
  <rdf:type rdf:resource="http://www.w3.org/2002/07/owl#Class"/>
  <rdfs:label>silvery</rdfs:label>
 </rdf:Description>
 <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0900005">
  <rdfs:label>inflorescence type head</rdfs:label>
 </owl:Class>
</rdf:RDF>
""",
        encoding="utf-8",
    )

    terms = _load_flopo_registry(registry, owl)

    assert "FLOPO_0980106" not in terms
    assert terms["FLOPO_0980092"].label == "silvery"
    assert "FLOPO_0900005" in terms


def test_audit_catalog_loads_pinned_obo_directly_and_indexes_only_live_terms(tmp_path):
    po = tmp_path / "po.obo"
    po.write_text(
        """format-version: 1.2

[Term]
id: PO:0030121
name: capitulum inflorescence
def: "An inflorescence with sessile flowers on a common receptacle." []
synonym: "flower head" EXACT []
synonym: "capitula (exact, plural)" EXACT []
synonym: "head (broad)" BROAD []
synonym: "体細胞plant胚 (Japanese, exact)" EXACT Japanese []
is_a: PO:0009049 ! inflorescence

[Term]
id: PO:0999999
name: obsolete floral thing
is_obsolete: true
""",
        encoding="utf-8",
    )
    pato = tmp_path / "pato.obo"
    pato.write_text(
        """format-version: 1.2

[Term]
id: PATO:0000322
name: red
""",
        encoding="utf-8",
    )
    owl = tmp_path / "flopo.owl"
    owl.write_text(
        """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:owl="http://www.w3.org/2002/07/owl#">
 <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0900005">
  <rdfs:label>inflorescence type head</rdfs:label>
 </owl:Class>
</rdf:RDF>
""",
        encoding="utf-8",
    )

    catalog = load_catalog_from_ontology_files(po, pato, owl)

    assert catalog.terms["PO_0030121"].definition.startswith("An inflorescence")
    assert catalog.terms["PO_0030121"].parents == ("PO_0009049",)
    assert catalog.relation_for_surface(catalog.terms["PO_0030121"], "flower head") == (
        "skos:exactMatch"
    )
    assert catalog.relation_for_surface(catalog.terms["PO_0030121"], "head") == (
        "skos:narrowMatch"
    )
    assert catalog.form_to_ids["flower head"] == {"PO_0030121"}
    assert catalog.form_to_ids["capitula"] == {"PO_0030121"}
    assert "capitula exact plural" not in catalog.form_to_ids
    assert "plant" not in catalog.form_to_ids
    assert catalog.terms["PO_0999999"].deprecated is True
    assert "obsolete floral thing" not in catalog.form_to_ids
    assert catalog.form_to_ids["red"] == {"PATO_0000322"}
    assert catalog.form_to_ids["inflorescence type head"] == {"FLOPO_0900005"}
