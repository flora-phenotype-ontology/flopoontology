# Botanical terminology, ontology extension, and normalization plan

Status: in progress (started 2026-07-14)

This plan turns unresolved botanical language into reviewed mappings or evidence-backed ontology
proposals without treating an LLM response as an ontology assertion. It covers PO anatomy terms,
PATO qualities, compositional FLOPO phenotypes, and the terminology-guided Saudi Flora extraction
pipeline.

## Scope and current baseline

The reproducible baseline to freeze at the start of the work is:

- 9,089 rows in `config/botanical_terminology.tsv`, representing 6,313 distinct normalized
  form/language pairs;
- 38 registry rows with redistributable textual definitions;
- 20,526 longest-match Saudi Flora mentions, of which 10,799 (52.61%) currently have an eligible
  normalization and 9,727 (47.39%) do not;
- 436 distinct corpus-attested surface forms among those missing mentions;
- 4,615 missing mentions blocked by a low retrieval score, 4,320 attached only to a
  non-equivalent candidate, and 792 with no candidate;
- at least 812 missing mentions apparently recoverable by indexing labels and exact synonyms from
  the complete released `ontology/flopo.owl`.

These figures are audit results, not permanent constants. The first implementation task must
recompute them and store input hashes, ontology versions, commands, and output counts so later
changes can be compared with the same corpus and mention policy.

## Semantic placement policy

Every surface form receives one of five outcomes before implementation:

1. **PO** for a coherent plant anatomical entity. A new class needs a genus-differentia textual
   definition, a direct parent, and only universally true `part_of` or `has_part` assertions.
2. **PATO** for a bearer-independent atomic quality. A new colour requires a referenced operational
   range or prototype; a label paraphrase is not a definition.
3. **FLOPO** for an entity-quality phenotype, contextual growth form, compound value, or
   alternative. Compound colours remain in FLOPO. `A or B` is represented with `owl:unionOf`, not
   conjunctive parents.
4. **Mapping only** when an existing class already represents the meaning. The relation must be
   explicit (`exact`, `close`, `broad`, `narrow`, or `related`) and directionally correct.
5. **Noise or unresolved** for habitat prose, taxonomic narrative, OCR fragments, or cases lacking
   enough evidence. Abstention is an expected result.

Special cases to resolve explicitly:

- `silver` and `silvery` are audited separately. Botanical silvery appearance can arise from
  colour, lustre/specular reflection, hairs, wax, or a combination, so it must not be collapsed to
  a simple silver RGB value without supporting evidence.
- PO NARROW synonyms such as inflorescence and fruit types are candidates for explicit PO
  subclasses only when they denote coherent anatomical subclasses rather than configurations or
  lexical variants.
- male/female flower proposals must compare explicit PO subclasses with compositional FLOPO
  definitions using PO `flower` and semantically applicable sex qualities. Existing NARROW synonym
  status does not itself establish equivalence.
- `leafy`, `leafless`, `bushy`, `climbing`, `scrambling`, `creeping`, `twining`, `trailing`, and
  similar whole-plant growth forms are developed as contextual FLOPO phenotypes. Reusable atomic
  qualities may still come from PATO, but the growth-form classes are neither PO anatomy classes
  nor unrestricted PATO values.
- Trifoliolate/bifoliolate leaf, stinging trichome, foliage, and plant latex are FLOPO-local
  phenotypes or support classes. PO/PATO supply the nearest biological parents and reusable
  components; these concepts are not upstream PO requests.

## Responsibility split

Claude Sonnet coordinators perform work that benefits from parallel literature reading and
context-sensitive proposal generation. They fan out specialist agents for PO, PATO, growth forms,
mapping literature, constrained mapping, and adversarial semantic review. Each run writes only to
an isolated directory under `scratchpad/claude-botanical-audit/`.

Codex performs deterministic and accountable work:

- hash and count inputs;
- parse PO/PATO/FLOPO and check identifiers, labels, synonyms, definitions, parents, and obsolete
  status;
- download and archive permitted evidence, recording exact pages/sections and checksums;
- validate all Claude TSV schemas and reconcile the independent runs;
- reproduce mapping baselines and implement retrieval/evaluation code;
- construct OWL/OBO changes only after proposal validation;
- run syntax, reasoning, competency-question, regression, and release tests;
- prepare diffs and PR text for human review.

No Claude proposal becomes `reviewed`, receives the curator ORCID, or enters an ontology without
independent verification. The curator ORCID is `0000-0001-8149-5890` and is attached only after
human acceptance.

## Phase 1: freeze inputs and reproduce the audit

1. Record Git commit/dirty-state information and SHA-256 hashes for the terminology registry,
   source manifest, Saudi segments, review queue, PO, PATO, FLOPO, and value-extension files.
2. Record the local PO/PATO release metadata and check current upstream PO/PATO before declaring a
   class absent.
3. Rebuild the terminology registry and Saudi coverage report from documented commands.
4. Save counts by source, language, semantic role, mapping relation, review status, retrieval
   failure category, and corpus frequency.
5. Add the complete released FLOPO label/exact-synonym signature to the runtime catalog and measure
   the predicted recovery of the 812 mentions as a separate, testable change.

Deliverable: a machine-readable baseline manifest and coverage report under `scratchpad/`, plus
regression fixtures containing no copyrighted flora text beyond short licensed/test excerpts.

## Phase 2: three independent Claude Sonnet audits

Run at most three Claude CLI coordinators concurrently. Each coordinator reads
`scratchpad/claude-botanical-ontology-fanout-prompt.md`, internally fans out at least seven
specialists, and writes to its own `run-01`, `run-02`, or `run-03` directory. All three audit the
full task; their emphasis differs to expose disagreements:

