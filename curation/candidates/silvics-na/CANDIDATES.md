# FLOPO Candidate Additions — Silvics of North America (USFS Agriculture Handbook 654) (`silvics-na`)

- **Records processed**: 20
- **Extracted trait rows**: 419
- **Formal assertions emitted**: 162
- **Distinct candidate value terms**: 18
- **Distinct candidate anatomical bearers**: 17
- **Distinct novel PO × PATO/FLOPO combinations**: 28

## Top Candidate FLOPO Value Terms (`value_term_candidates.tsv`)

| Quality word | Count | Taxa | Suggested PATO parent | Top bearers |
|---|---:|---:|---|---|
| `germination` | 2 | 2 | `PATO:0000141` (structure) | `PO_0009010` |
| `mycorrhizal` | 2 | 2 | `PATO:0000141` (structure) | `PO_0009005` |
| `resinous` | 2 | 2 | `PATO:0000150` (texture) | `PO_0009001` |
| `windfirm` | 2 | 2 | `PATO:0000141` (structure) | `PO_0000003` |
| `acicular` | 1 | 1 | `PATO:0000141` (structure) | `PO_0025034` |
| `carrot-like` | 1 | 1 | `PATO:0000052` (shape) | `PO_0009005` |
| `dormant` | 1 | 1 | `PATO:0000141` (structure) | `embryo` |
| `epigeal` | 1 | 1 | `PATO:0000141` (structure) | `PO_0009010` |
| `globe-shaped` | 1 | 1 | `PATO:0000052` (shape) | `PO_0009001` |
| `hardy` | 1 | 1 | `PATO:0000141` (structure) | `PO_0000003` |
| `intensive` | 1 | 1 | `PATO:0000141` (structure) | `PO_0009005` |
| `monosporangiate` | 1 | 1 | `PATO:0000052` (shape) | `PO_0025083` |
| `needlelike` | 1 | 1 | `PATO:0000052` (shape) | `PO_0025034` |
| `round` | 1 | 1 | `PATO:0000141` (structure) | `scale` |
| `submonoecious` | 1 | 1 | `PATO:0001894` (phenotypic sex) | `PO_0000003` |
| `surface` | 1 | 1 | `PATO:0000141` (structure) | `PO_0009010` |
| `unequal` | 1 | 1 | `PATO:0000141` (structure) | `wing` |
| `widespread` | 1 | 1 | `PATO:0000141` (structure) | `PO_0009005` |

## Top Candidate Anatomical Bearers (`bearer_candidates.tsv`)

| Bearer word | Count | Taxa | Qualities seen |
|---|---:|---:|---|
| `scale` | 8 | 4 | `amount|short|thin|fan-shaped|notched` |
| `percent` | 5 | 1 | `amount` |
| `cone` | 3 | 3 | `globose|ovoid|pendent` |
| `graft` | 3 | 1 | `amount|present|deep` |
| `pollen cone` | 2 | 2 | `red` |
| `/m²` | 1 | 1 | `amount` |
| `embryo` | 1 | 1 | `straight` |
| `mm/day` | 1 | 1 | `amount` |
| `month` | 1 | 1 | `amount` |
| `ovulate cone` | 1 | 1 | `subglobose` |
| `seed cone` | 1 | 1 | `purple` |
| `sinker` | 1 | 1 | `present` |
| `whorl` | 1 | 1 | `amount` |
| `wing` | 1 | 1 | `amount` |
| `winged` | 1 | 1 | `present` |
| `year` | 1 | 1 | `amount` |
| `°c` | 1 | 1 | `amount` |

## Top Novel PO × PATO / FLOPO Class Candidates (`novel_po_pato_combinations.tsv`)

| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Count | Taxa |
|---|---|---|---|---|---|---:|---:|
| `PO_0025083` | strobilus | `PATO_0000467` | present | `EQ|PO_0025083|PATO_0000467` | `novel` / `new_class_candidate` | 12 | 3 |
| `PO_0009005` | root | `PATO_0001472` | decreased depth | `EQ|PO_0009005|PATO_0001472` | `novel` / `new_class_candidate` | 7 | 7 |
| `PO_0009005` | root | `PATO_0001595` | depth | `EQ|PO_0009005|PATO_0001595` | `novel` / `new_class_candidate` | 4 | 4 |
| `PO_0009005` | root | `PATO_0001596` | increased depth | `EQ|PO_0009005|PATO_0001596` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0020127` | primary root | `PATO_0000467` | present | `EQ|PO_0020127|PATO_0000467` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0008037` | seedling | `PATO_0000119` | height | `EQ|PO_0008037|PATO_0000119` | `novel` / `new_class_candidate` | 2 | 2 |
| `PO_0009010` | seed | `FLOPO_0985004` | winged | `EQ|PO_0009010|FLOPO_0985004` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0009046` | flower | `PATO_0000587` | decreased size | `EQ|PO_0009046|PATO_0000587` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0009005` | root | `PATO_0000582` | increased weight | `EQ|PO_0009005|PATO_0000582` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0009005` | root | `PATO_0001665` | superficial | `EQ|PO_0009005|PATO_0001665` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0009005` | root | `FLOPO_0991027` | fibrous-rooted | `EQ|PO_0009005|FLOPO_0991027` | `allowed` / `new_class_candidate` | 1 | 1 |
| `PO_0009010` | seed | `FLOPO_0991046` | membranous | `EQ|PO_0009010|FLOPO_0991046` | `allowed` / `new_class_candidate` | 1 | 1 |
| `PO_0009010` | seed | `PATO_0000169` | viability | `EQ|PO_0009010|PATO_0000169` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0009010` | seed | `PATO_0000599` | decreased width | `EQ|PO_0009010|PATO_0000599` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0009026` | sporophyll | `PATO_0000070` | amount | `EQ|PO_0009026|PATO_0000070` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0009028` | microsporophyll | `PATO_0000070` | amount | `EQ|PO_0009028|PATO_0000070` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0009046` | flower | `FLOPO_0991003` | solitary | `EQ|PO_0009046|FLOPO_0991003` | `allowed` / `new_class_candidate` | 1 | 1 |
| `PO_0009046` | flower | `PATO_0001865` | spheroid | `EQ|PO_0009046|PATO_0001865` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0009049` | inflorescence | `PATO_0104311` | purplish red | `EQ|PO_0009049|PATO_0104311` | `allowed` / `new_class_candidate` | 1 | 1 |
| `PO_0009055` | bract | `FLOPO_0985003` | reflexed | `EQ|PO_0009055|FLOPO_0985003` | `allowed` / `new_class_candidate` | 1 | 1 |
| `PO_0009055` | bract | `PATO_0000574` | decreased length | `EQ|PO_0009055|PATO_0000574` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0025083` | strobilus | `FLOPO_0988008` | purple | `EQ|PO_0025083|FLOPO_0988008` | `allowed` / `new_class_candidate` | 1 | 1 |
| `PO_0025083` | strobilus | `FLOPO_0988084` | dark brown | `EQ|PO_0025083|FLOPO_0988084` | `allowed` / `new_class_candidate` | 1 | 1 |
| `PO_0025083` | strobilus | `FLOPO_0988237` | dark purple | `EQ|PO_0025083|FLOPO_0988237` | `allowed` / `new_class_candidate` | 1 | 1 |
| `PO_0025083` | strobilus | `PATO_0001249` | dark green | `EQ|PO_0025083|PATO_0001249` | `allowed` / `new_class_candidate` | 1 | 1 |
