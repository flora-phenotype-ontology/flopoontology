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

| Scope | Treatments | At 12 workers (~19 s each) | At 4 workers (~57 s each) |
|---|---:|---:|---:|
| Everything | 220,215 | ~48 days | ~5 months |
| Everything except WFO | 108,605 | ~24 days | ~2.5 months |
| The 36 floras below 35k treatments (all but eFlora of China and WFO) | 74,425 | ~16 days | ~7 weeks |

The Qwen endpoint, not the pipeline, is the bottleneck: the KV cache saturates at about 14
concurrent requests, and the time scales with the number of LLM calls. Storage is small (about
100 KB per treatment on disk in `local-corpora/<source>/`, so roughly 20 GB for everything;
`/mnt/data2` has 250 GB free).

**Decision 2026-11-09: run with `WORKERS=4`.** The endpoint is shared with other users on
unimatrix; the run may occupy it for months, but only at about a third of its capacity so other
work can proceed alongside. Four concurrent requests is the setting; six is the allowed maximum.

## Order: smallest flora first, publish after each

Decision 2026-11-09: the floras run one at a time in ascending order of size, and the trait
atlas is rebuilt and redeployed as soon as a flora is complete, so the website grows flora by
flora from the first day. `tools/run_floras_full.sh` holds the order (powo-tong 7 treatments …
eflora-foc 34,180, wfo 111,610) and does the publishing; `tools/run_floras_full.sh --status`
shows progress. With 4 workers, the 18 floras under 700 treatments finish in the first days,
the 36 floras other than eFlora of China and WFO in about seven weeks, eFlora of China takes
about three more weeks, and WFO about ten.

The thematic grouping below is kept as the way to read the results; it is no longer the run
order.

1. **African floras we hold in full (26k, ~1 week at 12 workers).** `kew-african`, `fdac`, `flora-zimbabwe`,
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

Started 2026-11-09 on ws in the `tmux` session `flopo-floras`
(`tmux attach -t flopo-floras`), from `/mnt/data2/leechuck/flopoontology`:

```bash
tmux new -d -s flopo-floras 'tools/run_floras_full.sh 2>&1 | tee -a local-corpora/run-logs/console.log'
tools/run_floras_full.sh --status          # done / running / failed / pending per flora
tail -f local-corpora/run-logs/driver.log  # one line per flora, attempt and atlas deployment
```

- The driver runs `tools/build_flora.sh <source>` with `WORKERS=4 LIMIT=0`, one flora at a
  time, retrying a failed flora twice (10 minutes apart) before moving on and marking it
  `local-corpora/run-logs/<source>.failed`. A finished flora is marked in
  `local-corpora/run-logs/done/`; remove the marker to run it again.
- After each flora: `flopo2.saudi.build` (all sources, about 30 minutes) and
  `tools/deploy_atlas.sh --stamp <time>-<sources>` (tests, release, QLever index, staging
  checks, switch, live and public checks, automatic rollback; about 10 minutes). The publish
  runs in the background so the next flora starts at once; one publish at a time, and floras
  that finish while one is running join the next. Old atlas releases other than the live one,
  the previous one and their bases are pruned to hold disk space (each release is about 1 GB).
- The caches and derived corpora under `local-corpora/` name ontology identifiers. After an
  identifier migration (as for the PATO bridges on 2026-11-08) run
  `tools/migrate_pato_bridges.py --local-corpora` and regenerate the annotated corpora
  deterministically (`flora_annotate.run` per flora, the Saudi annotate steps of
  `tools/build_saudi_flora.sh`), or the atlas build rejects the stale class-expression hashes.
- The Qwen stages cache every answer in `local-corpora/<source>/raw/<source>-qwen.jsonl` and
  `llm-*.jsonl`, so a crash or a stop loses at most the in-flight batch. Killing the tmux
  session and starting it again resumes where it was.
- Transcriptions cut off at the output cap (long treatments) are retried with a larger cap
  (4k, 8k, 12k, 16k tokens) before a segment is recorded as errored.