- run 01: botanical definitions, anatomy, homology, and universally true parthood;
- run 02: PATO qualities, operational colour definitions, growth forms, and composition;
- run 03: mapping retrieval/evaluation, source verification, and adversarial logical review.

Each run must produce the prescribed PO, PATO, growth-form, SSSOM, mapping-SOTA, blocker,
unresolved, summary, and manifest files. Missing rows, unsupported references, invented identifiers,
or schema violations fail the run; a polished narrative cannot compensate for them.

## Phase 3: evidence and ontology validation

For every proposed class or mapping:

1. Resolve each DOI/ISBN/stable URL and download the source when licensing permits.
2. Verify that the cited page or section supports the proposed differentia, prototype/range, and
   logical axiom. A source that merely uses a word does not define it.
3. Check current PO, PATO, and FLOPO labels, all synonym scopes, definitions, asserted/inferred
   ancestors, deprecations, and replacement terms.
4. Reject circular definitions, category errors, contingent parthood, taxon-specific senses stated
   universally, disjunction-as-conjunction, mixtures under component colours, and duplicate terms.
5. Keep disagreements from the three runs visible. Resolve them with evidence or leave the item
   unresolved.

Deliverable: a curator-facing decision table with one row per surface/concept, evidence status,
placement, proposed axioms, counterexamples, and a clear accept/revise/reject recommendation.

## Phase 4: ontology implementation after review

### FLOPO top-level and term-stability policy

- Review a bearer-centric phenotype top level before reparenting any released class. It separates
  continuant-target and process-target phenotypes. Do not recreate morphology, appearance,
  composition/cardinality, disposition, relation, or life-history branches as a `phenotypic
  aspect` hierarchy: reuse PATO:0000001 `characteristic` (exact synonym `quality`) and derive these
  views from the PATO fillers in phenotype definitions.
- Follow BFO's continuant/occurrent and quality/disposition distinctions without explicitly making
  the FLOPO root a BFO subclass or adding a new top-level import. A material plant bearer links to
  a process through participation; it must not have a process as a material part.
- Add a pinned GO module as a separate support hierarchy rooted at GO:0008150. A process phenotype
  links its bearer through RO:0000056 to a GO process, and links that process through RO:0000053 to
  any PATO:0001236 process characteristic. Neither GO processes nor PATO characteristics are
  subclasses of FLOPO phenotypes. Add `process` and `GO` to the terminology schema before runtime
  process normalization.
- Parent FLOPO-local anatomical or quality support classes directly beneath the closest live PO or
  PATO class and record local provenance editorially. Do not create a biological superclass whose
  only meaning is “FLOPO extension”.
- Decide obsoletion by referent stability. Definition/citation cleanup and wrong-parent repair keep
  an identifier when its intended referent is unchanged. If an existing class formally denotes a
  materially different referent, obsolete it, remove logical axioms/usages, and create or point to
  a replacement using `IAO:0100001`; use `oboInOwl:consider` when no exact replacement exists.
- Keep every top-level and local-extension row review-only until the curator accepts its placement,
  definition, and logical pattern.

### PO candidates

- Represent accepted missing anatomy temporarily in FLOPO using FLOPO identifiers and explicit
  provenance; never mint unofficial PO identifiers.
- Include textual definitions, direct parents, and universally true parthood axioms where possible.
- Add competency questions demonstrating intended classification and counterexamples demonstrating
  the boundary.
- Prepare a focused PO pull request with evidence, OBO/OWL changes, migration notes, and tests.
- When PO assigns identifiers, replace/deprecate the provisional FLOPO bridge predictably and update
  all mappings without breaking stable public annotations.

### PATO candidates

- Prefer existing PATO terms or exact synonyms when semantics match.
- For accepted missing atomic qualities, create provisional FLOPO representations with evidence and
  prepare a separate focused PATO pull request.
- Keep organ-specific, scalar, compound, patterned, or alternative phenotypes in FLOPO rather than
  causing PATO combinatorial expansion.
- Treat compound colours and colour alternatives as FLOPO classes with explicit component
  expressions.
- For historically variable atomic colour names, create an open unqualified PATO umbrella and one
  operational `sensu` child per named standard. Unqualified text maps to the umbrella; a sensu
  child is used only when the source identifies its standard. Do not define the open umbrella as
  the finite union of currently known children. If useful, expose a separately named reviewed-set
  union and regenerate it as standards are added. Preserve an existing source-specific identifier
  as a sensu child rather than silently broadening its definition.

### FLOPO release artifacts

Every accepted FLOPO change must update the actual released `ontology/flopo.owl`, its source module,
the inferred/derived artifact when required by the release process, ontology version IRI, release
date, mappings, registries, and documentation. Generated root-level OWL files are not substituted
for the released ontology.

No PO, PATO, or FLOPO PR is opened or pushed until the curator has reviewed the proposed diff and PR
text.

## Phase 5: mapping system

Implement a retrieve-adjudicate-repair pipeline rather than unconstrained identifier generation:

1. Unicode/case/punctuation normalization, exact preferred-label lookup, and exact-synonym lookup.
2. Morphological variants with traceable rules and collision tests.
3. Lexical retrieval using character n-grams/BM25 plus OAK `lexmatch`.
4. Dense retrieval evaluated with SapBERT, a scientific sentence encoder, and (if enough reviewed
   pairs exist) a botanical contrastive encoder.
5. Union and calibrated reranking of retrievers to maximize candidate recall@10.
6. Claude Sonnet adjudication constrained to retrieved identifiers, source context, definitions,
   hierarchy, semantic role, and organ context. It classifies the mapping relation or abstains; it
   cannot invent an identifier.
