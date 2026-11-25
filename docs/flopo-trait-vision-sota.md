# Trait recognition from photographs: published models and benchmarks, and the comparison prepared for them

State on 22 November 2026. Search, download and preparation only: **no comparison has been run and no Slurm job has been
submitted.** Every reference below was checked against its source page (Crossref record, arXiv abstract page, Hugging Face API,
figshare/Zenodo API, GitHub) on 22 November 2026; what could not be checked is marked *unverified*.

The foundation models already compared in the pilot (BioCLIP 2, BioCLIP 1, BioTrove, DINOv2, SigLIP 2, PlantCLEF DINOv2) are not repeated
here; they remain the frozen-encoder baselines (`embed_any.py`, `docs/flopo-trait-vision-training-tests.md`).

## 1. Result of the search in one paragraph

No published model recognises the **categorical morphology** of our pilot (habit, flower colour, leaf margin, simple versus compound,
leaf arrangement, spines, inflorescence type, fruit colour) from photographs, and no public photograph benchmark carries image-level
human labels for them (also found by the earlier literature round, `local-corpora/trait-vision-lit/5-baselines-benchmarks`). The
closest published work is of two kinds. (a) **Continuous functional traits with weak species-level labels from a trait database**
(Schiller et al. 2021; PlantTraitNet 2026): the same weak-supervision idea as ours, with TRY instead of floras, and with released weights
and a released benchmark. (b) **Per-image phenology** (PhenoVision, PhenoVisionL): flower, fruit and leaf presence, trained on
iNaturalist's human phenology annotations, with released weights. These two are what could be downloaded and prepared. Everything else
found is another organism (VLM4Bio, Fish-Vista, Bio-VQA, the sparse-autoencoder trait annotation), a competition without public weights
(PlantTraits2024), a labeller rather than a model (GPT-4V flower colour), or species identification only (PlantCLEF 2025/2026).

## 2. Candidates

Weights and benchmark columns say what is public. "Downloaded" gives the ORIX path (all below `/mnt/data/u/hohndor/flopo-vision/`).

