# FLOPO Candidate Additions — USDA NRCS PLANTS Database — Botanical Descriptions (`usda-plants`)

- **Records processed**: 678
- **Extracted trait rows**: 15,003
- **Formal assertions emitted**: 12,415
- **Distinct candidate value terms**: 188
- **Distinct candidate anatomical bearers**: 19
- **Distinct novel PO × PATO/FLOPO combinations**: 696

## Top Candidate FLOPO Value Terms (`value_term_candidates.tsv`)

| Quality word | Count | Taxa | Suggested PATO parent | Top bearers |
|---|---:|---:|---|---|
| `grass` | 24 | 24 | `PATO:0000141` (structure) | `PO_0000003` |
| `round` | 12 | 12 | `PATO:0000141` (structure) | `PO_0009010|FLOPO_0985030|PO_0009051|PO_0020038` |
| `native` | 9 | 9 | `PATO:0000141` (structure) | `PO_0000003` |
| `scale-like` | 8 | 8 | `PATO:0000052` (shape) | `PO_0009001|PO_0009051|PO_0009047|PO_0009060|PO_0009046` |
| `warm-season` | 8 | 8 | `PATO:0000141` (structure) | `PO_0000003` |
| `cool season` | 7 | 7 | `PATO:0000141` (structure) | `PO_0000003` |
| `naked` | 6 | 6 | `PATO:0000141` (structure) | `PO_0009049|PO_0000055|axis` |
| `stalked` | 6 | 6 | `PATO:0000141` (structure) | `PO_0009051|PO_0009049|PO_0005032` |
| `warm season` | 5 | 5 | `PATO:0000141` (structure) | `PO_0000003` |
| `broadest above the middle` | 4 | 4 | `PATO:0000141` (structure) | `PO_0009001` |
| `extensive` | 4 | 4 | `PATO:0000141` (structure) | `PO_0009005` |
| `leafless` | 4 | 4 | `PATO:0000141` (structure) | `PO_0003024` |
| `low-growing` | 4 | 4 | `PATO:0000141` (structure) | `PO_0000003` |
| `thicket-forming` | 4 | 4 | `PATO:0000141` (structure) | `PO_0000003` |
| `tough` | 4 | 4 | `PATO:0000141` (structure) | `PO_0009001|PO_0025034|PO_0025073|PO_0009047` |
| `adventitious` | 3 | 3 | `PATO:0000141` (structure) | `PO_0009005` |
| `cool-season` | 3 | 3 | `PATO:0000141` (structure) | `PO_0000003` |
| `drought tolerant` | 3 | 3 | `PATO:0000141` (structure) | `PO_0000003` |
| `fine` | 3 | 3 | `PATO:0000141` (structure) | `PO_0025034|PO_0009010|PO_0009047` |
| `reclining` | 3 | 3 | `PATO:0000141` (structure) | `PO_0000003|PO_0025073` |
| `stained` | 3 | 1 | `PATO:0000141` (structure) | `PO_0025034|PO_0009047|FLOPO_0986007` |
| `tufted` | 3 | 3 | `PATO:0000060` (spatial pattern) | `PO_0025034` |
| `winter hardy` | 3 | 3 | `PATO:0000141` (structure) | `PO_0000003` |
| `berrylike` | 2 | 2 | `PATO:0000052` (shape) | `PO_0009001` |
| `broadest above` | 2 | 2 | `PATO:0000141` (structure) | `PO_0025034` |

## Top Candidate Anatomical Bearers (`bearer_candidates.tsv`)

| Bearer word | Count | Taxa | Qualities seen |
|---|---:|---:|---|
| `per pound` | 5 | 5 | `amount` |
| `acorns per pound` | 3 | 3 | `amount` |
| `bulb-coat` | 3 | 1 | `brown|thin|reticulate` |
| `nerved` | 3 | 1 | `amount` |
| `seed stalk` | 2 | 2 | `amount` |
| `bur` | 1 | 1 | `amount` |
| `common` | 1 | 1 | `amount` |
| `female spike` | 1 | 1 | `amount` |
| `glabrou` | 1 | 1 | `amount` |
| `insect guideline` | 1 | 1 | `present` |
| `involucral leave` | 1 | 1 | `amount` |
| `micropylar tube` | 1 | 1 | `present` |
| `needles per bundle` | 1 | 1 | `amount` |
| `ovary lobe` | 1 | 1 | `amount` |
| `oz` | 1 | 1 | `amount` |
| `pounds per acre` | 1 | 1 | `amount` |
| `ratio of internode length` | 1 | 1 | `amount` |
| `seed catkin` | 1 | 1 | `sessile` |
| `tap` | 1 | 1 | `present` |

## Top Novel PO × PATO / FLOPO Class Candidates (`novel_po_pato_combinations.tsv`)

| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Count | Taxa |
|---|---|---|---|---|---|---:|---:|
| `PO_0000003` | whole plant | `FLOPO_0991072` | dioecious | `EQ|PO_0000003|FLOPO_0991072` | `allowed` / `new_class_candidate` | 30 | 30 |
| `PO_0000003` | whole plant | `FLOPO_0991071` | monoecious | `EQ|PO_0000003|FLOPO_0991071` | `allowed` / `new_class_candidate` | 28 | 28 |
| `PO_0009046` | flower | `PATO_0000070` | amount | `EQC|PO_0009046|n|PATO_0000070` | `allowed` / `new_class_candidate` | 24 | 24 |
| `PO_0025034` | leaf | `PATO_0104359` | entire | `EQ|PO_0025034|PATO_0104359` | `allowed` / `new_class_candidate` | 17 | 17 |
| `PO_0009001` | fruit | `PATO_0104354` | winged | `EQ|PO_0009001|PATO_0104354` | `allowed` / `new_class_candidate` | 14 | 14 |
| `PO_0020039` | leaf lamina | `PATO_0002258` | pointed | `EQ|PO_0020039|PATO_0002258` | `allowed` / `new_class_candidate` | 12 | 12 |
| `PO_0020104` | leaf sheath | `FLOPO_0991002` | basal | `EQ|PO_0020104|FLOPO_0991002` | `allowed` / `new_class_candidate` | 12 | 12 |
| `PO_0000003` | whole plant | `FLOPO_0991108` | climbing | `EQ|PO_0000003|FLOPO_0991108` | `allowed` / `new_class_candidate` | 11 | 10 |
| `PO_0009049` | inflorescence | `FLOPO_0991142` | spike-like | `EQ|PO_0009049|FLOPO_0991142` | `allowed` / `new_class_candidate` | 11 | 11 |
| `PO_0020039` | leaf lamina | `PATO_0001500` | tapered | `EQ|PO_0020039|PATO_0001500` | `allowed` / `new_class_candidate` | 11 | 10 |
| `PO_0030099` | samara fruit | `PATO_0000467` | present | `EQ|PO_0030099|PATO_0000467` | `blocked` / `new_class_candidate` | 11 | 11 |
| `PO_0009049` | inflorescence | `FLOPO_0991218` | flat-topped | `EQ|PO_0009049|FLOPO_0991218` | `allowed` / `new_class_candidate` | 9 | 9 |
| `PO_0025034` | leaf | `FLOPO_0980232` | simple grass-like | `EQ|PO_0025034|FLOPO_0980232` | `allowed` / `new_class_candidate` | 9 | 9 |
| `PO_0025034` | leaf | `PATO_0001968` | parallelodromous | `EQ|PO_0025034|PATO_0001968` | `allowed` / `new_class_candidate` | 9 | 9 |
| `PO_0000003` | whole plant | `FLOPO_0991244` | colonial | `EQ|PO_0000003|FLOPO_0991244` | `allowed` / `new_class_candidate` | 8 | 8 |
| `PO_0000049` | leaf lamina abaxial epidermis | `PATO_0000328` | low saturation | `EQ|PO_0000049|PATO_0000328` | `novel` / `new_class_candidate` | 8 | 8 |
| `PO_0000049` | leaf lamina abaxial epidermis | `PATO_0001320` | pubescent hair | `EQ|PO_0000049|PATO_0001320` | `allowed` / `new_class_candidate` | 8 | 8 |
| `PO_0004518` | bark | `FLOPO_0991026` | fibrous | `EQ|PO_0004518|FLOPO_0991026` | `allowed` / `new_class_candidate` | 8 | 8 |
| `PO_0020104` | leaf sheath | `PATO_0002488` | overlapping | `EQ|PO_0020104|PATO_0002488` | `allowed` / `new_class_candidate` | 8 | 8 |
| `PO_0009059` | corolla | `FLOPO_0991085` | bilabiate | `EQ|PO_0009059|FLOPO_0991085` | `allowed` / `new_class_candidate` | 7 | 7 |
| `PO_0020039` | leaf lamina | `PATO_0104359` | entire | `EQ|PO_0020039|PATO_0104359` | `allowed` / `new_class_candidate` | 7 | 7 |
| `PO_0025349` | awn | `PATO_0002445` | torsioned | `EQ|PO_0025349|PATO_0002445` | `allowed` / `new_class_candidate` | 7 | 7 |
| `PO_0009010` | seed | `PATO_0000586` | increased size | `EQ|PO_0009010|PATO_0000586` | `allowed` / `new_class_candidate` | 6 | 6 |
| `PO_0009046` | flower | `PATO_0000330` | irregular spatial pattern | `EQ|PO_0009046|PATO_0000330` | `blocked` / `new_class_candidate` | 6 | 6 |
| `PO_0009077` | staminode | `FLOPO_0991118` | bearded | `EQ|PO_0009077|FLOPO_0991118` | `allowed` / `new_class_candidate` | 6 | 6 |
