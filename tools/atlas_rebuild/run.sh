#!/bin/bash
# Rebuild the trait atlas after a change to the ontology, the rule tables or the annotator:
# re-annotate every finished flora, apply the passes that follow annotation, check, build, deploy.
# See docs/atlas-rebuild.md. Run from the repository root, in the background:
#
#   NOTE="what changed, one sentence for the release history" tools/atlas_rebuild/run.sh > LOG 2>&1 &
#
# Environment: L (log and marker directory, default ~/tmp/atlas-rebuild), BACKUP (directory for
# the annotation files as they were), FROM (reannotate | passes | build, default reannotate),
# DEPLOY=0 to stop after the build.
cd "$(git rev-parse --show-toplevel)" || exit 9
export PATH=$HOME/.cache/flopo-venv/bin:$PATH PYTHONPATH=. TMPDIR=${TMPDIR:-$HOME/tmp}
L=${L:-$HOME/tmp/atlas-rebuild}; T=tools/atlas_rebuild; FROM=${FROM:-reannotate}
BACKUP=${BACKUP:-$L/backup}
mkdir -p "$L"
room() { awk '/CommitLimit/{l=$2}/Committed_AS/{c=$2}END{print int((l-c)/1048576)}' /proc/meminfo; }
wait_room() { for _ in $(seq 1440); do [ "$(room)" -ge "$1" ] && return 0; sleep 60; done; return 1; }
say() { echo "== $(date '+%m-%d %H:%M') $*"; }
pgrep -af "deploy_atlas.sh --(stamp|resume)" | grep -v pgrep >/dev/null && { say "a deploy is running; stopping"; exit 3; }
[ -n "$NOTE" ] || [ "${DEPLOY:-1}" = 0 ] || { say "NOTE is not set (the line for the release history)"; exit 9; }

if [ "$FROM" = reannotate ]; then
  DONE=$(ls local-corpora/run-logs/done); N=$(echo $DONE | wc -w)
  say "backup to $BACKUP"; mkdir -p "$BACKUP"
  for d in $DONE; do
    f=local-corpora/$d/derived/$d-annotated.jsonl; [ -e "$BACKUP/$d-annotated.jsonl" ] || cp -p $f "$BACKUP/" || { say "backup failed: $d"; exit 2; }
  done
  cp -p local-corpora/saudi-flora/ncvc-derived/ncvc-saudi-annotated.jsonl local-corpora/saudi-collenette/derived/collenette-saudi-annotated.jsonl "$BACKUP/" || exit 2
  say "re-annotation of $N floras, three lanes (room $(room) GB)"
  BIG="eflora-fna kew-african nybg-naf fdac"   # the largest flora (eflora-foc) has a lane of its own
  REST=$(for d in $DONE; do case " eflora-foc $BIG " in *" $d "*) ;; *) echo $d;; esac; done)
  python -m tools.reannotate_flora eflora-foc > $L/lane-a.log 2>&1 & a=$!
  python -m tools.reannotate_flora $BIG > $L/lane-b.log 2>&1 & b=$!
  python -m tools.reannotate_flora $REST > $L/lane-c.log 2>&1 & c=$!
  ( NCVC=local-corpora/saudi-ncvc-guide; A=local-corpora/saudi-flora/ncvc-derived
    python -m flopo2.ingest.collenette_annotate > /dev/null &&
    python -m flopo2.ingest.ncvc_annotate $NCVC > /dev/null &&
    python -m flopo2.ingest.ncvc_annotate $NCVC -o $A --extra-rules flopo2/ingest/llm_term_rules.tsv --override-rules flopo2/ingest/flora_value_term_rules.tsv flopo2/ingest/collenette_normalization.tsv --atlas > /dev/null &&
    for corpus in $A/ncvc-saudi-annotated local-corpora/saudi-collenette/derived/collenette-saudi-annotated; do
      python -m flopo2.verify.data_model $corpus.jsonl --stage gated > $corpus.validation.json || true; done
  ) > $L/saudi.log 2>&1 & s=$!
  wait $a $b $c; wait $s; src=$?
  cat $L/lane-?.log | grep -E "^[a-z0-9-]+: " > $L/reannotate.summary
  n=$(grep -c "assertions" $L/reannotate.summary); f=$(grep -c "FAILED" $L/reannotate.summary)
  e=$(grep -v "data-model errors 0," $L/reannotate.summary | grep -c "data-model errors")
  say "floras re-annotated $n of $N, failed $f, with data-model errors $e; Saudi guides exit $src"
  # A failed flora leaves a truncated annotation file: fix the cause and run the flora again
  # (python -m tools.reannotate_flora NAME), then continue with FROM=passes.
  [ "$src" -eq 0 ] && [ "$f" -eq 0 ] && [ "$e" -eq 0 ] && [ "$n" -eq "$N" ] || { say "stopping before the passes; see $L/reannotate.summary"; exit 8; }
  FROM=passes
