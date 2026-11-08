# FLOPO matched supervision and annotation efficiency experiments

Completed 29 October 2026: 120 matched shape-training runs, a human-label budget study, and a separate cotton hairiness transfer test. The matched study does not establish that FLOPO-normalized flora text improves qualitative leaf-shape recognition over raw flora text, shuffled supervision, or native text–image predictions. It also does not establish a reduction in human-label requirements. Human-supervised fitting improves performance substantially, demonstrating that the representation and target categories support learning.

This study follows the exploratory whole-image shape gains in the [first pxGPT evaluation](flopo-pxgpt-results.md). It tests a new, controlled adapter setup. Its results bound that setup and do not invalidate the earlier measurements or establish that every use of FLOPO is ineffective.

## Matched source supervision

Both FG-CLIP2 and BioCLIP2 use their own frozen image and text encoders. Four arms share the same representation and output prompts: native predictions, raw source-phrase supervision, FLOPO-normalized phrase supervision, and shuffled normalized phrase supervision. BioCLIP's baseline here is native; it does not use the earlier FG-CLIP ridge distillation.

The common source cohort contains 186 leaf-shape assertions from 104 taxa, attached to 2,499 observations and 3,416 leaf regions. All Brassicaceae, including Brassica and potential synonyms within that family, are excluded before fitting. Raw and normalized arms see the same assertions and images. Normalization replaces each selected phrase with its canonical shape label or disjunction. The shuffled arm permutes these targets while retaining the same sampling and loss. Unmentioned traits are not converted into negative labels.

Each arm uses a rank-64 residual linear image adapter followed by unit normalization. Source training samples four observations per assertion and matches the adapted bag representation to the native text embedding, with an identical displacement penalty in every source-supervised arm. All source arms use 1,500 steps and the same random sampling for a given seed. Prediction uses canonical shape prompts. Whole-image features are averaged within benchmark photo sets before normalization; this differs from the earlier spatial-head probability averaging and is fixed for every arm here.

Event eligibility already comes from the normalized inventory. Consequently, this tests the value of canonicalizing the same selected phrases, not the entire raw-text extraction pipeline or a benefit of ontology identifiers alone. No new logical penalty is included.

## Shape recognition without human training labels

The strict pxGPT test cohort contains 182 photo sets from 129 cultivars. Compound categories such as obovate/spatulate remain grouped. The endpoint averages supported-category AP within datasets and then averages the three datasets equally. Scores below are three-seed probability ensembles.

| Source supervision | FG-CLIP2 macro AP | BioCLIP2 macro AP |
|---|---:|---:|
| Native | 0.4817 | 0.4865 |
| Raw | 0.4826 | 0.4870 |
| Normalized | 0.4740 | 0.4945 |
| Shuffled | 0.4767 | 0.4903 |

Differences are AP percentage points with paired cultivar-bootstrap 95% intervals. Of 2,000 draws, 1,997 retained the required classes. These nominal intervals are unadjusted for multiple comparisons and conditional on the trained ensembles. The test cohort was inspected in the previous experiment, so these follow-up results remain exploratory.

| Contrast without human labels | FG-CLIP2 difference [95% CI] | BioCLIP2 difference [95% CI] |
|---|---:|---:|
| normalized minus native | -0.78 [-4.16, +1.38] | +0.80 [-1.64, +3.41] |
| normalized minus raw | -0.87 [-3.29, +0.97] | +0.75 [-1.62, +3.70] |
| normalized minus shuffled | -0.27 [-2.38, +1.74] | +0.42 [-1.29, +2.84] |
| raw minus native | +0.09 [-2.55, +2.46] | +0.05 [-2.14, +1.83] |
| shuffled minus native | -0.51 [-3.58, +1.12] | +0.37 [-1.28, +1.99] |

No comparison establishes an annotation-normalization benefit. Training ran and changed the predictions: the source objective declined in all three trained arms for both encoders. The negative finding is therefore not explained by a skipped or inactive optimization step.

## Human annotation efficiency

