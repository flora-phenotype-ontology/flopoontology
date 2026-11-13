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

### Automatic EQ review and trait annotations

The global-flora candidate promotion workflow classifies candidates with ELK and then
checks their bearer compatibility and inferred neighbourhoods with Qwen. Every input
gets an added, equivalent-reuse, or triage disposition. See
[the workflow and annotation semantics](docs/automatic-eq-promotion.md).

The 2026-10-25 release adds 1,522 EQ classes after classification and Qwen review:
963 in the initial pass and 559 after re-extraction. Another 25 re-extracted
proposals map to existing classes. Of the original 2,195 candidates, 687 still
require review, including 28 with partially accepted corrections; see the
[current outcome ledger](curation/flopo-current-eq-dispositions-2026-10-25.tsv).
The release also includes 69 defined provisional flora qualities since v2026-10-14:
20 from earlier unpublished work, 25 missing IDs, and 24 additional qualities.

On 2026-11-08 the 687 held candidates were reviewed by Claude Fable 5.1 (an AI, at the
curator's instruction; not an expert botanist's review). 506 were accepted as proposed,
56 were remapped to the botanical quality the source meant (34 "acute" and 7 "subacute"
apices had been grounded to PATO process-duration qualities; others to new FLOPO values
such as head-shaped, fascicled, cartilaginous and reticulate), 27 reuse an existing class
with the same label, and 98 were rejected (unsupported by the source passages, relational
or vacuous qualities, process qualities on anatomical entities). The 561 resulting
signatures passed ELK and the deterministic bearer checks; 544 new classes were added and
17 reuse existing classes (`flopo2.verify.eq_release curate`, module
`ontology/flopo-automatic-eq-066f0473963c.ttl`). Every decision is in
[the curator ledger](curation/flopo-eq-curator-review-2026-11-08.tsv) and the
[promotion dispositions](curation/flopo-curator-eq-dispositions-2026-11-08.tsv). The same
review accepted 67 of the 69 provisional flora qualities, withdrew cherry-like
(FLOPO:0991042) and amplexicaul (FLOPO:0991066, replaced by clasping), widened unisexual to
inflorescences, and added six values (FLOPO:0991095–0991100); see
[the term review](curation/flopo-provisional-term-review-2026-11-08.tsv).
The `traitOrPhenotype` annotation identifies 5,956 traits and 19,051 phenotypes,
with explicit reasons for the 2,430 unclassified or inapplicable cases.

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
python -m flopo2.owl.trait_phenotype                # annotate PATO attributes versus values
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

For a new GitHub-hosted version, FP04 cannot resolve until the assets are published.
The normal pre-push and CI gates reject this error. An explicit release-staging
option is available: `FLOPO_PENDING_RELEASE_VERSION=YYYY-MM-DD git push ...`.
It runs a fresh official Dashboard and permits only the exact unresolved-version
FP04 result, checks the canonical version metadata and artifact SHA-256, and rejects
all other failures. Use it only for the release branch/tag publication step. Publish
the three matching assets, run the full gate without this option, then update
`master` through its ordinary gate and freeze the release. The hook rejects this
staging option for updates to `master`. The staging result is
not a claim that the public release has passed the complete Dashboard.

### 2026-11-13

28,146 FLOPO classes (1,306 deprecated identifiers retained); every earlier identifier
preserved; ELK finds no unsatisfiable classes.

- Corrects five class definitions that OWL tools could not read. FLOPO:0022142 'whole plant
  herbaceous' had lost its definition and FLOPO:0900035 'whole plant lianescent' had an empty
  superclass in 2026-11-08; the "exactly N leaflets" restrictions of FLOPO:0900067 and
  FLOPO:0980426 (tri- and bifoliolate leaf) used RO:0002180 without declaring it, in every
  release since 2026-07-31. OWLAPI read them as `http://org.semanticweb.owlapi/error#` classes,
  three of which 2026-11-08 asserts as superclasses. `tests/test_flopo_release_integrity.py`
  now guards against all three defects.
- 110 FLOPO flora values FLOPO:0991101–0991210 from the review of the quality words that 36
  parsed floras use and PATO lacks (unequal, urceolate, peltate, sheathing, climbing, cauline,
  included, adnate, superior and inferior ovary, dehiscent and its kinds, pinnatisect,
  introrse, …), each beneath the closest PATO class, with a PATO-style definition and a note
  on its PATO siblings. Candidates for submission to PATO.
