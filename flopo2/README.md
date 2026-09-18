# flopo2 — FLOPO 2.0 rebuild

LLM/Graph-RAG rebuild of the Flora Phenotype Ontology. The curated trait **database is the source
of truth**; the OWL ontology is a gated, reasoned derivative that **preserves every existing FLOPO
identifier**; taxa are normalized to **WFO + IPNI**; a dynamic Dockerized site serves the traits.

Full plan: `/home/leechuck/.claude/plans/lazy-marinating-boot.md`. Literature: `../resources/`.

## Modules (by phase)

| Module | Phase | Purpose |
|---|---|---|
| `terminology/` | 4–5 | Versioned botanical glossary registry, PO/PATO/FLOPO alignment, hybrid retrieval, span annotation, curation, SSSOM, and evaluation. **Done.** |
| `ids/registry.py` | 0 | Immutable signature→FLOPO_IRI registry from `ontology/flopo.owl`; `IdAllocator` reuses existing IRIs and mints new ones after the max. **Done.** |
| `ids/combinations.py` | 0 | Seed `config/valid_combinations.tsv` (PO×PATO whitelist/blocklist) from the registry. **Done.** |
| `ingest/florml.py`, `ingest/fdac.py`, `ingest/kew.py`, `ingest/cli.py` | 1 | Parse FlorML XML + `fdac` CSV + Kew export → `TextSegment`s (116k segments / 28k taxa). **Done.** |
| `taxon/normalize.py`, `taxon/cli.py` | 2 | GNparser + Global Names Verifier → WFO + IPNI + GBIF IDs, SQLite-cached → taxon table. **Done.** |
| `schema/flopo_trait.yaml` (+ generated `_models.py`, `_ddl.sql`) | 3 | LinkML extraction schema → Pydantic models + SQL DDL. **Done.** |
| `ANNOTATION_MODEL.md`, `../ontology/flopo-annotation-model.ttl` | 3 | SIO-aligned flora assertion/observation architecture, provenance, modality, quantitative values, seasons, PO developmental stages, scoped negation, and non-FLOPO annotation-class IDs. **Done.** |
| `eval/scoring.py`, `eval/gold.py`, `eval/cli.py` | 4 | Stratified gold sampler + metrics (exact/lenient P/R/F1, grounding confusion, negation, hallucination, flip-rate). **Done.** |
| `extract/graphrag.py` | 5 | Engine A: combined Graph-RAG over PO/PATO/TO. |
| `extract/spires_oak.py` | 5 | Engine B: SPIRES + OAK grounding. |
| `extract/router.py` | 5 | OpenRouter tiered routing (Qwen/DeepSeek → GLM 5.2). |
| `extract/baseline.py`, `extract/measurement.py`, `extract/context_recovery.py`, `extract/developmental_stage_recovery.py` | 5 | Conservative deterministic full-corpus rehearsal with audited botanical cues, explicit local bearers, exact assertion offsets, quantitative ranges, modality, seasons, scoped negation, same-bearer age/maturity qualities, and PO developmental stages. **Done.** |
| `extract/compose.py` | 6 | Source-span, related-part, and optional dependency parse-tree composition cross-check; splits accepted/review queues. **Done.** |
| `verify/gates.py` | 7 | Source-span + PO×PATO validity gates, FLOPO IRI reuse/new-class annotation, verifier/FloraTraiter hooks, accepted/review/blocked queues. **Done.** |
| `verify/data_model.py`, `verify/merge_jsonl.py` | 7 | Strict LinkML/wire/ontology/provenance/quantitative-value/SQLite validation and identity-safe multi-flora merging. **Done.** |
| `review/`, `verify/recover_qualitative_relations.py`, `verify/materialize_qualitative_consensus.py` | 7 | Immutable, hash-bound two-family machine review; exact qualitative-continuum candidates; conserved consensus-to-proposal admission with no simulated human approval. **Done.** |
| `review/support_inventory.py`, `review/support_occurrence_inventory.py`, `verify/materialize_support_*`, `../tools/update_flopo_machine_support_release.py` | 7–8 | Authority-gated local anatomy classes; two model families plus an independent adversary; one-item-per-span attachment review; machine-only release provenance and stable ID publication. **Done.** |
| `db/schema.sql`, `db/load.py` | 7 | SQLite-compatible curated trait DB with mandatory source-statement foreign keys, an annotation-class registry, structured modality/season fields, curation views, and JSONL loader. **Done.** |
| `owl/annotation_class.py`, `owl/annotation_extension.py`, `owl/assertions.py` | 8 | Give every canonical OWL phenotype expression a stable `FAC_` IRI outside FLOPO, define it once in an annotation extension, and link lossless source assertions to it. **Done.** |
| `owl/build.py`, `owl/qc.sh`, `owl/sssom.py` | 8 | Build and check the curated reusable FLOPO vocabulary independently of annotation-expression IDs. **Done.** |

