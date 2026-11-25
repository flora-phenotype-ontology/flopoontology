# Trait recognition from photographs: tests of 21 November 2026

Three sets of small tests on the pilot data (iNaturalist photographs, traits of the species from the
floras as labels, no labels of our own). Each test changes one thing against the regime used so far and is
scored on genera the model never saw. This file records what was run, what came out, and what follows.

Earlier rounds are in `docs/inaturalist-trait-learning.md` (design) and in the result files of October 2026.

## Setting

- **Photographs:** 1.01 million research-grade iNaturalist photographs of 33,000 species; embeddings of the
  frozen BioCLIP 2 image model.
- **Labels:** for each species and trait, the set of values that any flora states (`pilot-labels-v3.tsv`,
  60,000 species). Every photograph of a species takes the label of the species.
- **Baseline regime:** one linear classifier per trait; loss = minus the log of the probability mass on the
  stated set; equal weight per species and per class.
- **Held-out genera:** five rotations; each genus is held out once. All numbers below are for genera the
  model did not see.
- **Two tests, neither labelled by us:**
  - *agreed species*: species for which two or more floras state one value each, and the same one;
  - *observers*: the value an iNaturalist observer entered for a single observation.
- **Measure:** balanced accuracy (mean over values of the share recognised).

Caution for later rounds: the WFO corpus repeats the text of other floras. When WFO is counted as a flora,
"two floras agree" is mostly WFO plus its own source (9,392 of 11,085 flower-colour cases) and the test
becomes a one-flora test. The agreed-species test here uses the statement file from before WFO was
extended (`agreed-v3.tsv`).

## 1. Colour value space in training: no gain

Question: does it help to tell the model which colours are near each other, and that "X to Y" is a range?

Colour distances come from FLOPO itself: every colour class is a set of ISCC-NBS blocks, every block has a
central Munsell notation, and the centres give CIEDE2000 distances (`flopo2/traitvision/colour_space.py`).

| Training target (flower colour) | Agreed species (n = 1,428) | Observers (n = 12,160) |
|---|---|---|
| stated set, as before | 0.689 | 0.662 |
| + ends of "X to Y" statements, read as "X or Y" | 0.682 | 0.652 |
| + colours between the two ends | 0.688 | 0.651 |
| + partial credit for near colours, narrow (σ = 8) | 0.680 | 0.670 |
| + partial credit, medium (σ = 12) | not run on this test | 0.600 |

Repeats differ by about 0.001. Fruit colour behaves the same (0.296 before, 0.300 with ranges, 0.236 with
near colours).

Side results:

- **Dropped statements.** "X to Y" colour statements have no value term (the two ends are in
  `qualitative_value_relation`), so the first labels left them out: about 11% of flower-colour statements;
  4,000 species gain a colour. They are now extracted (`pilot-assertions-v4.tsv`, columns `rel`,
  `rel_from`, `rel_to`).
- **"To" is a range where it can be one.** For species stated "X to Y" with a basic colour in between
  (yellow to red), 28% of the photographs fall on the colour in between; for species stated "X or Y" with
  the same ends, 13%. Where there is no colour in between, the two readings look the same in photographs.

## 2. Measuring colour instead of learning it: does not reach the trained model

Question: if the flower can be found, is its colour not simply the average of its pixels?

Each pixel was given the nearest ISCC-NBS block; the block gives the FLOPO colour class
(`colour_measure.py`, `segment_colour.py`). Test: the 12,000 observations with an observer's colour.

| Method | Balanced accuracy |
|---|---|
| mean colour of the detected flower box, looked up | 0.30 |
| pixels in the middle of the box, minus the background of the photograph, looked up | 0.46 |
| block histogram of the box, naming learned from the floras | 0.44 |
| block histogram inside the petal outline (SAM, prompted by the box), naming learned from the floras | 0.46 |
| trained classifier on the whole photograph | 0.66 |
| trained classifier and measured colour together | 0.52 |

Why:

- **Boxes are mostly not petals.** In boxes of white flowers, 43% of the central pixels are leaf greens.
  Outlines remove much of this (the outline covers about half of a box), and the score barely moves, so
  background is not the main cause.
- **White in photographs is tinted.** White petals register as yellowish, greenish or bluish white. The
  standard files these blocks under yellow, green and blue at its first level. 8% of the pixels of white
  flowers fall in "white".
- **Botanical pink is the standard's purple.** 47% of the petal pixels of flowers that observers call pink
  fall in the purple region, 13% in pink.
- **Where name and standard agree, measuring works.** 68% of the petal pixels of yellow flowers are yellow.

## 3. Training regime with weak labels: 17 single changes

Run on all eight pilot traits (`regime_tests.py`). Change in balanced accuracy against the baseline, mean
over the traits; "agreed" and "observers" are the two tests.

| Change | Agreed | Observers | Reading |
|---|---|---|---|
| **Where the ceiling is** | | | |
| trained on observers' labels instead (4 traits), first version | −0.25 | −0.04 | **superseded by section 4**: this version gave the observer's value to every photograph and was under-trained |
| 10% of the training species | −0.14 | −0.13 | |
| 30% of the training species | −0.03 | −0.05 | the curve still rises at 100% |
| only species where 2+ floras agree | −0.12 | −0.10 | quantity beats purity |
| **Which photographs carry the label** | | | |
| only photographs with a detected box of the organ | −0.035 | −0.033 | same as dropping as many photographs at random (−0.030, −0.032) |
| second round on the half of each species' photographs that fit the label best | −0.002 | −0.002 | |
| second round, photographs weighted by fit | −0.018 | −0.011 | |
| loss on the mean of 8 photographs of a species | **+0.017** | −0.001 | better on 7 of 8 traits |
| **Which labels to trust** | | | |
| only species with one stated value | −0.003 | −0.003 | |
| target = share of floras stating each value | **+0.008** | −0.001 | better on 7 of 8 traits |
| noise-tolerant loss | −0.018 | −0.012 | |
| target mixed with the model's own prediction | +0.002 | +0.001 | |
| **Which model** | | | |
| one hidden layer | **+0.039** | −0.004 | better on 8 of 8; leaf arrangement +0.09, spines +0.14 |
| one hidden layer shared by the traits of a job | +0.034 | −0.006 | sharing adds nothing to the hidden layer |
| equal weight per genus | −0.011 | −0.014 | |
| no class weights | −0.183 | −0.147 | class weights are necessary |
| **At test time** | | | |
| mean log probability over the photographs | +0.003 | | |
| the 3 most confident photographs | +0.009 | | mixed |

Baseline per trait (agreed / observers): flower colour 0.689 / 0.661; fruit colour 0.301 / 0.361; habit
0.904 / 0.695; inflorescence 0.575 / none; leaf arrangement 0.619 / 0.499; simple or compound leaf
0.885 / 0.631; leaf margin 0.738 / 0.554; spines 0.612 / 0.773. Tests with few cases move by several
points between runs (spines 371 species, 230 observations; leaf margin 376 observations).

### Combination of the three changes that helped

Three repeats with different random seeds; all eight traits; mean balanced accuracy.

| Regime | Agreed species, mean of 8 traits | Observers, mean of 7 traits |
|---|---|---|
| baseline | 0.667 | 0.596 |
| hidden layer | 0.702 | 0.592 |
| loss over 8 photographs | 0.683 | 0.595 |
| targets from the share of floras | 0.673 | 0.595 |
| hidden layer + loss over 8 photographs | **0.709** | 0.590 |
| hidden layer + targets from the share of floras | 0.698 | 0.596 |
| all three | 0.700 | 0.590 |

Per trait, agreed species (baseline → hidden layer + loss over 8 photographs): flower colour 0.689 → 0.696;
fruit colour 0.302 → 0.334; habit 0.903 → 0.916; inflorescence 0.580 → 0.596; leaf arrangement
0.620 → 0.733; simple or compound leaf 0.892 → 0.907; leaf margin 0.739 → 0.765; spines 0.613 → 0.726.
Repeats differ by at most 0.013 on this test.

- The hidden layer and the loss over photographs add up; the targets from the share of floras do not add
  to them (and lower leaf margin, 0.765 → 0.691).
- On the observers' test nothing gains on average. For flower colour the combination is lower there
  (0.661 → 0.638), while the loss over photographs alone, on the linear classifier, is the best single
  setting for flower colour on both tests (0.701 and 0.671).

## 4. Classifiers trained on observers' labels (correction of the first "ceiling" test)

The first version gave the observer's value to every photograph of the observation and trained briefly. An
observer labels the observation, not a photograph. Redone with the label on the observation
(`observer_tests.py`, job 407325); test = observers' values in held-out genera. The labelled observations
have one or two photographs here (at most two were downloaded; 60% have two).

| Trained on | Flower colour | Habit |
|---|---|---|
| observers' values, value on every photograph, linear | 0.656 | 0.682 |
| the same, hidden layer | 0.675 | 0.729 |
| loss on the observation (mean of its photographs), hidden layer | 0.671 | 0.728 |
| loss on the better photograph of the observation, hidden layer | 0.676 | 0.722 |
| only observations with one photograph, hidden layer | 0.629 | 0.702 |
| only photographs with a detected flower box, hidden layer | 0.676 | – |
| flora labels on 1 million photographs, linear (baseline of section 3) | 0.661 | 0.695 |
| **Same observations, species with one stated value** (4,972 / 982 photographs) | | |
| observers' values, linear / hidden layer | 0.595 / 0.602 | 0.594 / 0.596 |
| flora values, linear / hidden layer | 0.478 / 0.507 | 0.524 / 0.550 |

- With proper training, about 10,000 observer-labelled observations do as well as or better than a million
  flora-labelled photographs **on the observers' test**. The earlier statement that they are worse was wrong.
- On identical photographs the observer's value is the better label by about 0.10. Part of this is that the
  test uses observers' values; on the agreed-species test the comparison has not been rerun.
- Treating the observation as a bag, or keeping only photographs with a flower box, changes little here.
  With at most two photographs per observation this data cannot show how much unlabelled-organ photographs
  cost in observations with many photographs.
- The flora labels of all values of a species on few photographs train badly with the present class
  weights (0.17–0.28 for flower colour): a species with a rare value in its set gets the weight of the rare
  value. With a million photographs this does not show; it should be fixed before small-data runs.
- Leaf traits have too few labelled observations (136–726) for a conclusion.

## 5. Photographs per observation: which photograph shows the organ

The download took only the first two photographs of every observation (`inat_select.py`, `PHOTOS = 2`).
Checked on labelled observations through the iNaturalist API (photo counts for 4,023 observations) and by
downloading every photograph of 1,023 of them and running the organ detector (box score ≥ 0.3;
`~/tmp/flopo-trait-vision/obsphotos/`, ORIX job 407364).

- **Photographs per observation:** one 40%, two 29%, three or more 30–36% (flower colour, fruit colour,
  habit; leaf margin 34%). A third of the observations have photographs that were never fetched.
- **Flower colour (800 observations):** a flower is found in 90% of first photographs, 87% of second, 82% of
  third, about 73% of later ones. In observations with two or more photographs, one third have a flower in
  some photographs and not in others. The flower is only in photograph 3 or later in 3% of the observations
  with three or more.
- **Fruit colour (223 observations):** a fruit is found in 26% of first photographs and 19% of second. With
  only the first two photographs, 33% of the observations show a detected fruit; with all photographs, 41%.
  In observations with three or more photographs, the fruit is only in photograph 3 or later in 24%, and in
  no photograph in 38% (the detector misses fruits, or the observer described a fruit that is not shown).
- These observations were labelled by people who looked at that organ, so the organ is more often present
  here than in the training photographs, where the label comes from the species.

So the value of an observation holds for some of its photographs only; for flowers mostly the first, for
fruits a minority of all photographs and often a late one.

## 6. All photographs of an observation, and the organ at both ends

Our 642,324 observations have 548,314 photographs beyond the first two (1.56 million in all;
`inat_rest.py`, combined list `inat-photos-v3-all.tsv`). For the 26,698 observations with an observer's
label, all photographs were embedded and searched for organs.

