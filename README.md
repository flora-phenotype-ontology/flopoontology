Project to identify phenotypes occurring in flora files.

There are three components:

1. ParseFloraFile is the original piece of code generated at the pro-iBiosphere Hackathon in Leiden. It will find PO and PATO terms in flora gabon and malaysia.
2. Lucene-based indexing: this is a refactoring of the original code that uses the Lucence indexes and analyzers.
3. MakePlantPhenotypeOntology generates a phenotype ontology from the generated descriptions.
4. DeprecateDumbClasses deprecates all unsatisfiable classes; this script needs to be run after adding axioms (e.g., a GCI) that makes classes that could not exist in FLOPO unsatisfiable. Useful when adding `has-part some (owl:Thing and has-quality some 'process quality') SubClassOf: owl:Nothing` or similar axioms.

The resulting ontology is available under a CC-0 license in the `ontology` folder. All code is available under the BSD license.

## Release artifacts

- `ontology/flopo.owl` is the full development release. It preserves every stable FLOPO
  term IRI and contains logical definitions, imports, local PO/PATO support terms, and
  obsolete identifier shells.
- `ontology/flopo-inferred.owl` is the ELK-classified development release.
- `ontology/flopo-light.owl` is the pre-classified browser release recommended for
  BioPortal. It contains only active FLOPO phenotype classes and named FLOPO-to-FLOPO
  subclass axioms. Its sole named root is `FLOPO:0000000` (`flora phenotype`); imported
  support vocabularies and obsolete terms remain available from the full release.

The light artifact reuses the canonical FLOPO IRIs unchanged; it is a view of the full
ontology, not a second identifier space. Rebuild the classified and light artifacts with:

```bash
uv run --frozen python tools/classify_flopo_release.py
uv run --frozen python -m flopo2.owl.light
```

### Release procedure

Each `tools/update_flopo_*_release.py` command embeds one generated module in
`ontology/flopo.owl` between `BEGIN/END GENERATED` markers. Re-embedding a module removes every
earlier declaration of the classes it declares, wherever they are, so after any module update
run the final passes in this order:

```bash
python -m tools.update_flopo_obo_qc_release          # restores definitions owned by the QC block
python -m tools.update_flopo_top_level_parents       # keeps only the two approved root children
python tools/prune_orphan_blank_nodes.py             # drops expression nodes left by replacements
python -m flopo2.ids.registry ontology/flopo.owl -o config/flopo_id_registry.tsv
python tools/classify_flopo_release.py && python -m flopo2.owl.light
python tools/obo_dashboard_gate.py                   # FP04 passes once the release is published
```

`tests/test_flopo_release_compatibility.py` requires every class IRI of every frozen public
release (`releases/<date>/`) to survive. After publishing, freeze the release with
`tools/freeze_flopo_release.py`. The colour backbone builder may be re-run on an embedded
release: it restores the pre-backbone declarations from `config/flopo_colour_backbone_base.ttl`.

### 2026-10-05

This release repairs the 2026-09-18 release:

- It restores 1,412 colour phenotypes, of which 1,173 IRIs had vanished.
- It brings back the 2026-07-31 upper-level rebuild that 2026-09-18 had reverted.
- It removes the phenotypic-sex class axiom. The flower sex phenotypes are reinstated and two
  new ones are added (FLOPO:0990000-0990001).
- It obsoletes the 21 classes built on the obsolete PATO:0000069.
- It adds creator and citation metadata.

The annotation class extension is rebuilt from the stage-25 corpus, after conflict resolution
and the colour-backbone migration.
