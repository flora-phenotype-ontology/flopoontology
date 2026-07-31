from flopo2.owl.pubescent_migration import build_migration_report


def test_pubescent_migration_is_complete_and_review_only(tmp_path):
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000001\t1\tleaf pubescent\t"
        "EQ|PO_0009025|PATO_0000455\t0\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000002\t2\tleaf red\t"
        "EQ|PO_0009025|PATO_0000322\t0\n"
    )
    owl = tmp_path / "flopo.owl"
    owl.write_text(
        """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:owl="http://www.w3.org/2002/07/owl#">
 <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0000001">
  <owl:equivalentClass><owl:Class><owl:intersectionOf rdf:parseType="Collection">
   <owl:Restriction>
    <owl:someValuesFrom rdf:resource="http://purl.obolibrary.org/obo/PATO_0000455"/>
   </owl:Restriction>
  </owl:intersectionOf></owl:Class></owl:equivalentClass>
 </owl:Class>
</rdf:RDF>
"""
    )
    pato = tmp_path / "pato.obo"
    pato.write_text(
        "format-version: 1.2\n\n"
        "[Term]\nid: PATO:0000455\nname: pubescent\n"
        'def: "A maturity quality at the onset of puberty." []\n\n'
        "[Term]\nid: PATO:0001320\nname: pubescent hair\n"
        'def: "A pilosity quality of being covered with short hairs or soft down." []\n'
    )
    rows, summary = build_migration_report(registry, owl, pato)
    assert len(rows) == 1
    assert rows[0]["old_flopo_id"] == "FLOPO_0000001"
    assert rows[0]["obsolete_label"] == "obsolete leaf pubescent"
    assert rows[0]["replacement_flopo_id"] == "FLOPO_0000003"
    assert rows[0]["replacement_flopo_id"] != rows[0]["old_flopo_id"]
    assert rows[0]["replacement_signature"] == "EQ|PO_0009025|PATO_0001320"
    assert rows[0]["replacement_id_status"] == "provisional_unreserved"
    assert rows[0]["term_replaced_by"] == (
        "http://purl.obolibrary.org/obo/FLOPO_0000003"
    )
    assert rows[0]["recommendation"] == "obsolete_and_replace_wrong_semantics"
    assert rows[0]["curator_decision"] == ""
    assert summary["migration_mode"] == "obsolete_and_replace"
    assert summary["cross_artifact_match"] is True
    assert summary["provisional_replacements_minted"] == 1
    assert summary["existing_replacements_reused"] == 0
    assert summary["old_logical_axioms_removed_required"] is True
    assert summary["term_replaced_by_required"] is True
    assert summary["proposed_ids_are_reserved"] is False
    assert summary["automatic_application"] is False
    assert summary["application_ready"] is False


def test_pubescent_migration_reuses_an_existing_correct_replacement(tmp_path):
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000001\t1\tleaf pubescent\t"
        "EQ|PO_0009025|PATO_0000455\t0\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000009\t9\tleaf pubescent\t"
        "EQ|PO_0009025|PATO_0001320\t0\n"
    )
    owl = tmp_path / "flopo.owl"
    owl.write_text(
        """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:owl="http://www.w3.org/2002/07/owl#">
 <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0000001">
  <owl:someValuesFrom rdf:resource="http://purl.obolibrary.org/obo/PATO_0000455"/>
 </owl:Class>
</rdf:RDF>
"""
    )
    pato = tmp_path / "pato.obo"
    pato.write_text(
        "[Term]\nid: PATO:0000455\nname: pubescent\ndef: \"puberty.\" []\n\n"
        "[Term]\nid: PATO:0001320\nname: pubescent hair\ndef: \"hairy.\" []\n"
    )
    rows, summary = build_migration_report(registry, owl, pato)
    assert rows[0]["replacement_flopo_id"] == "FLOPO_0000009"
    assert rows[0]["replacement_id_status"] == "existing_active"
    assert rows[0]["replacement_class_action"] == "reuse_existing_correct_class"
    assert summary["existing_replacements_reused"] == 1
    assert summary["provisional_replacements_minted"] == 0


def test_pubescent_migration_reports_cross_artifact_mismatch(tmp_path):
    registry = tmp_path / "registry.tsv"
    registry.write_text("flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n")
    owl = tmp_path / "flopo.owl"
    owl.write_text(
        """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:owl="http://www.w3.org/2002/07/owl#">
 <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0000001">
  <owl:someValuesFrom rdf:resource="http://purl.obolibrary.org/obo/PATO_0000455"/>
 </owl:Class>
</rdf:RDF>
"""
    )
    pato = tmp_path / "pato.obo"
    pato.write_text(
        "[Term]\nid: PATO:0000455\nname: pubescent\ndef: \"puberty.\" []\n\n"
        "[Term]\nid: PATO:0001320\nname: pubescent hair\ndef: \"hairy.\" []\n"
    )
    _rows, summary = build_migration_report(registry, owl, pato)
    assert summary["cross_artifact_match"] is False
    assert summary["owl_only_ids"] == ["FLOPO_0000001"]


def test_pubescent_migration_can_record_curator_approval(tmp_path):
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000001\t1\tleaf pubescent\t"
        "EQ|PO_0009025|PATO_0000455\t0\n"
    )
    owl = tmp_path / "flopo.owl"
    owl.write_text(
        """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:owl="http://www.w3.org/2002/07/owl#">
 <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0000001">
  <owl:someValuesFrom rdf:resource="http://purl.obolibrary.org/obo/PATO_0000455"/>
 </owl:Class>
</rdf:RDF>
"""
    )
    pato = tmp_path / "pato.obo"
    pato.write_text(
        "[Term]\nid: PATO:0000455\nname: pubescent\ndef: \"puberty.\" []\n\n"
        "[Term]\nid: PATO:0001320\nname: pubescent hair\ndef: \"hairy.\" []\n"
    )

    rows, summary = build_migration_report(registry, owl, pato, approved=True)

    assert rows[0]["replacement_id_status"] == "new_approved_reserved"
    assert rows[0]["curator_decision"] == "accept"
    assert "0000-0001-8149-5890" in rows[0]["curator_notes"]
    assert summary["proposed_ids_are_reserved"] is True
    assert summary["application_ready"] is True
    assert summary["automatic_application"] is False
