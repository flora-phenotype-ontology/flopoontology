# FLOPO Candidate Additions — USFS Fire Effects Information System (FEIS) — Plant Species (`feis-plants`)

- **Records processed**: 849
- **Extracted trait rows**: 17,165
- **Formal assertions emitted**: 13,716
- **Distinct candidate value terms**: 223
- **Distinct candidate anatomical bearers**: 53
- **Distinct novel PO × PATO/FLOPO combinations**: 594

## Top Candidate FLOPO Value Terms (`value_term_candidates.tsv`)

| Quality word | Count | Taxa | Suggested PATO parent | Top bearers |
|---|---:|---:|---|---|
| `native` | 54 | 54 | `PATO:0000141` (structure) | `PO_0000003` |
| `grass` | 25 | 25 | `PATO:0000141` (structure) | `PO_0000003` |
| `adventitious` | 21 | 20 | `PATO:0000141` (structure) | `PO_0009005|PO_0009006` |
| `conifer` | 19 | 19 | `PATO:0000141` (structure) | `PO_0000003` |
| `warm-season` | 19 | 19 | `PATO:0000141` (structure) | `PO_0000003` |
| `extensive` | 18 | 17 | `PATO:0000141` (structure) | `PO_0009005|PO_0004542|PO_0025025` |
| `sclerophyllous` | 17 | 16 | `PATO:0000141` (structure) | `PO_0000003|PO_0025034` |
| `cool-season` | 15 | 15 | `PATO:0000141` (structure) | `PO_0000003` |
| `graminoid` | 14 | 14 | `PATO:0000052` (shape) | `PO_0000003` |
| `fine` | 12 | 11 | `PATO:0000141` (structure) | `PO_0009005|PO_0009047|PO_0025073|PO_0025034` |
| `scale-like` | 11 | 11 | `PATO:0000052` (shape) | `PO_0004518|PO_0009001|PO_0004542` |
| `massive` | 9 | 8 | `PATO:0000141` (structure) | `PO_0004542|PO_0009005|PO_0025073|root crown|PO_0009047` |
| `tough` | 9 | 9 | `PATO:0000141` (structure) | `PO_0009005|PO_0004542|PO_0009047|PO_0004518|PO_0025034` |
| `round` | 8 | 8 | `PATO:0000141` (structure) | `PO_0009010|PO_0000003|canopy|PO_0009046` |
| `berrylike` | 7 | 7 | `PATO:0000052` (shape) | `PO_0009001` |
| `slow-growing` | 7 | 7 | `PATO:0000141` (structure) | `PO_0000003` |
| `thicket-forming` | 6 | 6 | `PATO:0000141` (structure) | `PO_0000003` |
| `tufted` | 6 | 6 | `PATO:0000060` (spatial pattern) | `PO_0009010|PO_0025034` |
| `creeping` | 4 | 4 | `PATO:0000141` (structure) | `PO_0009005` |
| `drought-tolerant` | 4 | 4 | `PATO:0000141` (structure) | `PO_0000003` |
| `semiwoody` | 4 | 4 | `PATO:0000150` (texture) | `PO_0009047|PO_0000003` |
| `drought resistant` | 3 | 3 | `PATO:0000141` (structure) | `PO_0000003` |
| `drought-resistant` | 3 | 3 | `PATO:0000141` (structure) | `PO_0000003|PO_0025034` |
| `fast-growing` | 3 | 3 | `PATO:0000141` (structure) | `PO_0000003` |
| `naked` | 3 | 3 | `PATO:0000141` (structure) | `PO_0009010|PO_0009049` |

## Top Candidate Anatomical Bearers (`bearer_candidates.tsv`)

| Bearer word | Count | Taxa | Qualities seen |
|---|---:|---:|---|
| `inch` | 5 | 2 | `amount` |
| `root crown` | 4 | 3 | `large|enlarged|irregularly shaped` |
| `seeds/fruit` | 4 | 3 | `amount` |
| `cm²` | 3 | 2 | `amount` |
| `tap` | 3 | 3 | `present` |
| `bur` | 2 | 2 | `present` |
| `cm/day` | 2 | 1 | `amount` |
| `heads/stem` | 2 | 1 | `amount` |
| `main root` | 2 | 2 | `amount` |
| `needle fascicle` | 2 | 1 | `amount` |
| `podetium` | 2 | 1 | `upright|fruticose` |
| `radial spine` | 2 | 2 | `amount` |
| `spore cover` | 2 | 2 | `absent` |
| `yr` | 2 | 1 | `amount` |
| `µg` | 2 | 2 | `amount` |
| `awn-teeth` | 1 | 1 | `amount` |
| `basal leave` | 1 | 1 | `amount` |
| `broken ridges` | 1 | 1 | `present` |
| `canopy` | 1 | 1 | `compact` |
| `cephalodium` | 1 | 1 | `small` |
| `compound leave` | 1 | 1 | `amount` |
| `constricted joints/pod` | 1 | 1 | `amount` |
| `crop` | 1 | 1 | `amount` |
| `cu cm` | 1 | 1 | `amount` |
| `fine rootlet` | 1 | 1 | `amount` |