## Artifacts produced so far

In `../config/`:
- `flopo_id_registry.tsv` — 24,664 FLOPO classes with canonical EQ signature + deprecation flag. **The identifier-stability contract.**
- `valid_combinations.tsv` — 22,865 allowed + 7 blocked PO×PATO combinations (2016 seed).
- `deprecated_to_reground.tsv` — 967 deprecated classes whose defining axiom was stripped; combos recovered by label-grounding in Phase 8.
- `taxon_cache.sqlite`, `taxon_table_sample.tsv` — Phase 2 resolution cache + a 60-taxon sample.
- `terminology_sources.tsv`, `botanical_terminology.tsv` — licensed-source manifest and durable
  botanical term mapping registry. See [`TERMINOLOGY.md`](TERMINOLOGY.md).

In `../gold/`:
- `annotation_template.jsonl` — 400 stratified segments (4 sources × organ × language) for botanist annotation; gates Phase 5.
- `paul_gold_review_100.tsv` — 100-segment review spreadsheet exported from the silver standard;
  Paul edits `gold_assertions_json`, which becomes the first human gold set.

## Install & run (uv)

```bash
uv venv --python 3.13
uv pip install -e '.[extract,nlp,graphrag,terminology,dev]'   # full toolchain
source .venv/bin/activate
pytest                                            # run the full test suite

python -m flopo2.ids.registry ontology/flopo.owl  # (re)build the IRI registry
python -m flopo2.ids.combinations                 # seed valid_combinations.tsv
python -m flopo2.ingest.cli stats                 # corpus stats (116k segments)
python -m flopo2.taxon.cli --limit 60             # resolve a taxon sample (network)
python -m flopo2.eval.cli sample --n 400          # build the gold annotation template
python -m flopo2.eval.curation                    # build gold/paul_gold_review_100.tsv
python -m flopo2.eval.curation --to-jsonl -o gold/gold_standard_100.jsonl
python -m flopo2.terminology.cli build
python -m flopo2.terminology.cli coverage segments.jsonl --update-frequencies
python -m flopo2.extract.compose gold/silver_standard.jsonl --limit 20 --parser auto \
  --accepted-out gold/composition_accepted.jsonl \
  --review-out gold/composition_review.jsonl
python -m flopo2.verify.gates gold/composition_checks.jsonl \
  -o gold/gated_assertions.jsonl \
  --accepted-out gold/gated_accepted.jsonl \
  --review-out gold/gated_review.jsonl \
  --blocked-out gold/gated_blocked.jsonl
python -m flopo2.verify.novel_combinations gold/gated_review.jsonl \
  -o gold/novel_po_pato_review.tsv
python -m flopo2.verify.approve_combinations gold/novel_po_pato_review.tsv \
  --approved-review curation/approved_po_pato.tsv \
  --reviewer https://orcid.org/0000-0001-8149-5890 \
  --review-date 2026-07-17 --source curator_review_2026-07-17
# Re-run the gates after approval so the reviewed assertions enter the accepted source of truth.
python -m flopo2.verify.gates gold/composition_checks.jsonl \
  -o gold/gated_assertions.jsonl \
  --accepted-out gold/gated_accepted.jsonl \
  --review-out gold/gated_review.jsonl \
  --blocked-out gold/gated_blocked.jsonl
# Losslessly upgrade an existing extraction artifact before loading/building it.
python -m flopo2.annotation.provenance legacy-gated.jsonl \
  -o provenance-gated.jsonl
# Materialize stable annotation-class links and define every distinct expression once.
python -m flopo2.owl.annotation_extension gold/gated_assertions.jsonl \
  -o ontology/flopo-annotation-extension.ofn \
  --annotated-jsonl gold/gated-annotated.jsonl \
  --registry ontology/flopo-annotation-class-registry.tsv --version candidate --format ofn
python -m flopo2.verify.data_model gold/gated-annotated.jsonl --stage gated \
  --require-annotation-class -o gold/gated-validation.json
python -m flopo2.db.load gold/gated-annotated.jsonl --db flopo2.sqlite
python -m flopo2.verify.data_model gold/gated-annotated.jsonl --stage gated \
  --require-annotation-class --db flopo2.sqlite -o gold/gated_validation.json
python -m flopo2.owl.build gold/gated_assertions.jsonl \
  -o ontology/flopo-v2-candidate.ofn --version candidate --format ofn
# Promote only explicitly reviewed, newly allocated EQ classes and their reusable
# phenotype parents. The source module keeps curator and assertion-level provenance;
# the release updater is idempotent and the registry reserves the resulting IDs.
python -m flopo2.owl.reviewed_extension ontology/flopo-v2-candidate.ofn \
  --approvals curation/approved_po_pato.tsv \
  --output ontology/flopo-reviewed-combinations.ttl --date 2026-07-17
python tools/update_flopo_reviewed_release.py --date 2026-07-17
python -m flopo2.ids.registry ontology/flopo.owl -o config/flopo_id_registry.tsv
# Re-gate and rebuild after promotion: every approved assertion must now report
# flopo_status=existing and a stable flopo_iri; a subsequent candidate must mint 0 IDs.
python -m flopo2.owl.assertions gold/gated-annotated.jsonl \
  -o ontology/flora-assertions.ofn --version candidate --format ofn
PYTHON=.venv/bin/python bash flopo2/owl/qc.sh ontology/flopo-v2-candidate.ofn gold/gated_assertions.jsonl
# Source modules can be OWL-DL checked independently; expression classification belongs to the
# imported annotation extension, where each definition occurs once.
java -cp tools/robot.jar tools/CheckOwlConsistency.java ontology/flora-assertions.ofn
python -m flopo2.owl.build gold/gated_assertions.jsonl \
  -o ontology/flopo-v2-release.ttl --version candidate --obsolete-unsupported-existing
PYTHON=.venv/bin/python bash flopo2/owl/qc.sh ontology/flopo-v2-release.ttl gold/gated_assertions.jsonl
python -m flopo2.owl.sssom ontology/flopo-v2-release.ttl \
  -o ontology/flopo-v2-mappings.sssom.tsv --to ont/trait.obo

# Rebuild locally curated categorical values after a PATO update. Exact PATO
# replacements are omitted; alternatives are OWL unions and compounds use
# explicit quality-component restrictions.
python tools/build_flopo_value_extension.py
python tools/update_flopo_release.py --date 2026-07-13
python -m flopo2.ids.registry ontology/flopo.owl -o config/flopo_id_registry.tsv

# Rebuild the approved bearer-centric hierarchy and local botanical support classes,
# then obsolete the 154 classes that accidentally used human puberty, embed their
# corrected botanical-pubescence replacements, and group every PATO:0001320 phenotype
# beneath FLOPO:0980977 pubescence phenotype. Both release updaters are idempotent.
uv run --frozen python tools/build_flopo_botanical_extension.py --date 2026-07-15
uv run --frozen python tools/update_flopo_botanical_release.py --date 2026-07-15
uv run --frozen python tools/build_flopo_pubescent_migration.py --date 2026-08-02
uv run --frozen python tools/update_flopo_pubescent_release.py --date 2026-08-02
uv run --frozen python -m flopo2.ids.registry ontology/flopo.owl \
  -o config/flopo_id_registry.tsv

# Classify against the controlled local PO/PATO closure, then publish the active,
# phenotype-only browser view. The latter has flora phenotype as its sole named root.
uv run --frozen python tools/classify_flopo_release.py
uv run --frozen python -m flopo2.owl.light

# Build the separately reviewed PATO PR module containing open lexical colour
# umbrellas and source-qualified operational senses. The optional closed scarlet
# union is deliberately deferred.
python tools/build_pato_colour_sensu_terms.py --date 2026-07-15
python tools/apply_pato_colour_sensu_terms.py \
  --pato-edit ../pato/src/ontology/pato-edit.obo
```