| # | Work (verified reference) | Predicts | Weights / code (licence) | Benchmark and reported score | Downloaded |
|---|---|---|---|---|---|
| 1 | **PhenoVision.** R. Dinnage, E. Grady, N. Neal, J. Deck, E. Denny, R. Walls, C. Seltzer, R. Guralnick, D. Li (2025). *Methods in Ecology and Evolution* 16(8):1763-1780, doi:10.1111/2041-210X.70081 (Crossref). Preprint bioRxiv 10.1101/2024.10.10.617505 | per photograph: flower present, fruit present (categorical, presence only) | HF `phenobase/phenovision`, ViT-L/16 fine-tuned from a PlantCLEF-2022 checkpoint, 1.21 GB, **MIT**; code github.com/Phenobase/phenovision (R targets pipeline; no LICENSE file seen in the listing, *unverified*); machine annotations of iNaturalist to March 2024: Zenodo 10.5281/zenodo.15306421, 12.9 GB, CC BY 4.0 | 20% genus-stratified test split (306,919 images) of 1,535,930 research-grade iNaturalist photographs with the community's own annotations. Card v1.1.0: accuracy flower 98.0%, fruit 97.0% (after removing an "equivocal" band); thresholds flower 0.48, fruit 0.60; expert check 98.6% / 90.4%. The preprint abstract says 98.5% / 95%. The test-image list is not distributed (*unverified*); the human annotations are on iNaturalist/GBIF | yes, `sota-models/phenovision/hf` (+ code clone) |
| 2 | **PhenoVisionL.** E. L. Grady, E. G. Denny, C. E. Seltzer, J. Deck, D. Li, R. Dinnage, R. P. Guralnick (2026). *Applications in Plant Sciences* 14(5), doi:10.1002/aps3.70067 (Crossref). Preprint bioRxiv 10.1101/2025.09.26.678778 | per photograph: green leaves, coloured leaves, breaking leaf buds | HF `phenobase/phenovisionL`, **MIT**, same architecture | 165,988 annotated records; >98% green and coloured leaves, >87% breaking buds (abstract, via search record) | yes, `sota-models/phenovisionL/hf` |
| 3 | **PlantTraitNet.** A. Sharma, J. Trost, D. Lusk, J. Dollinger, J. Schrader, C. Rossi, J. Lopatin, E. Laliberté, S. Haberstroh, J. Eichel, D. Mederer, J. M. Cerda-Paredes, S. S. Phartyal, L.-M. Schwarz, A. Linstädter, M. C. Caldeira, T. Kattenborn (2026). *Proc. AAAI* 40:39239-39248, doi:10.1609/aaai.v40i46.41272 (Crossref); arXiv:2511.06943 v3 (19 May 2026) | **continuous**: plant height, leaf area, SLA, leaf nitrogen, per photograph, with an uncertainty; input image + location (DINOv2-B, a depth-encoder, Climplicit) | HF model `ayushi3536/PlantTraitNet`: 3 multi-trait + 12 single-trait checkpoints, 1.83 GB each, licence tag **cc-by-nc-sa-4.0**; code github.com/GeoSense-Freiburg/PlantTraitNet, **MIT**; dataset HF `ayushi3536/PlantTraitNet`, 924 GB, CC BY 4.0 | Trained on about 220k images / 5k species with TRY species quantiles as weak labels; validated against sPlotOpen plot trait means on a 1-degree grid, 300k uncurated photographs, >890 cells: R2 / r = height 0.18 / 0.45, leaf area 0.34 / 0.57, SLA 0.27 / 0.59, leaf N -0.12 / 0.50 (refined model, Table 1 of v3). The released repository has no target scaler (`scalar.pkl`) | weights: 3 multi-trait + 4 single-trait seed-0 (12.8 GB); dataset: labels, trait maps, in-situ reference data, validation subset (see section 3) |
| 4 | **Schiller et al.** C. Schiller, S. Schmidtlein, C. Boonman, A. Moreno-Martínez, T. Kattenborn (2021). Deep learning and citizen science enable automated plant trait predictions from photographs. *Scientific Reports* 11:16395, doi:10.1038/s41598-021-95616-0 (Crossref) | **continuous**: growth height, leaf area, leaf N, SLA, seed mass, stem specific density, per photograph (image + 6 WorldClim variables) | figshare 10.6084/m9.figshare.13312040: Keras HDF5, 3 architectures x 6 traits (18 networks), 3.8 GB, **CC BY 4.0**; code github.com/ChrSchiller/cnn_traits (R), **CC0** | iNaturalist photographs (up to 8 per species) with TRY species means; 3-fold CV of the ensembles: R2 growth height .58, leaf area .45, LNC .16, SSD .2 (own PDF, p. 3). Image tables and TRY means: figshare 14410379 (CC BY 4.0; the TRY file itself, 3 MB) | yes: `sota-models/schiller2021/weights` + raw tables in `sota-benchmarks/schiller2021` |
| 5 | **PlantTraits2024** (FGVC11, Kaggle, CVPR 2024 workshop): over 70,000 iNaturalist images with ancillary data, TRY trait targets, six traits (site page: sites.google.com/view/fgvc11/competitions/planttraits2024). Write-ups: Ignesti, Moroni, Martinelli (2024) *Annals of CSIS* 39:625-630, doi:10.15439/2024F8703 (Crossref) | continuous (six traits) | no official weights. A first-place repository exists (github.com/dysdsyd/PlantTraits2024, MIT; no weights or score stated) | data only through Kaggle; the one score I found is a Stanford CS231n student report, R2 0.346 (search snippet, *unverified*); official leaderboard and trait list *unverified* (Kaggle blocks automated reading) | **no: needs the owner's action** (Kaggle login and acceptance of the competition rules) |
| 6 | **Pl@ntNet-300K.** C. Garcin, A. Joly, P. Bonnet, A. Affouard, J.-C. Lombardo, M. Chouet, M. Servajean, T. Lorieul, J. Salmon (2021), Zenodo 10.5281/zenodo.5645731, published 2021-04-29, CC BY 4.0 (Zenodo API). Venue of the paper (NeurIPS 2021 Datasets and Benchmarks) *unverified*, OpenReview blocks automated access | benchmark, not a model: 306,146 images, 1,081 species, with the **plant organ shown** (flower, fruit, leaf, bark, habit, ...) entered by Pl@ntNet users | dataset only | the organ label is a human, per-image label for exactly the "which photograph shows the flower/fruit" question | yes, `sota-benchmarks/plantnet-300k/plantnet_300K.zip` (31.7 GB) |
| 7 | **Wolf et al.** (2022) Citizen science plant observations encode global trait patterns. *Nat. Ecol. Evol.* 6:1850-1859, doi:10.1038/s41559-022-01904-x (Crossref) | no model: species trait means joined to observations | trait maps only | validation against sPlotOpen | no |
| 8 | **Younis et al.** S. Younis, C. Weiland, R. Hoehndorf, S. Dressler, T. Hickler, B. Seeger, M. Schmidt (2018) Taxon and trait recognition from digitized herbarium specimens using deep convolutional neural networks. *Botany Letters* 165:377-383, doi:10.1080/23818107.2018.1446357 (Crossref); arXiv:1803.07892 | categorical herbarium-leaf traits (margin, arrangement, ...) on herbarium sheets | not checked | herbarium sheets, not field photographs | not downloaded (different image domain; code/weights not checked) |
| 9 | **LeafMachine2.** B. Weaver, C. Smith (2023) *Applications in Plant Sciences* 11(5), doi:10.1002/aps3.11548 (Crossref) | herbarium leaf detection and measurement | github.com/Gene-Weaver/LeafMachine2, **GPL-3.0**; the repository now says "Replaced with LeafMachine3" | herbarium | not downloaded (herbarium; superseded) |
| 10 | **McKenzie et al.** (2025) Delayed flowering phenology of red-flowering plants in response to hummingbird migration. *Current Biology* 35, doi:10.1016/j.cub.2025.03.035 (Crossref) | flower colour by prompting GPT-4V, not a trained model | none | 11,729 species labelled; 85.4% of 294 red labels confirmed (via the local summary of the preprint) | no |
| 11 | **VLM4Bio.** M. Maruf, A. Daw, K. S. Mehrab and 19 others (2024) arXiv:2408.16176 (arXiv page; no journal reference listed); data HF `imageomics/VLM4Bio` (CC BY 4.0 with per-source licences, 1.8 GB), code github.com/sammarfy/VLM4Bio | trait questions on **fish, birds and butterflies**; no plants | benchmark only | 12 VLMs; GPT-4V 82.18% fish trait identification (local summary) | no (not plants; protocol sanity check only) |
| 12 | **Fish-Vista.** K. S. Mehrab, M. Maruf, A. Daw and 16 others (2024) arXiv:2407.08027 v2 | trait segmentation and identification on fish | n/a | fish | no |
| 13 | **Bio-VQA.** S. M. Rayeed, Q. Ma, C. V. Stewart, Y. Ma (2026) arXiv:2611.05559, "accepted to WACV 2027" (arXiv page) | VQA on animal images: taxonomy, attributes, counting, re-identification; BioCLIP 2 as a reference | not linked from the arXiv page | animals only | no |
| 14 | **Sparse-autoencoder trait annotation.** V. Pahuja, S. Stevens, A. East, S. Record, Y. Su (2026) *ICLR 2026*, arXiv:2604.01619 | image-level morphological trait descriptions for **insects** (Bioscan-Traits, 80k annotations on 19k BIOSCAN-5M images) | no repository linked from the arXiv page | insects | no |
| 15 | **PlantCLEF 2025 / 2026.** Species identification of plants in vegetation quadrats; no trait task (overview arXiv:2509.17602 found by search; not opened) | species only | PlantCLEF DINOv2 weights already compared | - | no |
| 16 | **PlantExpertVQA.** Sakib et al., arXiv:2508.17117 (v3 June 2026): 765,186 question-answer pairs on crops and diseases from 45 datasets | crop VQA | not linked | crops/diseases, not morphology | no |

Also noted and not repeated: BioCLIP 2 (Gu et al., NeurIPS 2025, arXiv:2505.23883; its trait evaluation is on fish and birds, plant
disease on PlantDoc; no plant-morphology result), BioCLIP (arXiv:2311.18803), BioTrove (arXiv:2406.17720), TaxaBind (arXiv:2411.00683). No
released plant flower-colour classifier exists on Hugging Face (the one search hit, "Wildflower Classifier v2", is a species model with no
weights yet).

### Things found while preparing that matter for the paper

- **PhenoVision's model card cites the wrong DOI.** The card and PhenoVisionL's card cite doi:10.1111/2041-210X.14346; Crossref says that
  DOI is the "Cover Picture and Issue Information" of *Methods in Ecology and Evolution* 16(4). The paper is 10.1111/2041-210X.70081.
  The card says the output order is [fruit, flower] (also in `config.json`); `run_phenovision.py` reads the order from the config.
