---
license: mit
library_name: open_clip
pipeline_tag: image-classification
base_model: imageomics/bioclip-2
tags:
- biology
- botany
- plants
- plant-traits
- phenotype
- ontology
- FLOPO
---

# FLOPOVision

FLOPOVision reads 26 morphological traits of a plant from a photograph: growth habit, life span, leaf shape, leaf margin,
leaf and stem hair, flower colour, corolla shape, inflorescence, fruit type and others. It does not need to know the species.
The trait values are those of the [Flora Phenotype Ontology (FLOPO)](https://github.com/flora-phenotype-ontology/flopoontology).

The model is a set of small heads on the frozen image tower of [BioCLIP 2](https://huggingface.co/imageomics/bioclip-2).
The heads were trained without any hand-labelled photograph. The labels are trait values that a language model extracted from
published floras, attached to the species, and the photographs are research-grade iNaturalist observations of those species.

Version 0.1. Categorical traits only; sizes (leaf length, plant height and others) are planned for a later version.

## Use

```bash
pip install torch open_clip_torch safetensors huggingface_hub pillow
python flopovision.py photo.jpg                 # one photograph
python flopovision.py a.jpg b.jpg c.jpg --json  # several photographs of one plant: probabilities are averaged
```

```python
from flopovision import FLOPOVision
model = FLOPOVision()
model.predict(['a.jpg', 'b.jpg'])
# {'leaf_hair': {'hairy': 0.91, 'glabrous': 0.09}, 'flower_colour': {'yellow': 0.84, ...}, ...}
model.predict(['a.jpg', 'b.jpg'], per_photo=True)   # one result per photograph
```

`flopovision.py` downloads BioCLIP 2 and the heads on first use. Files: `flopovision-heads.safetensors` (the heads),
`config.json` (traits, values, number of training species per value), `flopovision.py` (inference),
`train_release.py` (training).

## How it was trained

Each head is `Linear(768, 1024) - GELU - Dropout(0.2) - Linear(1024, values)` on the L2-normalised BioCLIP 2 image embedding.
A species is one training example: up to 64 photographs, the mean of the predicted probabilities over them, and the loss is
the negative log of the probability of the values that the floras allow for that species. A flora often allows several values
("flowers white or pink"), and a photograph shows only part of the plant, so the label is a set of values for a set of
photographs. Training data: 33,281 species with photographs and flora values; between 1,073 (substrate) and 20,482
(leaf shape) species per trait. The released heads are trained on all of these species.

## Accuracy

Measured with the same procedure in five folds in which whole genera are held out, so that every tested species belongs to a
genus the heads never saw. The score is balanced accuracy (mean over the values of a trait) on the species for which two
independent floras state the same single value, from up to 64 photographs per species. Mean over the 26 traits: 0.70.

| Trait | Values (most frequent first) | Balanced accuracy | Species tested |
|---|---|---|---|
| `branching` | branched, unbranched | 0.73 | 1,244 |
| `corolla_shape` | tubular, funnel, bell, rotate, salverform, urn ... | 0.49 | 583 |
| `flower_colour` | white, yellow, purple, pink, red, green ... | 0.65 | 3,675 |
| `flower_position` | terminal, axillary | 0.78 | 1,415 |
| `fruit_colour` | brown, red, green, yellow, black, orange ... | 0.32 | 1,344 |
| `fruit_shape` | elongate, ovoid, globose, flattened | 0.48 | 3,011 |
| `fruit_type` | capsule, achene, berry, legume, drupe, nut ... | 0.73 | 2,468 |
| `habit` | shrub, herb, tree, climber | 0.89 | 4,790 |
| `inflorescence` | raceme, panicle, cyme, spike, umbel, corymb ... | 0.59 | 2,676 |
| `leaf_apex` | acute, acuminate, obtuse, mucronate, emarginate | 0.52 | 2,120 |
| `leaf_arrangement` | alternate, opposite, whorled | 0.64 | 879 |
| `leaf_attachment` | sessile, petiolate | 0.79 | 945 |
| `leaf_base` | cuneate, rounded, cordate, truncate, decurrent, clasping | 0.52 | 1,905 |
| `leaf_complexity` | compound, simple | 0.88 | 2,660 |
| `leaf_hair` | hairy, glabrous | 0.83 | 3,785 |
| `leaf_margin` | toothed, entire, lobed | 0.68 | 2,561 |
| `leaf_persistence` | evergreen, deciduous | 0.87 | 601 |
| `leaf_position` | basal, cauline | 0.81 | 516 |
| `leaf_shape` | elliptic, lanceolate, ovate, oblong, linear, obovate ... | 0.53 | 1,791 |
| `leaf_texture` | coriaceous, papery, membranous, fleshy | 0.63 | 1,571 |
| `life_span` | perennial, annual, biennial | 0.80 | 3,559 |
| `posture` | erect, ascending, prostrate, climbing | 0.71 | 3,033 |
| `spines` | present, absent | 0.78 | 756 |
| `stem_hair` | hairy, glabrous | 0.84 | 2,432 |
| `stem_shape` | terete, angular, quadrangular | 0.67 | 445 |
| `substrate` | epiphytic, terrestrial | 0.94 | 162 |

Accuracy for a single photograph is lower than for a species with many photographs, and depends on whether the organ is in
view: a head returns a distribution for every photograph, including a photograph without fruit for `fruit_type`.

## Limits

- The labels are species-level statements from floras. The heads learn what plants with a stated value look like in
  photographs; a prediction for an individual plant that deviates from its species is supported for flower colour
  (blue against scarlet pimpernels, a genus held out from training: 98.6% agreement with the identification on 5,999
  observations) and is untested for most other traits.
- Predictions shift slightly with the surroundings in the photograph. Differences of a few percentage points between
  groups of photographs of one species should not be read as differences between the plants.
- Photographs are iNaturalist observations, with their geographic bias towards North America and Europe; the floras
  cover the world unevenly.
- Rare values (fewer than 50 training species) are left out. Low-accuracy traits (fruit colour, leaf apex, corolla
  shape) are included for completeness.
- The image tower, BioCLIP 2, was trained with taxonomic names; the control with held-out genera measures what carries
  over to unseen genera, not to unseen families.

## Licence and sources

The heads and the code are released under the MIT licence. BioCLIP 2 is MIT-licensed by its authors. The flora texts come
from World Flora Online and other published floras; the photographs from iNaturalist Open Data (CC0 and Creative Commons
licences; no photograph is redistributed here). Code and training pipeline:
<https://github.com/flora-phenotype-ontology/flopoontology> (`flopovision/`, `flopo2/traitvision/`). Model:
<https://huggingface.co/bio-ontology-research-group/FLOPOVision>.

A paper describing the method is in preparation.