The extraction JSONL is deliberately loss-aware. `assertions` contains grounded EQ records;
`source_statements` contains first-class verbatim evidence with stable source-scoped identifiers;
`unresolved_spans` contains exact source spans withheld because their negation, alternative or
mixture structure, bearer, stage/modifier, or ontology sense is not yet safe. Both collections
survive composition, gates, multi-flora merging, strict validation, and SQLite loading. A fresh
database path is required for every load so an artifact cannot be appended twice accidentally.
Every segment also carries `source_segment_index`, its zero-based occurrence within one source
file. This is part of provenance identity because real FlorML volumes can repeat identical
taxon/organ/text blocks with the same local character offsets. Gate the complete composition audit,
not only its accepted split, so composition failures remain review assertions in the database.
The `annotation.provenance` migration command streams legacy JSONL into a distinct output file,
materializes one retained source statement per source-scoped evidence span, links every assertion,
and normalizes legacy modality cues without changing the input artifact.

Qualitative continua such as *elliptic to ovate* use `qualitative_value_relation`, not
`value_operator: one_of`: a continuum licenses unstated intermediate values, while a temporal
transition places its endpoints at different times. These assertions deliberately have no
`phenotype_class_iri`, do not enter the FAC registry, and do not produce a taxon subclass axiom.
The source OWL module instead reifies their interpretation, ordered grounded endpoints, and exact
endpoint/connector evidence. Candidate recovery is source/hash bound; admission requires exact
agreement from two independent LLM model families followed by deterministic local validation and
the ordinary PO×PATO gate. Machine consensus is recorded as machine provenance and never labeled
as curator or human review.