- **PhenoVision's training data may overlap ours.** It was trained on 1.5 million iNaturalist photographs (genus-stratified 60/20/20
  split by its own hash). Our held-out genera are not its held-out genera, so its scores on our photographs are an upper bound; ours are
  scored only on genera our head never saw. State this wherever the two are put side by side.
- **PlantTraitNet's released checkpoints do not match the paper's description of the depth encoder.** The paper says a frozen
  Depth-Anything-V2 ViT-B encoder; in the released code its weights are only created as `DINOv2(model_name='vitb')` with no pretrained file
  and the stored depth-encoder weights differ between the multi-trait seeds 0, 100 and 200 while the seed-0 single-trait checkpoints equal
  seed 0, which is what a randomly initialised network frozen under a fixed seed looks like. I did not compare with the Depth-Anything-V2
  release, so treat this as a strong hint, not a finding. It does not change how the model is run (the stored weights are loaded).
- **Schiller's released models are the "Ensemble" setup with a second input:** six WorldClim 1.4 variables (BIO1, 12, 4, 7, 15, 13-14),
  scaled with the minima and maxima in the figshare `metadata.csv`. `run_schiller.py` reads WorldClim 1.4 (10 arc-minutes, downloaded)
  and rebuilds the networks from the stored configs (the R-keras files carry `trainable: null`; the Inception-ResNet-v2 residual Lambda layers
  are read as `inputs[0] + inputs[1] * scale`). The three architectures agreed with each other on three test photographs.
- **PlantTraitNet's trait values are in a normalised space** (no scaler is released), so they are compared by rank and Pearson r on log10.

## 3. What was downloaded

Total under `sota-models` + `sota-benchmarks`: 112 GB (models 19 GB, benchmarks 93 GB) plus 4.8 GB in two Python venvs (limit 150 GB; free space on the volume was 478 TB). Nothing is on the user's laptop.