**Existing flora-trained models, photographs chosen at test time only** (`allphotos_test.py`; balanced
accuracy against observers' labels):

| Trait (observations) | first two | all | organ photographs, else all |
|---|---|---|---|
| leaf margin (376) | 0.554 | 0.584 | 0.619 |
| leaf complexity (136) | 0.631 | 0.664 | 0.667 |
| habit (4,690) | 0.695 | 0.700 | 0.700 |
| flower colour (12,162) | 0.661 | 0.657 | 0.662 |
| flower colour, flower in some photographs only (2,240) | 0.660 | 0.659 | 0.687 |
| fruit colour (197) | 0.361 | 0.351 | 0.362 |
| leaf arrangement (726) | 0.499 | 0.487 | 0.497 |
| spines (230) | 0.773 | 0.750 | 0.762 |

**Trained on observers' labels, one bag per observation** (`observer_allphotos.py`, held-out genera,
3 seeds; training choice -> test choice):

| Trait | head | first two -> first two | all -> all | organ -> organ |
|---|---|---|---|---|
| leaf margin | MLP | 0.605 | 0.710 | 0.737 |
| leaf margin, leaf in some photographs only (156) | MLP | 0.524 | 0.733 | 0.779 |
| flower colour | MLP | 0.672 | 0.675 | 0.673 |
| flower colour, flower in some only (693) | MLP | 0.718 | 0.707 | 0.719 |
| habit | MLP | 0.729 | 0.732 | 0.732 |
| spines | linear | 0.845 | 0.851 | 0.863 |
| fruit colour (217) | linear | 0.378 | 0.385 | 0.380 |
| leaf arrangement | linear | 0.486 | 0.457 | 0.455 |

**Flora labels on the full set** (`allphotos_train.py`, 1.56 million photographs, MLP head with one bag per
species, held-out genera, one seed; the same choice of photographs in training and test):

| Trait | test | first two | all | organ photographs, else all |
|---|---|---|---|---|
| flower colour | agreed species (1,428) | 0.699 | 0.712 | 0.700 |
| flower colour | observers (12,162) | 0.638 | 0.649 | 0.651 |
| leaf margin | agreed (1,149) | 0.754 | 0.750 | 0.767 |
| leaf margin | observers (376) | 0.529 | 0.577 | 0.583 |
| leaf arrangement | agreed (456) | 0.733 | 0.729 | 0.721 |
| leaf arrangement | observers (726) | 0.500 | 0.516 | 0.524 |
| leaf complexity | agreed (1,385) | 0.907 | 0.909 | 0.901 |
| leaf complexity | observers (136) | 0.644 | 0.662 | 0.658 |
| fruit colour | agreed (610) | 0.330 | 0.337 | 0.328 |
| fruit colour | observers (197) | 0.401 | 0.395 | 0.425 |
| spines | agreed (371) | 0.722 | 0.692 | 0.739 |
| spines | observers (230) | 0.737 | 0.740 | 0.730 |
| habit | agreed (2,636) | 0.914 | 0.918 | 0.918 |
| habit | observers (4,690) | 0.697 | 0.699 | 0.699 |
| inflorescence | agreed (1,225) | 0.595 | 0.605 | 0.604 |

With flora labels the gain from more photographs is small on agreed species (a species already has many
photographs, so one more per observation adds little) and larger on single observations, where the later
photograph is often the only one that shows the organ (leaf margin 0.529 -> 0.583, flower colour
0.638 -> 0.651). Differences near 0.01 are within the spread between seeds.

Leaf traits gain much from the later photographs and from keeping only the photographs with a leaf.
Flower colour and habit were already served by the first two photographs. Fruit colour does not move,
because the fruit detector does not work:

* In 90 of 223 fruit-labelled observations no fruit was found in any photograph; in about 14 of 20
  inspected the fruit is plainly visible.
* Grounding DINO often answers "a flower a fruit" for one box. `detect.py` filed these under flower.
  Counting them as fruit finds a "fruit" in 91% of fruit-labelled observations, and in 90% of
  flower-labelled ones: the detector finds the reproductive structure but does not say which it is.
  A clean "a fruit" answer: 56% of fruit-labelled, 33% of flower-labelled observations.
* More words in the prompt (berry, seed pod, nut) and a smaller size limit do not separate better; nor
  does the image model's own fruit-versus-flower prompt on the whole photograph (58% against 37%).

A fruit-versus-flower decision per box therefore has to be learned. A label-free source exists:
iNaturalist's phenology annotations (flowering, fruiting, budding) on observations.

## 7. Flora labels and observers' labels together

`joint_train.py`: all photographs, MLP head, one bag per species for the flora labels and one bag per
observation for observers' labels; the observation bags together weigh 0.3 times the species bags. Held-out
genera, one seed. Balanced accuracy on agreed species / on observers' labels:

| Trait | flora only | observers only | both (0.3) |
|---|---|---|---|
| flower colour | 0.712 / 0.649 | 0.631 / 0.639 | 0.694 / 0.680 |
| habit | 0.918 / 0.699 | 0.830 / 0.715 | 0.916 / 0.717 |
| leaf margin | 0.767 / 0.583 | 0.535 / 0.745 | 0.764 / 0.691 |
| leaf arrangement | 0.721 / 0.524 | 0.388 / 0.462 | 0.680 / 0.562 |
| spines | 0.739 / 0.730 | 0.524 / 0.853 | 0.778 / 0.799 |
| fruit colour | 0.337 / 0.395 | 0.152 / 0.391 | 0.311 / 0.429 |

(Leaf complexity has too few observer labels: two folds had no observer training set.) Adding observers'
labels raises agreement with observers for every trait (by 0.02 to 0.11) and costs 0 to 0.04 on agreed
species, except spines, which gain on both. Weights of 1 and 3 cost more on agreed species and add nothing
on observers. Observers' labels alone do not carry over to the flora test: they cover few species.

## 8. Fruit or flower per photograph, from iNaturalist phenology annotations

`inat_phenology.py` fetched the phenology annotations of our 642,324 observations: 113,612 are annotated
(79,208 flowering, 26,734 fruiting, 20,389 budding). `phenology_head.py` trains a head on the frozen
embeddings with one bag per observation (maximum over its photographs), every genus held out once. Area under
the curve on held-out observations: flowering 0.956, fruiting 0.857, budding 0.712. The fruiting score passes
0.5 in 85% of observations annotated fruiting only and in 17% of those annotated flowering only (the
detector's clean "a fruit": 56% and 33% on the fruit- and flower-labelled observations). Scores for all 1.56
million photographs: `phenology-scores.npz`.

Fruit colour with this score choosing the photographs (`allphotos_train.py --pheno`, same choice in training
and test): agreed species 0.355 (threshold 0.5) and 0.328 (0.3) against 0.337 with all photographs; observers
0.371 and 0.405 against 0.395. No gain: choosing the right photograph is not what limits fruit colour.

### Colour scored by distance

`colour_score.py` scores a colour prediction by its distance from the stated colour in the colour value space
(per true colour, then averaged): `near` counts a prediction within 15 units as right, `skill` is
1 - distance / distance of the same predictions dealt out at random. All photographs, flora labels:

| Trait, test | exact | near | mean distance (chance) | skill |
|---|---|---|---|---|
| flower colour, agreed species | 0.704 | 0.743 | 6.4 (22.2) | 0.710 |
| flower colour, observers | 0.651 | 0.743 | 7.0 (21.4) | 0.674 |
| fruit colour, agreed species | 0.339 | 0.452 | 15.9 (22.1) | 0.280 |
| fruit colour, observers | 0.399 | 0.468 | 13.4 (22.4) | 0.404 |

Near misses explain a part of the low fruit-colour score (0.34 -> 0.45), not most of it: the predictions are
only 28% closer to the stated colour than random ones, against 71% for flowers. In the flora test 41% of the
species are "brown" (dry fruits); the model does not over-predict green, so unripe fruit is not the main cause.

## What the tests say

1. **Label for label, observers' values are better than flora values** (section 4): on the same
   photographs they give 0.60 against 0.48–0.51 for flower colour, and 10,000 labelled observations match a
   million flora-labelled photographs on the observers' test. The flora labels win by number and by the
   traits they cover. More labelled species still helps; cleaner flora labels with fewer species do not.
2. **Choosing photographs does not help**, whether by detector, by the model itself or by text prompts
   (earlier round). Pooling over a species' photographs in the loss does, a little.
3. **A small non-linear classifier is the largest single gain**, and it is largest for the traits that were
   weakest (arrangement, spines).
4. **The gains show on the species test, not on the observers' test.** The observers' test stays where a
   plain look-up of the flora also lands (0.68 for flower colour, 0.71 for habit): it measures the
   disagreement between observers and floras as much as it measures the model.
5. **Colour naming is not a colour-space problem.** Neither distances between colour classes nor measured
   pixels improve on what the image model already learned. The mismatch between the ISCC-NBS regions and
   botanical usage (pink, tinted white) is a finding for the FLOPO colour definitions.

## Next steps

In this order:

1. **Adopt hidden layer + loss over 8 photographs of a species as the baseline** (+0.04 on agreed species,
   no change on observers; targets from the share of floras are left out), and rerun the
   species-identification test with it. Find out why flower colour loses on the observers' test with the
   hidden layer before using it for that trait.
2. **Use both label sources.** Observers' values exist for flower colour (about 17,000 observations in all
   of iNaturalist) and growth form (about 8,000); add them to the flora labels in training, with the loss on
   the observation, and hold out part of them for the test. Download all photographs of these observations
   to measure what photographs without the organ cost.
3. **More labelled species.** The curve still rises. The extended WFO corpus roughly doubles the
   statements; "X to Y" statements are now included. Agreement must be counted without WFO.
4. **A better test of the observer side.** Score observers' labels only where the flora of the species
   allows the value, and report the flora look-up next to the model, so that model error and
   flora–observer disagreement are separated.
5. **Leaf shape as two numbers** (length to width, position of the widest point) from the measurements in
   the floras, with the shape words following from the ranges of pattern 17. This is the first trait where
   the value space gives the model a target it does not already have.
6. **Image features, not labels, for the traits that stay low** (fruit colour, inflorescence, arrangement):
   patch-level features of the frozen model with attention over patches, instead of one vector per
   photograph. This is the remaining lever the tests point to; retraining the whole image model was tried
   earlier and memorised species.
7. **FLOPO colour:** review where pale tints sit at the first level, and record botanical usage of pink and
   purple against the ISCC-NBS regions (annotation, not a change of the definitions), using the pixel data
   of this round.

Not worth repeating: near-colour targets on a linear classifier; photograph selection by detector or by
the model; noise-tolerant losses; colour measured from boxes or outlines as a predictor.

## Files

- Code: `flopo2/traitvision/` — `colour_space.py`, `colour_labels.py`, `value_arms.py`, `score_arms.py`
  (section 1); `colour_measure.py`, `segment_colour.py`, `score_measure.py`, `measure_head.py` (section 2);
  `regime_tests.py` (section 3); `observer_tests.py` (section 4). Job files: `tools/orix/traitvision_value_arms.sbatch`,
  `traitvision_segment.sbatch`, `traitvision_regime.sbatch`.
- Results (git-ignored): `local-corpora/trait-vision/varms/scores-v3-test.json`,
  `colour-measure-scores.json`, `colour-segment-field-head-scores.json`, `regime/*.json`.
- ORIX: `/mnt/data/u/hohndor/flopo-vision/pilot-v1/` (jobs 407133, 407211, 407230–407232, 407241–407243).

## 9. Baseline 2: all photographs, flora + observers, flora sizes, species identification (2026-11-22)

`baseline_v2.py` (`tools/orix/traitvision_baseline2.sbatch`, job 409538, 12 min; `local-corpora/trait-vision/baseline-v2/baseline-v2.json`;
per-photograph predictions on ORIX `pilot-v1/baseline-v2/pred-*.npz`). Frozen BioCLIP 2; MLP head with bags (species bags
from the floras, observation bags from observers at 0.3 of their weight); every photograph, organ photographs for leaf
traits and spines; class weights capped at 10; held-out genera, five folds, one seed. The species name is a label for
training only.