fi

if [ "$FROM" = passes ]; then
  say "position and plant-group passes"; python $T/apply_position_and_group.py > $L/convert.log 2>&1 || { say "failed"; tail -3 $L/convert.log; exit 2; }; say "$(grep TOTAL $L/convert.log | cut -c1-300)"
  say "bryophyte terms"; python $T/apply_bryophyte_terms.py > $L/moss-convert.log 2>&1 || { say "failed"; tail -3 $L/moss-convert.log; exit 2; }; say "$(grep TOTAL $L/moss-convert.log | cut -c1-200)"
  say "copies (room $(room) GB)"; wait_room 14
  python -m tools.atlas_duplicates > $L/duplicates.log 2>&1 || {
    [ -s local-corpora/saudi-flora/duplicates.tsv ] && say "copies: list not rebuilt; using the list of $(date -r local-corpora/saudi-flora/duplicates.tsv '+%m-%d %H:%M')" || { say "duplicates failed"; exit 6; }
  }
  say "ELK check of every flora (room $(room) GB)"; wait_room 30
  rm -f $L/check_all.log
  python $T/check_all.py $L/check_all.log > $L/check_all.err 2>&1 || { say "check failed"; tail -5 $L/check_all.err | cut -c1-300; exit 4; }
  grep -q "^DONE" $L/check_all.log || { say "check did not finish"; exit 4; }
  grep '^{' $L/check_all.log | grep -q '"unsatisfiable": null\|"taxon_contradictions": null' && { say "some floras were not checked; stopping"; exit 5; }
  say "class expression of every record"
  python $T/precheck_classes.py > $L/precheck.log 2>&1; grep -q "^FAILURES 0$" $L/precheck.log || { say "records without a class expression; see $L/precheck.log"; exit 5; }
  FROM=build
fi

free=$(df -BG --output=avail local-corpora | tail -1 | tr -dc 0-9)
[ "$free" -ge 150 ] || { say "only $free GB free; the build and a release need about 150 GB"; exit 6; }
say "atlas build (room $(room) GB, disk $free GB)"; wait_room 30
python -m flopo2.saudi.build --rebuild-assertions > $L/build.log 2>&1 || { say "build failed"; tail -5 $L/build.log | cut -c1-300; exit 7; }
say "build done"
[ "${DEPLOY:-1}" = 0 ] && exit 0
STAMP=$(date +%Y%m%d-%H%M)
printf '%s\t%s\t\t%s\n' "$STAMP" "$(date +%Y-%m-%d)" "$NOTE" >> deploy/atlas/data-releases.tsv
say "deploy $STAMP (room $(room) GB)"; wait_room 45
tools/deploy_atlas.sh --stamp "$STAMP" > $L/deploy.log 2>&1; rc=$?
say "deploy exit $rc"; grep "FAIL\|deploy_atlas:" $L/deploy.log | tail -8 | cut -c1-300
tools/deploy_atlas.sh --status 2>&1 | head -2
exit $rc