| Path | What | Size |
|---|---|---|
| `sota-models/phenovision/hf`, `sota-models/phenovision/code` | PhenoVision weights, thresholds, per-family accuracy, training report; code clone | 1.2 GB |
| `sota-models/phenovisionL/hf` | PhenoVisionL weights | 1.2 GB |
| `sota-models/planttraitnet/weights` | `multitrait_seed{0,100,200}.pth`, `singletrait_{LA,LN,plantheight,sla}_seed0_checkpoint.pth` (the single-trait checkpoints of seeds 100 and 200, 8 files of 1.83 GB, were not taken: not needed to run the comparison) | 12.8 GB |
| `sota-models/planttraitnet/{code,Depth-Anything-V2,climplicit,torch-home}` | their code, the Depth-Anything-V2 code (needed for the encoder class), Climplicit weights (HF `Jobedo/climplicit`), DINOv2 ViT-B/14 reg code and weights as torch hub loads them | 0.7 GB |
| `sota-models/schiller2021/{weights,code}` | 18 Keras models, `metadata.csv`, their global trait maps (tif), R code | 3.6 GB |
| `sota-benchmarks/schiller2021` | `TRY_final.txt` (species trait means), `species_links.txt` (image URLs, 1.9 GB) | 1.9 GB |
| `sota-benchmarks/planttraitnet` | all CSVs (train, filtered train, validation, benchmark, reference), trait maps; validation images of 15 of 26 species-initial tars (20,609 photographs, all checked present); the in-situ reference photographs for all four traits (9,148 usable rows of 10,396: rows without species or value are skipped; images extracted, the tars deleted again to stay under the size limit) | 62 GB |
| `sota-benchmarks/plantnet-300k` | the zip as published (306,146 images + metadata json) | 31.7 GB |
| `sota-benchmarks/worldclim14` | WorldClim 1.4 bio 10 arc-minute rasters (needed as Schiller's second input) | 0.1 GB |
| `sota-env`, `sota-tf-env` | two Python venvs I created (see section 5); the pixi environment `vision-pixi` was **not** changed | 0.3 GB + 4.5 GB |

Not downloaded and why: the PlantTraitNet training images (240 GB), the remaining validation tars (11 of 26 letters, 72 GB) and the benchmark
images (415 GB; they are the 300k uncurated photographs used for the sPlotOpen comparison). Their labels (`benchmark_data.csv`, `train.csv`,
`val.csv`) are here; images are fetched with `snapshot_download("ayushi3536/PlantTraitNet", repo_type="dataset", allow_patterns=[...])`.
sPlotOpen itself (the plot data behind their headline numbers) was not fetched; the HF dataset's `trait_maps/*.tif` hold the aggregated layers
and were downloaded. PlantTraits2024 needs a Kaggle login. The Phenobase machine annotations (12.9 GB, Zenodo) are PhenoVision's own output,
not human labels, so they were not taken.

## 4. The comparison, in both directions

### 4a. Their models on our test sets

All new inputs come from one photograph list, `sota-photos.tsv` (made by `make_manifest.py` on the ORIX login node; 1,617,029 photographs;
roles `all` 1,560,058, `train` 241,306 (at most 8 per labelled species, fixed by a hash), `small` 96,820 (the first 3 of those),
`field` 58,475 (all photographs of observer-labelled observations), `pheno` 176,510 (all photographs of observations with an iNaturalist
phenology annotation)). It carries latitude, longitude and month where known. The location of the observer-labelled observations came from
iNaturalist's public API (`fetch_field_coords.py`; 21 of 18,420 observations have none).

| Model | What it can be asked | Script | Scoring on our data |
|---|---|---|---|
| PhenoVision | flower / fruit presence per photograph | `run_phenovision.py` | `score_phenology.py`: area under the ROC curve and, at its published thresholds, sensitivity and specificity, against iNaturalist phenology annotations on the same observations as our own BioCLIP 2 head (bag maximum over up to 12 photographs; our head on held-out genera). Writes `phenovision-as-pheno.npz` so that **the existing `allphotos_train.py --pheno ... --thr 0.6`** runs the fruit-colour test with PhenoVision choosing the fruit photographs (job 6) |
| PhenoVisionL | leaf phenology | same run | scores are stored in the same `scores.npz`; not scored (no flora trait in the pilot is leaf phenology) |
| PlantTraitNet | height, leaf area, SLA, leaf N + its 1024-d representation | `run_planttraitnet.py` | (i) `probe_any.py` on its **representation** against BioCLIP 2 under the identical head and protocol (same photographs, held-out genera, balanced accuracy on agreed species and on observers); (ii) `pred_to_emb.py` + `probe_any.py --head linear --standardize` on its **predicted traits only**: how much of habit, leaf size related classes etc. is already in what a TRY-trained model predicts |
| Schiller | six TRY traits | `run_schiller.py` | as (ii) |
| BioCLIP 2 (reference arm) | - | existing embeddings | `probe_any.py --names bioclip2` restricted to the same photographs |

`probe_any.py` follows `allphotos_train.py` line by line (two-layer perceptron, loss on the mean prediction of a bag of 8 photographs, class
weights, five rotating held-out-genus folds by `train.bucket`, `regime_tests.bal`) but restricts all photographs to the manifest so that every
encoder sees the same pixels. Its BioCLIP 2 row is therefore the reference for the others, not the 1-million-photograph numbers of
`docs/flopo-trait-vision-training-tests.md`. The Schiller arm has 3 photographs per species, not 8 (512-pixel networks, 18 of them per photograph).

### 4b. Our model on their benchmarks

| Benchmark | Appropriate protocol | Why | Script |
|---|---|---|---|
| PlantTraitNet validation subset and in-situ reference photographs | **train our head on their labels**, genus-held-out | their labels are continuous TRY values and the plant functional type; our flora classes do not map onto them. The comparison is then between encoders and heads under the *same* labels, which tells how much of the difference to their model is regime and how much is label source. Evaluate: Spearman and Pearson r of height, leaf area, SLA, leaf N against the TRY species value (validation photographs) and against the value **measured on the plant** (reference photographs); balanced accuracy for the plant functional type. Not reproduced: their sPlotOpen grid benchmark (needs the 415 GB of images and the plot data) | `ptn_lists.py`, `embed_paths.py`, `ptn_benchmark.py fit/score` |
| Pl@ntNet-300K organ labels | **train our head on their organ labels** (train split), test on their test split, then apply the head to our photographs | organs are image-level labels entered by users; no flora class is involved. Gives an organ-aware photograph filter without our detector and a direct test against iNaturalist phenology | `plantnet_organ.py lists/fit` (also writes `organ-as-pheno.npz`) |
| PhenoVision's own test split | not possible as published | the list of test photographs is not distributed; the equivalent for us is iNaturalist's annotations on our observations (4a) | - |
| PlantTraits2024 | needs Kaggle | owner's action | - |
| Mapping our trait classes onto theirs | **not appropriate** for PlantTraitNet and Schiller: height is a number, our habit is a class (herb, shrub, tree, climber); a threshold mapping would invent the boundaries. The honest bridge is the linear probe of 4a (ii), which learns the mapping from our labels | | |

## 5. Scripts and how to run them

New files only; nothing existing in `flopo2/traitvision/` was changed. Python scripts are in `flopo2/traitvision/sota/`, Slurm scripts in
`tools/orix/`, all copied flat to ORIX `pilot-v1/src/` (as the existing ones are). They need only numpy, torch, PIL and (for two of them) transformers
and open_clip, like the pilot scripts. Two venvs were created because the pixi environment lacks packages (not changed):

- `sota-env`: the pixi Python with `--system-site-packages` plus `rshf`, `omegaconf` (needed to *unpickle* the PlantTraitNet checkpoints), `pandas`,
  `scikit-learn`, `joblib`, `einops`, `scipy` (installed with `--no-deps` after a first attempt pulled a second torch into the venv; that
  venv was deleted and rebuilt).
- `sota-tf-env`: TensorFlow 2.15.1 (with the CUDA wheels) + numpy < 2, for the Keras HDF5 models.

The pixi environment has **no** TensorFlow, rshf, omegaconf, pandas, sklearn, scipy, rasterio or joblib.

| Script | Does | Where it runs |
|---|---|---|
| `common.py` | image loading with reduced-size JPEG decoding, transforms, AUC | imported |
| `fetch_field_coords.py` | locations of observer-labelled observations (already run, 18,399 of 18,420 found) | any, network |
| `make_manifest.py` | `sota-photos.tsv` (already run, ORIX login node) | login node |
| `embed_paths.py` | BioCLIP 2 embeddings of any image list (also from the Pl@ntNet zip) | GPU |
| `run_phenovision.py`, `score_phenology.py` | PhenoVision / PhenoVisionL on all photographs, then the comparison with our head | GPU |
| `run_planttraitnet.py` | PlantTraitNet, 7 checkpoints, outputs + 1024-d representation | GPU |
| `run_schiller.py` | Schiller CNNs with WorldClim input | GPU |
| `pred_to_emb.py` | predicted traits as a tiny "embedding" | login node (seconds) |
| `probe_any.py` | the common probe on our tests | GPU |
| `ptn_lists.py`, `ptn_benchmark.py`, `plantnet_organ.py` | their benchmarks | login node (lists, score) / GPU (fit) |
| `summarize.py` | markdown tables from the outputs | login node |

Slurm scripts (all: `pi-hohndor` partition/account/qos, one H200, 48 cpus for the image jobs, under 2 h, GPU use logged every 30 s to
`logs/gpu-<job>.txt`; **none submitted**). The account's submit limit is shared with `mowl-bench`; use the existing retry wrapper
`~/tmp/flopo-trait-vision/qsub.sh`, not a bare `sbatch`, and never touch the other jobs.

Order, with the command lines (from `pilot-v1/src` on ORIX), expected run time, and what each needs first:

```bash
# 0. login-node preparation (CPU, minutes). Done already: make_manifest.py (sota-photos.tsv), fetch_field_coords.py (field-coords.tsv).
#    Still to do once, after the downloads: the two list builders.
R=/mnt/data/u/hohndor/flopo-vision; D=$R/pilot-v1; PY=$R/vision-pixi/envs/default/bin/python; cd $D/src
$PY ptn_lists.py --root $R/sota-benchmarks/planttraitnet --out $D/sota-out
$PY plantnet_organ.py lists --zip $R/sota-benchmarks/plantnet-300k/plantnet_300K.zip --out $D/sota-out

# 1. PhenoVision (about 40 min) -> sota-out/phenovision/{scores.npz, phenology-compare.json, phenovision-as-pheno.npz}
sbatch traitvision_sota_phenovision.sbatch
# 2. PlantTraitNet on our photographs (about 40 min) and on their photographs (about 10 min)
sbatch traitvision_sota_planttraitnet.sbatch ours
sbatch traitvision_sota_planttraitnet.sbatch ptn
# 3. Schiller (check the printed photographs/s after 5 minutes; if over 100 minutes projected, use three shards: "ours 0 3", "ours 1 3", "ours 2 3")
sbatch traitvision_sota_schiller.sbatch ours
sbatch traitvision_sota_schiller.sbatch ptn
# 4. our model on their benchmarks (about 30 min) -> sota-out/ptn/ours.npz, sota-out/plantnet-organ/*
sbatch traitvision_sota_benchmarks.sbatch
# 4b. login node, after 2 and 3 and 4:
$PY ptn_benchmark.py score --data $D/sota-out --ours $D/sota-out/ptn/ours.npz \
    --ptn $D/sota-out/ptn-val/pred.npz,$D/sota-out/ptn-ref/pred.npz \
    --schiller $D/sota-out/schiller-val/pred.npz,$D/sota-out/schiller-ref/pred.npz --out $D/sota-out/ptn
$PY pred_to_emb.py --pred $D/sota-out/planttraitnet/pred.npz --kind planttraitnet --out $D/sota-out/planttraitnet-pred
$PY pred_to_emb.py --pred $D/sota-out/schiller/pred.npz --kind schiller --out $D/sota-out/schiller-pred
# 5. the common probe on our tests (about 35 min) -> sota-out/probe-*/probe.json
sbatch traitvision_sota_probe.sbatch
# 6. fruit colour with PhenoVision's and the organ head's photograph choice (about 40 min)
sbatch traitvision_sota_fruit.sbatch
# 7. tables
$PY summarize.py $D/sota-out > $D/sota-out/sota-results.md
```

Run times are estimates from throughput arguments (JPEG decode at reduced size with 44 workers, ViT-B/L at 224 px in bf16/fp16 on an H200), not
measurements; the Schiller job is the least certain (18 networks at 512 px per photograph). **Check `logs/gpu-<job>.txt` within 5 minutes of
each start.** The probe job is the one most at risk of falling under 75%: its fits are small, so it runs eight processes on the GPU at once; if the
log still shows below 75% after five minutes, cancel it and give it more seeds or encoders rather than waiting.

What was tested before handing over (all on the login node, CPU, nothing submitted): PlantTraitNet loads all 7 checkpoints (every key matched), runs end to
end on 3 photographs and the single-trait height output follows the multi-trait one; PhenoVision and PhenoVisionL run on 6 photographs (a white
*Oxalis* flower: flower 1.00, fruit 0.00); the 18 Schiller networks load and the three architectures agree with each other on 3 photographs;
`make_manifest.py` ran on the full data; `probe_any.py` ran for one trait and one fold (bioclip2, spines) and gave plausible numbers;
`score_phenology.py`, `ptn_benchmark.py fit/score` and `plantnet_organ.py fit` ran end to end on **synthetic** inputs (random scores / random
embeddings: chance-level results, as they should be), which checks the plumbing and the file formats only. **Not tested:** anything on a GPU; `embed_paths.py` (needs open_clip and a GPU; it copies the loading code of `embed.py`); the Slurm scripts
(`bash -n` only). Reading images out of the Pl@ntNet zip through `ImageSet` was tested on 4 members, and the zip itself was checked by reading its
central directory and decompressing 20 random members.

## 5b. What could not be done, and why

- **No comparison was run** (instruction); every number in section 2 is a published one, none is ours.
- **PlantTraits2024 data and any official score**: Kaggle needs a login and acceptance of the rules. Owner's action; the competition is also a
  continuous-trait task, so it would add little over PlantTraitNet's data.
- **PlantTraitNet's headline benchmark (sPlotOpen, 1-degree grid)**: needs the 415 GB of benchmark images and the plot data; replaced by the
  validation subset and the in-situ reference photographs (4b).
- **PlantTraitNet in original units**: the target scaler is not in the release; rank and Pearson r only.
- **PhenoVision on its own test split**: the list of its test photographs is not distributed (*unverified*); iNaturalist's annotations on our
  observations are used instead, with the overlap caveat.
- **Venue of Pl@ntNet-300K and the exact trait list of PlantTraits2024** could not be verified (OpenReview and Kaggle block automated access).
- **GPU behaviour is untested**: the login node has no GPU; run times are estimates and GPU use must be checked in the first minutes of each job.
- **Not looked for in depth**: weights or code of Younis et al. 2018 (herbarium traits), which would be a useful categorical-morphology
  baseline on herbarium sheets but not on field photographs.

## 6. Which comparisons matter for the paper

The paper's claim is that **structured trait data from floras is useful for training trait recognisers**. A comparison supports it when it
changes the label source and holds the rest fixed, or when it shows that an established model does not already contain what the floras add.

1. **Label source, same photographs: flora habit versus TRY-derived height, in both directions** (4a ii and 4b PlantTraitNet reference). TRY is
   the other large source of species-level trait labels and PlantTraitNet / Schiller are the only published image models trained from such a
   source. Two numbers decide it: (a) how well the *height* a TRY-trained model predicts separates our *habit* classes on iNaturalist observers'
   labels and agreed species, against our flora-trained head, and (b) how well our head, trained with TRY labels on their data, predicts the height
   *measured* on the plant in their in-situ photographs, against PlantTraitNet. If the flora-trained habit head is as good on (a) and the
   regime is competitive on (b), the claim that flora labels are as usable as TRY labels, with 8 categorical traits TRY cannot supply, is supported
   without any hand labelling. It is the only comparison in which a published model and ours face the same traits.
2. **The same regime on their labels** (PlantTraitNet validation subset, 4b). A 90M-parameter multimodal model with a location input against a
   frozen encoder and a small head under identical TRY labels. If the frozen regime is close, the pilot's design (frozen BioCLIP 2, small
   head, held-out genera) is not the limiting factor, and what the flora labels add is attributable to the labels. If it is far, the pilot
   needs the location input or a heavier head before its numbers can be set beside PlantTraitNet's.