Missing botanical bearers use a separate two-level machine-review protocol. A reusable local
anatomy class enters FLOPO only when two independent model families copy the exact runner
signature, an independent third family finds no blocker, every cited authority file is locally
hash-verified, and deterministic PO/FLOPO collision and parent checks pass. Class acceptance never
bulk-accepts its routed flora spans: `support_occurrence_inventory.py` rebinds each span to the
frozen Stage 13 source and creates exactly one cluster per occurrence. Two-family agreement must
then copy the exact bearer–quality expression, including numeric bounds and units; disagreements,
ambiguous attachment, subpart descriptions, and bare numeric attributes remain held. The
materializer changes no human-curation allow-list and records `llm_consensus` provenance only.
The exact generated source module is retained as
`ontology/flopo-machine-reviewed-support.ttl`. Published IDs are retained in
`config/flopo_machine_support_id_registry.tsv`; completed campaigns
remain replayable after live catalogs advance through SHA-256-addressed snapshots under
`scratchpad/flopo-review-artifacts/sha256/`.

Machine-reviewed exact-colour EQ classes are published by
`tools/update_flopo_machine_reviewed_eq_release.py` from hash-verified materializations
(retained as `ontology/flopo-machine-reviewed-eq*.ttl`, IDs in
`config/flopo_machine_eq_id_registry.tsv`). Besides two-family agreement with an adversarial
`no_blocker`, the curator-set `two_of_three` rule (`--tiebreak FILE --tiebreak-rule
two_of_three`, `flopo2/review/tiebreak.py`) admits a held item when a third independent machine
reviewer and one campaign reviewer propose the identical signature and all deterministic gates
pass; an existing adversarial block still holds it. Such classes carry all three
`machine_reviewer` values and `machine_review_rule`, and are not human reviewed.