- 49 FLOPO-local anatomy classes FLOPO:0986007–0986055 beneath PO (spathe, gynostemium,
  pollinium, indusium, pseudobulb, style branch, calyx tube, floral disc, cupule, ochrea, …),
  provisional until PO has them.
- Review by Claude Fable 5.2 (AI) at the curator's instruction; every decision is in
  `curation/flopo-flora-candidate-review-2026-11-13.tsv`.

### 2026-11-08

27,987 FLOPO classes (1,306 deprecated identifiers retained); every earlier identifier
preserved; ELK finds no unsatisfiable classes.

- 544 EQ classes added after the curator review of the 687 candidates held on 2026-10-25;
  17 further candidates reuse existing classes, 27 collided with an existing label and were
  not minted, 98 were rejected. Reviewer: Claude Fable 5.1 (AI) at the curator's instruction.
- Six FLOPO flora values: acute (sensu botany), subacute (sensu botany), head-shaped,
  fascicled, cartilaginous (sensu botany), reticulate. 67 provisional values are now
  reviewed; cherry-like and amplexicaul are obsolete (amplexicaul replaced by clasping).
- PATO 2026-10-01 (pato-ontology/pato#618, #619, #620) is the pinned PATO. Its 18 new
  botanical qualities PATO:0104350–0104367 replace the provisional FLOPO bridges
  FLOPO:0985000–0985016 and FLOPO:0987000: every axiom, combination and rule now uses the
  PATO identifier (`tools/migrate_pato_bridges.py`, `config/flopo_pato_bridge_migration.tsv`),
  and the bridges are deprecated shells with `IAO:0100001`. The PO bridges (corolla lip,
  corolla tube, haustorium, …) stay provisional until Planteome/plant-ontology#734 is merged.
- Three "purplish red" candidates await a colour class for that ISCC-NBS sector.

### 2026-10-25

[Published release](https://github.com/flora-phenotype-ontology/flopoontology/releases/tag/v2026-10-25):
27,437 FLOPO classes, including 1,522 new EQs and 69 provisional flora qualities
since v2026-10-14. All previous identifiers are preserved. The 90 release tests
passed, and the complete postpublication OBO Dashboard passed all 14 implemented
checks with zero errors and zero unsatisfiable classes. Download hashes and the
unaltered Dashboard results are recorded in
[the release validation](releases/2026-10-25/validation.json).

### 2026-10-14

- Plane and solid egg shapes are separated. PATO:0001891 is a solid (3-D) egg shape but was
  labelled "ovate", the botanical word for the plane outline of a leaf or petal;
  [pato-ontology/pato#627](https://github.com/pato-ontology/pato/pull/627) relabels it "ovoid"
  and adds plane ovate and solid obovoid. Until it is merged FLOPO uses the temporary classes
  FLOPO:0991024 (ovate, beneath PATO 2-D shape) and FLOPO:0991025 (obovoid). The 150 FLOPO
  classes built on PATO:0001891 keep their IRIs: 30 on flat organs (leaf, leaflet, petal, sepal,
  bract, glume, …) now use FLOPO:0991024, and the other 120 keep PATO:0001891 and are relabelled
  "… ovoid" (`tools/build_flopo_flora_corrections.py`).
- The 129 "increased length" and "decreased length" classes have the exact synonyms "… long"
  and "… short".
- Disjointness axioms (`config/flopo_disjoint_values.tsv`): a single whole plant cannot be both
  herbaceous and frutescent, arborescent or ligneous, both suffrutescent or frutescent and
  arborescent, have two of annual, biennial and perennial life span, or be both evergreen and
  deciduous. They are stated as `DisjointClasses(E and has_quality some A, E and has_quality
  some B)`, so they constrain individual plants; a taxon described as "herb" by one flora and
  "shrub" by another is a conflict for review, not an inconsistency. Hairiness is not declared
  disjoint, because a glabrescent organ is hairy and later glabrous.

When #627 is merged, the temporary classes are replaced by PATO:0104368 and PATO:0104369.

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

## FLOPO Trait Atlas

Trait statements from multiple floras are annotated with FLOPO, PO and PATO, published as RDF,
and browsed through a website with a SPARQL endpoint. The collection began with the Saudi
guides below and now includes extracts from 40 sources (24 October 2026), including African,
Asian and American floras. Many are small pilot samples; the website reports the included
taxa and transcribed statements per source, not completeness of the original floras.
The historical `web/saudi/` and `local-corpora/saudi-flora/` paths remain in use.

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

Before the LLM term rules, `flopo2.ingest.llm_reread` has Qwen re-read the rows whose part or
quality did not match. It separates part and quality, uses the glossed standard term, and gives
counts, processes and relations to other parts their own reasons. The steps and fixes to reuse
for a new flora are in `docs/flora-annotation-playbook.md`.

A later table's rule that grounds a word replaces an NCVC "hold" for that word
(`ncvc_annotate.merge_rules`). The default NCVC corpus in `derived/` keeps to the reviewed NCVC
table; the atlas reads its own NCVC run in `local-corpora/saudi-flora/ncvc-derived/`.

### FLOPO flora value terms (FLOPO:0991000-0991999)

Quality words of the floras that PATO lacks are FLOPO-local value classes, each directly
beneath its closest PATO class, like the provisional PATO candidates of FLOPO:0985xxx. Examples
are axillary, solitary, capitate, caespitose (tufted), creeping, mat-forming,
leafy, twiggy, subsessile, bipinnate, unisexual, exfoliating, fissured, and the odours
sweet-scented, spicy-scented, sour-smelling, musty-smelling and foetid. Each class is a
candidate for submission to PATO.

FLOPO:0991026–0991045 (2026-10-15, not yet reviewed) add fibrous, fibrous-rooted, beaked,
horned, zigzag, umbelliform, medium-sized, pectinate (comb-like), indeterminate, subterranean,
aerial, androgynous, virgate (broom-like), palm-like, claw-shaped, pea-sized, cherry-like,
straggly, submerged and floating.

FLOPO:0991046–0991070 add 25 provisional values required by the broader flora extracts,
including membranous, scarious, pilose, puberulous and mucronate. These remain marked
`pending final vetting`; embedding them makes the dataset self-contained without implying
curatorial acceptance.

```bash
python -m tools.build_flopo_flora_value_extension   # spec -> module, rules, (bearer, attribute) pairs
python -m tools.update_flopo_flora_value_release    # embed in flopo.owl, then the final passes above
```

The spec is `config/flopo_flora_value_terms.tsv`.

The flora corrections module (plane ovate, length synonyms, disjoint values; see 2026-10-14) is
built from the release itself, after the value terms are embedded:

```bash
python -m tools.build_flopo_flora_corrections            # -> ontology/flopo-flora-corrections.ttl
python -m tools.update_flopo_flora_corrections_release   # embed, then the final passes above
```

### iNaturalist images and observations

The atlas can display licensed iNaturalist photographs and observation links through the
audited crosswalk built by `python -m flopo2.saudi.inaturalist --snapshot /path/to/inat_taxa.csv`.
Difficult names are assessed by Qwen and checked against live iNaturalist records and WFO.
Unresolved taxa retain a name-search link. See
[iNaturalist integration and trait-learning research](docs/inaturalist-trait-learning.md)
for refresh instructions, matching safeguards and the weak-supervision literature review.

### Visual trait reasoning pilot

The experimental implementation in `flopo2/vision/` follows the
[architecture and experiment design](docs/flopo-visual-reasoning-design.md). It compiles
a bounded positive OWL fragment, preserves organ–quality binding, computes exact marginal
query probabilities under explicit categorical choices, and trains small organ × colour
heads on frozen localized features. The downstream profile scorer has no hidden image or
species-classification channel. This is a development pilot, not a validated recognition service.

GPU extraction runs on Orix with the pinned environment and model revisions in `deploy/orix/`.
Download models with `flopo2/vision/prefetch.py` before allocating a GPU; submit
`deploy/orix/extract.sbatch` after copying the image manifest, images and extractor to Orix.
The completed extraction produces `regions.jsonl`, per-image crop features and `run.json`.

```bash
# Local CPU preparation (the release and raw artifacts are not committed).
python -m flopo2.vision.pilot freeze --release PATH_TO_RELEASE --out DATA --taxa 60
python -m flopo2.vision.pilot collect --out DATA --observations 200
# After retrieving the completed Orix extraction under DATA/extraction:
python -m flopo2.vision.review --data DATA
python -m flopo2.vision.audit --data DATA
REVIEW_BIND=127.0.0.1 bash tools/serve_visual_review.sh DATA
```

The review packet exports only explicitly reviewed images. Review organ boxes and colour
labels, or mark a region's colour `unlabelled` to review eligibility without providing a
colour target. Unknown and unassessable colours never become negative labels. Corrected or
deleted boxes require feature re-extraction with `extract.py --reviewed EXPORT.json` into
a separate output directory. Machine proposals are not independent gold annotations.

`weak-event-candidates.json` is a separate source-review worksheet. It is intentionally
unusable for training until a reviewer checks source stability, compatible scope and eligible
region indices, and supplies development-audited contamination/reliability values. Every
allowed alternative must be representable by visually anchored primitives; partially
representable unions are rejected. Retain each candidate's pinned source identifiers/hash.

```bash
# Localized supervised control; CPU suffices for these small frozen-feature heads.
python -m flopo2.vision.train --data DATA --reviewed EXPORT.json \
  --extraction REVIEWED_EXTRACTION --out RUN_SUPERVISED --seed 0
# Same inputs and seed, now with reviewed weak source events.
python -m flopo2.vision.train --data DATA --reviewed EXPORT.json \
  --extraction REVIEWED_EXTRACTION --weak-events AUDITED_EVENTS.json \
  --out RUN_WEAK --seed 0
python -m pytest -q tests/vision
```

Both commands produce development training diagnostics only. The independent evaluation,
grouped splits, learned composition baseline and richer-axiom controls in the experiment
design remain necessary before making an accuracy or reasoning-benefit claim.

Manual annotations are **optional for training**. The fully automatic path uses frozen
organ proposals, a BioCLIP image/text prior and research-grade taxon labels joined to flora
events. It preserves machine labels as unreviewed, uses one focal region per organ per image,
balances repeated observations, and runs fixed noise sensitivities rather than treating
species descriptions as exact image labels:

```bash
# On Orix, encode the pinned text prior and train three noise settings in one GPU job.
# First copy flopo2/vision/{__init__,extract,logic,model,prototypes,weak_train}.py into
# the isolated workbench package. The existing frozen audit and models remain on data storage.
sbatch deploy/orix/prototypes.sbatch
# Alternatively, after retrieving DATA/text-prior, train the small heads locally:
python -m flopo2.vision.weak_train --data DATA --out NEW_RUN_DIRECTORY
```

The earlier reviewed-anchor trainer remains available for optional supervised refinement.
Held-out research-grade species labels can evaluate plant identification without manual
trait labels. Direct visual trait accuracy needs an independent annotated benchmark; source
compatibility and agreement with a pretrained model are not substitutes for that evaluation.

The next model (`flopo2.vision.multi`) has a shared organ predictor and conditional heads for
colour, outline, three-dimensional shape, hairiness and margins. It predicts 33 named states
plus unknown states. `expand.py` freezes the schema and split before fitting: earlier pilot
genera remain in training, while novel genera are reserved and overlapping observers,
observations and exact/perceptual duplicate candidates are excluded across splits. The
pretrained-prior regularizer also sees training images only.

```bash
python -m flopo2.vision.pilot freeze --release RELEASE --out DATA_V2 --taxa 120
python -m flopo2.vision.pilot collect --out DATA_V2 --per-taxon 8
python -m flopo2.vision.expand --data DATA_V2 --prior DATA_V1
python -m flopo2.vision.phenotypes --release RELEASE --data DATA_V2
# Copy inputs/code to the Orix workbench and data directory specified in this script:
sbatch deploy/orix/multi.sbatch
```

The saved `model.pt` includes the trait heads, fixed species profiles and a reference
distribution estimated from training-image priors. Species ranking consumes only explicit
trait distributions. There is no species-loss gradient or hidden image embedding in the
ranker. The first evaluation compares pretrained traits, weakly trained traits and colour-only
evidence over the same candidate catalogue. It measures held-out species identification,
not direct trait accuracy or an advantage of OWL over equivalent procedural reasoning.

```bash
# Predict on cached image regions; the photo's true taxon is not an input.
python -m flopo2.vision.predict --checkpoint RUN/model.pt \
  --extraction DATA_V2/extraction --photo-id PHOTO_ID \
  --phenotypes DATA_V2/phenotype-queries.json --out prediction.json
# For a new image, run feature extraction inside an Orix GPU allocation:
python -m flopo2.vision.predict --checkpoint RUN/model.pt \
  --image plant.jpg --models PINNED_MODEL_DIRECTORY \
  --phenotypes DATA_V2/phenotype-queries.json --out prediction.json
```

Predictions include region boxes, uncertain trait states, species evidence contributions and
supported FLOPO phenotype identifiers. Broad entailed phenotypes are included in the query
coverage count; they are not additional independently learned outputs. Unsupported or
unobservable traits remain unknown. The initial collection samples one species per genus,
so its identification results do not establish discrimination among closely related species.

### How statements are represented

- Colour phrases are read on the ISCC-NBS backbone (`flopo2/ingest/colour_words.py`). A
  compound of two hues becomes the intermediate category: orange-red is 'reddish orange',
  orange-yellow is 'orange yellow', grey-green is 'grayish green'. Other compounds become their
  head colour.
- Alternatives ("annual or perennial", "white, pink or purple") are one value, the union
  `has_quality some (annual or perennial)`. Continua and changes in time ("ovate to oblong", "red
  tending to orange-yellow", "white becoming pink") are qualitative value relations, because an
  intermediate value is neither endpoint. A botanical compound ("linear-lanceolate") is a
  continuum between its two words. Both are matched deterministically first.
  `flopo2.ingest.llm_relations` (Qwen) locates the endpoints of the rest, and the spans are
  re-verified verbatim before use.
- Every annotation class carries its OWL definition in the assertion modules:
  - negation is `ObjectComplementOf` (the part lacks the quality; for "present", the part is absent);
  - measurements are `has_magnitude some xsd:decimal[>= a, <= b]` with a UO unit (`has_value_unit`).
- Counts ("containing 2–3 seeds") are measurements of PATO amount on the counted part, in the UO
  count unit.
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

### Experimental latent-trait taxon likelihood (DeepLog)

`flopo2.vision.latent` adds an optional exact DeepLog backend for grounded categorical
queries and a normalized taxon likelihood through which species labels can train latent
traits. The real-image development branch now trains through this likelihood;
the deployed predictor still uses the earlier model. See
[the architecture and experiment](docs/flopo-visual-reasoning-design.md) for the revised
objective, missing-profile normalization, grounding requirements and matched ablations.

Use a separate Python >=3.12 environment with PyTorch and `pydeeplog[mvsdd]==5.0.0`.
The existing Orix vision environment is Python 3.11 and must not be replaced in place.
The optional tests skip when DeepLog is absent:

```bash
python -m pip install 'pydeeplog[mvsdd]==5.0.0'
python -m pytest -q tests/vision/test_latent.py
```

`CompiledQueries(domains, queries)` consumes the finite formulas from `logic.Scene` and
batched normalized categorical probabilities. `LatentTaxonWMC(domains, profiles, reference)`
returns log probabilities over the named taxon profiles. Remove unassessable groups before
constructing each profile; an empty profile is `True`. Training minimizes NLL of the
research-grade taxon label plus the grounding/source auxiliary losses described in the
design. No human trait labels are needed for the synthetic learning check or for starting
this weakly supervised training design. All substantive GPU experiments belong on Orix.

The real-image development runner now uses those pretrained trait heads with a five-member
BEARS ensemble and a matched ordinary ensemble. BEARS joint-concept diversity uses a
Monte Carlo estimator; the taxon likelihood uses exact DeepLog circuits. Preparation stays
outside the GPU allocation, and the run uses training and validation only:

```bash
# In the separate deploy/orix/latent Pixi environment; cached DATA_V2 features/prototypes.
python -m flopo2.vision.latent_train prepare --data DATA_V2 --out PREPARED
# On Orix: deploy/orix/latent/train.sbatch runs this in an H200 allocation.
python -m flopo2.vision.latent_train train --prepared PREPARED --out NEW_RUN \
  --members 5 --epochs 200 --world-samples 64
```

The heads begin with the pinned BioCLIP 2 prototypes and are regularized toward their
pretrained predictions. Ensemble disagreement is reported separately from recognition
accuracy; it does not establish that shortcuts have been eliminated.

Orix run **341490** completed both ensembles; checkpoints and metrics are recorded in
[the run record](docs/flopo-latent-bears-run.json). Both trained ensembles achieved 0/26
top-1 and 1/26 top-5 validation identifications, below the pretrained top-5 baseline.
BEARS increased disagreement, but it remained small. These are experimental checkpoints,
not an improved production recognizer; the test split was not evaluated.