3. **Fruit versus flower photograph choice: PhenoVision and the Pl@ntNet organ head against our detector** (jobs 1, 4 and 6). It is the only
   published component our pipeline can use directly (fruit colour is the weakest trait, 0.30 balanced accuracy, because Grounding DINO cannot
   tell fruit from flower). It does not test the main claim, but it removes a known weakness and gives the one place where a published,
   human-label-trained model can be compared with ours on identical photographs, with the caveat of possible training overlap (section 2).

No published baseline exists for margin, arrangement, compound versus simple, spines, inflorescence or flower colour from photographs;
for those the baselines remain the zero-shot prompts and the other frozen encoders already run, and the paper should say that no
trained recogniser had been published.

## 7. Results (2026-11-22)

Full tables: `local-corpora/trait-vision/sota-results.md` (ORIX `pilot-v1/sota-out/`), `pt2024.json`.

**Their models on our tests** (same head and protocol for every encoder, held-out genera, balanced accuracy, mean of 8 traits; 7 for observers):

| input to the head | agreed species | observers |
|---|---|---|
| BioCLIP 2 embedding (ours) | 0.672 | 0.605 |
| PlantTraitNet representation | 0.551 | 0.480 |
| PlantTraitNet predicted traits | 0.434 | 0.400 |
| Schiller 2021 predicted traits | 0.355 | 0.333 |

