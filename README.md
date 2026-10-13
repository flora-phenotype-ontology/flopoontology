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
python -m tools.update_flopo_bearer_parents         # EQ class under its bearer's 'E phenotype'
python tools/classify_flopo_release.py
python -m tools.update_flopo_inferred_parents       # assert the classified hierarchy (browsers)
python tools/classify_flopo_release.py && python -m flopo2.owl.light
python tools/obo_dashboard_gate.py                   # FP04 passes once the release is published
```

Since the 2026-10 release, `flopo.owl` asserts the reasoner's direct superclasses. Most classes
are defined only by equivalent-class axioms over PO and PATO, so a browser that shows the asserted
hierarchy (BioPortal) or cannot load the imports (AberOWL) otherwise sees one flat list. The
bearer pass is needed because trait classes ("bark odor") are not subsumed by "bark phenotype"
without reflexive parthood.

`tests/test_flopo_release_compatibility.py` requires every class IRI of every frozen public
release (`releases/<date>/`) to survive. After publishing, freeze the release with
`tools/freeze_flopo_release.py`. The colour backbone builder may be re-run on an embedded
release: it restores the pre-backbone declarations from `config/flopo_colour_backbone_base.ttl`.

### 2026-10-13

- `flopo.owl` asserts the classified hierarchy: entity–quality classes sit beneath their bearer's
  phenotype class, followed by the reasoner's direct superclasses. BioPortal (asserted axioms
  only) and AberOWL (when the PO and PATO imports fail to load) previously showed flat lists.
- 23 flora value terms (FLOPO:0991000–0991023) are added beneath PATO, reviewed before release;
  FLOPO:0991008 was withdrawn unreleased.
- Four seed-weight classes with malformed IRIs (`obo/flopo.owl#FLOPO_02102xx`) are obsolete and
  replaced by FLOPO:0992000–0992003.

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

## Saudi Flora Trait Atlas

Trait statements from Saudi floras are annotated with FLOPO, PO and PATO, published as RDF, and
browsed through a local website with a SPARQL endpoint.

| Source | Ingest |
|---|---|
| NCVC, *Guide to the native plants of the Kingdom of Saudi Arabia* (2024) | `flopo2.ingest.ncvc_guide` / `ncvc_annotate` |
| S. Collenette, *An illustrated guide to the flowers of Saudi Arabia* (1985) | `flopo2.ingest.collenette_llm` (Qwen transcription of the OCR entries) / `collenette_annotate` |

Both guides go through the same anchoring, grounding and FLOPO gates. Colour words are read
on the ISCC-NBS colour backbone (`config/botanical_colour_synonyms.tsv`). Rule tables are applied
in this order:

1. `flopo2/ingest/ncvc_normalization.tsv` (reviewed);
2. `flopo2/ingest/flora_value_term_rules.tsv`, generated from the FLOPO flora value terms (below);
3. `flopo2/ingest/collenette_normalization.tsv` (reviewed by Claude);
4. `flopo2/ingest/llm_term_rules.tsv`: Qwen's choice among lexical candidates, filtered by
   deterministic guardrails and a second, independent verification call. Every rule is marked
   `llm_proposed`.

A later table's rule that grounds a word replaces an NCVC "hold" for that word
(`ncvc_annotate.merge_rules`). The default NCVC corpus in `derived/` keeps to the reviewed NCVC
table; the atlas reads its own NCVC run in `local-corpora/saudi-flora/ncvc-derived/`.

### FLOPO flora value terms (FLOPO:0991000-0991999)

Quality words of the Saudi floras that PATO lacks are FLOPO-local value classes, each directly
beneath its closest PATO class, like the provisional PATO candidates of FLOPO:0985xxx. Examples
are axillary, solitary, capitate, caespitose (tufted), semi-prostrate, creeping, mat-forming,
leafy, twiggy, subsessile, bipinnate, unisexual, exfoliating, fissured, and the odours
sweet-scented, spicy-scented, sour-smelling, musty-smelling and foetid. Each class is a
candidate for submission to PATO.

```bash
python -m tools.build_flopo_flora_value_extension   # spec -> module, rules, (bearer, attribute) pairs
python -m tools.update_flopo_flora_value_release    # embed in flopo.owl, then the final passes above
```

The spec is `config/flopo_flora_value_terms.tsv`.

### How statements are represented

- Colour phrases are read on the ISCC-NBS backbone (`flopo2/ingest/colour_words.py`). A
  compound of two hues becomes the intermediate category: orange-red is 'reddish orange',
  orange-yellow is 'orange yellow', grey-green is 'grayish green'. Other compounds become their
  head colour.
- Alternatives and continua become qualitative value relations ("ovate to oblong", "red tending
  to orange-yellow", "white or pink"). They are matched deterministically first.
  `flopo2.ingest.llm_relations` (Qwen) locates the endpoints of the rest, and the spans are
  re-verified verbatim before use.
- Every annotation class carries its OWL definition in the assertion modules:
  - negation is `ObjectComplementOf` (the part lacks the quality; for "present", the part is absent);
  - measurements are `has_magnitude some xsd:decimal[>= a, <= b]` with a UO unit (`has_value_unit`).
- Numeric values of one taxon, part and attribute from several statements or sources are merged
  into one range (graph `merged`, `fb:MergedTrait` with its member records). The merged range has
  an OWL class, and each source value entails the axiom `taxon SubClassOf has_phenotype some`
  that class.

Taxa are merged across sources by their accepted World Flora Online record. OCR misspellings of
names are fixed only when WFO verifies the correction.

```bash
tools/build_saudi_flora.sh                  # transcribe (cached), annotate, build RDF
~/.cache/flopo-venv/bin/python -m flopo2.saudi.server   # http://127.0.0.1:8777/
```

`flopo2.saudi.build` writes one named graph per source and layer to `local-corpora/saudi-flora/`:
- the OWL assertion module (`flopo2.owl.assertions`),
- a browse index (`http://phenomebrowser.net/flopo/browse#`),
- places,
- taxa,
- vocabulary.

The server loads these graphs, plus `ontology/flopo-inferred.owl`, into Oxigraph. The
browser is in `web/saudi/`.

The data stays git-ignored because both guides are copyrighted and the dataset quotes their
sentences as evidence.