| trait | agreed species | observers |
|---|---|---|
| flower colour | 0.697 | 0.686 |
| fruit colour | 0.311 | 0.429 |
| habit | 0.895 | 0.718 |
| inflorescence | 0.605 | - |
| leaf arrangement | 0.720 | 0.565 |
| leaf complexity | 0.904 | 0.705 |
| leaf margin | 0.764 | 0.691 |
| spines | 0.778 | 0.799 |

**Sizes stated by the floras** (`extract_measures.py`, labels `measure-labels-v2.tsv`; Spearman of the predicted against the
flora value, species of unseen genera): height 0.914 (19,612 species), leaf length 0.866, leaf width 0.902, fruit length
0.836, fruit width 0.820, seed length 0.833, petal length 0.775, flower diameter 0.784.

**Species identification of unseen genera** (15,000 observations, all their photographs; 1,329 candidate species on average,
50 within the family; the true species ranked first / in the first 5 / in the first 10):

| traits used | all candidates | within the family |
|---|---|---|
| chance | 0.001 / - / - | 0.117 / - / - |
| first baseline (8 categorical, two photographs, flora labels only) | 0.015 / - / - | - |
| 8 categorical | 0.024 / 0.097 / 0.158 | 0.217 / 0.538 / 0.696 |
| + height and leaf size | 0.048 / 0.154 / 0.237 | 0.264 / 0.600 / 0.748 |
| + all eight sizes | 0.062 / 0.189 / 0.282 | 0.280 / 0.616 / 0.760 |
| sizes only | 0.027 / 0.084 / 0.129 | 0.224 / 0.533 / 0.681 |
| flora values read exactly: 8 categorical | 0.683 / 0.948 / 0.988 | 0.811 / 0.985 / 0.998 |
| flora values read exactly: + all sizes | 0.949 / 0.990 / 0.998 | 0.972 / 0.998 / 1.000 |

The last two rows are the ceiling: what the floras' traits could identify if every trait were read from the photographs
without error (for a size, the species' own value).

## 10. Fruit colour from the fruit region (2026-11-22)

`fruit_region.py` (`tools/orix/traitvision_fruitregion.sbatch`, job 409537; `local-corpora/trait-vision/fruit-region/fruit-region.json`;
ORIX `pilot-v1/fruit-region/`). BioCLIP 2 embeddings of 1,472,222 boxes (every "fruit" box, and "flower" boxes on photographs
with a fruiting score above 0.3; at most three per photograph) and 65,632 boxes of observers' photographs. Protocol of
`allphotos_train.py`, three seeds; a species or observation without a region falls back to its whole photographs. Balanced
accuracy exact (seed range) / near / skill.

| fruit region defined by | arm | agreed species (610) | observers (197) |
|---|---|---|---|
| - | whole photograph | 0.339 (0.337-0.341) / 0.451 / 0.27 | 0.400 (0.395-0.405) / 0.471 / 0.41 |
| detector "fruit" box | region only | 0.354 / 0.475 / 0.29 | 0.425 / 0.518 / 0.41 |
| PhenoVision >= 0.6 | region only | 0.370 (0.364-0.379) / 0.502 / 0.33 | 0.513 (0.502-0.524) / 0.554 / 0.51 |
| PhenoVision >= 0.6 | region + whole, one bag | 0.339 / 0.470 / 0.27 | 0.516 / 0.592 / 0.53 |
| our phenology head > 0.5 | region only | 0.366 / 0.471 / 0.26 | 0.467 / 0.497 / 0.46 |
| fruit box or PhenoVision | region only | 0.362 / 0.485 / 0.30 | 0.523 / 0.616 / 0.51 |
| fruit box or PhenoVision | region + whole, one bag | 0.344 / 0.476 / 0.27 | 0.540 / 0.610 / 0.54 |

The region helps once a fruiting score decides which boxes are fruit. The pilot's earlier crop test (job 406414: detector
"fruit" boxes of the first two photographs, linear head) had been worse than the whole photograph. Not tested: the "a fruit"
phrase as its own arm (the `phrase` column exists only for the 548k later photographs).

### Fruit regions in baseline 2 (2026-11-23)

`baseline_v2.py` now reads fruit colour from the regions (`REGION`: boxes on photographs with PhenoVision
fruiting >= 0.6; a photograph without one keeps its whole embedding; `--regions ''` turns it off, `--reuse DIR`
takes the other traits from an earlier run). ORIX `pilot-v1/baseline-v2r/`, job 410600; 220,483 photographs and
9,980 observers' photographs have a region (473,745 regions).

| | Agreed species | Observers |
|---|---|---|
| Fruit colour, whole photograph (baseline 2) | 0.311 | 0.429 |
| Fruit colour, regions | 0.372 | 0.540 |

Species identification barely moves (all candidates, categorical + all sizes: first 0.062 -> 0.063, first ten
0.282 -> 0.282; categorical only: first 0.024 -> 0.025). Fruit colour is one weak trait among sixteen, and only
14% of the photographs show a fruit.

## 12. Four more traits from the floras (2026-11-23)