**Our model on their benchmarks**

* PlantTraitNet photographs (Spearman; validation / in-situ reference). Ours is BioCLIP 2 + a head fitted on their validation
  photographs with held-out genera; theirs is the released multi-trait model.

  | trait | ours | PlantTraitNet | Schiller 2021 |
  |---|---|---|---|
  | height | 0.876 / 0.857 | 0.862 / 0.835 | 0.781 / 0.739 |
  | leaf area | 0.727 / 0.534 | 0.796 / 0.744 | 0.568 / 0.628 |
  | specific leaf area | 0.579 / 0.550 | 0.668 / 0.447 | 0.463 / 0.395 |
  | leaf nitrogen | 0.463 / 0.239 | 0.559 / 0.397 | 0.238 / -0.044 |

  Plant functional type from our head: balanced accuracy 0.837.
* PlantTraits2024 (Kaggle), R2 averaged over six traits, five-fold cross-validation on the training set (log scale, outliers
  dropped; test labels are not public): image 0.586, climate and soil columns 0.239, image + columns 0.618. A submission file
  for the leaderboard is at ORIX `pilot-v1/sota-out/pt2024/submission.csv` (not submitted).
* Pl@ntNet-300K organ labels: our head 0.740 accuracy, 0.580 balanced (fruit recall 0.81, flower 0.77).

**Fruit or flower per photograph** (65,788 held-out observations with iNaturalist phenology annotations; area under the curve):

| | flowering | fruiting | fruit vs flower only |
|---|---|---|---|
| PhenoVision | 0.978 | 0.935 | 0.967 |
| our phenology head | 0.954 | 0.849 | 0.913 |
| Pl@ntNet organ head on our embeddings | 0.910 | 0.780 | - |

PhenoVision was trained on iNaturalist photographs with these annotations, so its score here is not on unseen data.

**Fruit colour with fruit photographs chosen by each** (trained on all, tested on chosen; agreed / observers): detector
0.328 / 0.425, our phenology head 0.355 / 0.371, PhenoVision 0.363 / 0.418, Pl@ntNet organ head 0.357 / 0.420. No choice of
photographs lifts fruit colour clearly.

Run notes: the embedding loader held 80 GB with 44 workers and six prefetched batches (now two); a bare `wait` in the probe
and fruit job scripts also waited for the GPU logger, so both idled to the time limit after finishing (fixed).

## 8. Kaggle score, the winner's design, and flora sizes against TRY (2026-11-22)

**PlantTraits2024 on Kaggle** (submission 58731814, image + columns, frozen embedding): R2 0.430 public, 0.440 private; about
rank 28 of 398 on the public board, top 0.61. The cross-validation figure of section 7 (0.618) is on a log scale without
outliers; on the raw scale the same model gives 0.48.

**The winner ("PlantHydra", github.com/dysdsyd/PlantTraits2024):** DINOv2 ViT with the last blocks fine-tuned (a
PlantCLEF-2024-pretrained ViT-B helped), a regression head for the six traits jointly, a classifier over 17,396 pseudo-species
(photographs with the same six values) whose answer is the probability-weighted mean of the species' values, the tabular
columns through a small attention block, and a hand-weighted blend. The species head works there because test and training
photographs are of the same species. **We do not adopt it: the species of a photograph is unknown in our setting** (species is
what the traits are meant to determine), and our tests are on unseen genera. On the frozen embedding the species head added
little anyway (cross-validation 0.618 -> 0.631; `planttraits2024.py`, kept for the benchmark only, not submitted). Fine-tuning
the last blocks was tested earlier on our traits and was flat on unseen genera.

**Flora sizes learned from photographs, tested against TRY** (`extract_measures.py`, `flora_try.py`,
`tools/orix/traitvision_floratry.sbatch`; result `pilot-v1/flora-try/flora-try.json`). 864,154 accepted measurements from
the floras; labels per species: plant height (upper end), leaf length and width (middle of range). Training: 25,315 species,
1.22 M photographs, no TRY value. The species name is a training label only, never an input; every prediction comes from a
model that saw no species of that genus.

| Spearman | flora-trained (unseen genera) | our head trained on TRY | PlantTraitNet | flora value itself vs TRY |
|---|---|---|---|---|
| TRY height, validation photographs | 0.892 | 0.876 | 0.862 | 0.929 (636 species) |
| TRY height, field reference | 0.906 | 0.857 | 0.835 | 0.883 |
| TRY leaf area, validation (length x width) | 0.773 | 0.727 | 0.796 | 0.783 (477 species) |
| TRY leaf area, field reference | 0.636 (n 1283) | 0.534 (n 1060) | 0.744 (n 1060) | 0.750 |

Held-out flora values (species level): height 0.915, leaf length 0.866, leaf width 0.904.

## 9. DINOv2 against BioCLIP 2 on our tests (2026-11-22)

`probe_any.py --ids-from dinov2` (`tools/orix/traitvision_encoders.sbatch`, job 409177; ORIX `pilot-v1/encoders/`). Same head,
same photographs (161,832 training photographs, at most eight per species; 29,453 of labelled observations), held-out genera,
three seeds, balanced accuracy.