Three predetermined seeds select nested budgets of 8, 16, 32 and 55 cultivars from the original development partition. The largest budget includes 71 human-labelled photo sets. Nine additional development cultivars are reserved and unused for fitting. Every occurrence of a cultivar stays in its partition. All four arms receive exactly the same labels at each seed and budget. The native arm with human labels is the human-only control.

Each budget starts from its own arm's source-trained initialization and runs 400 fixed supervised steps. Labels are strict human shape references; stage-specific grouped categories are retained in the categorical loss. No checkpoint, learning rate, threshold or budget is selected using test performance. The same already-inspected test cohort is used throughout.

### FG-CLIP2

| Labelled cultivars | Human only | Raw flora then human | FLOPO-normalized then human | Shuffled then human |
|---|---:|---:|---:|---:|
| 8 | 0.5670 | 0.5903 | 0.5485 | 0.5317 |
| 16 | 0.5884 | 0.6191 | 0.6061 | 0.6084 |
| 32 | 0.5802 | 0.5952 | 0.5917 | 0.5798 |
| 55 | 0.6073 | 0.6288 | 0.6392 | 0.6226 |

### BioCLIP2

| Labelled cultivars | Human only | Raw flora then human | FLOPO-normalized then human | Shuffled then human |
|---|---:|---:|---:|---:|
| 8 | 0.6245 | 0.6320 | 0.6199 | 0.5676 |
| 16 | 0.6231 | 0.6234 | 0.6118 | 0.5914 |
| 32 | 0.6437 | 0.6478 | 0.6595 | 0.6393 |
| 55 | 0.6183 | 0.6250 | 0.6180 | 0.6399 |

The following summary averages AP differences equally over all four positive label budgets. It does not select the most favorable budget.

| Mean difference across budgets | FG-CLIP2 difference [95% CI] | BioCLIP2 difference [95% CI] |
|---|---:|---:|
| normalized minus native | +1.07 [-2.14, +4.24] | -0.01 [-1.15, +1.13] |
| normalized minus raw | -1.20 [-3.16, +1.26] | -0.48 [-1.76, +0.62] |
| normalized minus shuffled | +1.08 [-3.47, +5.32] | +1.78 [-0.40, +4.42] |
| raw minus native | +2.27 [-1.09, +5.25] | +0.47 [-0.44, +1.42] |

All these intervals include zero. Human-only fitting with eight cultivars reaches 0.5670 AP for FG-CLIP2 and 0.6245 for BioCLIP2, versus 0.4817 and 0.4865 without human fitting. Additional source supervision has no consistent advantage over that control. The curves are not monotonic, so a selected favorable budget would give a misleading impression of annotation efficiency.

## Fresh external transfer test

