# Full weakly supervised trait experiment — 27 October 2026

Training and development evaluation completed on Orix. The larger experiment does **not establish a better trait recognizer or a benefit from FLOPO reasoning**. No model was selected. These are leaf-shape development results, not a validated 36-trait benchmark.

All 31 checkpoint and prediction hashes passed verification. Training job `347540` completed in 57m01s on four H200s; evaluation job `347621` completed in 2m43s on one H200. All jobs exited successfully. The 124 audit prediction arrays and 62 matched-control arrays are finite and their hashes match the evaluation manifest.

## Trait results

Rows report the ordinary mean-probability ensemble of three fixed seeds, except the pretrained baseline. AP measures ranking across images separately for each trait; top choice compares scores between shape classes and is a secondary metric. These are not species-recognition metrics.

| Model | Field macro AP | External macro AP | Field top choice | External top choice |
|---|---:|---:|---:|---:|
| Pretrained FG-CLIP 2 Large | 0.8793 | 0.4345 | 12/23 | 0/14 |
| Direct weak supervision | 0.7819 | 0.4382 | 9/23 | 0/14 |
| Adapted MIL | 0.7407 | 0.4382 | 13/23 | 0/14 |
| Adapted MIL + FLOPO hierarchy | 0.7384 | 0.4382 | 12/23 | 0/14 |
| Adapted MIL + FLOPO projection | 0.7407 | 0.4382 | 13/23 | 0/14 |
| Shuffled flora profiles | 0.6738 | 0.4382 | 8/23 | 0/14 |
| Frozen encoder MIL, cap 10 | 0.8699 | 0.4435 | 15/23 | 0/14 |
| Frozen encoder MIL, cap 50 | 0.8679 | 0.4435 | 14/23 | 0/14 |
| Frozen encoder MIL, cap 200 | 0.7905 | 0.4435 | 14/23 | 0/14 |
| Adapted MIL, cap 10 | 0.6550 | 0.4435 | 11/23 | 0/14 |
| Adapted MIL, cap 50 | 0.7079 | 0.4435 | 11/23 | 0/14 |

The references are a previously inspected, single-AI audit: 39 field crops and 17 external photographs. Only 17 field and 9 external images have singleton shape labels for AP; three shapes have both positive and negative examples in each dataset. The field singleton labels comprise 14 heart-shaped, two ovate and one oblong leaf. Allowed-set top choice uses 23 field and 14 external assessable images. Unknown and ambiguous labels are not turned into negative examples for AP. Literal shape categories are not a complete set of ontology truth values.

Fine-tuning reduced field AP relative to the matched pretrained baseline. At cap 200, adapted MIL, both FLOPO arms and shuffled profiles all have external ensemble AP 0.4382. Increasing the adapted-MIL cap from 10 to 50 to 200 raises field AP (0.6550, 0.7079, 0.7407), but all remain below pretrained 0.8793; external AP does not improve monotonically. This fixed-step experiment does not establish how a longer, converged fit would scale.

FLOPO adds only six supported marginal implications in this vocabulary. It changes predictions, but neither hierarchy penalties nor approximate projection improve external-original AP over MIL. The masked-external diagnostic changes from 0.7083 MIL to 0.7157 with either FLOPO arm; this small, previously inspected result does not establish a general reasoning benefit. This is not exact WMC or full OWL reasoning.

External shape scores also have a strong between-class bias: the pretrained model ranks oblanceolate first for all 17 images; the MIL ensemble ranks oblanceolate first for 12, lanceolate for three and oblong for two. This explains why modest per-trait AP can coexist with zero correct top choices. The data do not establish that calibration alone would solve trait recognition.

All ensemble metrics and individual-seed AP values, including masked external images, are retained in [the diagnostic record](flopo-full-diagnostic.json); full individual metrics are in `local-corpora/full-diagnostic-v1/diagnostic.json`. Seed variability is substantial: frozen cap-200 field AP ranges from 0.7546 to 0.8949. An ensemble AP is not the arithmetic mean of individual AP values.

## Training signal and controls

The download contains 52,011 images from 28,250 observations and 333 taxa. Split and organ filtering yield 10,110 regions, including 8,152 training regions from 192 taxa. Usable flora assertions supervise 32 traits over 3,423 observations and 157 taxa. Four context-dependent traits are intentionally excluded from this crop supervision; eight supervised traits have fewer than five source taxa. These are source assertions, not image-level trait labels.

A deterministic replay of the MIL sampler shows 9,600 crop presentations per run, including 8,000 during encoder adaptation. At cap 200 this covers only 2,594–2,695 distinct regions during encoder updates across seeds. A typical taxon receives 15 sampled source assertions. In seed 20261026, fruit hairiness has only six source-assertion presentations. Thus the download size substantially overstates the direct training signal for rare traits. Details are in `local-corpora/flopo-full-v1/sampling-audit.json`.

The matched erasure control compares the same whole photograph before and after gray-filling its detected organ box. Across the 200 reserved regions and their matching non-context trait scores, average probability decreases by 0.0288 pretrained and 0.0465 with adapted MIL. This demonstrates sensitivity to the erased region, not correct trait recognition; gray erasure is artificial and the boxes are not verified segmentations. The older crop-versus-erased-whole-photo comparison changes two things and is not used for causal interpretation.

The shuffled-profile arm is a negative control, not an exactly matched image-exposure experiment: reassigning profiles changes eligible bags (150 source-supervised taxa and 3,477 observations in seed 20261026 versus 157 and 3,423 for MIL). Similar external results are therefore evidence against a demonstrated profile benefit, not a precise causal effect estimate.

Field audit taxa, genera and exact image hashes are absent from training. External exact names do not overlap, but genus Acer does. The additional unseen-genus stratum has the same assessable metrics because the excluded examples do not contribute usable labels. Exact-name checking does not resolve synonyms; foundation-model pretraining overlap is unknown.

## What follows from this experiment

The immediate technical targets are uneven trait exposure, preserving pretrained visual rankings during adaptation, and separating per-trait evidence from between-trait score calibration. A controlled follow-up should compare trait-balanced sampling and an adaptation-strength/duration ablation with the same pretrained and frozen-head baselines, retaining missing traits as unknown. These are proposed tests, not established solutions. No new training job was launched from these development results.

The 1,500-image blinded review packet is ready (700 validation, 800 test), but remains unannotated. Independent image-level trait references are necessary to determine whether changes help beyond the small shape audit. They are for evaluation and validation-only calibration; training can remain weakly supervised using iNaturalist taxa and flora profiles.

Protocol: [full experiment](flopo-full-experiment.json). Raw outputs: `local-corpora/full-runs-v1/` and `local-corpora/full-diagnostic-v1/`. Review interface: `local-corpora/full-trait-review-v1/review.html`. Do not distribute its private join table to reviewers.

Diagnostic artifact SHA-256: `d0825a09c64f56e0e0930e3692ec327803bc597cea7a414845e73453d378bdb1`.