| encoder | flower colour | fruit colour | habit | inflorescence | leaf arrangement | leaf complexity | leaf margin | spines | mean |
|---|---|---|---|---|---|---|---|---|---|
| BioCLIP 2 (agreed species) | 0.667 | 0.310 | 0.895 | 0.586 | 0.612 | 0.913 | 0.707 | 0.646 | 0.667 |
| DINOv2 ViT-L (agreed) | 0.624 | 0.291 | 0.818 | 0.599 | 0.617 | 0.843 | 0.660 | 0.669 | 0.640 |
| PlantCLEF-2024 DINOv2 ViT-B (agreed) | 0.638 | 0.257 | 0.828 | 0.535 | 0.593 | 0.822 | 0.675 | 0.626 | 0.622 |
| BioCLIP 2 + DINOv2 (agreed) | 0.643 | 0.342 | 0.860 | 0.617 | 0.631 | 0.881 | 0.671 | 0.703 | 0.668 |
| BioCLIP 2 + PlantCLEF (agreed) | 0.667 | 0.296 | 0.902 | 0.590 | 0.602 | 0.885 | 0.674 | 0.667 | 0.660 |
| BioCLIP 2 (observers) | 0.651 | 0.369 | 0.698 | - | 0.497 | 0.630 | 0.560 | 0.746 | 0.593 |
| DINOv2 ViT-L (observers) | 0.551 | 0.246 | 0.673 | - | 0.431 | 0.663 | 0.576 | 0.768 | 0.558 |
| PlantCLEF-2024 DINOv2 ViT-B (observers) | 0.580 | 0.416 | 0.657 | - | 0.482 | 0.706 | 0.582 | 0.657 | 0.583 |
| BioCLIP 2 + DINOv2 (observers) | 0.601 | 0.377 | 0.704 | - | 0.487 | 0.665 | 0.539 | 0.758 | 0.590 |
| BioCLIP 2 + PlantCLEF (observers) | 0.624 | 0.411 | 0.696 | - | 0.503 | 0.702 | 0.548 | 0.712 | 0.599 |

Decision: no switch. Neither DINOv2 model beats BioCLIP 2 alone, and joining them moves the mean by less than the spread between seeds.

## 10. Flora + TRY training against PlantTraitNet on its benchmark (2026-11-22)

`try_joint.py` (`tools/orix/traitvision_tryjoint.sbatch`, jobs 409520, 409548, 409570; `local-corpora/trait-vision/try-joint/`).
Spearman, validation photographs / field reference; ours always on unseen genera, three seeds per fold.

| model | height | leaf area | specific leaf area | leaf nitrogen |
|---|---|---|---|---|
| PlantTraitNet multi-trait (published) | 0.862 / 0.835 | 0.796 / 0.744 | 0.668 / 0.447 | 0.559 / 0.397 |
| TRY labels only | 0.874 / 0.856 | 0.718 / 0.534 | 0.571 / 0.524 | 0.453 / 0.212 |
| TRY + flora sizes + categorical traits as extra outputs | 0.875 / 0.862 | 0.725 / 0.543 | 0.572 / 0.536 | 0.454 / 0.208 |
| flora predictions only -> TRY head | 0.888 / 0.894 | 0.741 / 0.565 | 0.507 / 0.488 | 0.302 / 0.073 |
| embedding + flora predictions -> TRY head | 0.889 / 0.889 | 0.752 / 0.632 | 0.575 / 0.525 | 0.434 / 0.191 |
| same, TRY species values also put on our photographs | 0.896 / 0.895 | 0.770 / 0.675 | 0.630 / 0.542 | 0.485 / 0.165 |

Flora traits as extra outputs of one network do nothing; flora predictions as inputs to the TRY head lift height and leaf
area. PlantTraitNet is beaten on height (both tests) and on specific leaf area on the field reference; not on leaf area, on
specific leaf area for validation, or on leaf nitrogen. Unequal conditions: all 4,587 validation species are in
PlantTraitNet's training set (222,590 labelled photographs); ours sees ~16,500 TRY photographs per fold (+153,702 of our
photographs of 2,616 TRY species in the last row) and is tested on genera it never saw.

## 11. Even comparison with PlantTraitNet (2026-11-23)

`try_even.py` (`tools/orix/traitvision_tryeven.sbatch`, job 410962, 32 min, GPU 91%; results `local-corpora/trait-vision/try-even/`,
copy of the score files in `try-joint/`). PlantTraitNet's 222,590 training photographs were downloaded and embedded with BioCLIP 2
(`sota-out/emb-ptn-train`). PlantTraitNet takes the photograph's location as an input (Climplicit climate embedding), so arms with
the same location embedding (`loc`) are allowed; no other climate columns are used. Species name is never an input.

### 11.1 Even scoring: the models of section 10, split by what PlantTraitNet saw

All 1,110 validation species (20,609 photographs of the downloaded subset; 4,587 species in the full set) are in PlantTraitNet's
training set, so the split is only possible on the field reference. Spearman; ours = `stack+emb@ours` of section 10 (unseen genera).

| reference rows | n | PlantTraitNet | ours (section 10) |
|---|---|---|---|
| height, species in its training set | 1595 | 0.733 | 0.714 |
| height, species not in its training set | 2363 | 0.769 | 0.890 |
| height, genus not in its training set | 1505 | 0.627 | 0.842 |
| leaf area, species in | 603 | 0.660 | 0.592 |
| leaf area, species not in | 435 | 0.767 | 0.710 |
| leaf area, genus not in | 125 | 0.798 | 0.807 |
| specific leaf area, species in | 1076 | 0.249 | 0.441 |
| specific leaf area, species not in | 704 | 0.616 | 0.657 |
| specific leaf area, genus not in | 284 | 0.763 | 0.809 |
| leaf nitrogen, species in | 902 | 0.217 | -0.039 |
| leaf nitrogen, species not in | 452 | 0.643 | 0.458 |
| leaf nitrogen, genus not in | 145 | 0.564 | 0.357 |

(Rows without a binomial are in neither species group. Within-group correlations can exceed the pooled one.)

### 11.2 Even training: our head on PlantTraitNet's training photographs

Regime `all` = as PlantTraitNet (every training photograph; validation = other photographs of the same species). Regime `folds` =
TRY head and flora network never saw the test photograph's genus. Arms: `emb` embedding only; `f3`/`f8` flora network outputs
(3 or 8 sizes + categorical probabilities) as further inputs; `loc` location embedding; `ours` TRY species values also on our photographs.
Spearman, validation (n 20,609) / reference all (n 4460, 1060, 1804, 1378).