- For a flora whose full run has started but not finished (a run log in
  `local-corpora/run-logs/` without a `done/` marker), the atlas build uses the snapshot it saved
  last time (`local-corpora/saudi-flora/rdf/<source>-corpus-tagged.jsonl`) instead of the corpus
  the run is rewriting, so the website keeps that flora's earlier state (dropping it fails the
  deploy's coverage check, C6) until the run marks it done; `--include-unfinished` reads the live
  corpus instead. Assertion modules are written
  as N-Triples under their `.ttl` names: rdflib's Turtle writer is superlinear (21 min against 5 s
  for 283 treatments) and a publish that included the partial eFlora of China hung for 16 hours
  on 2026-11-09/10. The assertion modules and the per-source index and places graphs are streamed
  to disk in chunks of 200,000 triples: ws runs with strict overcommit (`vm.overcommit_memory=2`)
  beside other workloads, and eFlora of China held as one rdflib graph (about 40 GB) failed with
  `MemoryError`. The QLever index is built with 2 threads, 1M-triple batches and 1 GB of sort memory
  (`QLEVER_INDEX_THREADS`, `QLEVER_INDEX_MEMORY` override) for the same reason.
- One manual command still works for a single flora: `WORKERS=4 LIMIT=0 tools/build_flora.sh <source>`.
- Watch `squeue`-free: the endpoint is a plain HTTP service, so check
  `curl -s unimatrix01.kaust.edu.sa:8000/v1/models` and the per-source log for 429/5xx.
- Nightly: `python -m flopo2.verify.data_model <source>-annotated.jsonl --stage gated` on the
  finished sources, and the candidate roll-up.

## ORIX lane (added 2026-11-09)

Decision 2026-11-09: ORIX runs floras too, opportunistically. `tools/orix_qwen_lane.sh` (tmux
session `flopo-orix` on ws) keeps one preemptible job queued on the ORIX `freecycle-h100` or
`freecycle-h200` partition (whichever has an idle GPU; the job is moved if the other type frees up
first). The job (`tools/orix/qwen_flopo.sbatch`, copied to `/mnt/data/u/hohndor/flopo-qwen/`)
serves Qwen3.8-27B-FP8 with vLLM 0.28 from the pixi environment that already exists on ORIX
(`/mnt/data/u/hohndor/qwen-serve-cu129`, model in the HF cache; about four minutes to start) on
one GPU, bound to the node network with a per-job random key. The lane script fetches the key,
opens an SSH tunnel through the login node (`127.0.0.1:8200` on ws) and starts
`LANE=orix WORKERS=32 tools/run_floras_full.sh`, which takes the **largest** flora first (WFO
excluded, `ORIX_SKIP`) while the unimatrix lane continues from the smallest; the two lanes meet in
the middle. Claims in `local-corpora/run-logs/claims/` keep them off the same flora; completed
floras queue in `local-corpora/run-logs/publish-pending` and whichever lane holds the publish lock
republishes the atlas, so publishing stays one at a time.

When the job is preempted, hits its 24 h limit or dies, the driver stops its build within two
minutes (the endpoint health check fails), the lane resubmits, and the flora resumes from its
caches on the next job. The job itself exits after 30 minutes without a request so an orphaned
allocation never holds an idle GPU; `tmux kill-session -t flopo-orix` cancels the job. The shared
term-decision cache may be appended by both lanes; its loader skips a torn line. The ORIX lane
state is shown by `tools/run_floras_full.sh --status` and logged in
`local-corpora/run-logs/orix/lane.log`.

When the Slurm controller on ORIX stops answering (seen 2026-11-09 19:33, about an hour), `squeue`
fails for every job; the lane then asks the job's vLLM server itself (`/health` from the login node)
and keeps the tunnel and the build running while it answers, instead of treating the silence as the
job's end. Submissions during the outage fail and are retried every 10 minutes; `sbatch`'s message is
in the lane log.

## Before starting

- Qwen window: agreed 2026-11-09 (weeks or months, at 4 workers).
- WFO runs last and in full unless decided otherwise before the run reaches it (a genus
  sample of about 15k is the alternative).
- `eflora-mfoc` (mosses) and `plazi` (treatments of many families) will produce the most
  "no ontology term" candidates; plan a curation pass after phase 2 and after phase 4 rather
  than at the very end.
- Licensing: the flora texts stay in the git-ignored `local-corpora/`; only annotations with
  short evidence spans are published, as for the Saudi guides.
- Fallback if unimatrix is unavailable: the same stages run against OpenRouter
  (`flopo2/extract/router.py`; DeepSeek-V3.2 was the best cheap model in the 2026 pilot, about
  $40 per 116k segments), with `--base-url`/`--model`/`--key-file` on each LLM stage.
