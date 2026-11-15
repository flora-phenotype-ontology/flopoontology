# FLOPO Candidate Additions — USDA NRCS PLANTS Database — Botanical Descriptions (`usda-plants`)

- **Records processed**: 678
- **Extracted trait rows**: 15,003
- **Formal assertions emitted**: 11,827
- **Distinct candidate value terms**: 308
- **Distinct candidate anatomical bearers**: 51
- **Distinct novel PO × PATO/FLOPO combinations**: 622

## Top Candidate FLOPO Value Terms (`value_term_candidates.tsv`)

| Quality word | Count | Taxa | Suggested PATO parent | Top bearers |
|---|---:|---:|---|---|
| `grass` | 24 | 24 | `PATO:0000141` (structure) | `PO_0000003` |
| `forb` | 20 | 20 | `PATO:0000141` (structure) | `PO_0000003` |
| `bunchgrass` | 18 | 18 | `PATO:0000141` (structure) | `PO_0000003` |
| `bunch` | 16 | 16 | `PATO:0000141` (structure) | `PO_0000003` |
| `rolled` | 14 | 14 | `PATO:0000141` (structure) | `PO_0025034|PO_0020039` |
| `round` | 12 | 12 | `PATO:0000141` (structure) | `PO_0009010|FLOPO_0985030|PO_0009051|PO_0020038` |
| `sod-forming` | 10 | 10 | `PATO:0000141` (structure) | `PO_0000003` |
| `wiry` | 10 | 10 | `PATO:0000141` (structure) | `PO_0009047|PO_0025034|PO_0004542` |
| `flat-topped` | 9 | 9 | `PATO:0000141` (structure) | `PO_0009049` |
| `native` | 9 | 9 | `PATO:0000141` (structure) | `PO_0000003` |
| `colonial` | 8 | 8 | `PATO:0000141` (structure) | `PO_0000003` |
| `scale-like` | 8 | 8 | `PATO:0000052` (shape) | `PO_0009001|PO_0009051|PO_0009047|PO_0009060|PO_0009046` |
| `warm-season` | 8 | 8 | `PATO:0000141` (structure) | `PO_0000003` |
| `cool season` | 7 | 7 | `PATO:0000141` (structure) | `PO_0000003` |
| `naked` | 7 | 7 | `PATO:0000141` (structure) | `PO_0009049|PO_0000055|axis|PO_0020141` |
| `stalked` | 6 | 6 | `PATO:0000141` (structure) | `PO_0009051|PO_0009049|ovulate cone` |
| `crooked` | 5 | 5 | `PATO:0000141` (structure) | `PO_0009047|PO_0025073|PO_0025349` |
| `threadlike` | 5 | 5 | `PATO:0000052` (shape) | `PO_0025034` |
| `tubercled` | 5 | 5 | `PATO:0000141` (structure) | `PO_0009001|PO_0009055` |
| `warm season` | 5 | 5 | `PATO:0000141` (structure) | `PO_0000003` |
| `bean-like` | 4 | 4 | `PATO:0000052` (shape) | `PO_0009010|PO_0009046` |
| `broadest above the middle` | 4 | 4 | `PATO:0000141` (structure) | `PO_0009001` |
| `burgundy` | 4 | 4 | `PATO:0000141` (structure) | `PO_0025073|PO_0025034` |
| `extensive` | 4 | 4 | `PATO:0000141` (structure) | `PO_0009005` |
| `leafless` | 4 | 4 | `PATO:0000141` (structure) | `PO_0003024` |

## Top Candidate Anatomical Bearers (`bearer_candidates.tsv`)

| Bearer word | Count | Taxa | Qualities seen |
|---|---:|---:|---|
| `cone scale` | 12 | 3 | `length|fan-shaped|amount|ovate|green` |
| `needle` | 7 | 7 | `amount|present` |
| `acorn` | 6 | 5 | `amount|present` |
| `per pound` | 5 | 5 | `amount` |
| `per bundle` | 4 | 2 | `amount` |
| `acorns per pound` | 3 | 3 | `amount` |
| `bulb-coat` | 3 | 1 | `brown|thin|reticulate` |
| `flower head` | 3 | 3 | `amount|small` |
| `husk` | 3 | 3 | `sticky|persistent|thick` |
| `nerved` | 3 | 1 | `amount` |
| `bulb coat` | 2 | 1 | `light-colored|indistinct` |
| `ovulate cone` | 2 | 1 | `ovoid|length` |
| `root stock` | 2 | 1 | `horizontal|thick` |
| `seed stalk` | 2 | 2 | `amount` |
| `side` | 2 | 2 | `amount` |
| `aerial` | 1 | 1 | `present` |
| `blisters` | 1 | 1 | `present` |
| `bur` | 1 | 1 | `amount` |
| `capitate` | 1 | 1 | `present` |
| `common` | 1 | 1 | `amount` |
| `fascicle sheath` | 1 | 1 | `short` |
| `female spike` | 1 | 1 | `amount` |
| `floral tube` | 1 | 1 | `length` |
| `fruiting head` | 1 | 1 | `pendulous` |
| `glabrou` | 1 | 1 | `amount` |