7. Bidirectional consistency checks and LogMap-style logical repair against PO/PATO/FLOPO.
8. SSSOM output with method, confidence, source version, evidence, and proposal/review status.
9. Human acceptance before a mapping becomes reviewed or eligible for ontology/release use.

The evaluation design follows the separation emphasized by OAK/SSSOM and ontology-matching work
such as [BERTMap](https://aaai.org/papers/05684-bertmap-a-bert-based-ontology-alignment-system/),
[SapBERT](https://aclanthology.org/2021.naacl-main.334/),
[LLMs4OM](https://arxiv.org/abs/2404.10317), and
[LLM-assisted LogMap](https://aclanthology.org/2026.eacl-long.110/): candidate retrieval, semantic
adjudication, and logical repair are measured separately.

Independent source checking sharpens that design. OAK `lexmatch` is a deterministic normalized
label/synonym equality matcher, so it is a lexical baseline rather than a semantic retriever. The
FLOPO–PTO task has a directly relevant quantitative precedent: AML reported F1 0.86 in OAEI 2018.
OAEI Bio-ML 2024 does not support naming one universal SOTA system: BioGITOM led three of five
semi-supervised equivalence tasks, HybridOM led two, and the unsupervised leaders varied by task.
The 2026 LLM-oracle study supports using an LLM only to adjudicate uncertain LogMap candidates and
reports a top-two OAEI 2025 Bio-ML result; it also warns about benchmark leakage and the need for
new blind alignments. Therefore the FLOPO evaluation uses a hidden botanical split, reports
retrieval and adjudication separately, and treats current benchmark rankings as evidence for
ablation choices rather than proof of expected botanical performance.

## Phase 6: validation and tests

### Proposal and mapping validation

- schema, UTF-8/TSV, uniqueness, and referential-integrity checks for every artifact;
- SSSOM metadata and predicate-direction validation;
- no unknown/generated PO/PATO/FLOPO identifiers;
- no curator attribution on machine-proposed rows;
- all definitions nonempty for class proposals and every citation resolvable;
- explicit tests that BROAD/NARROW/RELATED synonyms are not silently normalized as exact;
- deterministic reruns and stable hashes for unchanged inputs.

### Ontology validation

- RDF/OWL parsing and OBO round-trip checks;
- ROBOT `report` and ELK classification over the release candidate;
- HermiT checks for small modules using constructs outside OWL EL, especially unions;
- zero unintended unsatisfiable named classes;
- duplicate-label/synonym collision and obsolete-parent checks;
- SPARQL/OWL competency tests for direct parentage, parthood, sex phenotype, growth forms, compound
  colours, and `owl:unionOf` alternatives;
- explicit negative tests showing that an `A or B` phenotype is not inferred to be both A and B;
- ID/signature stability and provisional-to-upstream migration tests;
- release metadata tests for version IRI and release date in `ontology/flopo.owl`.

### Mapping evaluation

Create a stratified, human-adjudicated gold set with splits that prevent surface/synonym leakage.
Report candidate recall@1/5/10, top-1 accuracy, exact/close auto-accept precision and coverage,
mapping-relation macro-F1, NIL precision/recall/F1, calibration/selective accuracy, run-to-run LLM
stability, and slices by language, source, role, frequency, and atomic/compound status.

Compare at least:

- exact lexical baseline;
- lexical hybrid;
- dense only;
- lexical+dense hybrid;
- hybrid+Claude;
- hybrid+Claude+logical repair.

Release gates are candidate recall@10 at least 0.95, automatic-eligibility precision at least 0.95,
no extraction hallucination-rate increase, no language/source slice losing more than 0.02 F1, and at
least +0.05 exact entity-quality F1 for terminology-guided extraction. Coverage is reported
alongside precision so abstaining on everything cannot pass.

### Repository regression tests

- run focused terminology, value-extension, OWL-build, composition, curation, and gate tests first;
- run the complete Python test suite;
- run `flopo2/owl/qc.sh` on the candidate ontology and gated release artifact;
- rebuild twice and compare normalized outputs to test idempotence;
- rerun Saudi coverage and the extraction ablation on the frozen corpus/gold split.

## Review and delivery checkpoints

1. **Claude audit review:** present convergent proposals, disagreements, invalid citations, and gaps;
   do not edit ontologies yet.
2. **Placement review:** curator approves PO/PATO/FLOPO/mapping/noise decisions and definitions.
3. **Diff review:** present local FLOPO changes and separate proposed PO/PATO PR diffs plus test
   results before any push or PR update.
4. **Mapping review:** present gold-set and ablation metrics, threshold behavior, and residual error
   analysis before enabling automatic eligibility.
5. **Release review:** verify `ontology/flopo.owl`, inferred artifacts, version IRI, release date,
   provenance, and migration mappings before commit/push.

The work is complete only when every one of the 436 corpus-attested unresolved surfaces is mapped,
modeled, rejected as noise, or explicitly left unresolved with evidence; all accepted ontology
changes have passed semantic and mechanical validation; and the measured extraction change meets the
release gates.

## Implementation log

### 2026-07-14

- Froze a reproducible baseline under
  `scratchpad/botanical-terminology-baseline-2026-07-14/`. The manifest records 14 input hashes,
  Git state, source-definition availability, ontology release metadata, all 436 missing surfaces,
  and the 4,615 low-score / 4,320 non-equivalent / 792 NIL failure split.
- Added `flopo2.terminology.audit` to reproduce the baseline without emitting copyrighted flora
  text, plus tests for definition-status and failure-cause accounting.
- Added `flopo2.terminology.validate_audit` to validate Claude deliverables, including required
  files and schemas, numeric confidence, known identifiers, SSSOM proposal provenance, absence of
  curator attribution, and coverage of all 436 missing surfaces.
- Started three isolated Claude Sonnet coordinator sessions. Each coordinator fans out its own PO,
  PATO, FLOPO, mapping, and adversarial-review specialists and writes only to its assigned
  `scratchpad/claude-botanical-audit/run-0N/` directory.
- Corrected runtime catalog construction so released FLOPO labels and scoped synonyms are admitted
  as phenotype candidates. The implementation streams `ontology/flopo.owl` rather than loading it
  as an RDF graph.
- Added `flopo2.terminology.catalog_recovery` to compare the old PO/PATO-only form layer with the
  expanded PO/PATO/FLOPO layer. On fixed old mention spans, the expanded catalog recovers exactly
  812 previously ineligible mentions across 29 surfaces. End-to-end longest-span coverage changes
  from 52.61% (10,799/20,526) to 55.89% (11,071/19,807); the denominator changes because longer
  FLOPO forms merge some former spans.
- Passed Ruff on the new terminology code and the complete Python suite after the catalog change.
  Claude proposal outputs remain unaccepted pending mechanical validation, source checking, and
  curator review.
- Downloaded and checksum-pinned PO `v2026-01-09` and PATO
  `master@83ec8697a02e3ef07beb9f5ea0256670ab1a4b15`; Git blob hashes match the official GitHub
  objects. The audit validator can take repeatable `--ontology-obo` arguments, avoiding false
  absence claims from the repository's 2013 PO snapshot.
- Strengthened proposal validation so the mapping and gap/noise tables must be a duplicate-free,
  disjoint partition of the frozen 436 surfaces. This caught and forced repair of two superficially
  polished Claude runs, including one that had silently switched to the 398-surface post-catalog
  baseline.
- Completed three Claude coordinator audits with at least seven internal specialist/adversarial
  agents per run. All three now independently pass the same frozen-baseline/current-ontology gate:
  run 01 has 166 mapping + 270 gap/noise rows, run 02 has 181 + 255, and run 03 has 137 + 299.
  The remaining unknown-ID warnings occur only inside blocker histories documenting hallucinated
  IDs that were removed from live proposals.
- Added `flopo2.terminology.compare_audits` and generated
  `scratchpad/claude-botanical-audit/curator-comparison.tsv`. After OBO CURIE canonicalization, only
  27/436 surfaces have the same relation-and-target/gap signature in all three runs; the other 409
  remain explicit disagreements. Pairwise exact agreement is 47 (runs 01/02), 57 (02/03), and 143
  (01/03), demonstrating that majority vote is not an acceptable substitute for curation.
- Cross-run proposal convergence is strongest for PO labellum/corolla-lip, corolla tube, bulb
  tunic, haustorium, and corona candidates; and for PATO crimson, campanulate, filiform, and hastate.
  `silver`/`silvery`, scarlet, odour values, perianth/corolla boundaries, pseudobulb, and climbing
  growth-form semantics remain disputed and require primary-source adjudication.
- Independently confirmed the mapping-system architecture against official OAK documentation,
  OAEI 2018/2024 results, and the 2026 LLM-oracle paper. The mapping literature does not justify
  adopting an LLM-only normalizer or claiming a single universal SOTA system.
- The complete Python suite now passes with 106 tests, and Ruff is clean. No ontology, registry,
  release artifact, PR, commit, or curator-authored mapping has been changed by this phase.

### 2026-07-15

- Downloaded, checksum-pinned, and manually checked the glossary and literature evidence used for
  the leading PO/PATO/FLOPO proposals. Added `curation/botanical_evidence.tsv` as a provenance
  manifest and `curation/botanical_concept_proposals.tsv` as a curator-facing proposal source;
  machine proposals have blank decisions and carry no curator ORCID.
- Rejected the Claude proposals that treated crimson or scarlet as one universal ISCC-NBS block:
  the published standard maps those names to different blocks depending on source and context.
  Evidence currently supports campanulate, filiform, and hastate most strongly as atomic PATO
  candidates; the anatomy proposals retain explicit caveats for homology and contingent parthood.
- Added a deterministic current-ontology mapping validator and complete curator-table builder.
  Direct parsing of pinned current OBO files exposed and fixed three catalog hazards: obsolete
  candidates, PO editorial synonym suffixes being indexed as literal text, and a non-English
  synonym collapsing to the English token `plant`.
- Classified all 436 frozen missing surfaces against current PO/PATO/FLOPO labels and formal OBO
  synonym scopes: 19 have a deterministic exact lexical candidate, 7 have exact collisions, 49
  have only BROAD/NARROW/RELATED candidates, and 361 have no lexical candidate. None is accepted
  automatically because even the exact forms include entity/phenotype collisions or contextual
  senses. After the 2026-07-15 evidence passes, the frozen curator table enriches 124 surfaces
  accounting for 7,762 of 9,727 missing mentions; 312 surfaces / 1,965 mentions remain queued.
- Re-ran the current mapping audit against PATO's authoritative `pato-edit.obo` at merge commit
  `83ec8697`, not only its lagging generated root `pato.obo`. The edit source is byte-identical to
  the repository's post-merge `ont/quality.obo`; the extra exact candidate is `feathery` to
  PATO:0005010. Both artifacts and roles are recorded so the historical baseline remains
  reproducible without pretending that the newly merged classes are absent.
- A source-context audit found that 1,051/1,201 occurrences of `wide` (87.5%), 322/333 of `tall`
  (96.7%), and 533/553 of `high` (96.4%) are numeric-unit constructions. These are extraction
  grammar, not missing categorical PATO values. Added a conservative bilingual measurement parser
  for length, width, height, thickness, and diameter with numeric ranges, UO normalization, exact
  source spans, and negative tests for habitat prose. On the Saudi segments it recognizes 2,560
  measurements in 1,204/1,239 descriptions; contextual entity binding remains a separate gate.
- No ontology axiom, released OWL file, terminology registry decision, commit, push, or upstream PR
  has been made in this curation phase.
- Refreshed the vendored PO dependency from the 2013 snapshot to official release `v2026-01-09`
  and added a deterministic OBO-to-grounding-lexicon builder. Regenerated both PO and PATO TSVs
  from their checked-in authoritative sources (1,659 live PO terms and 1,925 live PATO terms), with
  repeat-build byte comparisons and tests for synonym scope, language, subsets, and obsolescence.
  This is a dependency/index refresh only; it does not add candidate axioms to any ontology.
- Rebuilt the terminology registry into a scratch artifact, preserving the committed registry.
  Current PO/PATO/FLOPO forms reduce the unresolved set from 436 surfaces / 9,727 mentions to 393
  surfaces / 8,659 mentions and raise eligible mention coverage from 52.61% to 57.57%. The current
  missing-surface validator has 50 scoped-synonym reviews and 343 surfaces with no lexical exact
  candidate; all former exact candidates are now admitted by the runtime catalog.
- Added fixed-span measurement recovery accounting. Numeric measurement grammar explains another
  1,841 missing mentions (1,028 `wide`, 504 `high`, 308 `tall`, and 1 `thick`), raising recognized
  terminology-or-measurement coverage to 66.59%. These are not counted as complete assertions
  until a contextual PO bearer has been bound and validated.
- Corrected the FLOPO RDF/XML catalog reader after the independent lexical check exposed a
  serialization boundary: 295 released FLOPO classes are represented as `rdf:Description` with
  `rdf:type owl:Class`, while 24,200 use `owl:Class` elements. Both are class declarations and all
  24,495 registry identifiers are present in one of those forms. A regression test now excludes
  only genuinely untyped annotation descriptions. Rebuilding with the corrected reader restores
  the prior 20,409-span Saudi segmentation exactly.
- Added an independently executable OAK `lexmatch` baseline and quantitative comparator. Default
  OAK finds 87/91 frozen lexical pairs (95.60% pair recall; 100% precision against the
  scope-preserving set); its four misses are space/hyphen variants. The versioned botanical
  hyphen-normalization rule raises recall to 91/91. OAK labels every shared result
  `skos:closeMatch`, so it remains a retrieval check and cannot replace formal OBO synonym-scope
  handling or curator adjudication. On the 393-surface current residual set, default OAK finds all
  52/52 scoped lexical pairs.
- Downloaded and checksum-pinned ten additional NYBG glossary entries for annual, perennial,
  trifoliolate, winged, reflexed, solitary flower, caespitose, viscid, lanate, and sericeous.
  Added a manifest validator that verifies all 45 evidence files (47,754,642 bytes) against their
  recorded SHA-256 hashes and rejects missing, changed, duplicate, or undated evidence.
- Added independently checked proposals for the high-frequency residuals rather than treating them
  as one class of ontology gaps. Existing-term proposals cover sticky/viscid, arching/arched,
  botanical sessile, scented/odorous, and ripe/mature; new atomic candidates cover reflexed,
  winged, ascending, spreading, lanate, sericeous, and annual/perennial life-span values; a
  FLOPO-local proposal covers trifoliolate leaf with exactly three leaflets; and FLOPO patterns
  retain
  tufted/caespitose growth, solitary cardinality, veined colour, sweet scent, milky exudate, and
  plant armature composition. No proposal is curator-approved or applied. The current residual
  curator table now enriches 105/393 surfaces and 7,044/8,659 missing mentions, leaving 288
  surfaces / 1,615 mentions for evidence review.
- Found a high-impact pre-existing homonym error: 154 released FLOPO classes use PATO:0000455 for
  botanical `pubescent`, but PATO:0000455 is a maturity quality at the onset of sexual puberty.
  PATO:0001320 is the pilosity class defined by coverage with short hairs or soft down. UPOV and
  the AOS glossary independently confirm the plant sense. Corrected runtime/baseline grounding and
  added a review-only obsolete-and-replace migration generator; its cross-artifact check finds
  exactly the same 154 classes in `config/flopo_id_registry.tsv` and `ontology/flopo.owl`, with
  blank curator decisions. It deterministically proposes 154 new, unreserved replacement
  signatures using PATO:0001320 and retains the old identifiers as future annotation-only obsolete
  terms with exact replacement links. No released signature has yet been changed.
- Read and checksum-pinned additional NYBG, American Orchid Society, Florida Invasive Plants, and
  Flora of Australia glossary evidence for apex, base, lobe, cyathium, botanical hair/trichome,
  trunk, frond, pinna, and pinnule. Full Saudi concordances changed two tempting lexical decisions:
  11 of 12 `frond(s)` mentions are palm leaves, so a fern-only class is inadequate, and both
  singular `hair` mentions are the place name Hair while plural `hairs` is anatomical.
- Added 16 blank-decision curator proposals that separate ontology gaps from existing mappings and
  extraction artifacts. Strong PO subclass candidates now include trunk, frond, pinna, pinnule,
  and cyathium; cyathium is explicitly removed from the cyme lane and receives only universal
  staminate-flower/involucre parts. Generic plant-structure apex/base are proposed as parents for
  review, while the generic lamina-lobe boundary is held for PO resolution because NYBG and PO use
  different shape/depth criteria.
- Identified 377 habitat/geology mentions and 61 population-abundance mentions as context-specific
  non-phenotype text, plus 257 compound-suffix fragments and 86 degree/manner modifiers that need
  compositional parsing rather than new ontology classes. Existing-class proposals cover ordinary
  `plant(s)` to PO:0000003, clustered arrangements to PATO:0001629, and organ margins to
  PO:0025005 or a bearer-specific descendant.
- The current-ontology curator table now enriches 78 of 393 unresolved surfaces, covering 6,521 of
  8,659 missing mentions; 315 surfaces / 2,138 mentions remain pending. The frozen baseline remains
  intact for comparison, every curator decision remains blank, and no candidate axiom has been
  applied to PO, PATO, FLOPO, the released OWL, or the committed terminology registry.
- Verified all 35 evidence-file checksums from the manifest and reproduced the current curator TSV
  and JSON byte-for-byte in a separate output. Ruff is clean and all 124 collected Python tests
  pass, including the explicit `NONE`/`reject_as_noise` schema path.
- Extended the pinned evidence set first to 57 manifest rows (48,854,649 verified bytes) with official
  PlantNET C--Z glossary sections, the Flora of Australia glossary, the NYBG clasping entry, and
  the RHS foliage definition. Every local artifact again matches its recorded SHA-256 checksum.
- Completed independent corpus-concordance review of the residual long tail. The current table now
  attaches an explicit proposal, mapping, modeling pattern, sense split, or context-specific noise
  decision to all 393/393 surfaces and all 8,659/8,659 mentions. Replaying the same proposal source
  against the original frozen audit covers all 436/436 surfaces and all 9,727/9,727 mentions. All
  curator decisions and notes remain blank.
- The completed pass rejects several tempting lexical mappings: natural `dwarf` is not PATO's
  abnormal `dwarf-like`; `strong` and `faint` predominantly modify odor rather than fragility or
  conspicuousness; floral `callus` is not undifferentiated plant callus tissue; fruit `husk` is not
  an inflorescence bract; `free petals` maps to unfused-from, not skeletal autogenous; and a generic
  `tuft` is not the seed-micropyle-specific PO coma.
- The frozen replay exposed additional release repair candidates without changing the released
  ontology: FLOPO:0980163 `three-angled` is incorrectly parented under `bent`; FLOPO:0980174
  `golden` and FLOPO:0980342 `cottony` have label-paraphrase definitions; and the rose-pink,
  pale-rose-pink, and purple-magenta temporary values need explicit FLOPO colour-composition
  semantics rather than conjunctive component-colour subsumption. No ontology axiom or registry
  decision has been applied.
- Strengthened proposal validation so an accepted class proposal must cite a known evidence item,
  extra TSV columns fail closed, and machine-generated proposal files cannot populate curator
  decision or notes fields. Focused tests cover all three failure modes.
- Completed a semantic quality gate over every recommended upstream class proposal. The final
  upstream review set contains 26 evidence-backed atomic candidates (10 PO and 16 PATO), all with
  textual definitions, cited evidence, known live parents, and blank curator fields. `winged` is a
  general shape rather than a subclass of ridged; `ascending` and atomic `spreading` are
  orientations; ambiguous woolly/silky/pleated forms are not exact synonyms; and
  annual/perennial values use explicit expected-life-span ranges.
- Rerouted trifoliolate and bifoliolate leaf phenotypes, stinging trichome, foliage, plant latex,
  and whole-plant growth forms to FLOPO. Added a review-only bearer-centric FLOPO top-level
  proposal, separate PATO-quality and GO-process support vocabularies, local PO/PATO-parented
  support classes, and explicit migration/validation gates. Foliage avoids PO's
  adjacency-requiring collective-structure class; plant latex is defined from laticifer literature
  and kept distinct from plant sap.
- Downloaded and checksum-pinned Saccardo and Ridgway colour standards, RHS/UPOV colour guidance,
  and a laticifer review. The evidence manifest now has 63 verified rows (59,481,218 bytes). A
  source-qualified prototype table records recognition criteria or an explicit no-single-prototype
  result for cream, crimson, scarlet, silver, gold, lemon, mahogany, salmon, chestnut, chocolate,
  olive, rose, and straw; it preserves cross-standard sense splits and does not treat display RGB
  values as normative physical colour chips.
- Added a review-only sensu hierarchy for the true-colour families: unqualified terms are open
  PATO umbrellas and named standards retain separate operational children. Scarlet has Saccardo,
  Ridgway, and Wilson children plus an optional, separately labelled closed reviewed-set union.
  The existing RHS-defined PATO:0104031 remains source-specific in the proposal. Silver and golden
  cross-category appearance senses stay outside the pure-colour hierarchy.
- Validated the revised top-level and colour proposals with focused structural tests and the full
  locked Python suite (156 tests); Ruff passes for every changed Python test. No released ontology,
  identifier registry, curator decision, commit, push, or pull request was changed.
- The complete current breakdown shows that 337/8,659 unresolved mentions (3.89%) correspond to
  the 26 recommended missing atomic PO/PATO proposals. Existing-term registry, mapping, or ontology
  repair accounts for 2,236 (25.82%), contextual composition, local FLOPO extension, or modeling
  for 3,808 (43.98%), unresolved sense/definition work for 1,649 (19.04%), and context-specific
  noise for 629 (7.26%).
- Regenerated both current and frozen curator tables after the routing changes. Every one of the
  393 current and 436 frozen surfaces remains covered, all curator fields remain blank, and no
  ontology, registry decision, commit, push, or pull request was changed in this phase.

### 2026-09-18

- The curator (Robert Hoehndorf) approved
  `scratchpad/qwen-concept-proposal-review-20260917/` as recommended. All 230 rows of
  `curation/botanical_concept_proposals.tsv` now carry a curator decision (171 accept, 35
  accept_with_revision, 20 defer, 4 reject) and dated notes, written deterministically by
  `scratchpad/qwen-concept-proposal-review-20260917/apply_curator_decisions.py` from the
  reviewer-edited table plus the packet's final fields. `curation/curator_approvals.tsv` records the
  approval rows. `flopo2.terminology.curation_table` accepts such a table only with the explicit
  `--curator-reviewed` flag; machine proposal tables must still leave curator fields blank.
- A later decision of the same day adopts an ISCC-NBS colour backbone. The 11 colour rows (4, 5, 6,
  24, 25, 162, 177, 196, 198, 223, 228) are approved but create, revise or obsolete no colour class;
  they are implemented through the backbone.
- `tools/build_flopo_botanical_extension_2.py` builds `ontology/flopo-botanical-extension-2.ttl`
  (catalogued as `http://purl.obolibrary.org/obo/flopo-botanical-extension-2.owl`): 17 provisional
  PATO-candidate qualities and 14 provisional PO-candidate entities as FLOPO-local classes under
  their closest live PATO/PO parent, 7 FLOPO growth-form phenotypes (including a new climbing class
  so FLOPO:0900035 keeps its woody-climber referent), and in-place revisions of FLOPO:0900033,
  0900034, 0900035, 0900039, 0900044 and 0022142. No PO or PATO identifier is minted.
  Identifiers come from `config/flopo_botanical_concept_id_registry.tsv`, which reserves the block
  FLOPO:0985000-0985999 (38 used). The block sits far above the sequential allocations
  (FLOPO:0981091 at the time), so concurrent colour-EQ and backbone allocators cannot collide.
- FLOPO:0980163 three-angled is reparented from bent to triangular (PATO:0001875) through a curated
  override in `config/flopo_value_axioms.tsv`; `ontology/flopo-value-extensions.ttl` is regenerated.
- Upstream PR and issue texts are drafted in `curation/upstream_drafts/` and have not been opened.
- The module is not yet embedded in `ontology/flopo.owl`; the release step is
  `tools/update_flopo_botanical_extension_2_release.py` followed by the value-extension update,
  registry resync and classification.
- The curator approved two machine-review admission rules, now written into
  `flopo2/ANNOTATION_MODEL.md` §3: a held qualitative-value-relation item is admitted when a third
  independent model family agrees exactly with one of the two campaign reviewers and every
  deterministic gate still passes ("2-of-3"); and a deterministic recovery rule may admit relations
  without per-item model review when a seeded, stratified audit of its output reaches a 95% Wilson
  lower bound of at least 0.95. Both remain machine provenance, never curator or human review.
- Five deterministic recovery modules were added under `flopo2/verify/recover_claude_*.py` (plus
  matching `tests/test_recover_claude_*.py`), each mining one residual `unresolved_spans` reason
  from stage 22 (`scratchpad/flopo-claude-recovery-20260918/BRIEF.md`): `hyphen_compound`
  (shape/colour continua across a hyphen or slash), `developmental_stage`
  (clause-scoped stage qualifiers), `missing_bearer` (clause-head/trichome/heading bearers),
  `alternatives_transitions` (closed-vocabulary continuum unions), and `explicit_disjunction`
  (closed bilingual value tables for `X or Y`). Each was rebuilt a second time against the
  current config (picking up the day's approved PO×PATO pairs and the leaflet-context guard); after
  rebuild the modules together resolve roughly 10,300 spans with per-module Wilson 95% lower bounds
  of 0.95–1.00, reports in each module's `scratchpad/flopo-claude-recovery-20260918/<category>/report.md`.
- A third-reviewer ("Claude Opus 5") tie-break pass re-judged every item still held by the earlier
  two-model campaigns, applying the curator's 2-of-3 rule: 47 exact-colour EQ classes (355
  occurrences) and 20 contextual exact-colour occurrences
  (`scratchpad/flopo-exact-colour-eq-class-review-20260804-v2/tiebreak-20260918/`,
  `scratchpad/flopo-claude-recovery-20260918/colour-tiebreak/`); 17 leaf-base, 107 leaf-apex and 43
  shape-recovery items (`scratchpad/flopo-claude-recovery-20260918/shape-tiebreak/`, one shape item
  later excluded by the gated validator for a bearer-interval defect, leaving 42 in the delta).
- The tie-break pass also found and corrected a systematic mis-bearing error: 836 stage-22
  assertions had attached a leaf apex/base/lamina quality that the source text actually gives to a
  leaflet. All 836 were removed and their spans restored to `unresolved` pending a leaflet bearer
  (`scratchpad/flopo-claude-recovery-20260918/shape-tiebreak/leaflet-bearer-corrections.tsv`,
  `correction-delta.jsonl`); a new guard, `flopo2/extract/leaflet_context.py`, is now wired into the
  baseline extractor and the recovery/campaign candidate generators so a rerun cannot regenerate the
  error.
- The curator approved 7 new FLOPO-local anatomy support classes, FLOPO:0986000-0986006 (leaflet
  apex, leaflet base, leaflet lamina, indumentum, perianth lobe, calyx lobe, corolla lobe;
  `curation/flopo_anatomy_support_classes_20260918.tsv`,
  `config/flopo_anatomy_support_id_registry.tsv`,
  `ontology/flopo-anatomy-support-extension.ttl`) and, separately, 379 PO×PATO bearer/attribute
  pairs surfaced by `missing_bearer`, `explicit_disjunction` and the NCVC ingest
  (`curation/curator-2026-09-18-po-pato-approvals.tsv`, 90 excluded after a strict sanity screen,
  promoted into `config/valid_combinations.tsv`), plus 26 leaflet-specific
  FLOPO:0986xxx x PATO pairs (`scratchpad/flopo-claude-recovery-20260918/shape-tiebreak/leaflet-readmit-pair-candidates.tsv`).
  With the leaflet classes and pairs approved, `flopo2/verify/readmit_leaflet_bearers.py` re-bears
  332 of the 836 corrected assertions on the new classes (the rest are still held by guards for
  surface restriction, ranges/alternatives, or non-atomic values).
- The 47 tie-break-admitted colour classes were released alongside the 66 already in
  `ontology/flopo.owl`, giving 113 machine-reviewed exact-colour EQ classes, FLOPO:0980979-0981091
  (`config/flopo_machine_eq_id_registry.tsv` +113; `ontology/flopo.owl` version 2026-09-18;
  `ontology/flopo-inferred.owl` regenerated; no new unsatisfiable classes; the OBO Dashboard gate is
  unchanged, still only the pre-existing FP04 error).
- `scratchpad/flopo-stage23-20260918/run_merge.sh` merges the day's corrections, tie-breaks and
  recovery deltas onto stage 22 through a new precedence-resolved, fail-closed applier
  (`flopo2/verify/apply_deltas.py`: corrections, then tie-breaks, then recovery categories ordered
  by their audited Wilson lower bound). Result (`merge-report.json`): 7,343 of 116,322 segments
  patched, assertions 156,282 -> 164,232 (+8,786 added, 836 removed), unresolved spans 197,341 ->
  187,845; 30 duplicate-key conflicts logged to `conflicts.tsv` and excluded rather than guessed at.
  Gated strict validation on the merged stage-23 corpus: 0 errors.
- Ranked OBO Dashboard QC fixes were implemented in `flopo2/owl/obo_fix.py`
  (`scratchpad/qc-fix-20260918/`): every deprecated FLOPO entity's label now gets the "obsolete "
  prefix (1,007 of 1,007 `missing_obsolete_label` warnings cleared) and textual definitions are now
  generated for the remaining native classes, from their logical pattern or from curated
  genus-differentia text in the new `config/flopo_curated_definitions.tsv` (80 of 86
  `missing_definition` warnings cleared, 6 remain). A rerun of the dashboard shows FP06 Textual
  Definitions passing; the only remaining error is the pre-existing FP04 Versioning (unresolved
  versionIRI, needs a release publication, not a code fix).
- A review-only ISCC-NBS colour backbone design was drafted
  (`scratchpad/colour-backbone-20260918/DESIGN.md`): 303 distinct standard classes (13 level-1, 29
  level-2, 267 level-3 blocks; 27 already exist as PATO IDs, 276 would need new IDs), 904 vernacular
  synonym rows scoped EXACT/NARROW/RELATED, and a migration plan that would obsolete 103 of the 213
  existing FLOPO colour-bearing classes (the 78 single colour-name values and 25 source-qualified
  `sensu` classes) in favour of the backbone, repointing 1,423 of 1,739 EQ colour fillers. Nothing
  in `ontology/`, `config/` or `curation/` was changed; the design is pending curator sign-off on
  nine open questions (Q1-Q9 in the document), including whether Centore's GPL-licensed transcription
  may ground CC0 facts and how the 276 new classes should be identified (FLOPO-local vs. a PATO PR).
- A four-extension FLOPO trait schema proposal was drafted and ranked by value/effort
  (`scratchpad/schema-extension-20260918/PROPOSAL.md`): growth-form/life-span EQ definitions (no
  schema change, unlocks 396 NCVC rows plus ~17.2k corpus habit clauses), per-operand/per-endpoint
  degree and value qualifiers, taxon occurrence/geography, part/scope restrictions, and composite
  range/alternative operands. Nothing under `flopo2/schema/`, `flopo2/ANNOTATION_MODEL.md` or
  `ontology/` was changed.
- The NCVC Saudi native-plants guide (2024, Arabic with English translation, copyrighted, no open
  licence) was ingested as a new corpus source through `flopo2/ingest/ncvc_guide.py` and
  `flopo2/ingest/ncvc_annotate.py`: 301 species records (300 distinct taxa), 1,204 text segments
  (602 English/602 Arabic), 7,554 source statements, and 4,959 transcribed phenotype rows giving
  3,383 gated assertions (2,976 accepted, 407 review; 2,265 linked to an existing FLOPO EQ class, 271
  a novel PO×PATO pair from 90 distinct candidates). Habit/life-span/fruit/inflorescence terms are
  normalized through the reviewed `flopo2/ingest/ncvc_normalization.tsv`; 61 assertions are held for
  documented data-quality problems (`flopo2/ingest/ncvc_data_quality_holds.tsv`). A separate
  distribution table (2,769 rows) records taxon occurrence across the 13 Saudi ISO 3166-2 regions
  plus named localities, joined against a gazetteer (GeoNames/Wikidata) and taxa resolved through
  WFO/POWO (22 accepted-family corrections). All raw transcriptions and derived text stay under the
  git-ignored `local-corpora/saudi-ncvc-guide/`, per the guide's "all rights reserved" notice; only
  facts, not verbatim text or images, are stored. Open items from this ingest (no PATO/FLOPO term
  for growth-form/life-span classes, sexual system, or position terms; alternatives held rather than
  converted; counts unrepresentable; no taxon-occurrence slot in the trait schema) are listed in
  `scratchpad/OPEN_ITEMS_20260918.md`.