`gate.status == accepted` means the assertion is safe for the layered OWL build. Reusable PO–PATO
traits and manifestations go into FLOPO. Every distinct complete phenotype expression—including
source-specific intervals and arbitrary disjunctions—receives a stable `FAC_` class IRI in the
separate annotation extension. The source module retains provenance and modality and links to that
IRI; it does not repeat the expression. A finite numerical flora range is a PATO
attribute phenotype with a datatype/unit restriction, not a measurement event. `usually`, `often`,
and other qualified claims are retained as SIO-aligned meta-level assertion individuals and are not
silently promoted to universal taxon axioms. Cardinality still requires review. Negation is
accepted only when its `quality` or `absence` scope is explicit and is rendered at that exact OWL
scope. See [`ANNOTATION_MODEL.md`](ANNOTATION_MODEL.md).
The deterministic extractor recognizes frequency, epistemic, approximation, and degree cues as
separate axes and retains their exact spelling. It attaches named ENVO/application seasons and
calendar-month ranges only within the same local clause; it does not infer hemisphere or turn the
French auxiliary phrase `a été` into a summer context.

The value-extension build is governed by
`config/flopo_value_candidates.tsv` (the reviewed source values),
`config/flopo_value_pato_mappings.tsv` (provisional FLOPO values replaced by permanent
PATO terms), `config/flopo_value_id_registry.tsv` (stable identifiers), and
`config/flopo_value_axioms.tsv` (reviewed local axioms and definitions).
It produces `ontology/flopo-value-extensions.tsv` and
`ontology/flopo-value-extensions.ttl`; the release update command embeds that generated module
in the actual `ontology/flopo.owl` artifact and then the registry command reserves its identifiers.
In particular, an “A or B” flora value is an anonymous `owl:unionOf` class description on the
right-hand side of an `FAC_` equivalent-class axiom in the annotation extension. It is never
translated into conjunctive `is_a` axioms and is not minted as a reusable FLOPO class merely
because it occurs in one treatment. JSONL and SQLite use `phenotype_class_iri` as the semantic
annotation target; `value_operator` and the other decomposed fields are derivation and QC data.

The botanical hierarchy is governed by
`curation/flopo_top_level_and_local_extension_proposals.tsv`,
`config/flopo_botanical_id_registry.tsv`, and `curation/curator_approvals.tsv`.
Its generated source is `ontology/flopo-botanical-extension.ttl`; the actual release imports the
pinned GO 2026-06-15 root module and embeds the approved classes. The separate
`ontology/flopo-pubescent-migration.ttl` preserves every incorrect old identifier as an obsolete
annotation shell with `IAO:0100001` pointing to a newly minted EQ class using PATO:0001320. All
live EQ classes using that botanical pubescence quality are asserted beneath
`FLOPO:0980977 pubescence phenotype`; its logical definition also classifies future matches there.
The full `ontology/flopo.owl` remains the development artifact. The generated
`ontology/flopo-light.owl` is the pre-classified BioPortal/browser view: it retains active
phenotype IRIs and annotations but omits logical definitions, imports, support vocabulary, and
obsolete terms so that `flora phenotype` is its single named root.