| model | height | leaf area | specific leaf area | leaf nitrogen |
|---|---|---|---|---|
| PlantTraitNet multi-trait | 0.862 / 0.835 | 0.796 / 0.744 | 0.668 / 0.447 | 0.559 / 0.397 |
| emb, all | 0.943 / 0.880 | 0.906 / 0.740 | 0.844 / 0.570 | 0.806 / 0.452 |
| emb+f3, all | 0.951 / 0.880 | 0.920 / 0.748 | 0.864 / 0.600 | 0.833 / 0.435 |
| emb+f8, all | 0.952 / 0.880 | 0.920 / 0.741 | 0.867 / 0.592 | 0.835 / 0.426 |
| emb+loc, all | 0.960 / 0.870 | 0.932 / 0.745 | 0.893 / 0.593 | 0.861 / 0.481 |
| emb+f8+loc, all | 0.964 / 0.888 | 0.938 / 0.737 | 0.900 / 0.602 | 0.870 / 0.459 |
| emb+f8+loc+ours, all | 0.963 / 0.894 | 0.938 / 0.745 | 0.903 / 0.601 | 0.875 / 0.441 |
| emb, folds (unseen genera) | 0.891 / 0.871 | 0.753 / 0.706 | 0.585 / 0.501 | 0.438 / 0.381 |
| emb+f8, folds | 0.893 / 0.880 | 0.751 / 0.701 | 0.587 / 0.491 | 0.437 / 0.332 |
| emb+f8+loc, folds | 0.893 / 0.882 | 0.752 / 0.692 | 0.598 / 0.498 | 0.434 / 0.276 |

Reference rows of species that are not in PlantTraitNet's training set (neither model has a TRY label for them; n 2363, 435, 704, 452):

| model | height | leaf area | specific leaf area | leaf nitrogen |
|---|---|---|---|---|
| PlantTraitNet | 0.769 | 0.767 | 0.616 | 0.643 |
| emb, all | 0.852 | 0.725 | 0.643 | 0.566 |
| emb+f8, all | 0.859 | 0.733 | 0.665 | 0.552 |
| emb+f8+loc, all | 0.871 | 0.752 | 0.700 | 0.613 |
| emb+f8+loc+ours, all | 0.880 | 0.748 | 0.679 | 0.593 |

Reading. With the same training photographs, the frozen BioCLIP 2 embedding with a small head is ahead of PlantTraitNet on all four
traits on its validation set and on height, specific leaf area and leaf nitrogen on the whole field reference; leaf area on the
reference is a tie (0.737-0.748 against 0.744). The validation gain is mostly recognition of species seen in training (the same
head on unseen genera drops to 0.75 / 0.59 / 0.44 for leaf area, specific leaf area, leaf nitrogen), which is exactly what
PlantTraitNet's own split permits. On species neither model has a label for, ours leads on height and specific leaf area and is
behind on leaf area (0.75 against 0.77) and leaf nitrogen (0.61 against 0.64). The flora predictions add 0.01-0.03 on validation in
this regime and nothing consistent on the reference; eight sizes are no better than three; the location embedding helps.

Limits: three seeds averaged, no seed spread measured; the small cells (n 125-450) carry a sampling error of several points; 7.7% of a
sample of 1,500 validation photographs have a near-identical training photograph (cosine > 0.99), which favours both models that
trained on that set; validation is the downloaded 15-of-26 letter subset; head settings (12,000 steps, width 2048) were not tuned.

## 12. More flora traits, the leaf-area label, and training the image model (2026-11-23)

**More flora traits** (`labels_extra.py` -> `extra-labels.tsv`, `agreed-extra.tsv`, `measure-labels-v3.tsv`; names brought to the
accepted name): leaf texture (33,455 species), life span (27,897), leaf persistence (5,550), leaf shape (65,712), leaflet length and
width. As inputs of the TRY head (`try_even.py`, arm `fx`; job 411071; scores `try-even/even-scores-fx.json`). Field reference, Spearman:

| reference rows | n | PlantTraitNet | emb+f8+loc, all | emb+fx+loc, all | emb+f8, unseen genera | emb+fx, unseen genera |
|---|---|---|---|---|---|---|
| height, all | 4460 | 0.835 | 0.888 | 0.880 | 0.880 | 0.880 |
| height, species not in its training set | 2363 | 0.769 | 0.871 | 0.855 | 0.860 | 0.857 |
| leaf area, all | 1060 | 0.744 | 0.737 | 0.730 | 0.701 | 0.702 |
| leaf area, species not in | 435 | 0.767 | 0.752 | 0.737 | 0.688 | 0.689 |
| specific leaf area, all | 1804 | 0.447 | 0.602 | 0.606 | 0.491 | 0.498 |
| specific leaf area, species not in | 704 | 0.616 | 0.700 | 0.716 | 0.643 | 0.645 |
| leaf nitrogen, all | 1378 | 0.397 | 0.459 | 0.475 | 0.332 | 0.347 |
| leaf nitrogen, species not in | 452 | 0.643 | 0.613 | 0.641 | 0.518 | 0.567 |

Validation (emb+fx+loc, all): 0.965 / 0.939 / 0.902 / 0.873, as emb+f8+loc within 0.003. The new traits help leaf nitrogen and
specific leaf area a little and nothing else. (Their larger effect is on species identification: training-tests section 12.)

**Leaf-area label** (`labels_extra.py ceiling`): flora leaf area against TRY's over species with both, Spearman 0.800 for
length x width, 0.800 with a factor for the stated shape, 0.799 with the leaflet where the flora gives one; compound-leaved species
alone 0.68 -> 0.72 (n 168 -> 475). The reading does not matter; coverage rises from 2,401 to 2,781 species.

**Training the image model** (`finetune_try.py`, `tools/orix/traitvision_fttry.sbatch`, job 411104, run `ft-try/all-loc`): last six
blocks of BioCLIP 2, TRY photographs and flora photographs (sizes + 12 categorical traits) in every batch, three epochs, location
input; the genera of one fold kept out of both streams and used for stopping (6,000 TRY photographs, mean Spearman of the four
traits, every 300 steps). Stopping score: 0.6434 untouched, 0.638-0.644 throughout, 0.6442 at the end: no gain on unseen genera.
Benchmark, untouched -> after: validation height 0.941 -> 0.947, leaf area 0.888 -> 0.898, specific leaf area 0.820 -> 0.833,
leaf nitrogen 0.757 -> 0.774; reference 0.877 -> 0.883, 0.618 -> 0.622, 0.563 -> 0.560, 0.427 -> 0.422 (reference rows as this
script counts them: n 4460, 1283, 2027, 1378). The gain is on species seen in training only. GPU 44% (image decoding limits it); the
held-out-fold run was not started. Third attempt at training the image model with the same outcome.