`labels_extra.py`; `baseline_v2.py` reads `extra-labels.tsv` / `agreed-extra.tsv` when present (ORIX `pilot-v1/baseline-v3/`, job
411070; the eight pilot traits reused from `baseline-v2r`; whole photographs; no observers' test exists for these traits).
Unseen genera, agreed species, balanced accuracy: leaf persistence 0.847 (n 1,391; 2 values), life span 0.720 (6,172; 3),
leaf texture 0.634 (3,904; 4), leaf shape 0.505 (3,782; 8).

Species identification (same candidates as before: by the eight pilot traits; ~1,329 per observation), first / first 5 / first 10:

| | 8 traits (baseline-v2r) | 12 traits |
|---|---|---|
| categorical | 0.025 / 0.097 / 0.160 | 0.044 / 0.150 / 0.232 |
| categorical + all sizes | 0.063 / 0.190 / 0.282 | 0.086 / 0.237 / 0.339 |
| flora values read exactly, categorical | 0.683 / 0.948 / 0.988 | 0.889 / 0.988 / 0.997 |
| within family (50), categorical + all sizes | 0.280 / 0.617 / 0.761 | 0.315 / 0.655 / 0.796 |

## 13. Fourteen more traits and the counts (2026-11-23)

`labels_extra.py` now also writes leaf_hair, stem_hair, leaf_apex, leaf_base, leaf_attachment, leaf_position, posture, branching,
stem_shape, substrate, fruit_type, fruit_shape, corolla_shape, flower_position (apex/base by the statement's wording). Counts:
`extract_counts.py` -> `counts-all.tsv` (306,989 statements, unit `count`); eleven of them in `measure-labels-v3.tsv` as log10 of the
count (n_flowers, n_stamens, n_petals, n_sepals, n_leaflets, n_seeds, n_leaf_lobes, n_ray_flowers, n_veins, n_styles, n_carpels).
`baseline_v2.py` reads `measure-labels-v3.tsv` when present (sizes by accepted name, leaflet sizes, counts; `--sizes-v2` for the old file).

Unseen genera, agreed species, balanced accuracy (ORIX `baseline-v4`, job 411215): substrate 0.923, leaf position 0.832, leaf hair
0.806, stem hair 0.806, flower position 0.780, leaf attachment 0.754, branching 0.739, stem shape 0.700, posture 0.685, fruit type
0.627, leaf base 0.539, fruit shape 0.476, corolla shape 0.465, leaf apex 0.452.

Sizes and counts, Spearman on unseen genera (`baseline-v5`, job 411272; species with a value and photographs): height 0.915, leaf
length 0.868, leaf width 0.904, fruit length 0.848, fruit width 0.825, seed length 0.844, petal length 0.784, flower diameter 0.796,
leaflet length 0.908, leaflet width 0.895; counts: leaflets 0.827, ray flowers 0.765, veins 0.647, flowers 0.611, stamens 0.555,
carpels 0.526, petals 0.458, seeds 0.451, leaf lobes 0.337, styles 0.333, sepals 0.229.

Species identification (~1,329 candidates; first / first 5 / first 10):

| | 12 traits, sizes v2 | 26 traits, sizes v2 (v4) | 26 traits, sizes v3 (v5) | + counts (v5) |
|---|---|---|---|---|
| categorical | 0.044 / 0.150 / 0.232 | 0.079 / 0.229 / 0.337 | 0.077 / 0.230 / 0.337 | |
| categorical + all sizes | 0.086 / 0.237 / 0.339 | 0.114 / 0.306 / 0.422 | 0.127 / 0.340 / 0.463 | 0.131 / 0.341 / 0.465 |
| within family, categorical + all sizes | 0.315 / 0.655 / 0.796 | 0.326 / 0.675 / 0.808 | 0.348 / 0.701 / 0.832 | 0.350 / 0.701 / 0.831 |

(v4 had fruit colour on whole photographs by a slip of `--reuse`; v5 has the regions again.) As inputs of the TRY head the 26 traits
do not help (sota section 12 table, `even-scores-t26.json`: reference leaf nitrogen 0.433, leaf area 0.716 against 0.475 / 0.730 with 12).

## 14. Extraction check without labels: agreement between floras (2026-11-23)

`validate_extraction.py agreement` -> `local-corpora/trait-vision/extraction-agreement.json`. Per trait, every species that two
sources describe (pairs with identical wording left out): share of pairs whose value sets share a value, against the same for two
different species (chance); kappa = (compatible - chance) / (1 - chance). Kappa: leaf persistence 0.97, leaf position 0.96, fruit
type 0.95, habit 0.91, leaf arrangement 0.90, life span 0.89, leaf complexity 0.87, flower position 0.86, substrate 0.85, stem shape
0.84, inflorescence 0.79, leaf margin 0.79, spines 0.75, branching 0.75, posture 0.73, stem hair 0.73, fruit colour 0.73, flower
colour 0.71, fruit shape 0.70, leaf hair 0.67, leaf texture 0.65, leaf attachment 0.64, leaf shape 0.64, corolla shape 0.63, leaf
base 0.62, leaf apex 0.55. Disagreement mixes extraction errors with real differences between floras (variable species, regions).

Saudi Arabia as case-study region: 1,233 accepted species in the two Saudi guides; 972 have photographs in our set (48,440), 1,191
have flora labels (median 7 of 26 categorical traits; 569 with 8 or more); iNaturalist has 3,898 research-grade vascular-plant
observations in Saudi Arabia (826 species; 3,071 observations with an open photo licence), counted on 2026-11-23.

## 15. Extraction and predictions against other people's curated data, and a larger model as reader (2026-11-23)

**Larger model as reader** (`judge_extraction.py`; `local-corpora/trait-vision/judge/`, summary `extraction-judge-summary.json`): 3,650
accepted statements sampled (100 per categorical trait, 50 per size and count), each shown to Opus (`claude-max -p --model opus`) with
the flora passage and the value we took; 3,643 judged. Correct 0.830 (0.818-0.842); wrong part 244, restricted to a stage/position
216, wrong value 135, not stated 23. Best: habit 0.99, life span 0.99, fruit width 0.98, styles 0.98, inflorescence 0.96, substrate
0.96, veins 0.96, flower position 0.94, height 0.94, stamens 0.94. Worst: leaf lobes 0.16 ("lobes" of calyx/corolla grounded as leaf
lamina lobes), petal length 0.42 (corolla tube, keel), ray flowers 0.54 (umbel rays, hair rays), leaf attachment 0.70 (upper/lower
leaves), leaf hair 0.70 (young/old), fruit colour 0.71, leaf base 0.71, leaf apex 0.72. By source: FNA 0.73, WFO 0.83, FOC 0.86.
Fixed after it in `labels_extra.py`: n_leaf_lobes dropped, n_ray_flowers only for Asteraceae, corolla length no longer petal length
(labels rebuilt; `baseline-v5` predates the fix). Not fixed: fruit "capsule" of mosses, statements about upper/lower leaves.

**Hand-built matrices of Marcos et al. 2025** and **GIFT 3** (`validate_external.py`, `external/gift_fetch.py`;
`external-validation.json`; testing only). Flora labels: F1 over values, species with both; photographs: predicted class inside the
reference set, unseen genera (`baseline-v5/species-pred.tsv.gz` from `species_pred.py`), over the classes the reference can express.

| West Africa (Bonnet 2005) | labels n | F1 | photos n | in set |
|---|---|---|---|---|
| leaf complexity | 120 | 0.943 | 217 | 0.972 |
| stem shape | 16 | 0.938 | 217 | 0.949 |
| leaf attachment | 42 | 0.933 | 142 | 0.937 |
| spines | 50 | 0.932 | 217 | 0.806 |
| leaf margin | 93 | 0.896 | 215 | 0.930 |
| fruit type | 141 | 0.891 | 197 | 0.553 |
| flower position | 132 | 0.879 | 217 | 0.802 |
| habit | 221 | 0.829 | 224 | 0.897 |
| leaf arrangement | 87 | 0.824 | 217 | 0.733 |
| leaf base | 155 | 0.745 | 217 | 0.866 |
| flower colour | 175 | 0.733 | 216 | 0.690 |
| leaf apex | 193 | 0.707 | 217 | 0.871 |
| leaf shape | 132 | 0.693 | 211 | 0.877 |
| inflorescence | 125 | 0.595 | 177 | 0.446 |

| GIFT | labels n | F1 / Spearman | photos n | in set / Spearman |
|---|---|---|---|---|
| habit (herb, shrub, tree) | 26,722 | 0.863 | 28,064 | 0.870 |
| life span | 18,226 | 0.922 | 26,580 | 0.883 |
| leaf persistence | 1,367 | 0.922 | 3,885 | 0.749 |
| substrate | 3,374 | 0.856 | 24,161 | 0.813 |
| fruit type | 1,316 | 0.834 | 2,121 | 0.593 |
| flower colour | 642 | 0.519 | 813 | 0.554 |
| fruit colour | 170 | 0.531 | 271 | 0.262 |
| height | 22,929 | 0.947 | 11,497 | 0.920 |
| leaf length | 10,047 | 0.835 | 5,875 | 0.761 |
| leaf width | 9,109 | 0.904 | 5,459 | 0.827 |
| fruit length | 5,994 | 0.944 | 4,513 | 0.780 |
| fruit width | 4,224 | 0.908 | 2,614 | 0.769 |

Caribbean (27 species) and palms (PalmTraits: fruit length 0.969, fruit width 0.957, stem height 0.904 for the labels) are in the JSON.
GIFT is itself compiled from floras and databases, some of which may be among our sources, so it is not fully independent; its
colours have many values per species (low precision for us means we list fewer or other colours).

## 16. After feedback from two botanists: scope, provenance, rebuilt labels (2026-11-23)

**Scope** (`scope.py`, used by `extract.py`, `extract_measures.py`, `extract_counts.py`): vascular plants only (the moss flora
`eflora-mfoc` dropped; any record whose family and genus are both unknown to WCVP dropped) and every description once (records listed
in `local-corpora/saudi-flora/duplicates.tsv` of `tools.atlas_duplicates` dropped: 29,137 copies, 27,129 of them in WFO). Re-extracted
from the floras as re-derived on 2026-11-23 (position pass: "basal leaves", "lateral umbels" now carry a context and are not taken as
general): `pilot-assertions-v5.tsv`, `measures-all.tsv`, `counts-all.tsv` (old ones `*-pre-scope.tsv`). `labels_extra.py` then writes
all 26 traits to `labels-v5.tsv` and `agreed-v5.tsv` (the eight pilot traits now from the same pass, WFO included: habit 53,334
species, flower colour 53,565); `baseline_v2.py` and `validate_external.py` read them when present (`--labels-v3` for the old files).

**Agreement between floras on the cleaned sources** (`extraction-agreement.json`; before: `extraction-agreement-pre-scope.json`): mean
kappa 0.772 -> 0.752; near-copies had inflated it a little (stem shape 0.84 -> 0.77, branching 0.75 -> 0.70, leaf attachment 0.64 -> 0.60).

**Provenance of GIFT** (`external/gift/references.json`, `gift-shared-references.tsv`): GIFT names the source of each value; values
whose source is also ours (Flora of China and FRPS, Flora of West Tropical Africa, Flora of Zimbabwe, Flora of Gabon, African Plants
- A Photo Guide, ...) are left out in the variant "GIFT, sources not among ours". Labels v5: habit F1 0.836 (31,690 species), life
span 0.913 (12,231), substrate 0.855, leaf persistence 0.868 (188), fruit type 0.835; height Spearman 0.942 (16,251), leaf width
0.888, leaf length 0.757, fruit length 0.912, fruit width 0.853. TRY could not be audited: the PlantTraitNet benchmark gives species
means without the contributing data sets. iNaturalist photographs are research grade only (`inat_select.py`).

**Ablation arms** (`baseline_v2.py --arm`): one-value (one of the alternatives at random), adjacent (a neighbouring value counts 0.3;
`NEIGHBOURS`), no-observers, no-cap, photo (no bags). Runs under ORIX `pilot-v1/baseline-v6/<name>` (`traitvision_baseline_multi.sbatch`,
three runs side by side on one GPU): seeds s0-s3 and the five arms; jobs 411436, 411437 and a third.

## 17. Seeds and ablation arms on the rebuilt labels (2026-11-24)

Runs `pilot-v1/baseline-v6/<name>` (jobs 411436, 411437, 411503; 20-23 min each, GPU 89-91% with three runs side by side).
Identification of observations of unseen genera: 1,553 candidates per observation (chance first 0.0007), within the family 60.

| run | categorical: first / 10 | + sizes + counts: first / 5 / 10 | within family: first |
|---|---|---|---|
| full, seeds 0-3 | 0.068-0.069 / 0.310-0.311 | 0.112-0.114 / 0.317 / 0.435 | 0.309-0.312 |
| one-value (one alternative at random) | 0.062 / 0.277 | 0.104 / 0.298 / 0.416 | 0.297 |
| adjacent (a neighbouring value counts 0.3) | 0.060 / 0.275 | 0.100 / 0.275 / 0.383 | 0.289 |
| photo (no bags) | 0.059 / 0.274 | 0.103 / 0.292 / 0.412 | 0.297 |
| no-observers | 0.071 / 0.313 | 0.113 / 0.316 / 0.438 | 0.308 |
| no-cap | 0.067 / 0.306 | 0.111 / 0.314 / 0.432 | 0.307 |

Seed spread is about 0.001. Set-valued labels and species bags each add about one point of first place. Partial credit for a
neighbouring value (the `adjacent` arm) is *worse* than the plain sets (leaf shape 0.528 -> 0.332, leaf apex 0.515 -> 0.418 on agreed
species): the sets as the floras state them are the better target. Observer labels and the class-weight cap do not change
identification; observer labels raise the score on observers' photographs (leaf arrangement 0.493 -> 0.563, leaf margin 0.608 -> 0.683,
flower colour 0.654 -> 0.685) and lower nothing on agreed species beyond 0.02.

**Why some of the eight original traits score lower than in section 13** (`label_check.py` on ORIX `src/`; species mean over all
photographs, so the numbers differ a little from the runs): the test got harder, the labels did not get worse. The agreed test sets
roughly doubled (habit 3,126 -> 6,799 species, flower colour 1,730 -> 5,037), and all species in both sets keep their value. The old
model (baseline-v5) on the new test species drops as the new model does (leaf arrangement 0.719 -> 0.639 old model, 0.709 -> 0.620
new; leaf margin 0.747 -> 0.691 and 0.729 -> 0.677; flower colour 0.697 -> 0.647 and 0.691 -> 0.642); on the old test species the new
model is within 0.02 of the old one except spines (0.745 -> 0.708) and fruit colour (0.357 -> 0.334), and better on habit
(0.895 -> 0.929). The species that are new in the test score lower for both models (leaf arrangement 0.57 / 0.55).

**Taxonomy baseline** (`family-baseline.json`; no photograph, the true family given): the most common value in the family among the
genera of the training folds, as the guess for the agreed species of unseen genera. Balanced accuracy below the photograph model on 25
of 26 traits (habit 0.501 vs 0.894, leaf complexity 0.619 vs 0.888, flower colour 0.205 vs 0.642, leaf shape 0.237 vs 0.528, life span
0.358 vs 0.795, stem shape 0.650 vs 0.671); only fruit type is better guessed from the family (0.798 vs 0.733).

**Photograph predictions of the new run against the curated data** (`validate_external.py local-corpora/trait-vision baseline-v6/s0`,
`external-validation.json`; the earlier file with baseline-v5 predictions kept as `external-validation-v5pred.json`). Predictions for
unseen genera against GIFT values whose sources are not ours: habit balanced 0.782 (22,193 species), life span 0.796 (18,410),
substrate 0.877 (23,708), leaf persistence 0.657, fruit type 0.557 (10 classes), flower colour 0.477 (9 classes); height Spearman
0.922 (7,883), leaf width 0.841, leaf length 0.737, fruit length 0.822, fruit width 0.759. West Africa (Bonnet 2005, ~217 species):
0.40 (inflorescence, 6 classes) to 0.98 (leaf complexity).

## 18. Baselines without training (2026-11-24)

`zeroshot.py`, `tools/orix/traitvision_zeroshot.sbatch` (job 413687, a few minutes); same observations and candidates as section 17
(1,553 candidates per observation, 60 within the family); results `baseline-v6/zeroshot/zeroshot.json` and `baseline-v2.json`.
BioCLIP 2 image and text embeddings only, nothing trained on the flora labels.

| baseline | first | in first 5 | in first 10 | within family: first |
|---|---|---|---|---|
| chance | 0.0007 | | | 0.103 |
| trait prompts ("a photo of a plant; leaf shape: ovate"), 26 traits, our identification | 0.003 | 0.014 | 0.025 | 0.133 |
| trait text (the candidate's flora values as sentences), similarity to the photographs | 0.001 | 0.007 | 0.015 | 0.121 |
| flora text (the candidate's description, names removed, up to 24 sentences) | 0.009 | 0.024 | 0.037 | 0.137 |
| **trained heads, 26 traits** (section 17) | 0.068 | 0.209 | 0.310 | 0.255 |
| **trained heads + sizes + counts** | 0.113 | 0.317 | 0.435 | 0.310 |
| species name ("a photo of <name>"): upper reference, uses the name | 0.823 | 0.951 | 0.970 | 0.859 |

Per trait, the prompts are far below the trained heads on the agreed species (habit 0.598 vs 0.894, leaf complexity 0.568 vs 0.888,
flower colour 0.533 vs 0.642, leaf shape 0.165 vs 0.528, fruit type 0.094 vs 0.733). The prompts are plain (trait words and value,
not tuned); the tuned prompts for the eight original traits of the pilot were also well below trained heads. The species-name row
shows that BioCLIP 2 has seen these species with their names in its own training: "unseen genera" holds for our heads and labels, not
for the image model, and the paper has to say so. `flora-texts.tsv` (32,848 species, 640,989 sentences) is the name-free text.

## 19. Identification rule, what the semantics add, and the published extraction on the same matrices (2026-11-24)

**Identification rule** (`baseline_v2.py --rule ratio|wmc --temp T`, job 413855, predictions of run s0 reused). The rule in use
already sums probabilities, no cut-offs: per trait log(sum over values p(value | photographs) x P(value | candidate) / P(value)), with
P(value | candidate) uniform over the candidate's set. `wmc` (weighted model count) scores the set as an event: P(value in the set |
photographs) / P(value in the set). 1,553 candidates, categorical + sizes + counts, first / in first 10: ratio 0.113 / 0.435; wmc
0.113 / 0.435; probabilities flattened (exponent 0.5) 0.100-0.102 / 0.40-0.41; sharpened (exponent 2) 0.104 / 0.40. No gain: the two
rules are equal and the probabilities as they come out of the heads are best. Not tried: weights per trait learned on the training
folds, dependence between traits.

**What the semantic choices add** (section 17, mean balanced accuracy over 26 traits on agreed species; seeds 0.698, spread 0.002):
one-value 0.702, adjacent 0.686, photo 0.695, no-observers 0.698, no-cap 0.698. Only 16.6% of the 681,236 species-trait labels have
more than one value, so the "or" matters little for single traits (leaf margin -0.043, leaf shape -0.025; leaf arrangement +0.048,
leaf base +0.032) and adds 0.9 points of first place in identification, where candidates are matched as sets. Not ablated yet: the
grouping of values by the ontology (subsumption), statements with a position or stage context left out, values defined by a measure
(linear from length:width), ranges of sizes (labels and identification use the midpoint of the range, not the range).

**Marcos et al. 2025 on the same matrices** (`validate_external.py compare`, `external-comparison.tsv`/`.json`): their published
per-species output (Mistral on web text, `LLM/Results/Mistral/*/summary.csv`) and our flora labels, mapped to our classes by the same
table and scored the same way against the three hand-built matrices.

| data set (species-trait pairs) | Marcos: pairs with a value, F1 | ours: pairs, F1 | same pairs: Marcos F1 / ours F1 |
|---|---|---|---|
| West Africa (4,630) | 2,807, 0.789 | 1,743, 0.783 | 1,251: 0.752 / 0.802 |
| Caribbean (440) | 259, 0.755 | 151, 0.705 | 114: 0.745 / 0.720 |
| Palms, fruit colour and shape (570) | 417, 0.543 | 98, 0.612 | 73: 0.531 / 0.576 |

West Africa per trait on the same species: ours higher on 10 of 14 (leaf apex 0.716 vs 0.445, leaf complexity 0.944 vs 0.850,
inflorescence 0.638 vs 0.544), theirs on 4 (flower position, leaf arrangement, spines by 0.02-0.03). They cover more pairs (61% vs
38% in West Africa): they search the web per species, we read fixed floras. Their method was built and tuned for these matrices and
vocabularies; ours is mapped to them afterwards.

## 20. Extraction against the published methods, in full (2026-11-24)

**Marcos et al. 2025** (`validate_external.py compare`; full table with precision, recall, F1, macro F1, species of either method and
the bootstrap interval of the difference: `external-comparison.tsv`, `.json`). F1 of ours minus theirs on the species-trait pairs both
methods have, 1,000 bootstrap samples: West Africa +0.050 (+0.034 to +0.067; 1,251 pairs), Caribbean -0.024 (-0.106 to +0.053; 114),
palms +0.045 (-0.057 to +0.143; 73). West Africa on each method's own pairs: theirs P 0.850 R 0.735 F1 0.789 (2,807 pairs of 4,630),
ours P 0.809 R 0.759 F1 0.783 (1,743). Per trait on the shared species, ours is higher beyond the interval for flower colour (+0.055),
inflorescence (+0.094), leaf apex (+0.271) and leaf complexity (+0.094); no trait is lower beyond the interval. Palms: fruit colour
ours +0.195 (+0.053 to +0.339), fruit shape -0.110 (-0.226 to +0.011). Coverage is theirs: they search the web for every species.

**Domazetoski et al. 2025** (`validate_external.py gift`, `external-comparison-gift.json`). Their models (DistilBERT) are trained on
GIFT values and tested on held-out POWO descriptions: mean macro precision 90.6-90.8%, recall 88.6% over five traits (epiphyte F1 93.8%,
life form 82%); no predictions are published (repository `external/domazetoski/repo`: notebooks only), so their numbers are as
reported. Ours never saw GIFT; same measure (macro over classes), species in both:

| trait | species | macro P | macro R | macro F1 | per class F1 |
|---|---|---|---|---|---|
| growth form | 41,395 | 0.805 | 0.923 | 0.849 | herb 0.946, shrub 0.703, tree 0.899 |
| epiphyte | 3,275 | 0.819 | 0.868 | 0.840 | epiphytic 0.890, terrestrial 0.790 |
| climber | 40,888 | 0.761 | 0.778 | 0.769 | climber 0.565, self-supporting 0.974 |
| life cycle | 17,549 | 0.903 | 0.949 | 0.925 | annual 0.889, perennial 0.961 |

Mean macro precision 0.822, recall 0.880: recall as theirs, precision 8 points lower, without training on the reference. (GIFT
sources that are not ours: growth form 0.832, epiphyte 0.841, climber 0.778, life cycle 0.915.) Climber is our weak class: it is read
off habit "climber" or posture "climbing", not extracted as its own trait. Sizes, error of the log value over the range of log values
(their "nMAE", as far as their text defines it): height 0.029 (theirs 5.3%), leaf length 0.047 (theirs 16-24%), leaf width 0.057;
median factor between ours and GIFT 1.17 (height), 1.50 (leaf length), 1.46 (leaf width). The normalisation may differ from theirs.

**Pattern 17 on the data** (`labels_extra.py labels DIR measure`): of 6,699 species whose flora says "linear" and gives leaf length and
width, 3,700 (55%) have length : width >= 10; of 4,929 species with a stated shape and a ratio >= 10, 3,700 (75%) say linear.
5,082 species without a stated shape get "linear" from the ratio.

## 21. Identification with a model per trait, and the remaining semantic ablations (2026-11-24)

**Learned identification** (`baseline_v2.py --learn`, `learn_identification`; jobs 414022, 414066, 414067; results in
`baseline-v6/learn/baseline-v2.json` under `identification_learned`). Per test fold, learned on the sampled observations of the other
four folds (other genera, their predictions from heads that never saw them), starting at the fixed rule, cross-entropy of the true
species among the candidates: a weight per trait, size and count and the width of each size's error ("weights"); and in addition per
trait a table of how well each flora value goes with each predicted value ("value table"). 1,553 candidates:

| rule | categorical: first / 10 | + sizes + counts: first / 5 / 10 | within family: first |
|---|---|---|---|
| fixed rule | 0.068 / 0.310 | 0.113 / 0.317 / 0.435 | 0.309 |
| weights | 0.071 / 0.317 | 0.121 / 0.329 / 0.450 | 0.327 |
| weights + value table | 0.086 / 0.366 | 0.135 / 0.357 / 0.479 | 0.336 |

All learned weights are below 1 (the traits are not independent, so the fixed sum counts shared evidence several times). Highest:
number of ray flowers 0.79, leaflet length 0.78, fruit length 0.63, number of carpels 0.58, number of stamens 0.53, flower diameter
0.51, height 0.45, flower colour 0.45, leaf length 0.43, leaf shape 0.41, habit 0.38; lowest: posture 0.18, fruit shape 0.20, spines
0.21, fruit colour 0.21, leaf base 0.22, stem shape 0.23. The value table is where neighbouring values now enter: learned from the
data instead of a fixed 0.3 (section 17, which was worse). Not saved yet: the tables themselves.

**Label variants** (`labels_extra.py labels DIR <variant>` -> `labels-v5-<variant>.tsv`; `baseline_v2.py --labels`; the candidates and
the agreed test species stay those of the standard labels; full training, job 413959). Identification with sizes and counts:

| labels | species-trait labels | fixed rule: first / 10 | weights + value table: first / 10 | per-trait accuracy on agreed species |
|---|---|---|---|---|
| standard | 681,236 | 0.113 / 0.435 | 0.135 / 0.479 | mean 0.698 |
| ctx: position and stage statements taken as general | +9,659 | 0.113 / 0.437 | 0.136 / 0.479 | 0.699 |
| nosub: colours without the ontology's subclasses | -12,691 | 0.110 / 0.427 | 0.133 / 0.470 | 0.700 (flower colour +0.035, fruit colour +0.025) |
| canon: no grouping of terms under a class | -66,053 | 0.107 / 0.427 | 0.131 / 0.467 | 0.703 (fruit shape +0.088, leaf base +0.063; stem shape -0.045, leaf margin -0.036) |
| rare: rare values allowed | +2,641 | 0.111 / 0.431 | 0.135 / 0.474 | 0.697 (leaf apex -0.049) |
| measure: linear from length : width >= 10 | +5,082 | 0.112 / 0.436 | 0.135 / 0.479 | 0.697 |

**Ranges of sizes** (`--ranges`; `measure-labels-v3.tsv` now has `low`, `high`): the candidate's stated range blurred by the model's
error instead of a bell around its middle (ident), no training error inside the range (train), both. Fixed rule 0.111 / 0.432,
0.112 / 0.434, 0.110 / 0.430 against 0.113 / 0.435; with weights + value table 0.136 / 0.473, 0.135 / 0.476, 0.135 / 0.473 against
0.135 / 0.479. No gain.

Reading: the model per trait is the gain (+2.2 points first place, +4.4 in the first ten). The semantic choices in the labels move
identification by 0.4 points or less: grouping of terms and the colour hierarchy help a little (more species labelled, the per-trait
accuracy on the agreed species does not rise and for fruit shape and leaf base it falls: the grouped terms are noisier labels);
context filter, rare values, linear from the measure and size ranges make no measurable difference.

## 22. Three applications (2026-11-24)

`flopo2/traitvision/applications.py` (`climate`, `within`, `gaps`); results under `local-corpora/trait-vision/applications/`
(`climate.tsv/.json`, `within.json`, `gaps.json`). Input: `obs-pred.npz` (ORIX `src/obs_table.py`): 641,883 observations with place,
date, species and the mean prediction of every trait over their photographs (run s0; every prediction from the fold that held out
the genus). Climate: WorldClim 2.1 at 10 arc-minutes (mean annual temperature, annual precipitation, temperature seasonality).

**1. Known trait-climate relations, on 2-degree cells.** Per cell the share of species with a value (or the mean size) over the
species observed there, against the cell's climate; cells with 20 or more species. "Floras": flora value of each species seen in the
cell. "Photographs": mean prediction over the observations made in the cell, per species. "No flora": photographs of species that
have no flora value for the trait (10 or more species). Pearson r (cells):

| relation (expected sign) | floras | photographs | photographs, species without a flora value |
|---|---|---|---|
| entire leaf margin, woody dicots, with temperature (+) | +0.78 (340), slope 0.026 per degree | +0.74 (850), slope 0.014 | +0.52 (1,016) |
| leaf area with temperature (+) | +0.63 (1,471) | +0.62 (1,777) | +0.53 (1,515) |
| leaf area with log precipitation (+) | +0.75 | +0.71 | +0.60 |
| plant height with temperature (+) | +0.79 (1,559) | +0.81 (1,777) | +0.78 (1,308) |
| plant height with log precipitation (+) | +0.66 | +0.61 | +0.48 |
| spines, woody species, with log precipitation (-) | -0.19 (134) | -0.58 (894) | -0.49 (1,242) |
| annual, herbs, with temperature (+) | +0.67 (1,039) | +0.68 (1,418) | +0.51 (1,323) |
| annual, herbs, with log precipitation (-) | 0.01 | -0.05 | -0.13 |
| compound leaves, woody dicots, with temperature (+) | +0.32 (300) | +0.22 (850) | -0.03 |
| evergreen, woody species, with temperature seasonality (-) | -0.70 (248) | -0.67 (894) | -0.64 (1,155) |
| epiphytic with log precipitation (+) | +0.38 (78) | +0.72 (1,777) | +0.70 (2,215) |
| fleshy leaves with log precipitation (-) | -0.66 (830) | -0.75 (1,777) | -0.72 (2,021) |

Ten of twelve relations have the expected sign with |r| above 0.5 from photographs; the slope of the leaf-margin relation from the
floras (0.026 per degree) is close to the published about 0.03, from photographs it is half (mean probabilities, not counts of
species, flatten it). Photographs give two to twenty times more cells than the floras for traits that few floras state (spines,
epiphytes, evergreen). Not excluded: the image model may read the habitat in the photograph as well as the plant. Monocots, conifers
and cycads are left out of "dicots" by a list of families.

**2. Variation within species.** Sizes: for species with 30 or more observations that span a range of climate (sd of temperature
3 degrees or more, or sd of log precipitation 0.15 or more), the slope of the predicted size on climate over the species'
observations. Leaf area with log precipitation: 4,275 species, 61.7% of slopes positive, median +0.08 log units per tenfold
precipitation (between species +1.04); with temperature 55.1% positive (3,627 species). Height: 59.2% positive with temperature, 58.1%
with precipitation. Flower diameter and fruit length: 46-52%. Same direction as between species, an order of magnitude weaker.
Observers' values (`field-pred-<trait>.npz` of run `baseline-v6/field`, job 414198; species of unseen genera for which observers
recorded two or more values): flower colour, 282 species and 5,522 observations: the prediction, among the values recorded for the
species, is the observer's value for 72.4% (64.7% when observers' values are shuffled within species, 97.5% point 65.4%; always
taking the species' most common value gives 79.7%). Habit 59.3% against 59.3%, leaf arrangement 60.6% against 58.6%, leaf margin
60.0% against 56.2% (31 and 17 species): no signal. So within a species the heads follow flower colour a little and sizes weakly.

**3. What the catalogue and the photographs add to GIFT** (public API; species with a value). Floras: 1,242,600 species-trait values in
48 traits; for the 13 traits GIFT also has, 369,579 of ours are for species without a GIFT value (flower colour 52,852 against
GIFT's 1,809 species; leaf length 69,147 new against 19,541; fruit type 25,459 against 6,566; height 45,842 against 70,293; habit
11,313 against 222,174). Photographs, for species with neither a flora nor a GIFT value: 221,075 values in 20 categorical traits at a
confidence where the predictions for agreed species of unseen genera are 90% right (leaf complexity 25,896, leaf persistence 23,456,
leaf position 22,720, spines 20,786, leaf attachment 18,722, stem hair 17,478, flower position 15,632). The count before the
confidence cut (1.04 million) includes traits that do not apply to a species and is not a result.

**Even comparison with PlantTraitNet, with intervals** (`try_even.py score`, bootstrap over species, 1,000 samples; ORIX
`try-even/even-scores-boot.json`): Spearman of ours minus PlantTraitNet on its field reference: height +0.053 (+0.030 to +0.078),
specific leaf area +0.155 (+0.084 to +0.257), leaf nitrogen +0.062 (-0.007 to +0.143), leaf area -0.007 (-0.048 to +0.031). On
species absent from its training set: height +0.102 (+0.064 to +0.144), specific leaf area +0.084 (+0.020 to +0.154), leaf area
-0.015 (-0.061 to +0.031), leaf nitrogen -0.030 (-0.116 to +0.046). No cell is lower beyond its interval. Adding TRY values on our
own photographs to the training changes nothing beyond the intervals (height +0.058, leaf nitrogen +0.044 on the whole reference).

## 23. Botanist-scored reference, error severity, flower colour and climate (2026-11-24)

**AusTraits v7.0.0** (Falster et al.; CC BY 4.0; `external/austraits`, Zenodo 10.5281/zenodo.15718081; values scored by botanists
from the Australian floras and field data; none of its sources is among our floras). `validate_external.py austraits`,
`external-austraits.json`. Flora values (set precision / recall / F1) and photograph predictions for unseen genera (balanced
accuracy on species with one value):

| AusTraits trait | floras: species | F1 | photographs: species | balanced accuracy (classes) |
|---|---|---|---|---|
| growth form | 2,497 | 0.875 | 2,849 | 0.894 (4) |
| life history | 1,968 | 0.857 | 2,906 | 0.881 (3) |
| fruit type | 1,302 | 0.893 | 2,283 | 0.644 (12) |
| leaf compoundness | 729 | 0.887 | 2,079 | 0.861 (2) |
| leaf phyllotaxis | 491 | 0.922 | 1,702 | 0.775 (3) |
| leaf margin | 795 | 0.806 | 1,668 | 0.689 (2) |
| leaf shape | 1,605 | 0.606 | 1,880 | 0.491 (8) |
| flower colour (their six groups) | 948 | 0.682 | 1,102 | 0.664 (6) |
| fruit colour | 606 | 0.618 | 920 | 0.271 (8) |
| leaf base | 533 | 0.732 | 847 | 0.544 (4) |
| stem growth habit (posture) | 1,063 | 0.760 | 1,247 | 0.645 (4) |
| leaf phenology | 71 | 0.805 | 510 | 0.712 (2) |
| leaf hairs | 64 | 0.759 | 95 | 0.812 (2) |
| growth substrate | 22 | 0.870 | 111 | 0.835 (2) |
| physical defence (spines) | 39 | 0.641 | 436 | 0.652 (2) |

Sizes, Spearman (floras / photographs): height 0.911 / 0.917, leaf length 0.827 / 0.804, leaf width 0.907 / 0.880, fruit length
0.961 / 0.873, fruit width 0.945 / 0.878, seed length 0.956 / 0.752; median factor between flora value and AusTraits 1.14-1.33.

**Are the mistakes semantically close?** (`applications.py errors`, `errors.json`; agreed species of unseen genera.) Of the wrong
answers, the share on a value next to the true one on its scale, against the share expected if wrong answers were spread as the
model's answers are overall: flower colour 0.303 against 0.112 (2.7 times), leaf margin 0.299 / 0.126 (2.4), life span 0.309 / 0.154
(2.0), posture 0.737 / 0.521 (1.4), leaf texture 1.35, leaf base 1.30, leaf shape 0.614 / 0.493 (1.25), leaf arrangement 1.17, leaf
apex 1.10; fruit colour, fruit shape and habit at chance. With a neighbouring value counted half: flower colour 0.770 (plain accuracy
0.730), leaf shape 0.713 (0.586), posture 0.814 (0.706), leaf apex 0.742 (0.592).

**Flower colour and climate** (`applications.py colour`, `colour.json`; 2-degree cells, 1,417 cells from floras and 1,777 from
photographs; Pearson r of the share of species with the colour). Floras / photographs: blue with temperature -0.40 / -0.32 and with
elevation +0.29 / +0.41; purple with temperature -0.41 / -0.44, with elevation +0.33 / +0.42; orange with temperature +0.39 / +0.57
and with absolute latitude -0.42 / -0.66; red with latitude -0.42 / -0.41; white with log precipitation +0.49 / +0.37; yellow with
log precipitation -0.46 / -0.43; green with elevation -0.30 / -0.47. Within species (floras allow white and a pigmented colour; 920
to 1,103 species with 30 or more observations): the predicted share of the pigmented colour does not change with temperature,
precipitation or latitude (48.8-51.2% of species positive) and barely with elevation (52.7%, z 1.8).

## 24. Identification with the place of the observation; image models trained without names; more seeds (2026-11-24)

**Place** (`baseline_v2.py --geo DIR`; `applications/obs-regions.tsv`, `species-regions.tsv` from `~/tmp/flopo-trait-vision/geo/regions.py`):
every observation is assigned to its botanical country (TDWG level 3 polygons, github.com/tdwg/wgsrpd; 92.4% of observations fall in
a polygon) and every species to the countries WCVP records it from (native and introduced; 32,690 of 33,281 photographed species;
median 7 countries; 95.3% of observations lie in a country listed for their species). A candidate that is not recorded from the
observation's country counts 0.02 (fixed rule) or with a learned weight. Run `baseline-v6/geo` (job 414248; predictions of s0).
On average 299 of the 1,553 candidates are recorded from the observation's country, the true species among them for 94.8%.

| rule (26 traits, sizes, counts) | first | first 5 | first 10 | within family: first |
|---|---|---|---|---|
| fixed rule | 0.113 | 0.317 | 0.435 | 0.309 |
| weights + value table | 0.135 | 0.357 | 0.479 | 0.336 |
| fixed rule + place | 0.209 | 0.484 | 0.608 | 0.424 |
| weights + place | 0.260 | 0.590 | 0.724 | 0.509 |
| weights + value table + place | 0.295 | 0.626 | 0.752 | 0.529 |
| place alone (within family) | 0.000 (0.123) | | | |

**Image models trained without taxon names** (`--emb`; job 414244; all three runs without observer labels and without fruit regions):

| image model | mean balanced accuracy, 26 traits | identification, fixed rule: first / 10 | weights + value table: first / 5 / 10 |
|---|---|---|---|
| BioCLIP 2 (trained on names of these species) | 0.696 | 0.112 / 0.437 | 0.137 / 0.356 / 0.481 |
| DINOv2 (images only, no text, no labels) | 0.653 | 0.071 / 0.307 | 0.083 / 0.246 / 0.354 |
| SigLIP 2 (web image-text) | 0.655 | 0.071 / 0.313 | 0.085 / 0.244 / 0.347 |

Height 0.914 / 0.898 / 0.901, leaf length 0.863 / 0.843 / 0.839 (Spearman). With an image model that never saw a species name, trait
accuracy drops by 0.04 and identification keeps about 60% of its level (8.3% first against a chance of 0.07%).

**Seeds of the learned identification** (full training, seeds 0, 1, 2; job 414255): weights + value table 0.135, 0.137, 0.138 first;
0.479, 0.478, 0.478 in the first ten.

**Fine classes** (`labels_extra.py labels DIR fine` -> `labels-v5-fine.tsv`; `baseline_v2.py --all-classes`; job 414334): a term stated
for 300 or more species is its own class under its coarse class (95 more classes: 17 flower colours, 10 fruit shapes, 8 kinds of
hairs for leaf and for stem, 6 leaf textures, serrate / dentate / crenate margins, ...); a colour stated as a basic colour allows
every finer colour under it (the ontology's subclasses). Same candidates and observations:

| labels | categorical, fixed: first / 10 | all, fixed | all, weights + value table: first / 5 / 10 | + place |
|---|---|---|---|---|
| standard (coarse) | 0.068 / 0.310 | 0.113 / 0.435 | 0.135 / 0.357 / 0.479 | 0.295 / 0.626 / 0.752 |
| fine | 0.078 / 0.326 | 0.119 / 0.441 | 0.143 / 0.367 / 0.488 | 0.302 / 0.626 / 0.758 |

Fine classes are the one label choice that raises identification beyond the seed spread (+1.0 point with categorical traits alone,
+0.8 with everything). **DINOv2 with place:** 0.212 / 0.519 / 0.660 (weights + value table). **Second seed with place:** 0.295 / 0.626 / 0.751.

**Flower colour with the family taken out** (`applications.py colour-family`, `colour-family.json`; flora values; every species' colour
share minus its family's mean, then cell means). r before / after: blue with temperature -0.40 / -0.46 (woody species alone -0.09 /
-0.45); purple with temperature -0.41 / -0.37 (herbs with elevation +0.48 / +0.51); white with temperature +0.25 / +0.40 and with
log precipitation +0.49 / +0.39; yellow with log precipitation -0.46 / -0.30; orange with temperature +0.39 / +0.21 and red +0.33 /
+0.19 (about half is turnover of families); green +0.33 / -0.02 (all of it is turnover of families). So the blue, purple, white and
yellow patterns hold inside families; orange and red hold in part; green does not.

## 25. Flower colour and climate: phylogeny, growth form, pollination proxies, sampling (2026-11-24)

Literature: `local-corpora/trait-vision-lit/11-flower-colour-climate/summaries.md` (largest earlier study found: Dellinger et al. 2025,
Am J Bot, doi:10.1002/ajb2.70044, global, 2,815 species in 51 clades).

**Species-level models with the phylogeny** (`applications.py colour-data` -> `colour-species.tsv`, `colour-countries.tsv`;
`flopo2/traitvision/colour_phylo.R` -> `colour-phylo.tsv`; R 4.5 with ape and phylolm in `~/tmp/flopo-trait-vision/Rlib`). Response: the
flora states the colour for the species (yes/no). Predictors, standardised: mean annual temperature, log precipitation, elevation and
solar radiation of the species' range (mean over the botanical countries WCVP records it from as native; no iNaturalist data), and
growth form (herb, woody, climber, mixed, unknown). Tree: Smith and Brown 2018 ALLMB (`applications/phylo`). Species of wind-pollinated
families left out. 42,633 species. Phylogenetic logistic regression (phyloglm, logistic_MPLE) / phylogenetic linear model with Pagel's
lambda (0.51-0.72); coefficient and significance (*** p < 0.001):

| colour | temperature | log precipitation | elevation | radiation | woody against herb |
|---|---|---|---|---|---|
| blue | -0.19** / -*** | -0.17** / n.s. | n.s. / +** | n.s. | -1.21*** |
| purple | -0.23*** / -*** | n.s. | n.s. | +0.19*** / +** | -1.02*** |
| pink | -0.32*** / -*** | -0.14*** / n.s. | -0.21*** / -*** | +0.28*** / +*** | -0.47*** |
| red | +0.36*** / +*** | +0.18*** / n.s. | +0.09** / +*** | -0.09** / -* | n.s. |
| orange | n.s. | +0.23*** / +** | n.s. | +0.51*** / +*** | -0.21* |
| yellow | -0.15*** / n.s. | -0.17*** / -*** | n.s. | +0.05** / n.s. | -0.42*** |
| white | -0.20*** / -* | +0.05** / +*** | -0.31*** / -*** | +0.26*** / +*** | +0.35*** |

Holding in both phylogenetic models: blue, purple and pink in colder ranges; red in warmer ranges; white in wetter and yellow in drier
ranges; orange with radiation and precipitation (not with temperature once radiation is in the model); white with low elevation.
Growth form matters (blue and purple are colours of herbs, white of woody plants and climbers) and is in the model.

**Pollination.** No global data set of pollination type was at hand. Proxies: wind-pollinated families left out (above); corolla shape
(tube against open) as a covariate for the 6,422 species with a stated corolla shape (`colour-phylo-corolla.tsv`): white with
precipitation (+0.15**), yellow with precipitation (-0.10*), blue with temperature (-0.22*), pink with temperature (-0.26**), orange
with radiation (+0.55***) and precipitation (+0.29**) remain; red with temperature does not (+0.01). Not done: AusTraits has a
pollination syndrome for about 9,000 Australian taxa, a direct check for one continent.

**Sampling** (`applications.py colour-bias`, `colour-bias.json`).
- Without iNaturalist: 298 botanical countries with 50 or more species (native species per WCVP, flora colours): blue with
  temperature r -0.50, purple -0.50, orange +0.64, red +0.50; white with log precipitation +0.66, yellow -0.68. Partial correlations
  given the other climate variables: white with precipitation +0.56, yellow -0.58, orange with precipitation +0.45, purple with
  temperature -0.29, blue with temperature -0.06 (blue with precipitation -0.33).
- Cells (2 degrees, iNaturalist observations): r is stable for 10, 20 or 50 species per cell, with the numbers of observations and
  species taken out, and with a bootstrap over 10-degree blocks: blue -0.40 (-0.49 to -0.30), purple -0.41 (-0.49 to -0.32), orange
  +0.39 (+0.31 to +0.45), red +0.33 (+0.24 to +0.42), white with precipitation +0.49 (+0.43 to +0.54), yellow -0.46 (-0.52 to -0.40).
- By continent (Africa and Arabia, Asia, Australasia, Europe, North America, South and Central America): white with precipitation
  +0.50, +0.61, +0.31, +0.31, +0.46, +0.27; yellow -0.59, -0.42, -0.25, -0.39, -0.51, -0.24; blue with temperature -0.26, -0.51, -0.41,
  -0.18, -0.04, -0.18; purple -0.22, -0.57, -0.05, -0.22, -0.18, -0.08; orange -0.26, +0.47, +0.27, +0.52, +0.27, +0.09; red +0.24,
  +0.27, +0.46, -0.11, +0.64, +0.04.

Reading: white flowers in wet places and yellow flowers in dry places hold in every test (phylogeny, growth form, corolla shape,
without iNaturalist, every continent). Blue, purple and pink in cold ranges hold with the phylogeny but are uneven between continents.
Red in warm ranges holds with the phylogeny, not in the corolla subset. Orange follows radiation and precipitation.

## 26. More hypotheses tested with the flora values (2026-11-24)

Literature scan by a Sonnet agent: `local-corpora/trait-vision-lit/12-hypotheses/summaries.md` (short; most references unconfirmed).
Its candidates: trait-to-gene scan, dioecy correlates, genome size, fruit colour, invasiveness and threat, island rule, spines,
hairiness, zygomorphy, flowering time. Not testable here: dioecy (no sexual system among the 26 traits), genome size and chromosome
numbers (the Kew C-values site refuses automated download, CCDB not reachable).

Code: `flopo2/traitvision/macro.py` (`table` writes `applications/species-traits.tsv`, 118,803 species; `island`),
`flopo2/traitvision/macro_phylo.R` (`applications/macro-phylo.tsv`). All values are flora values; climate is that of the native
range (WCVP botanical countries); estimates are per standard deviation with the tree of Smith and Brown (2018).

| test | species | result with phylogeny | earlier work found |
|---|---|---|---|
| flower size against flower number (height, growth form in the model) | 6,992 | -0.17 (p 1e-28); -0.19 without phylogeny | Sargent et al. 2007: 251 species; Lanuza et al.: 1,506 species |
| flower size against leaf area | 13,185 | +0.21 (p 1e-123) | |
| flower size against seed length | 6,892 | +0.36 (p 1e-95) | |
| stamen number against flower size | 5,450 | +0.23 (p 1e-110) | |
| principal components of height, leaf area, seed length, petal length | 5,771 | first axis 59% (plant, leaf, seed size); second 22%, petal length alone (loading 0.93); petal length with height r 0.14 | E-Vojtko et al. 2022: European forbs |
| hairy leaves against climate | 30,561 | precipitation -0.24 (p 1e-29), elevation +0.16 (p 1e-23), temperature and radiation weak | no global test found |
| flower size against climate | 18,362 | precipitation -0.03 (p 0.001), temperature none | |
| seed length against climate | 13,664 | temperature -0.02, precipitation +0.01; without phylogeny +0.06 and -0.05 | |
| fleshy fruit against climate | 21,132 | precipitation +0.02 (p 0.004); without phylogeny +0.49 | |
| annual against climate | 19,211 | temperature +0.38, precipitation -0.12 | known (235,000 species) |
| succulent leaves | 25,280 | precipitation -0.89 | known |
| climber | 53,613 | temperature +0.57 | known |
| leaf area, height against precipitation | 36,887; 53,255 | +0.14; +0.10 | known |

Islands (endemics of oceanic or long-isolated islands against mainland congeners; our floras hold few island species): 83 genera,
191 island species for height: island species taller by 0.085 log10 units (0.006 to 0.162), woody share +7.8 points (3.4 to 12.9;
85 genera), annual share -10.7 points (30 genera); island rule for height (small genera larger, large genera smaller on islands):
slope -0.16 against a null of -0.02 (-0.14 to +0.10) from random splits of the mainland species, p 0.007; leaf area -0.14, p 0.054;
seed, fruit, petal size: nothing. Same size as Biddick et al. 2019 (175 taxa), so no gain in scale.

Flower colour with a recorded pollinator (GIFT; 1,783 species with insect pollination and a tree tip, mostly European sources):
white with precipitation +0.035 (p 0.63), yellow -0.067 (p 0.34): same signs as in the 42,633 species (+0.053 and -0.171), too few
species to decide. AusTraits pollination: only 256 of its species have a flower colour from our floras. The species-level effects
of section 25 are small (0.05 to 0.17 logit per standard deviation of precipitation); the large correlations are those of floras
(cells, countries).

### Traits against gene families (UniProt proteomes)

Data: UniProt lists 634 proteomes of vascular plants (411 species); 309 species have one with BUSCO completeness of 80% or more;
23 of these are retired and come back empty, 286 remain, 280 with a tip (own or congener) in the tree. Per proteome the number of
proteins in each Pfam family, PANTHER family and PANTHER subfamily (`applications/genes/`, `fetch.sh`, `genes.py matrix`). Trait
values: flora value of the species, else of the genus when three or more species have one and 90% agree; 102 to 252 species per
trait (species-level flora value alone: 237 species with any trait). Controls from GIFT: nitrogen fixation (25 of 192 species),
C4 photosynthesis (13 of 242). Test (`genes_scan.R`, `genes/scan.tsv`): log2(copies + 1) of a family against the trait, with
proteome size and completeness, Pagel's lambda, Benjamini-Hochberg per trait; about 32,000 families per trait, 12,400 without
subfamilies.

Result: nothing usable.
- With subfamilies: nitrogen fixation 1,305 families, C4 111, woody 61, fleshy fruit 31, climber 8, blue or purple flowers 4, at
  q < 0.05. These are subfamilies that exist in one lineage only (legumes, one grass clade; lambda estimated as 0), so they follow
  ancestry.
- Whole families only (`genes/scan-families.tsv`): nitrogen fixation 34, fleshy fruit 8, C4 6, stamen number 2, woody 1, all other
  traits 0. The control hits are not the known genes (no NIN or RPG for nodulation, no PEPC, PPDK or malic enzyme for C4); the
  fleshy-fruit hits are housekeeping families with slightly more copies (lambda 0), as expected from genome duplication in a few
  fleshy-fruited lineages.
- Reading: 100 to 250 sequenced species per trait, few independent origins of each trait among them, and copy numbers from
  unequal annotations do not support a trait-to-gene scan. It would need orthogroups built from the sequences, tests per
  independent origin, and more genomes. The trait catalogue is not the limit here; the number of genomes is.

### Sexual system and checks of the flower size results (2026-11-24, later)

Sexual system is in the catalogue (statements on the whole plant or flower), though not among the 26 traits: 5,758 species with
one stated system (1,943 dioecious, 950 monoecious, 2,865 bisexual); `macro.py table` now writes `dioecious`, `sex`, `pale_flower`.
`Rscript flopo2/traitvision/macro_phylo.R local-corpora/trait-vision/applications flowers` writes `macro-phylo-flowers.tsv`.
- Dioecy (2,641 species with tree tip and growth form): woody +0.52 logit with phylogeny (p 2e-5); fleshy fruit +0.42 (p 0.07; 982
  species); pale (white or green) flowers +0.13 (p 0.25); climate nothing; seed length +0.15 (p 7e-4; 860 species); petal length
  nothing. Known correlates, same scale as earlier work, not used in the paper.
- Flower size against number with phylogeny: herbs -0.18 (1,793 species), woody -0.14 (2,394), flower diameter in place of petal
  length -0.13 (2,447), without solitary flowers -0.16 (6,669), with leaf area in the model -0.25 (5,234); within families:
  negative in 32 of 49 families with 30 or more species, median r -0.12 (`applications/flower-axis.json`). Flower number is per
  inflorescence.
- Flower axis after removing family means (5,524 species): first component 51%, second 22% with petal length -0.81.
- Hairy leaves: precipitation -0.31 in herbs (5,612 species) and -0.29 in woody species (11,252); elevation +0.21 in woody
  species only; temperature +0.33 and +0.20.

Paper draft `paper/trait-vision/main.tex` (12 pages) updated: AusTraits, control with DINOv2, identification with place, fine
classes, error severity; application sections are now (1) known trait-climate relations, (2) flower colour and climate, (3) flower
size, number and the separate axis, (4) new database values. The gene scan and dioecy are left out.

## 27. Uses of the photograph models: within species, land cover, native and introduced range, curation (2026-11-24)

Code: `flopo2/traitvision/within.py` (`context`, `slopes`, `ranges`, `habitat`, `adjusted`); outputs `applications/obs-context.npz`,
`within-slopes.json`, `within-ranges.json`, `within-habitat.json`, `within-adjusted.json`, `curator.json`.

Context per observation: climate and elevation (WorldClim 2.1, 10 arc-minutes), land cover of the 1-km cell (EarthEnv consensus
land cover, Tuanmu and Jetz 2014, 11 classes in percent; `applications/landcover/`), observer (95,529), day of year, native or
introduced range (WCVP by botanical country: 525,012 native, 31,432 introduced, 27,414 neither). OpenStreetMap was not used:
641,883 point queries are not practical; the land cover raster gives urban, cultivated, tree, shrub and herbaceous cover.
`obs-pred.npz` holds at most 30 observations per species.

Every analysis removes the species mean. Signals in units of the standard deviation between species; climate in standard
deviations (temperature 6.9 C ... see `within-slopes.json`). 15,157 species with 30 observations, 454,710 observations.

Control traits (cannot differ between plants of one species) respond like the traits that can:

| signal | within species: temperature | precipitation | between species: temperature | precipitation |
|---|---|---|---|---|
| height | +0.026 | +0.019 | +0.33 | +0.21 |
| leaf area | +0.006 | +0.038 | +0.12 | +0.40 |
| hairy leaves | +0.038 | -0.037 | +0.06 | -0.26 |
| fleshy leaves | +0.021 | -0.083 | +0.08 | -0.56 |
| evergreen | +0.098 | +0.011 | +0.14 | +0.09 |
| control: annual | +0.098 | -0.019 | +0.27 | -0.26 |
| control: epiphytic | -0.032 | +0.064 | +0.22 | +0.38 |
| control: berry | +0.015 | +0.029 | +0.18 | +0.33 |
| control: opposite leaves | +0.001 | -0.022 | +0.20 | +0.00 |

All intervals (bootstrap over species) are about +-0.005 to 0.01. The within-species response is about a tenth of the relation
between species for varying and for control traits alike, and it has the sign of the relation between species. So the heads on
whole-photograph embeddings read part of their answer from what surrounds the plant (or from the look of the place), and the
within-species results of section 22 (leaf area with precipitation in 62% of species) cannot be read as variation of the plants.
With the eight control signals as covariates the slopes hardly change (the controls explain 2 to 8% of the within-species
variance of a signal), so the surroundings do not act through one shared axis that could be regressed out.

Land cover within species (per 100% cover; climate, season, number of photographs in the model): height +0.05 with tree cover,
+0.06 urban; leaf area +0.06 tree cover, +0.08 urban; fleshy leaves -0.20 tree cover; controls again of the same size (annual
+0.11 urban, epiphytic +0.11 urban, capsule +0.05 tree cover).

Native against introduced range (1,239 species with 5 or more observations in each; 30,685 observations; climate in the
model): height +0.018 (0.008 to 0.028), leaf area +0.019, hairy leaves -0.041, evergreen +0.049; controls: capitulum -0.039,
epiphytic +0.031, compound leaves -0.021. Same reading.

Next: the same analyses on predictions from crops of the leaf, flower and fruit (job 414888: `crop-leaf`, `crop-flower`,
`crop-fruit` under `baseline-v6/`), where the head sees the organ and little of the surroundings.

### The model as a check on trait values

Species with one flora value, a prediction from photographs (genus unseen in training) and a GIFT value from a source that is
not ours (`applications/curator.json`):

| trait | species | floras and GIFT disagree | AUC of the model for these | where the model contradicts the flora (p < 0.5): species, GIFT disagrees, share of all disagreements |
|---|---|---|---|---|
| habit (herb / woody) | 9,280 | 2.9% | 0.87 | 437, 26%, 43% |
| life span (annual / perennial) | 5,441 | 2.6% | 0.78 | 564, 12%, 46% |
| epiphytic / terrestrial | 558 | 9.7% | 0.73 | 49, 29%, 26% |

Checking the 5% of habit values that the model contradicts finds 43% of the conflicts with GIFT, nine times the base rate.

### The same on crops of the organ (job 414891, GPU use 81%)

`flopo2/traitvision/crop_to_photo.py` averages the crop embeddings of a photograph (crop id = photo id * 16 + k);
`tools/orix/traitvision_pcrop.sbatch` trains the heads on them (`baseline-v6/pcrop-leaf`, `pcrop-flower`, `pcrop-fruit`; 343,338
photographs with a leaf crop, 432,323 with a flower crop). Leaf crops, agreed species: leaf hair 0.815, leaf complexity 0.817,
leaf margin 0.688. Within species (`python -m flopo2.traitvision.within slopes pcrop-leaf`; 607 species with 20 observations,
13,005 observations; flower crops 1,432 species, 30,968 observations):

- leaf crops: leaf area with precipitation +0.096 (0.055 to 0.139), fleshy leaves -0.118, hairy leaves -0.063, hairy leaves with
  elevation +0.075; controls: annual with temperature +0.126 (0.040 to 0.216), berry +0.092 and +0.062, epiphytic with
  precipitation +0.050.
- flower crops: hairy leaves with temperature +0.080, woody +0.045; controls: epiphytic with precipitation +0.043.

The control traits respond on crops as well. A control response therefore has two possible sources that this design cannot
separate: surroundings that remain in the crop, or leaves that look different in a dry place and are then read as the leaves of
an annual or a succulent. Either way a within-species shift of a predicted trait is a shift in how the photograph looks, and it
needs measured values on single plants to be read as a trait. Observers recorded no sizes (iNaturalist fields: growth form,
flower colour, leaf margin, leaf arrangement, thorns, fruit colour); the one trait with a check on single observations is flower
colour (section 22: 72.4% against 64.7% shuffled).

Paper: the sentence on leaf area within species is removed; the check of database values by the model is added.

## 28. Flower colour forms within species (2026-11-25)

Question: can the flower-colour model read the colour form of a single photographed plant in a species it never saw, well enough
to map colour forms over the range of a species? Code: `flopo2/traitvision/colour_cline.py` (`select`, `analyse`),
`colour_cline_fit.py` and `tools/orix/traitvision_cline.sbatch` (ORIX job 415916). Data: `local-corpora/trait-vision/cline/`.

Design. 115 species: 55 with a published flower colour polymorphism and 60 heavily observed species for which the floras give two
or more colours. Up to 2,500 research-grade observations each (at most 20 per observer), 281,141 photographs, 280,587 embedded.
The colour head was trained on 15,783 species, leaving out all 93 genera of the 115 species. On 920 other held-out species with
one agreed colour it gives 69.7% accuracy (balanced 41%).

Colour forms by region (photographs with a top probability above 0.6):

| Species | Region | Photographs | Predicted forms | Published |
|---|---|---|---|---|
| Raphanus raphanistrum | Europe north of 50 N | 245 | yellow 82%, white 14% | yellow in the north, white in the south (Flora Europaea) |
| | Mediterranean | 153 | yellow 59%, white 33% | |
| | western North America | 699 | purple 47%, white 36%, yellow 15% | Californian wild radish is of hybrid origin with R. sativus (reference to verify) |
| | eastern North America | 167 | yellow 91% | |
| Iris lutescens | Iberia | 231 | purple 96%, yellow 0% | Spanish populations purple only |
| | southern France (3 to 7.5 E) | 1,172 | yellow 50%, purple 45% | polymorphic, yellow share 0 to 1 |
| | Italy | 99 | purple 75%, yellow 25% | polymorphic |
| Dactylorhiza sambucina | all | 2,495 | yellow 67%, pink 27% | yellow and red-purple forms |
| Gentiana lutea | north-west Iberia | 152 | mean orange probability 0.057 against 0.003 elsewhere | orange in north-west Iberia |

Lysimachia arvensis could not serve as the test: iNaturalist files the blue form as L. loeflingii, and 1% of the L. arvensis
photographs are read as blue. Parrya nudicaulis (653 photographs): purple 80%, white 12%; the published increase of white with
summer temperature in Alaska is not seen (white against temperature -0.07, interval -0.19 to +0.03).

Climate across species. Contrast pigmented (blue, purple, pink, red) against white, within species, 61 species with both forms:
mean within-species correlation with temperature -0.02 (interval -0.04 to 0.00), precipitation -0.04 (-0.06 to -0.01), elevation
+0.045 (0.023 to 0.069; positive in 46 of 61). Control: the same contrast in species for which the floras give one colour only
(section 27 corpus, 20 or more observations per species): elevation +0.012 (white only, 2,097 species), +0.021 (pigmented only,
2,244), +0.017 (yellow only, 2,445); in the 54 other downloaded species +0.031. The elevation trend in the colour-form species is
two to three times the control, with overlapping intervals. Temperature and precipitation show no trend beyond the control, so the
herbarium result of Sullivan and Koski 2021 (less pigment where warmer, more where drier, 12 species) is not reproduced.

Reading: the model maps discrete colour forms of unseen species and recovers the published geography of two species; climate
trends shared across species are weak and close to the size of the photograph effect.

### 28b. All traits within the 115 species, and the plan for 1,000 species (2026-11-25)

Literature (web search, 25 Nov 2026): single-species studies map flower colour from iNaturalist photographs (Monarda fistulosa,
Encelia farinosa, Convolvulus arvensis, Leptosiphon parviflorus); one preprint assigns one colour per species to 11,729 North
American species with GPT-4V. No study found that maps colour forms within many species, and none for other traits.

`flopo2/traitvision/trait_atlas_fit.py` (ORIX job 416055, `tools/orix/traitvision_atlas.sbatch`): 26 categorical traits, five
folds over genera, each photograph predicted by the head trained without its genus -> `cline/pred-all.npz`.
`flopo2/traitvision/atlas_scan.py cline` -> `cline/atlas-scan.tsv`: per trait and species the two most frequent predicted forms
among confident photographs (top probability above 0.6, above 0.8 for two-class traits), and the share of the variance between
them that 2-degree cells explain, against the 99th percentile of 100 permutations.

Species with a second form at 10% or more and regional structure more than 0.1 above the permutation level: flower colour 15 of
110; leaf persistence 8; leaf apex 7; fruit type, leaf base, leaf margin, stem hair 4 each; habit, life span, substrate, spines 0.
The traits that cannot vary within a species (habit, life span, substrate) show no strong regional structure, in contrast to
the small shifts of section 27. Fruit type shows structure in species with regional colour forms (Aquilegia coerulea,
Leptosiphon parviflorus), so a pattern in another trait can be carried by the colour form or by the organ in view; an atlas
needs a filter for this. Candidates that agree with described infraspecific taxa (to verify): Vaccinium vitis-idaea erect
against prostrate (R2 0.33), Castilleja miniata hairy against glabrous (0.32), Antirrhinum majus leaf hair (0.29).

Running: 1,000 most observed labelled species (at least 9,830 research-grade observations each), 1,000 photographs each
(`atlas/`); pimpernel aggregate, 6,000 observations over Lysimachia arvensis (65,749) and L. loeflingii (8,035) (`cline2/`).

### 28c. Scarlet and blue pimpernel (2026-11-25)

`colour_cline.py select_pair` -> `cline2/` (hash sample of 6,000 research-grade observations over Lysimachia arvensis and
L. loeflingii, 5,999 photographs); all-traits heads without the genus (Lysimachia and Anagallis in one fold; ORIX job 416071).
Blue = P(blue)+P(purple) above P(red)+P(orange)+P(pink).

Against the iNaturalist identification (10.9% filed as the blue species): agreement 98.6%, 99.2% of the blue species read as
blue, 1.5% of the scarlet read as blue, AUC 0.994.

Native range (longitude -12 to 45, latitude 28 to 62; 1,995 observations), predicted blue share by latitude: 28-38 N 55%
(identified 52%), 38-43 N 18% (15%), 43-48 N 4% (3%), 48-62 N 0%. Correlation of predicted blue with temperature +0.47
(1-degree block bootstrap 0.41 to 0.55), solar radiation +0.38 (0.30 to 0.49), log precipitation -0.26 (-0.33 to -0.18),
latitude -0.48 (-0.54 to -0.42); the identifications give the same values within 0.01. All four are in the direction of
Arista et al. 2013 (blue increases with temperature and sunshine, decreases with precipitation and latitude).