[CotLeaf-X](https://doi.org/10.25919/eqhx-1x73), released with [HairNet2](https://doi.org/10.1186/s13007-024-01149-8), provides expert scores for individual cotton leaf microscopy images under CC BY-NC-SA 4.0. A fixed hash sample selected 64 images from each of its four anonymized genotype groups, independently of scores and predictions. All 256 source files matched the server-advertised byte lengths and were decoded to lossless PNG. The sample and score mappings were fixed before inference.

The overlap screen compared the images to 21,654 fine-tuning photographs. It found six <=4-bit dHash candidates, all excluded conservatively, and no identical decoded images within the sample. These candidates are not confirmed duplicates. No Gossypium photographs occur in that fine-tuning manifest. Foundation-model pretraining overlap remains unknown.

Expert scores use different ordinal scales in populations A and B. The declared task is relative **high versus low hairiness**, not glabrous versus hairy: A uses low <=1 and high >=3; B uses low <=3 and high >=5. Intermediate scores are excluded. After the overlap screen, 250 images remain, of which 170 meet these endpoint definitions: 85 in each population. Their positive counts are 36 and 55. The endpoint is mean AP across the two populations using the model's generic leaf-hairy score.

All 38 earlier checkpoints were scored without fitting on cotton, with three-seed ensembles for trained arms. These are the earlier spatial heads, not the new shape adapters. In particular, the BioCLIP baseline in this table retains its training-only FG-CLIP ridge initialization; the native BioCLIP baseline belongs to the matched shape study above.

| Existing supervision | FG-CLIP2 high-hairiness AP | BioCLIP2 high-hairiness AP |
|---|---:|---:|
| Baseline | 0.8323 | 0.8603 |
| Flora only | 0.8290 | 0.9068 |
| Image teacher | 0.9533 | 0.9472 |
| Teacher plus flora | 0.8966 | 0.9243 |
| Teacher plus flora plus constraints | 0.8867 | 0.9195 |
| Shuffled constraints | 0.8942 | 0.9227 |
| Shuffled profiles | 0.9465 | 0.9360 |

Flora-only supervision improves BioCLIP by 4.65 AP points and changes FG-CLIP by -0.33 points. Adding flora to the teacher decreases AP by 5.66 and 2.29 points respectively. The constraint arm also declines relative to combined training. The shuffled-profile loss mismatch documented in the earlier study still applies, so this control does not isolate label semantics perfectly.

These are descriptive findings. The release's plant-number and leaf identifiers collapse to four anonymized groups, preventing reliable reconstruction of independent plants. Consequently, no image-IID confidence intervals are reported. The BioCLIP gain is narrower external evidence that flora supervision can help phenotype recognition; it does not establish a general benefit or an advantage of FLOPO normalization itself.

A fresh shape-specific confirmation remains uncompleted because a suitable second independently labelled cohort has not been obtained. The [MORPHYLL paper](https://palaeo-electronica.org/content/2018/2114-database-of-fossil-leaves) requires registration for traits/images and its portal was inaccessible. [Indic-Leaf](https://github.com/vamsidharmuthireddy/Indic-Leaf-Dataset) supplies species-level attributes, which would not provide independent specimen-level shape truth. The cotton test is a separate hairiness/domain-transfer result, not a replacement for shape replication.

[External protocol, overlap audit and completed jobs](flopo-cotleaf-evaluation.json), [full external metrics and seeds](flopo-cotleaf-results.json), and [inference code](../flopo2/vision/cotleaf_infer.py) preserve the evidence.

## Interpretation

The requested matched training and label-efficiency experiments are complete, along with the separate fresh cotton transfer test. A fresh shape-specific replication remains outstanding for lack of suitable accessible labels. The evidence currently supports feasibility of learning these qualitative traits with existing human annotations. It does not yet support a general FLOPO-normalization advantage or lower human-label requirements. The earlier whole-image shape gains remain useful exploratory observations, with their original model and loss qualifications.

This result is specific to the available assertions, frozen encoders, adapter, bag aggregation, prompts and training schedule. It is not a universal negative result about FLOPO. In particular, canonicalizing selected phrases is only one possible use of the ontology; it does not test whether ontology-based extraction recovers more usable assertions, improves provenance, or transfers rare labels through reliable logical relationships. Further work should address source-label fidelity and trait visibility before adding more constraints or scaling this unchanged training recipe.

## Verification and artifacts

Both full training shards completed successfully in approximately two minutes each, producing all 120 planned model runs. The two-encoder preflight verified 16 small runs, shared sampling and active gradient updates. The scorer verified the full grid, every model and prediction hash, exact human-training row lists, and equal source-sampling audit hashes across label arms. All frozen input hashes and the exclusion of Brassicaceae were checked locally. The two cotton inference shards also completed successfully, and their image identities, all 38 checkpoint identities and all prediction hashes were verified before scoring. Sixteen focused tests cover split integrity, grouped labels, metrics, incomplete artifacts, and overlap-audit validation.

- [Frozen experiment protocol](flopo-shape-experiments.json)
- [All results, seed scores, budget contrasts and uncertainty](flopo-shape-results.json)
- [Runtime and completion record](../local-corpora/shape-experiments-v1/workflow.json) and [completion audit](../local-corpora/shape-experiments-v1/completion-audit.json)
- [Preparation](../flopo2/vision/shape_experiments.py), [training](../flopo2/vision/shape_experiments_train.py), and [scoring](../flopo2/vision/shape_experiments_score.py)
- [Focused tests](../tests/vision/test_shape_experiments.py)

Raw source data, features, models and predictions remain under the git-ignored `local-corpora/shape-experiments-v1/` directory and the corresponding Orix experiment directory. The protocol and compact numerical results are retained in the documentation tree.
