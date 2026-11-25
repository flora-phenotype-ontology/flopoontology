# Trait recognition from photographs: results as of 24 November 2026

One page of the main findings. Details, jobs and files are in `flopo-trait-vision-training-tests.md` (sections in brackets) and
`flopo-trait-vision-sota.md` (marked "sota"). The paper draft is `paper/trait-vision/main.tex`.

## Setting

- 1.01 million research-grade iNaturalist photographs of about 33,000 species; frozen BioCLIP 2 image embeddings.
- Labels from 39 floras (vascular plants, every description once): 681,236 species-trait labels for 112,712 species in 26
  categorical traits; sizes and counts for 106,251 species (10 sizes, 10 counts). No hand labels.
- All photograph results are for genera that the trait heads never saw (five folds over genera). The species name is a training
  label only.

## 1. Traits from photographs

| what | result | where |
|---|---|---|
| 26 categorical traits, balanced accuracy on species where two floras agree | 0.35 (fruit colour) to 0.94 (substrate); mean 0.698; seed spread 0.002 | [17] |
| sizes, Spearman with the flora value | 0.79 to 0.91 (height 0.91, leaf width 0.90) | [13, 18] |
| counts, Spearman | 0.22 (sepals) to 0.83 (leaflets) | [13, 18] |
| against GIFT values from sources that are not ours | habit 0.78 (22,193 species), life span 0.80, substrate 0.88, height Spearman 0.92 | [17] |
| family-majority guess (true family given) | below the photograph model on 25 of 26 traits | [17] |
| BioCLIP 2 with trait prompts, no training | far below (habit 0.60 against 0.89, leaf shape 0.17 against 0.53) | [18] |
| PlantTraitNet benchmark, trained on its photographs, Spearman on its field reference | height 0.888 against 0.835, specific leaf area 0.602 against 0.447, leaf nitrogen 0.459 against 0.397, leaf area 0.737 against 0.744 | sota 11 |

## 2. Species identification from traits (unseen genera, 1,553 candidates per observation)

| method | first | first 5 | first 10 | where |
|---|---|---|---|---|
| chance | 0.0007 | | | |
| BioCLIP 2 + trait prompts | 0.003 | 0.014 | 0.025 | [18] |
| BioCLIP 2 + flora text of the candidates | 0.009 | 0.024 | 0.037 | [18] |
| trained heads, fixed rule, 26 traits | 0.068 | 0.209 | 0.310 | [17] |
| + sizes and counts | 0.113 | 0.317 | 0.435 | [17] |
| + weights per trait learned on other genera | 0.121 | 0.329 | 0.450 | [21] |
| + value table per trait learned on other genera | 0.135 | 0.357 | 0.479 | [21] |
| flora values read exactly (ceiling) | 0.99-1.00 | | | [17] |
| BioCLIP 2 given the species name (it has seen the species) | 0.823 | 0.951 | 0.970 | [18] |

Within the family (60 candidates): 0.309 with the fixed rule, 0.336 with the learned one. Closest published result: Rodriguez et al.
(WACV 2024), 12% first and 38% in the first ten among about 1,490 unseen bird species from text descriptions.

## 3. What the semantic choices add [17, 19, 21]

| choice | effect on identification (first / first 10) |
|---|---|
| sets of values ("or") instead of one value | +0.9 / +1.9 points |
| species bags instead of single photographs | +1.0 / +2.3 points |
| fixed partial credit for neighbouring values | -1.3 / -5.2 points |
| value table learned per trait (neighbours from the data) | +1.4 / +2.9 points over learned weights |
| grouping of terms under a class | +0.4 / +1.2 points |
| colour hierarchy of the ontology | +0.2 / +0.9 points |
| position and stage statements left out; rare values left out; linear from length : width; size ranges | no measurable difference |

## 4. Extraction from the floras

| check | result | where |
|---|---|---|
| larger model (Opus) reads 3,643 statements against the source | 83.0% correct (before the scope and position fixes) | [15] |
| two floras on the same species | mean kappa 0.75 | [16] |
| GIFT, sources not ours | habit F1 0.84 (31,690 species), life span 0.91, height Spearman 0.94 | [16] |
| Marcos et al. 2025, same species-trait pairs, F1 ours minus theirs | West Africa +0.050 (+0.034 to +0.067), Caribbean -0.024 (-0.106 to +0.053), palms +0.045 (-0.057 to +0.143); their coverage 61% against our 38% in West Africa | [20] |
| Domazetoski et al. 2025 measure against GIFT | ours macro precision 0.82, recall 0.88 without GIFT training; theirs 0.91 and 0.89 with it | [20] |

