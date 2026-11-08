# Plan: running the 38 external floras in full against Qwen on unimatrix

Status 2026-11-08. The multi-flora pipeline (`tools/build_flora.sh`, `flopo2/ingest/pipeline.py`)
has only run as a pilot: 20 species treatments per flora (81 for the Flora of Iraq), 38 floras,
about 20,000 trait statements. This plan scales it to every treatment we hold locally.

## What there is to run

`python -m flopo2.ingest.external stats` (2026-11-08):

| Group | Sources | Treatments |
|---|---|---:|
| World Flora Online descriptions | `wfo` | 111,610 |
| eFloras | `eflora-foc` 34,180 · `eflora-fna` 11,193 · `eflora-other` 3,888 · `eflora-fop` 3,578 · `eflora-mfoc` 1,655 · `eflora-fom` 31 · `eflora-andes` 13 | 54,538 |
| African floras we hold in full | `kew-african` 12,104 · `fdac` 6,570 · `flora-zimbabwe` 3,374 · `flora-gabon` 3,112 · `korup-flora` 129 · `africa-tree-db` 642 | 25,931 |
| North American monographs and guides | `nybg-naf` 10,895 · `illinois-wildflowers` 1,233 · `feis-plants` 849 · `usda-plants` 678 · `silvics-na` 184 | 13,839 |
| Kew POWO regional floras | `powo-neotropical` 3,961 · `powo-ftea` 842 · `powo-fz` 798 · `powo-ildis` 409 · `powo-kew` 405 · `powo-fwta` 364 · `powo-fsom` 244 · `powo-cayman` 174 · `powo-cate` 112 · `powo-fiq` 82 · `powo-grassbase` 74 · `powo-tong` 7 | 7,472 |
| Other | `flora-malesiana` 2,992 · `smithsonian-botany` 1,383 · `flora-guianas` 1,162 · `plazi` 562 · `plants-tibet` 443 · `phytokeys` 283 | 6,825 |
| **Total** | 38 sources | **220,215** |

`fdac-genera` has no species treatments (genus descriptions only) and is excluded.

## Throughput and cost

Measured in the pilot (16 pipeline workers, Qwen3.8-27B-FP8 on unimatrix node005, 2× RTX 4090,
served through `unimatrix01:8000`): the transcription stage took about 6 s per treatment; all
seven stages (segment dump, Qwen transcription, annotation, Qwen re-read of unmatched rows,
Qwen term rules, Qwen relations and chains, final annotation and candidate staging) averaged
about 19 s per treatment when the 38 pilots ran back to back on one evening.

| Scope | Treatments | Wall time at ~19 s each | At ~10 s (tuned) |
|---|---:|---:|---:|
| Everything | 220,215 | ~48 days | ~26 days |
| Everything except WFO | 108,605 | ~24 days | ~13 days |
| African floras we hold in full | 25,931 | ~6 days | ~3 days |

The Qwen endpoint, not the pipeline, is the bottleneck: the KV cache saturates at about 14
concurrent requests, so `WORKERS=12` is the ceiling and the time scales with the number of
LLM calls. Storage is small (about 100 KB per treatment on disk in `local-corpora/<source>/`,
so roughly 20 GB for everything; `/mnt/data2` has 260 GB free).

The endpoint is shared with other users on unimatrix. Running continuously for weeks takes most
of its capacity; agree the time window, or run only at night (a `--limit` per invocation and
the per-source caches make the pipeline resumable, so it can be stopped and restarted).

## Order (phases, each useful on its own)

1. **African floras we hold in full (26k, ~1 week).** `kew-african`, `fdac`, `flora-zimbabwe`,
   `flora-gabon`, `korup-flora`, `africa-tree-db`. These are the floras FLOPO was built from,
   the text is already in the repository, and they share the Saudi guides' African context.
2. **Kew POWO regional floras and the other monographs (14k, ~3 days).** All `powo-*`,
   `flora-malesiana`, `flora-guianas`, `smithsonian-botany`, `plazi`, `plants-tibet`,
   `phytokeys`.
3. **North American material (14k, ~3 days).** `nybg-naf`, `illinois-wildflowers`,
   `feis-plants`, `usda-plants`, `silvics-na`.
4. **eFloras (55k, ~2 weeks).** `eflora-foc` is the big one; `eflora-fna`, `eflora-fop`,
   `eflora-other`, `eflora-mfoc` (mosses: a different vocabulary, expect many new candidates).
5. **WFO (112k, ~3 weeks).** Last, and possibly sampled first: one treatment per genus
   (about 15k) gives most of the vocabulary coverage at a seventh of the cost; the rest can
   follow when the endpoint is free.

Each phase ends with: the per-flora candidate reports (`curation/candidates/<source>/`), the
cross-flora roll-up (`flopo2.ingest.flora_candidates --all --rollup`), a review of the new
value-term and bearer candidates (the same curator-review route used on 2026-11-08), an
atlas rebuild (`flopo2.saudi.build`) and a staged deployment (`tools/deploy_atlas.sh`).

## How to run

On ws, in a `tmux` session, from `/mnt/data2/leechuck/flopoontology`:

```bash
export WORKERS=12 LIMIT=0 PYTHON=$PWD/.venv/bin/python
tools/build_flora.sh kew-african fdac flora-zimbabwe flora-gabon korup-flora africa-tree-db \
  2>&1 | tee -a local-corpora/run-logs/phase1-$(date +%F).log
```

- One source at a time inside the script; the Qwen stages cache every answer in
  `local-corpora/<source>/raw/<source>-qwen.jsonl` and `llm-*.jsonl`, so a crash or a stop
  loses at most the in-flight batch. Re-running the same command resumes.
- Watch `squeue`-free: the endpoint is a plain HTTP service, so check
  `curl -s unimatrix01.kaust.edu.sa:8000/v1/models` and the per-source log for 429/5xx.
- Nightly: `python -m flopo2.verify.data_model <source>-annotated.jsonl --stage gated` on the
  finished sources, and the candidate roll-up.

## Before starting

- Confirm the Qwen window with the other users of unimatrix node005 (or accept night-only runs).
- Decide on WFO: full run or genus sample first.
- `eflora-mfoc` (mosses) and `plazi` (treatments of many families) will produce the most
  "no ontology term" candidates; plan a curation pass after phase 2 and after phase 4 rather
  than at the very end.
- Licensing: the flora texts stay in the git-ignored `local-corpora/`; only annotations with
  short evidence spans are published, as for the Saudi guides.
- Fallback if unimatrix is unavailable: the same stages run against OpenRouter
  (`flopo2/extract/router.py`; DeepSeek-V3.2 was the best cheap model in the 2026 pilot, about
  $40 per 116k segments), with `--base-url`/`--model`/`--key-file` on each LLM stage.
