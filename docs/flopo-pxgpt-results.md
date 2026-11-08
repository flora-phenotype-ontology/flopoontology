# FLOPO qualitative trait recognition on pxGPT Brassica

Update 29 October 2026: the proposed matched supervision and label-efficiency experiments have been run. See the [completed follow-up report](flopo-shape-experiments-results.md), including a separate fresh cotton transfer test.

Completed 28 October 2026. An independent human-labelled benchmark now replaces the need for manual photograph review. The existing models show a promising but exploratory benefit from flora annotations for whole-image leaf-shape recognition. They do not establish a reliable benefit for the primary hairiness endpoint, and the tested logical constraints add no consistent benefit. This evaluates the current supervision method; it does not establish that FLOPO annotations cannot help.

## Benchmark and evaluation

The [pxGPT Brassica v2.0.0 release](https://zenodo.org/records/22907554) supplies photographs, trait codebooks and human scores under CC BY 4.0. Its human references describe photo sets, not individually labelled images. Mature sets represent one plant; seedling sets may contain sibling plants. We used only human-derived references, not pxGPT narratives or model predictions. All 27,566 reference cells were crosschecked against the original human scores, and all 7,896 selected photographs passed their published checksums.

The frozen cultivar split assigns 184 photo sets to development and 415 to test, keeping repeated cultivars together across stages. Strict references require at least two raters and a majority greater than one half, excluding unassessable values and ordinal tie breaks. The primary endpoint averages hairy/glabrous AP within each eligible dataset, then averages datasets equally. Seedling contributes 44 hairy and 119 glabrous test sets; mature v1 contributes seven and 69. This gives **239 test sets from 173 cultivars**. Mature v2 has only two strict positive cases and is excluded from the primary average. AP measures ranking, not classification accuracy.

The primary view uses the existing leaf detector and five spatial tiles. Predictions are averaged over every photograph in a set; a missing detection contributes zero evidence and remains in the denominator. Detection succeeded on 4,567 of 7,896 photographs (57.8%). Three primary seedling sets have no leaf detection. Whole-image views are secondary. Shape preserves compound categories such as obovate/spatulate and excludes categories only partly represented by the current vocabulary. Its supported-class macro AP covers 182 test sets from 129 cultivars across three datasets; it is a restricted categorical task, not a complete set of phenotype truth values.

Both frozen encoders and all 38 primary checkpoints were evaluated, with three-seed probability ensembles for each trained arm. No model was selected or retrained using benchmark results. Thresholded hairiness metrics use strict development references only; otherwise a fixed threshold of 0.5 is used when development support is insufficient. Shape AP is threshold-free; the stored shape balanced accuracies use 0.5 and are not calibrated estimates.

## Primary hairiness results

| Supervision | FG-CLIP2 | BioCLIP2 |
|---|---:|---:|
| Baseline | 0.5414 | 0.5241 |
| Flora annotations | 0.5688 | 0.5375 |
| Image teacher | 0.7507 | 0.7756 |
| Teacher plus flora | 0.6602 | 0.6312 |
| Teacher plus flora plus constraints | 0.6508 | 0.6318 |
| Teacher plus flora plus shuffled constraints | 0.6646 | 0.6403 |
| Teacher plus shuffled profiles | 0.6672 | 0.6827 |

The FG-CLIP baseline is the existing pretrained initialization. The BioCLIP baseline is initialized by training-only ridge distillation from FG-CLIP logits; it is **not native BioCLIP zero shot**. Flora and teacher arms train the existing heads on their respective supervision sources. The constraint arm adds six supported marginal implications, not full OWL reasoning.

Differences below are AP percentage points. Intervals use 2,000 paired cultivar-cluster bootstrap draws, of which 1,999 retain the necessary classes. They are nominal 95% intervals without multiplicity correction and describe sampling uncertainty for the fixed trained ensembles, not uncertainty over training seeds. The first two contrasts were the declared primary comparisons; the remaining two were secondary controls.

| Contrast | FG-CLIP2 difference [95% CI] | BioCLIP2 difference [95% CI] |
|---|---:|---:|
| Flora minus baseline | +2.74 [-0.55, +6.40] | +1.34 [-1.25, +4.00] |
| Combined minus teacher | -9.06 [-14.03, -4.27] | -14.44 [-20.97, -7.79] |
| Constraints minus combined | -0.93 [-2.90, -0.19] | +0.07 [-0.26, +0.42] |
| Combined minus shuffled profiles | -0.71 [-4.15, +1.53] | -5.15 [-10.52, -0.44] |

Flora-only training gives small gains whose intervals include zero. Adding flora supervision to the teacher decreases hairiness AP in both encoders. Teacher-only performance shows that these images contain a learnable signal; the current flora supervision package does not improve it. The macro average should not hide rare-positive performance: BioCLIP flora-only seedling hairy AP is 0.269, approximately its 44/163 positive prevalence, and mature v1 hairy AP is 0.123. Strong glabrous AP alone is insufficient evidence of useful hair recognition.

## Secondary shape findings

Whole-image shape AP is more encouraging:

| Supervision | FG-CLIP2 shape AP | BioCLIP2 shape AP |
|---|---:|---:|
| Baseline | 0.5027 | 0.4865 |
| Flora annotations | 0.5136 | 0.5441 |
| Image teacher | 0.4695 | 0.4663 |
| Teacher plus flora | 0.5220 | 0.5036 |
| Teacher plus flora plus constraints | 0.5226 | 0.5021 |
| Teacher plus flora plus shuffled constraints | 0.5233 | 0.5067 |
| Teacher plus shuffled profiles | 0.4750 | 0.4628 |

Adding flora to teacher supervision increases whole-image shape AP by 5.25 points for FG-CLIP2 and 3.73 points for BioCLIP2. BioCLIP flora-only also improves over its baseline by 5.76 points. These are hypotheses for replication: the intervals below were calculated after inspecting the complete point estimates, are unadjusted, and the BioCLIP flora-only lower bound is very close to zero. The corresponding combined-versus-shuffled-profile intervals include zero. Detected-leaf shape gains are small or absent. Whole images may preserve useful information that the current detector or crop loses, but this experiment does not establish the cause.

All secondary task/view contrasts are reported here to avoid selecting only positive findings:

| Task and view | Contrast | FG-CLIP2 difference [95% CI] | BioCLIP2 difference [95% CI] |
|---|---|---:|---:|
| Shape, detected leaf | Flora minus baseline | -0.92 [-2.05, -0.02] | +0.72 [-0.29, +1.57] |
| Shape, detected leaf | Combined minus teacher | -0.46 [-1.59, +0.59] | +1.36 [-0.23, +2.38] |
| Shape, detected leaf | Constraints minus combined | -0.03 [-0.22, +0.02] | -0.03 [-0.28, +0.02] |
| Shape, detected leaf | Combined minus shuffled profiles | -0.40 [-2.18, +1.11] | +0.53 [-0.69, +1.80] |
| Shape, whole image | Flora minus baseline | +1.09 [-2.38, +6.05] | +5.76 [+0.04, +10.87] |
| Shape, whole image | Combined minus teacher | +5.25 [+0.69, +11.10] | +3.73 [+0.25, +8.47] |
| Shape, whole image | Constraints minus combined | +0.07 [-0.54, +0.61] | -0.15 [-0.98, +0.20] |
| Shape, whole image | Combined minus shuffled profiles | +4.70 [-0.70, +11.58] | +4.08 [-1.02, +8.77] |
| Hairiness, whole image | Flora minus baseline | -6.34 [-11.43, -1.22] | -3.06 [-7.46, +0.83] |
| Hairiness, whole image | Combined minus teacher | -6.60 [-11.04, -2.44] | -17.01 [-25.15, -6.82] |
| Hairiness, whole image | Constraints minus combined | -0.45 [-3.10, +1.07] | -0.03 [-0.89, +0.34] |
| Hairiness, whole image | Combined minus shuffled profiles | -0.85 [-7.86, +5.13] | -10.66 [-20.12, -3.90] |

The constraint contrasts offer no consistent benefit on either task. Whole-image hairiness also declines when flora is added to the teacher. The less restrictive reference sensitivity analysis and every individual seed are retained in the full results; its eligible datasets can differ from the strict analysis, so it is not an identical-population comparison.

## What can be claimed

We have completed the engineering and obtained independent qualitative-trait evaluation. There is conditional evidence that flora annotations can improve a particular shape-recognition setup. A general claim of annotation utility, an advantage of FLOPO normalization over raw flora text, and an additional reasoning benefit remain unestablished.

Several limits matter. The combined arm adds source supervision and scoped negative losses, while the shuffled-profile arm omits those negative losses. Their difference therefore cannot isolate label semantics cleanly. The BioCLIP baseline is distilled. The test domain is cultivated Brassica, and 284 Brassica tournefortii photographs occur in fine-tuning, so this is not genus-held-out transfer. The audit found no exact or near-duplicate candidates against 21,654 fine-tuning photographs, but foundation-model pretraining overlap is unknown. No conclusion follows about all visual traits, individual-image localization, or unseen genera.

## Next experiment

1. **Make shape recognition the next explicit hypothesis.** Select a small, adequately supported qualitative vocabulary from the source and benchmark codebooks. Preserve grouped categories and unknown labels. The current results motivate whole-image shape evaluation; choosing it now makes further work on this same test set exploratory. A confirmatory claim needs a new independent labelled cohort or a genuinely untouched test set.
2. **Isolate annotation utility and normalization.** Train matched raw-flora, FLOPO-normalized, and shuffled-label heads with identical images, source records, sampling, initialization, losses and schedules. Include a native encoder baseline and teacher-only control. First test normalized annotations without extra logical penalties; assess constraints separately after establishing a supervision benefit. Remove Brassica and synonyms from every training source if claiming genus transfer.
3. **Test annotation efficiency using existing human labels.** On a separately declared supervised track, compare human-only training with flora pretraining followed by the same small human-label budgets. Keep cultivar groups intact and reserve calibration and testing separately. A consistent improvement at low label budgets would demonstrate practical utility without requiring new manual annotations. Use a human-supervised head as a learnability control and report the learning curve, not a selected budget.
4. **Prioritize label support and visibility before more scale.** Quantify actual training exposure per trait and organ, and compare fixed whole-image and crop aggregation on development data. Investigate the weak-label/teacher conflict with matched losses. Expanding the ontology constraints or collecting more unlabelled images is a lower priority until this comparison succeeds.

No further training is needed to establish what the existing models do: that evaluation is complete. The next contribution should be a controlled test of why annotations help shape recognition and whether they reduce human-label requirements.

## Reproducibility and verification

The four inference shards completed successfully, all 168 downloaded output hashes were verified, and all 50 model/ensemble results and 100 view-specific prediction arrays are present. Ensemble arrays agree with the individual-seed averages within 8e-8. Secondary point estimates independently agree with the primary report's per-dataset metrics. Eleven focused tests pass. The pre-result scoring amendment strengthened shard identity validation and ensured strict-development threshold calibration without changing the primary target or metric.

- [Frozen design and completed execution record](flopo-pxgpt-evaluation.json)
- [Full metrics and individual seeds](../local-corpora/pxgpt-results-v1/results.json)
- [All exploratory secondary intervals](../local-corpora/pxgpt-results-v1/secondary-intervals.json)
- [Completion audit](../local-corpora/pxgpt-results-v1/completion-audit.json) and [audit script](../local-corpora/pxgpt-results-v1/completion_audit.py)
- [Benchmark preparation](../flopo2/vision/benchmark.py), [inference](../flopo2/vision/benchmark_infer.py), [scoring](../flopo2/vision/benchmark_score.py), and [secondary analysis](../flopo2/vision/benchmark_secondary.py)
- [Benchmark discovery and earlier assessment](flopo-existing-benchmarks.md)

Raw downloaded data and prediction artifacts are local, git-ignored files; the compact [result summary](flopo-pxgpt-results.json) records the report's estimates and hashes within the documentation tree.
