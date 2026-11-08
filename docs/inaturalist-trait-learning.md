# Learning plant traits from iNaturalist and FLOPO

Literature search and proposed experiments, updated 24 October 2026. This is a research design,
not a report of trained models. The searches covered plant images with species-derived
weak labels, text-derived visual attributes, biological vision foundation models,
multiple-instance learning, and concept bottlenecks. Publisher/proceedings records were
checked; the Schiller, PlantTraitNet and BioCLIP 2 full papers were read for their relevant
methods and evaluation. This is a targeted search, not a systematic review or proof of novelty.

Species-linked weak supervision is already established. FLOPO's testable contribution is
structured supervision about **which organ has which quality, under which conditions**, with
explicit uncertainty, rather than assigning an undifferentiated species trait vector to every
photograph. Better prediction is a hypothesis to test, not a consequence of using an ontology.

## Closest work

| Work | What was demonstrated | Implication for FLOPO |
|---|---|---|
| [Schiller et al., 2021, Scientific Reports](https://doi.org/10.1038/s41598-021-95616-0) | Linked iNaturalist photographs to TRY species traits and trained CNNs for six functional traits. Compared species means, species-specific trait distributions, climate information and ensembles. The discussion explicitly notes the lack of matched individual-level measurements for conclusive validation. | The image–species–trait join and noisy species-derived labels are prior art. Our baseline must include this form of supervision. |
| [Sharma et al., 2026, PlantTraitNet, AAAI](https://ojs.aaai.org/index.php/AAAI/article/view/41272) | Uses iNaturalist and Pl@ntNet photographs with TRY species distributions, image/depth/geospatial representations, trait-specific uncertainty, and iterative filtering. Reports a reference set with images and measurements from the same individuals and a separate comparison against community-weighted trait maps. | Uncertainty-aware weak supervision is also prior art. Morphological visibility, formal organ–quality semantics and identification through those traits are more relevant differentiators than another uncertainty head. Their filtering reference set is not an untouched final test set. |
| [Tirkaz et al., 2015, Computer Vision and Image Understanding](https://doi.org/10.1016/j.cviu.2015.02.006) | Mines visual attributes from text using taxonomy and distributional similarity; evaluates supervised plant recognition and zero-shot animal recognition. | Text-derived plant attributes and taxonomic structure are not new. Do not misdescribe this paper as demonstrating zero-shot plant recognition. Compare flat text attributes against FLOPO-normalized attributes. |
| [Gu et al., 2025, BioCLIP 2, NeurIPS](https://github.com/Imageomics/bioclip-2) | A biological vision-language model trained with hierarchical taxonomic labels, evaluated beyond species identification, including trait-related tasks. BioCLIP 2.5 is also available. | Use a frozen biological encoder as a strong baseline before fine-tuning. Its published trait results do not establish FLOPO morphological trait recognition; image overlap with pretraining must be audited. |
| [Koh et al., 2020, Concept Bottleneck Models, ICML](https://proceedings.mlr.press/v119/koh20a.html) | Predicts concepts before labels and permits interventions on concept predictions; evaluated on bird identification and radiology. | Supports an image → FLOPO traits → plant identity architecture, including user corrections. It does not solve weak concept supervision by itself. |
| [Oikarinen et al., 2023, Label-Free Concept Bottleneck Models, ICLR](https://openreview.net/forum?id=FlCg47MNvBA) | Constructs concept bottlenecks without manually labelled concept training data using language/vision representations. | Include a label-free concept baseline using the same trait vocabulary. A FLOPO bottleneck alone is not a novelty claim. |
| [Ilse et al., 2018, Attention-based Deep Multiple Instance Learning, ICML](https://proceedings.mlr.press/v80/ilse18a.html) | Learns from bag labels using permutation-invariant attention aggregation. | Useful for multiple photographs per observation, but a positive species trait does **not** guarantee that any photograph in an observation shows the organ. Standard positive-bag assumptions require modification. |
| [Kiryo et al., 2017, Positive-Unlabeled Learning with Non-Negative Risk Estimator, NeurIPS](https://proceedings.neurips.cc/paper/2017/hash/7cce53cf90577442771720a370c3c723-Abstract.html) | Addresses learning from positives and unlabelled examples without treating unlabelled data as negatives. | Relevant to incomplete floras. Its assumptions about positive sampling and class priors must be assessed: flora authors preferentially record diagnostic traits, so naive PU learning is not automatically valid. |

Adjacent work includes [Marcos et al., 2025, automatic morphological trait extraction from
the web](https://doi.org/10.1002/aps3.70005), which evaluates text-to-trait extraction, and
[LeafMachine2](https://pmc.ncbi.nlm.nih.gov/articles/PMC10617304/), which uses annotated
herbarium images for organ detection and quantitative leaf measurement. These address the
text-label and organ-measurement components, respectively, rather than validating our entire
weakly supervised field-photo pipeline.

## Proposed FLOPO contribution

1. **Compositional labels.** Predict bearer and quality jointly: yellow petals differ from yellow
   leaves. Share representations across organs and qualities and test held-out combinations.
2. **Visibility and scope.** Separate taxon-level knowledge, specimen state and image visibility.
   Use observation photo sets with a latent organ-visibility variable; permit every image in a
   set to be uninformative. An organ detector or a small visibility-labelled subset is needed to
   prevent a trivial solution that declares every trait invisible. Attention alone is not proof
   of localization.
3. **Faithful partial labels.** Preserve absence, alternatives, developmental stage, frequency,
   quantitative ranges, source and review status. “White or pink” is a set of possibilities, not
   two simultaneous positive image labels. Missing information contributes no negative target;
   explicit absence applies only to the stated bearer and scope. Do not invent equal probabilities
   for alternatives or interpret a flora range as a measured population distribution.
4. **Selective logical constraints.** Test hierarchy consistency and valid bearer–quality
   combinations. Apply disjointness only to the same individual/organ/state, not whole species
   profiles: different organs or life stages may legitimately differ. Keep provenance conflicts
   visible rather than forcing one label.
5. **Identification through observed traits.** Rank taxa with an incomplete, uncertainty-weighted
   trait profile and permit abstention or genus-level output. Compare a strict concept bottleneck
   with direct image classification and a combined model; only the strict bottleneck supports a
   claim that identity depends exclusively on the displayed traits.

## Does PlantTraitNet use an ontology?

Not in the published prediction method. PlantTraitNet learns four numerical TRY traits:
plant height, leaf area, specific leaf area and leaf nitrogen. It uses species-level trait
distributions as weak labels, multimodal features and uncertainty-aware regression. The
paper and released implementation do not describe FLOPO, OWL axioms or logical entailment.
This is a statement about the model, not a claim that TRY lacks standardized trait definitions.
See the [AAAI paper](https://doi.org/10.1609/aaai.v40i46.41272) and the inspected
[model implementation](https://github.com/GeoSense-Freiburg/PlantTraitNet/blob/31a3d14f3f477447fbd268f252c6019f5c8f31b3/src/models/planttraitnet.py)
and [trait likelihood loss](https://github.com/GeoSense-Freiburg/PlantTraitNet/blob/31a3d14f3f477447fbd268f252c6019f5c8f31b3/src/loss_util/MixedNLLLoss.py).
The pinned source snapshot is retained in `local-corpora/planttraitnet-source/`.

FLOPO would change the target to compositional morphological phenotypes and introduce
axioms that affect learning and inference. Using FLOPO identifiers as flat output labels
would not, by itself, demonstrate a benefit from reasoning.

## Current architecture and reasoning experiment

The initial suggestion to transplant DeepGO-SE has been superseded by the
[visually grounded FLOPO architecture and experiment](flopo-visual-reasoning-design.md).
It separates taxon descriptions, individual organs and image assessability, learns localized
visual predicates, and executes supported FLOPO definitions over their probabilities. The
experiment distinguishes supplied logical composition from learned composition, and tests
richer inference separately from an equivalent procedural EQ executor.

DeepGOZero/DeepGO-SE remain relevant comparisons for ontology-informed prediction, but a
whole-image embedding does not itself solve visibility, organ binding or the mismatch between
species-level descriptions and photographed individuals. The linked design specifies the
weak-label likelihood, grounding annotations, downstream taxon scorer and falsification tests.

There is already a measurable retrieval effect in atlas candidate
`20261024-global-inat-0620`: an exact yellow-flower quality match retrieves 291 taxa;
including subclasses of yellow retrieves 439 (148 additional taxa). Both queries require
an explicit flower bearer and a non-negated record. This demonstrates broader retrieval
through the colour hierarchy, not improved image recognition or independently verified
biological accuracy. It is precisely why a hierarchy-only baseline is necessary before
claiming a benefit from richer FLOPO axioms.

```sparql
PREFIX fb: <http://phenomebrowser.net/flopo/browse#>
PREFIX obo: <http://purl.obolibrary.org/obo/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?mode (COUNT(DISTINCT ?taxon) AS ?taxa) WHERE {
  VALUES ?mode { "exact" "hierarchy" }
  ?record a fb:TraitRecord ; fb:taxon ?taxon ; fb:bearer obo:PO_0009046 ;
          fb:quality ?quality ; fb:negated false .
  ?quality rdfs:subClassOf* obo:FLOPO_0988004 .
  FILTER(?mode = "hierarchy" || ?quality = obo:FLOPO_0988004)
} GROUP BY ?mode
```

## First experiment

Select 20–40 traits that can be visually assessed in the available photos, after measuring
taxon and image coverage. Start with flower colour, leaf outline and margin, arrangement and
conspicuous growth form. Exclude odour, physiology and absolute dimensions without a scale from
claims of direct visual recognition. Some may later be predicted indirectly, with that task
labelled separately.

Build observation-level image manifests with observation/photo IDs, accepted taxon identity,
crosswalk evidence, image license, attribution, retrieval date and hashes. Keep uncertain
taxonomic links out of training. Research-grade identification improves selection but is not
error-free, and not every photograph depicts the identified organism. The website's selected
taxon photographs are illustrative and are not the training set.

Use the same images, encoder and training budget for successive comparisons:

| Experiment | Added information |
|---|---|
| Direct species classifier plus species→trait lookup | Measures how far species recognition alone explains apparent trait accuracy |
| Flat weak trait predictor | Species-derived labels without FLOPO structure |
| Text/label-free concept baseline | Trait descriptions without formal constraints |
| FLOPO bearer–quality predictor | Compositional organ-specific labels |
| Visibility-aware observation model | Multiple views, invisible/unknown states and alternatives |
| Ontology-constrained variant | Hierarchy and scoped consistency losses |

Keep all photographs of an observation, duplicate images and near-duplicates in one split.
Run separate species-held-out, genus-held-out and geography/observer-separated evaluations.
Audit foundation-model pretraining overlap, and describe held-out taxa as held out from our
fine-tuning unless absence from pretraining is established. Prevent species names from leaking
into image-to-trait inputs. Compare background-only and organ-cropped controls.

Reserve an independently annotated test set of visible organ–trait labels, including variation
within species, invisible organs and rare states. Do not reuse it for filtering or model
selection. Evaluate macro per-trait precision/recall/AP, calibration, selective accuracy versus
coverage, and ontology violations. For identification report macro top-1/top-5, unknown-taxon
rejection and performance after correcting a predicted trait. Bootstrap by taxon or observation,
not by individual photo.

Proceed to larger training only if the structured model improves independent trait recognition
or transfer over the flat baseline without merely recovering taxon identity. The available
literature supports the feasibility of the approach; it does not yet show that FLOPO improves it.

## Website crosswalk and refresh

The 23 October 2026 run produced 1,482 verified links out of 1,667 local atlas taxa,
including 139 accepted after Qwen review. There are reusable photographs for 1,279 taxa.
185 remain unresolved; a name-search link is shown instead of an asserted identity. The
resolver examined 261 initially ambiguous/unmatched cases and additional discrepancies
revealed by checking live records. Of the identifiers counted by the original summary as
WFO matches, 44 are nonstandard `bare-name-wfo-...` placeholders; that summary should not
be interpreted as a count of fully established accepted taxonomic identities.

Release `20261023-inat-web-2125` was initially deployed at
[the atlas server](http://10.73.11.158:8778/). It preserves the published 1,320-taxon RDF
release: 1,173 of those taxa now have iNaturalist links and 1,029 have photographs. The
larger catalogue is ready for later flora releases. Publishing the newer flora RDF was
blocked by existing C4c/C5b failures for ontology terms absent from this checkout; the
website-only deployment passed all required gates without changing the published traits.
The public `phenomebrowser.net/flopo/` route still returned its existing 404 at verification.

Validation: 79 unit tests across the required atlas checks and integration tests; a browser
crawl of 27 pages and 117 distinct SPARQL queries; focused photo-loading, unresolved-match
and mobile-overflow checks; and live catalogue checksum verification. QLever/Oxigraph parity
passed, with the permitted `SAMPLE()` label warning affecting 10 of 16,909 cells (0.06%).
The full-paper PDFs, extracted text and source/hash ledger are retained locally under
`local-corpora/inaturalist-literature/`; browser screenshots are under
`local-corpora/inaturalist-browser/`.

### Global release, 24 October 2026

Release `20261024-global-inat-0620` replaces the Saudi-only dataset at
[the campus atlas](http://10.73.11.158:8778/). It contains 40 source collections, 1,956 taxa,
35,326 trait assertions and 3,939,083 quads. Many sources are small pilot extracts; this is
not complete coverage or completed normalization of every flora. The 25 value terms needed
by the broader data (FLOPO:0991046–0991070) were embedded as provisional terms, classified,
and included in the release. Existing public FLOPO identifiers remain preserved.

The refreshed crosswalk confirms 1,725 iNaturalist links (157 Qwen-verified), with reusable
photographs for 1,472 taxa; 231 remain unresolved. Catalogue and RDF taxa are now aligned.
The site is titled **FLOPO Trait Atlas**, reports all sources, and identifies partial source
coverage and provisional mappings. Narrow screens can scroll wide trait matrices locally.

The reported Firefox network error could not be reproduced in fresh Firefox or Chromium
sessions. Logs showed several failed Firefox requests without corresponding backend queries;
the initiating connection failure is undiagnosed. A separate confirmed defect retained rejected
promises in the browser cache, preventing subsequent navigation from recovering. Failed loads
are now evicted, interrupted requests are retried once, and page/catalogue Retry controls are
available. Fault injection confirmed recovery after both request attempts were interrupted.

Validation includes 81 atlas/integration/deployment tests, 21 flora-value/classification/release
compatibility tests, the 27-page crawl and 117 captured SPARQL queries. All 116 SELECT queries
have matching result counts in QLever and Oxigraph and run within two seconds; `SAMPLE()`
accounts for the permitted warning on 49/28,461 compared cells (0.17%). Forty RDF resource
descriptions agree. The first graph-count check incorrectly treated absent empty graphs as
missing data; the corrected check and regression test accept zero triples while continuing
to reject missing nonempty graphs and unexpected data. The corrected gate passed before
promotion, and the check history preserves the original failure and successful recheck.
The final browser crawl used the same query set as the database comparison. Blue retains
the preceding release for rollback. Live Firefox and Chromium checks passed for the overview,
taxon list and North American *Abies grandis* page, including licensed photos and observation
links; Chromium also passed the mobile overflow check.

`flopo2.saudi.inaturalist` reads the atlas taxa and an iNaturalist taxonomy TSV. It uses printed
source names as synonyms, sends difficult cases to Qwen, retrieves candidates and rechecks live
taxa. Proposed renamed taxa require an exact WFO match to the atlas accepted WFO identifier.
Inactive taxa, incompatible ranks, unsupported family conflicts, invented IDs and uncertain model selections
remain unresolved. A family difference is accepted only when an exact WFO lookup yields the same
accepted identifier and Qwen selects the candidate with high confidence; this accommodates historical
family classifications while preserving identity checks. Qwen reasoning is evidence for a decision, not an authoritative taxonomic
source. Cache files retain retrieved API responses and model prompts/decisions.

```bash
python -m flopo2.saudi.inaturalist \
  --snapshot /path/to/inat_taxa.csv \
  --taxa local-corpora/saudi-flora/rdf/taxa.nt
```

The output `inaturalist.json` is a public sidecar consumed by the browser and copied into atlas
releases. `inaturalist-audit.json` and `inat-cache/` retain the fuller mapping evidence locally.
Use a fresh output/cache directory for a fresh API snapshot, then replace the public sidecar
after review; rerunning with the same cache resumes the existing snapshot. This avoids hidden
taxonomy changes during a build. The catalogue timestamp is a build time; cached retrieval times
are in the audit cache. A future training export should pin these response hashes as well.

Only explicitly licensed photos are included (CC0, CC BY, CC BY-SA, CC BY-NC, CC BY-NC-SA),
with attribution and source links. Observation counts are snapshots. The website links to
current observations, and does not claim that pictured traits have been verified.
Follow [iNaturalist API guidance](https://www.inaturalist.org/pages/api%2Brecommended%2Bpractices)
for refreshes and use [published bulk datasets](https://www.inaturalist.org/pages/developers)
for training collections. Retain photo licenses separately from observation licenses; a training
dataset/model release needs a license policy appropriate to its intended use.