## Top Novel PO × PATO / FLOPO Class Candidates (`novel_po_pato_combinations.tsv`)

| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Count | Taxa |
|---|---|---|---|---|---|---:|---:|
| `PO_0000003` | whole plant | `FLOPO_0991072` | dioecious | `EQ|PO_0000003|FLOPO_0991072` | `allowed` / `new_class_candidate` | 30 | 30 |
| `PO_0000003` | whole plant | `FLOPO_0991071` | monoecious | `EQ|PO_0000003|FLOPO_0991071` | `allowed` / `new_class_candidate` | 27 | 27 |
| `PO_0009046` | flower | `PATO_0000070` | amount | `EQC|PO_0009046|n|PATO_0000070` | `allowed` / `new_class_candidate` | 23 | 23 |
| `PO_0025034` | leaf | `PATO_0104359` | entire | `EQ|PO_0025034|PATO_0104359` | `novel` / `new_class_candidate` | 16 | 16 |
| `PO_0009001` | fruit | `PATO_0104354` | winged | `EQ|PO_0009001|PATO_0104354` | `novel` / `new_class_candidate` | 14 | 14 |
| `PO_0020039` | leaf lamina | `PATO_0002258` | pointed | `EQ|PO_0020039|PATO_0002258` | `novel` / `new_class_candidate` | 12 | 12 |
| `PO_0020104` | leaf sheath | `FLOPO_0991002` | basal | `EQ|PO_0020104|FLOPO_0991002` | `allowed` / `new_class_candidate` | 12 | 12 |
| `PO_0020039` | leaf lamina | `PATO_0001500` | tapered | `EQ|PO_0020039|PATO_0001500` | `novel` / `new_class_candidate` | 11 | 10 |
| `PO_0030099` | samara fruit | `PATO_0000467` | present | `EQ|PO_0030099|PATO_0000467` | `novel` / `new_class_candidate` | 11 | 11 |
| `PO_0009049` | inflorescence | `FLOPO_0991142` | spike-like | `EQ|PO_0009049|FLOPO_0991142` | `allowed` / `new_class_candidate` | 9 | 9 |
| `PO_0025034` | leaf | `FLOPO_0980232` | simple grass-like | `EQ|PO_0025034|FLOPO_0980232` | `allowed` / `new_class_candidate` | 9 | 9 |
| `PO_0000049` | leaf lamina abaxial epidermis | `PATO_0001320` | pubescent hair | `EQ|PO_0000049|PATO_0001320` | `allowed` / `new_class_candidate` | 8 | 8 |
| `PO_0004518` | bark | `FLOPO_0991026` | fibrous | `EQ|PO_0004518|FLOPO_0991026` | `allowed` / `new_class_candidate` | 8 | 8 |
| `PO_0020104` | leaf sheath | `PATO_0002488` | overlapping | `EQ|PO_0020104|PATO_0002488` | `novel` / `new_class_candidate` | 8 | 8 |
| `PO_0009059` | corolla | `FLOPO_0991085` | bilabiate | `EQ|PO_0009059|FLOPO_0991085` | `allowed` / `new_class_candidate` | 7 | 7 |
| `PO_0020039` | leaf lamina | `PATO_0104359` | entire | `EQ|PO_0020039|PATO_0104359` | `novel` / `new_class_candidate` | 7 | 7 |
| `PO_0025349` | awn | `PATO_0002445` | torsioned | `EQ|PO_0025349|PATO_0002445` | `novel` / `new_class_candidate` | 7 | 7 |
| `PO_0009010` | seed | `PATO_0000586` | increased size | `EQ|PO_0009010|PATO_0000586` | `novel` / `new_class_candidate` | 6 | 6 |
| `PO_0009046` | flower | `PATO_0000330` | irregular spatial pattern | `EQ|PO_0009046|PATO_0000330` | `novel` / `new_class_candidate` | 6 | 6 |
| `PO_0009077` | staminode | `FLOPO_0991118` | bearded | `EQ|PO_0009077|FLOPO_0991118` | `allowed` / `new_class_candidate` | 6 | 6 |
| `PO_0020039` | leaf lamina | `PATO_0002450` | firm | `EQ|PO_0020039|PATO_0002450` | `novel` / `new_class_candidate` | 6 | 6 |
| `PO_0020104` | leaf sheath | `PATO_0002254` | flattened | `EQ|PO_0020104|PATO_0002254` | `novel` / `new_class_candidate` | 6 | 6 |
| `PO_0020106` | leaf sheath auricle | `PATO_0002258` | pointed | `EQ|PO_0020106|PATO_0002258` | `novel` / `new_class_candidate` | 6 | 6 |
| `PO_0025034` | leaf | `FLOPO_0991161` | trifoliolate | `EQ|PO_0025034|FLOPO_0991161` | `allowed` / `new_class_candidate` | 6 | 6 |
| `PO_0025034` | leaf | `PATO_0001968` | parallelodromous | `EQ|PO_0025034|PATO_0001968` | `novel` / `new_class_candidate` | 6 | 6 |