## Top Novel PO × PATO / FLOPO Class Candidates (`novel_po_pato_combinations.tsv`)

| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Count | Taxa |
|---|---|---|---|---|---|---:|---:|
| `PO_0009005` | root | `PATO_0104356` | spreading | `EQ|PO_0009005|PATO_0104356` | `novel` / `new_class_candidate` | 42 | 42 |
| `PO_0000003` | whole plant | `FLOPO_0991072` | dioecious | `EQ|PO_0000003|FLOPO_0991072` | `allowed` / `new_class_candidate` | 40 | 40 |
| `PO_0000003` | whole plant | `FLOPO_0991071` | monoecious | `EQ|PO_0000003|FLOPO_0991071` | `allowed` / `new_class_candidate` | 38 | 38 |
| `PO_0009046` | flower | `PATO_0000070` | amount | `EQC|PO_0009046|n|PATO_0000070` | `allowed` / `new_class_candidate` | 32 | 29 |
| `PO_0000003` | whole plant | `PATO_0001603` | increased life span | `EQ|PO_0000003|PATO_0001603` | `novel` / `new_class_candidate` | 21 | 21 |
| `PO_0009001` | fruit | `FLOPO_0991149` | dehiscent | `EQ|PO_0009001|FLOPO_0991149` | `allowed` / `new_class_candidate` | 17 | 17 |
| `PO_0004518` | bark | `FLOPO_0991026` | fibrous | `EQ|PO_0004518|FLOPO_0991026` | `allowed` / `new_class_candidate` | 14 | 14 |
| `PO_0030099` | samara fruit | `PATO_0000467` | present | `EQ|PO_0030099|PATO_0000467` | `novel` / `new_class_candidate` | 14 | 14 |
| `PO_0009001` | fruit | `PATO_0104354` | winged | `EQ|PO_0009001|PATO_0104354` | `novel` / `new_class_candidate` | 13 | 13 |
| `PO_0025034` | leaf | `PATO_0104359` | entire | `EQ|PO_0025034|PATO_0104359` | `novel` / `new_class_candidate` | 13 | 13 |
| `PO_0009005` | root | `PATO_0000700` | rough | `EQ|PO_0009005|PATO_0000700` | `novel` / `new_class_candidate` | 12 | 12 |
| `PO_0000003` | whole plant | `PATO_0000515` | tolerant to | `EQ|PO_0000003|PATO_0000515` | `novel` / `new_class_candidate` | 10 | 10 |
| `PO_0000003` | whole plant | `PATO_0001604` | decreased life span | `EQ|PO_0000003|PATO_0001604` | `novel` / `new_class_candidate` | 10 | 10 |
| `PO_0004518` | bark | `PATO_0001595` | depth | `EQ|PO_0004518|PATO_0001595` | `novel` / `new_class_candidate` | 10 | 10 |
| `PO_0000003` | whole plant | `FLOPO_0991366` | multistemmed | `EQ|PO_0000003|FLOPO_0991366` | `allowed` / `new_class_candidate` | 9 | 9 |
| `PO_0009046` | flower | `FLOPO_0991104` | urceolate | `EQ|PO_0009046|FLOPO_0991104` | `allowed` / `new_class_candidate` | 9 | 9 |
| `PO_0009049` | inflorescence | `FLOPO_0991142` | spike-like | `EQ|PO_0009049|FLOPO_0991142` | `allowed` / `new_class_candidate` | 9 | 9 |
| `PO_0000003` | whole plant | `FLOPO_0991268` | clonal | `EQ|PO_0000003|FLOPO_0991268` | `allowed` / `new_class_candidate` | 8 | 8 |
| `PO_0009001` | fruit | `PATO_0001732` | non-deciduous (any body part) | `EQ|PO_0009001|PATO_0001732` | `novel` / `new_class_candidate` | 8 | 8 |
| `PO_0009006` | shoot system | `PATO_0000467` | present | `EQ|PO_0009006|PATO_0000467` | `novel` / `new_class_candidate` | 8 | 1 |
| `PO_0004542` | rhizome | `FLOPO_0991035` | subterranean | `EQ|PO_0004542|FLOPO_0991035` | `allowed` / `new_class_candidate` | 7 | 7 |
| `PO_0009010` | seed | `PATO_0000586` | increased size | `EQ|PO_0009010|PATO_0000586` | `novel` / `new_class_candidate` | 7 | 7 |
| `PO_0009047` | stem | `PATO_0000001` | characteristic | `EQV|PO_0009047|ONE_OF|PATO_0000402&PATO_0001503` | `novel` / `annotation_extension_only` | 7 | 7 |
| `PO_0009047` | stem | `PATO_0104367` | biennial life span | `EQ|PO_0009047|PATO_0104367` | `novel` / `new_class_candidate` | 7 | 7 |
| `PO_0004542` | rhizome | `PATO_0001472` | decreased depth | `EQ|PO_0004542|PATO_0001472` | `novel` / `new_class_candidate` | 6 | 6 |