Network note: `taxon/normalize.py` calls the public GNparser + Global Names Verifier APIs (no
local binary). `OPENROUTER_API_KEY` is read by the Phase 5 extraction engines (not yet built).
ROBOT is installed locally as `bin/robot` backed by `tools/robot.jar`.

## NCVC Saudi native-plants guide ingest

`flopo2/ingest/ncvc_guide.py` parses the page-by-page transcription of the 2024 NCVC Saudi
native-plants field guide (Arabic text plus a literal English translation; one species per
two-page spread) into `TextSegment`s, taxon-occurrence rows, and transcribed phenotype rows.
`flopo2/ingest/ncvc_annotate.py` is the deterministic second stage: it grounds every phenotype row
through exact PO/PATO labels or synonyms and the reviewed rules in
`flopo2/ingest/ncvc_normalization.tsv` (growth form, life span, fruit/inflorescence type, leaf
persistence, sexual system), applies the documented data-quality holds in
`flopo2/ingest/ncvc_data_quality_holds.tsv`, and emits a gated corpus artifact in the same
`source_statements`/`assertions`/`unresolved_spans` wire format as the main flora pipeline.

```bash
.venv/bin/python -m flopo2.ingest.ncvc_annotate local-corpora/saudi-ncvc-guide
```

Outputs land under `local-corpora/saudi-ncvc-guide/derived/`: the annotated JSONL corpus, a
phenotype-disposition audit, a whole-plant-class table (habit/life-span classes with no EQ
signature), a novel PO×PATO candidate table, a distribution table (taxon x ISO 3166-2 region and
locality), a growth/cultivation-trait table, a taxon table, and `validation.json`/`summary.json`.
`REPORT.md` in the same directory is regenerated from those files on every run.

**Licensing.** The source PDF, its Arabic and English transcriptions, and any photos are
copyrighted "all rights reserved" by the guide's publisher; no open licence is stated. The raw
PDF, transcriptions and all derived text under `local-corpora/` are therefore git-ignored and must
never be committed — only the facts extracted into the trait database and ontology (species names,
regions, EQ phenotypes) are durable outputs.

## Recovery, tie-break and merge tooling

`flopo2/verify/recover_claude_<category>.py` (categories: `hyphen_compound`,
`developmental_stage`, `missing_bearer`, `alternatives_transitions`, `explicit_disjunction`) are
deterministic recovery modules that mine one residual `unresolved_spans` reason left over after the
LLM-review campaigns, each with a paired `tests/test_recover_claude_<category>.py` and a seeded,
stratified precision self-review. `flopo2/verify/recover_claude_*.py recover <stage.jsonl> --delta
DELTA --report REPORT.json` (see each module's `--help`) writes a segment-scoped delta rather than
a full corpus copy.

`flopo2/verify/recover_claude_*` (and the shape/leaf-apex/leaf-base tie-break work) reuse two
shared pieces of infrastructure:

- `flopo2/verify/apply_deltas.py` applies an ordered, precedence-resolved list of deltas
  (corrections, then tie-break admissions, then recovery categories ranked by their audited Wilson
  lower bound) to one base corpus stage, failing closed on any conflicting pair of deltas and
  reporting duplicate-key conflicts rather than guessing at them.
- `scratchpad/flopo-stage23-20260918/run_merge.sh` is the reproducible driver: it regenerates the
  alternatives/transitions admitted-plus-held delta, the leaflet-bearer readmission, the surface-
  restriction correction, then calls `apply_deltas merge` against a manifest to rebuild the merged
  corpus stage and load it into a fresh SQLite database. Rerun it from the repo root whenever a
  delta file changes; it validates the result with `flopo2.verify.data_model --stage gated
  --strict-source-statements` before finishing.

Outputs of a merge run are scoped-in-place next to their inputs (each recovery/tie-break directory
under `scratchpad/flopo-claude-recovery-20260918/`) and are not copied into `flopo2/`; only the code
modules above are part of the package.