## Open before submission

- The 83% judge figure predates the cleanup and has to be measured again.
- New runs of section 21 have one seed.
- BioCLIP 2 has seen the test species with their names; "unseen" holds for the trait heads and labels.
- Flower and leaf regions (as done for fruit) have not been run.
- Regional case study and trait maps are not started.
- FloraTraiter and the Australian Asteraceae set are not compared.

## 5. Applications (section 22 of the test notes)

- Trait-climate relations on 2-degree cells (641,883 observations): 10 of 12 known relations recovered from photographs with |r| > 0.5
  (entire leaf margin with temperature r 0.74; flora values r 0.78, slope 0.026 per degree; also from species without a flora value).
- Within species: leaf area rises with precipitation in 62% of 4,275 species; flower colour follows observers' values (72% against
  65% shuffled).
- Added to GIFT: 369,579 flora values for species without a GIFT value in 13 shared traits; 221,075 photograph-only values at 90% precision.
- PlantTraitNet benchmark with intervals: ahead beyond sampling error on height and specific leaf area, level on leaf area and leaf
  nitrogen, also on species absent from its training; adding TRY values on our photographs gives nothing more.

## 6. Added on 24 November, evening (sections 23-24 of the test notes)

- **Botanist-scored reference (AusTraits v7, Australian flora, independent of our floras):** flora values F1 0.86-0.92 for growth form,
  life history, fruit type, leaf compoundness, phyllotaxis (0.61 leaf shape); photographs of unseen genera: balanced accuracy 0.89
  growth form, 0.88 life history, 0.86 compoundness; sizes Spearman 0.83-0.96 (floras), 0.75-0.92 (photographs).
- **Identification with the place of the observation** (WCVP distribution by botanical country, 299 of 1,553 candidates remain):
  29.5% first, 62.6% in the first five, 75.2% in the first ten; within the family 52.9% first. Two seeds agree to 0.001.
- **Fine classes through the ontology:** 14.3% first without place (13.5% coarse), 30.2% with place.
- **Image model that never saw a species name (DINOv2):** traits 0.65 against 0.70; identification 8.3% first without place, 21.2% with.
- **Mistakes are semantically close:** wrong flower colours fall on a neighbouring colour 2.7 times as often as chance; leaf margin 2.4,
  life span 2.0, posture 1.4, leaf shape 1.25.
- **Flower colour and climate (53,565 species):** blue and purple flowers in cold and high places, orange and red at low latitudes,
  white where it is wet, yellow where it is dry; the same from floras and from photographs. No change within species.

## 7. Flower colour and climate, tested (section 25)

42,633 species with the phylogeny, growth form, elevation and radiation in the model, wind-pollinated families left out: white in
wetter and yellow in drier ranges, blue / purple / pink in colder ranges, red in warmer ranges, orange with radiation. White-wet and
yellow-dry also hold without iNaturalist data (298 botanical countries, r +0.66 and -0.68), with corolla shape as a covariate, and on
all six continents. Largest earlier study found: 2,815 species.

## 8. Further hypotheses (section 26)

- Flower size against flower number: -0.17 standard deviations per standard deviation with the phylogeny, 6,992 species (largest
  earlier tests found: 251 and 1,506 species).
- Flower size is its own axis: in 5,771 species the first component (59%) is plant, leaf and seed size, the second (22%) is petal
  length alone; flower size still rises with leaf area (+0.21; 13,185 species) and seed length (+0.36; 6,892 species).
- Hairy leaves: more frequent in dry ranges (-0.24) and at high elevation (+0.16), 30,561 species; no global test found.
- Confirmed at larger scale, known before: annuals in hot dry ranges, climbers in warm ranges, large leaves and tall plants in wet ranges.
- Islands: taller, more woody, fewer annuals than mainland congeners, island rule for height; only 191 island species, no gain in scale.
- Gene families of 286 sequenced species against the traits: no usable association; the controls (nitrogen fixation, C4) do not
  recover their known genes.
- Not testable here: dioecy (trait not extracted), genome size (database not downloadable).
