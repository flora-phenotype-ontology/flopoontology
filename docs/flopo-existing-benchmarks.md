# Existing benchmarks for FLOPO trait learning

Update 29 October 2026: the proposed matched supervision and label-efficiency experiments have been run. See the [completed follow-up report](flopo-shape-experiments-results.md), including a separate fresh cotton transfer test.

Assessment dated 28 October 2026, following the completed teacher and spatial-view experiment. **Update: the independent benchmark evaluation is now complete; see the [results and revised next steps](flopo-pxgpt-results.md).** The assessment below records the evidence available before those benchmark scores. Existing human annotations provide a route to evaluation without asking Robert to review photographs. The strongest verified candidate is the pxGPT Brassica release. The immediate scientific objective should be to test whether FLOPO-derived flora annotations improve recognition of a small set of visible qualitative traits. An additional benefit from logical constraints is a separate hypothesis.

## Verified evaluation data

The [pxGPT Brassica release v2.0.0](https://zenodo.org/records/22907554) contains photographs, trait codebooks, human scores and references derived exclusively from those scores. Its ten annotators were blinded to model outputs. References describe photo sets: a mature record represents one plant, while a seedling set can contain sibling plants. Treating these as independently labelled photographs would be incorrect. The release is CC BY 4.0.

I downloaded the documentation and annotation archive, checked its published MD5 and all 16 internal SHA-512 entries, and checked table keys and image-count joins. Local analysis gives:

| Dataset | Photo sets | Sets with human scores | Listed photographs | Qualitative trait fields |
|---|---:|---:|---:|---:|
| Seedling | 284 | 284 | 1,878 | 38 |
| Mature v1 | 142 | 112 | 2,784 | 45 |
| Mature v2 | 277 | 203 | 5,208 | 43 |

There are 78,973 human scores, 599 scored sets and 321 cultivar IDs overall. Cultivars recur across datasets. The archive includes disagreements and unassessable states, so these totals are not counts of usable independent test cases. At the time of this initial inventory, photographs had not been downloaded and models had not been scored. The completed evaluation is linked above.

Evidence and reproducible inventory:

- [Inventory](../local-corpora/benchmark-discovery-20261028/inventory.json)
- [Inventory script](../local-corpora/benchmark-discovery-20261028/audit.py)
- [Downloaded annotation guide](../local-corpora/benchmark-discovery-20261028/pxgpt_brassica_release/ANNOTATION_GUIDE_en_zh.md)
- [Downloaded reference policy](../local-corpora/benchmark-discovery-20261028/pxgpt_brassica_release/DATA_DESCRIPTION.md)

## Practical overlap with our outputs

The following counts are my calculations from the downloaded tables, before any benchmark prediction. The conservative subset requires at least two raters, a strict majority, an assessable value and no ordinal tie-breaking.

| Candidate task | Available conservative references | Interpretation |
|---|---|---|
| Seedling leaf hairiness | 176 glabrous, 47 sparse, 13 dense | A useful binary hairy versus glabrous task after an explicit mapping; do not equate sparse hair with a narrower pubescence subtype. |
| Mature v1 leaf hairiness | 96 glabrous, 10 pubescent | Small, imbalanced external check, with labels for individual-plant photo sets. |
| Seedling and mature v1 leaf shape | 63 ovate, 10 orbicular, 2 lanceolate, plus grouped categories | Ovate is usable; lanceolate is too rare for a persuasive separate result. The 133 obovate/spatulate references cannot be split into two asserted labels. |
| Seedling leaf margin | 50 serrate/dentate, 55 crenate, 34 entire, 13 lobed, 1 wavy | Serrate/dentate is a grouped target. Several other states would require extending the current output vocabulary. |

The current vocabulary has leaf hairiness and several relevant shapes, but only serrated and dentated margin outputs. Codebook alignment is still required: a leaf-blade label, a whole-leaf label and a cotyledon label are not automatically interchangeable. Unresolved nominal ties remain unknown. Report performance and coverage on the conservative subset, with a sensitivity analysis using all published assessable references and their disagreement information.

Flower colour is unsuitable as an initial endpoint here: the seedling references have only one yellow case, no white cases, 281 unassessable cases and two unresolved ties. This dataset also does not supply a ready evaluation of our three held-out fruit/petal combinations.

## Other candidates

[DiasMorph](https://doi.org/10.1038/s41597-024-03607-3) pairs diaspore scans with recorded structures and appendages across 1,442 taxa. It is promising for later qualitative structural traits. The [versioned deposit](https://doi.org/10.6084/m9.figshare.21206507.v5) exposes metadata and a labels-and-structures CSV; I retrieved the repository metadata, but downloading that CSV returned HTTP 403. Its exact categorical coverage is therefore not verified locally. A diaspore can comprise different organs, so it must not automatically be mapped to our fruit bearer. Continuous colour and shape measurements are not independent categorical human labels.

[MORPHYLL](https://palaeo-electronica.org/content/2018/2114-database-of-fossil-leaves) records specimen-level fossil-leaf margin, lobation and venation traits. The paper describes roughly 6,000 leaves but restricts trait data and high-resolution images to registered users; the portal did not resolve through the browser tool in this check. It is a possible later domain-transfer test, not an immediately verified open download. No contact request was sent.

## What the completed experiments establish

The earlier full collection contains 52,011 images from 28,250 observations and 333 taxa. Filtering yielded 8,152 training regions; usable flora assertions supervise 32 traits over 157 taxa. The subsequent staged workflow records 62 completed and hash-verified outputs across two frozen encoders. Data collection, weak-label training, teacher supervision, controls and prediction retention are implemented.

The latest diagnostic still uses the previously inspected AI leaf-shape audit. Only 17 field and 9 external images have singleton labels for AP; allowed-set top-choice evaluation uses 23 and 14. These are insufficient for a definitive trait-learning claim.

| Staged model | Field shape macro AP | External shape macro AP |
|---|---:|---:|
| BioCLIP baseline | 0.7221 | 0.5648 |
| BioCLIP plus flora supervision | 0.7331 | 0.6172 |
| BioCLIP plus teacher supervision | 0.6873 | 0.7250 |
| BioCLIP plus both sources | 0.6026 | 0.6929 |
| BioCLIP plus both and FLOPO constraints | 0.6026 | 0.6373 |

Values are three-seed probability ensembles except the baseline. The BioCLIP baseline uses the existing training-only ridge initialization from FG-CLIP logits; it is not native BioCLIP zero-shot prediction. The modest flora-only improvement is encouraging development evidence. Combining flora with the teacher did not beat the teacher on external AP, and adding constraints reduced it further. With FG-CLIP, combined supervision and combined-plus-FLOPO both score 0.5028 externally; shuffled profiles score 0.6926. Thus neither annotation utility nor an additional reasoning benefit is yet established independently.

Sources: [full experiment report](flopo-full-results.md), [staged workflow](../local-corpora/staged-v1/workflow.json), [BioCLIP diagnostic](../local-corpora/staged-runs-v1/bioclip2/diagnostic.json), [FG-CLIP diagnostic](../local-corpora/staged-runs-v1/fgclip2/diagnostic.json). Shape results from the transfer arms do not evaluate the withheld fruit/petal combinations.

## Recommended next experiment

1. **Freeze a narrow benchmark protocol.** Start with hairiness and well-supported shape states. Specify organ mappings, grouped labels, missing-value handling, photo-set aggregation and the confidence subset before computing predictions. Keep every view and every occurrence of a cultivar in one partition across stages. Freeze a test partition before model selection; any calibration uses only a separate development partition. Use human references only, excluding supplied narratives and model outputs.

2. **Evaluate existing models first.** Download the relevant photographs, extract the same views for every arm, and score all declared baseline, flora, teacher, combined and constraint variants without selecting a winner on the test set. Include an end-to-end view using detected organs; a failed detector must not silently remove difficult examples. This is an external photo-set recognition test, not validation of every image or organ localization.

3. **Make the annotation contribution identifiable.** Compare the pretrained baseline, a flat head trained with FLOPO-derived flora labels, the same schedule with shuffled profiles, and the same head with ontology structure. Keep images, sampling, initialization, loss budget and output labels matched. Separately compare teacher-only with teacher-plus-flora. This distinguishes useful flora supervision from a foundation-model prior, teacher performance and an additional effect of constraints. To claim that normalization itself helps, add raw text attributes versus FLOPO-normalized labels from the same source records.

4. **Test transfer and data efficiency.** The existing training manifest contains 284 photographs of Brassica tournefortii, so the present external evaluation cannot be called genus-held-out. A subsequent matched training comparison should exclude Brassica and relevant synonyms from every training source, while retaining the benchmark for evaluation. Check image hashes and near-duplicates after download; absence from foundation-model pretraining remains unverified. Compare nested annotation budgets and bootstrap by cultivar, not photograph. Report per-trait AP, macro AP, balanced accuracy and assessable coverage; thresholds are selected on development data only.

5. **Use supervised controls to diagnose failure.** On a separate, explicitly supervised benchmark track, fit a simple head to the available human training references with the same encoder and cultivar-separated splits. This checks whether the encoder and chosen targets are learnable. If that works but flora supervision fails, investigate weak-label quality and organ visibility. If neither works, inspect the mapping, visual representation and domain mismatch before scaling further. Once annotation utility is established, test compositional or logical benefits on targets with adequate independent references.

A useful first result would show better recognition or lower annotation requirements for a few independently labelled qualitative traits. It need not include species identification, quantitative traits or full OWL reasoning. No new training job was launched. The proposed evaluation of existing checkpoints was subsequently implemented and completed.

## Independent evaluation completed

Later on 28 October, the evaluation was implemented and submitted. All three image archives passed their repository checksums. The frozen cohort contains 599 annotated photo sets and 7,896 photographs, with 184 development sets and 415 test sets assigned by cultivar across stages. No new human annotation is requested. Reference counts and agreement were checked against all 27,566 cells in the underlying human-score table.

The primary endpoint is the equal-dataset mean of hairy/glabrous macro average precision on strict test references. A dataset needs at least five cases of each state: seedling contributes 44 hairy and 119 glabrous test sets; mature v1 contributes seven and 69. Mature v2 has only two strict positive test cases and is reported separately. Grouped leaf-shape recognition, whole-image views and less restrictive reference handling are secondary analyses. Thresholds use development references only; uncertainty uses paired resampling of cultivar groups.

The overlap audit verified every benchmark image against its published SHA-512 and found no exact or <=4-bit dHash candidates among 21,654 fine-tuning training photographs. It found no identical decoded images across benchmark cultivar IDs. These checks do not establish absence from foundation-model pretraining.

Eleven focused tests now pass. GPU preflight 351295 completed successfully. Full inference array 351305 completed all four shards with exit 0, in 16–17 minutes each. The workstation controller collected the predictions, verified all 168 output-file hashes and scored all 38 checkpoints and 12 ensembles against human references. No further job is pending for this evaluation.

The [completed report](flopo-pxgpt-results.md) finds no reliable flora-only gain on the primary hairiness endpoint and a decrease when flora is added to teacher supervision. Whole-image shape recognition shows exploratory gains, which motivate a matched annotation-ablation and label-efficiency experiment. Additional logical constraints provide no consistent benefit.

The authoritative runtime record is [workflow.json](../local-corpora/pxgpt-benchmark-v1/workflow.json); the frozen design and completed execution record are in [flopo-pxgpt-evaluation.json](flopo-pxgpt-evaluation.json). Full results are stored under `local-corpora/pxgpt-results-v1/`, with a compact version in [flopo-pxgpt-results.json](flopo-pxgpt-results.json).
