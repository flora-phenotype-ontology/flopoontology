"""Transcribe any flora's species treatment segments into NCVC-style phenotype records with Qwen on unimatrix.

Generalizes :mod:`flopo2.ingest.collenette_llm` across English and non-English floras (eFloras,
POWO regional floras, World Flora Online, Plazi/Pensoft/BHL treatments, FlorML floras, FDAC, Kew).

For non-English descriptions (French, Spanish, Portuguese, German, Latin), the model writes
``entity_en`` and ``quality_en`` in standard botanical English so the shared PO/PATO/FLOPO rules
and lexicons apply unchanged, while ``source_en`` is copied character-for-character from the
verbatim source text so deterministic span anchoring holds.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from flopo2.ingest.collenette_llm import (
    DEFAULT_BASE_URL,
    DEFAULT_KEY_FILE,
    DEFAULT_MODEL,
    _key,
    call,
    expand,
    parse_json,
)
from flopo2.ingest.external import CORPORA_DIR, FLORA_SOURCES

PROMPT_ID = "flora_phenotype_transcription_v1"

INSTRUCTIONS_EN = """The entry below is a botanical species description from "{flora_title}".
It describes the named taxon ({taxon}, family {family}). Extract all morphological and phenotypic
traits of the named taxon; ignore remarks comparing other species or genera (put those in "other").

Return ONLY this compact JSON object (arrays keep the output short; no indentation):
{{"p": [[entity, quality, value_low, value_high, unit, source_en, negated, stage, frequency, [alternatives]]],
 "ab": "verbatim abundance/status phrase or empty",
 "fl": "verbatim flowering/fruiting time phrase or empty", "fm": [flowering months 1-12],
 "loc": [[verbatim place text, standard English name, feature_type, region/country code or "", "stated" or "inferred"]],
 "hab": "verbatim habitat phrase or empty",
 "el": [low, high, "m" or "ft", "verbatim elevation text"],
 "other": "text about other species, or empty", "notes": ""}}

A "p" row:
- entity = plant part, singular in English (whole plant, stem, bark, branch, leaf, petiole, stipule,
  leaf blade, leaflet, inflorescence, bract, pedicel, flower, calyx, sepal, corolla, petal, stamen,
  anther, ovary, style, stigma, fruit, seed, root, rhizome, spine ...);
- quality = ONE botanical quality in English (shrub, tree, herb, perennial, annual, erect, ovate,
  lanceolate, elliptic, glabrous, pubescent, yellow, white, aromatic, or for measurements/counts:
  height, length, width, diameter, depth, number);
- value_low / value_high = numbers or null;
- unit = "m", "cm", "mm" or "" (convert dm to cm only if needed, otherwise keep m/cm/mm; for counts,
  put the counted plural noun in unit or use quality "number of <part>");
- source_en = EXACT verbatim substring copied character-for-character from the entry text;
- negated = true/false;
- stage = developmental stage or condition ("when young", "in fruit", "when dry") or "";
- frequency = "usually", "often", "sometimes", "rarely" or "";
- alternatives = list of alternative/endpoint English quality strings (for "ovate to oblong" or
  "white or pink", put the first value in quality and ["oblong"] or ["pink"] in alternatives).

Rules for "p" (be exhaustive):
- One row per bearer-quality pair. Split "erect glabrous perennial herb 30-60 cm tall" into:
  whole plant / erect; whole plant / glabrous; whole plant / perennial; whole plant / herb;
  whole plant / height 30-60 cm.
- Habit and life-span words (herb, shrub, subshrub, tree, liana, climber, vine, annual, biennial,
  perennial, woody, herbaceous, succulent, caespitose, tufted, prostrate, creeping, scandent,
  epiphytic, aquatic, cushion-like, spiny, unarmed, dioecious, monoecious) go on entity "whole plant".
- Organ subheadings ("Leaves:", "Flowers:", "Fruit:"): apply to all traits in that clause unless a
  more specific sub-part (petiole, blade, calyx, corolla, stamen, ovary) is named.
- Measurements: quality is "height", "length", "width", "diameter" or "depth"; numbers go in
  value_low/value_high (same number twice for a single value), unit "m", "cm" or "mm". For "to 50 cm",
  value_low is null and value_high is 50. For "2-5 x 1-2 cm" on a leaf blade, emit TWO rows:
  leaf blade / length 2-5 cm and leaf blade / width 1-2 cm, both with the verbatim measurement span.
- Counts ("sepals 5", "stamens 10-15", "ovary 3-locular", "seeds 2-4 per locule"): emit entity as
  the counted part (sepal, stamen, locule, seed), quality "number", value_low/value_high as the
  count, unit as the counted plural noun, and source_en as the verbatim count phrase.
- Fruit and inflorescence types (capsule, berry, drupe, pod, legume, achene, cypsela, samara,
  nutlet, spike, raceme, panicle, umbel, cyme, head, capitulum, catkin): entity is that structure,
  quality "present".
- Absence ("petals absent", "estipulate", "without spines"): entity is the absent part (petal,
  stipule, spine), quality "present", negated true.
- source_en MUST be copied character-for-character from the entry text and must contain the words
  (and numbers, for a measurement) that state the trait. Do not invent traits.

Taxon: {taxon} ({family})
Entry text:
<<<
{text}
>>>"""

INSTRUCTIONS_MULTILINGUAL = """The entry below is a botanical species description (in {lang_name}) from "{flora_title}".
It describes the named taxon ({taxon}, family {family}).

IMPORTANT MULTILINGUAL RULE:
- Write `entity` and `quality` (and any `alternatives`) in STANDARD BOTANICAL ENGLISH (e.g.,
  "feuilles ovales à oblongues, glabres" -> entity "leaf", quality "ovate", alternatives ["oblong"],
  and a second row entity "leaf", quality "glabrous").
- Copy `source_en` CHARACTER-FOR-CHARACTER in the ORIGINAL LANGUAGE from the entry text (e.g.,
  "ovales à oblongues", "glabres", "sans stipules", "1,5-3 cm de long"). Never translate `source_en`!
  Convert decimal commas in `value_low`/`value_high` to JSON numbers (e.g. "1,5 cm" -> 1.5), while
  keeping "1,5 cm" verbatim in `source_en`.

Return ONLY this compact JSON object (no indentation):
{{"p": [[entity_en, quality_en, value_low, value_high, unit, verbatim_source_span, negated, stage, frequency, [alternatives_en]]],
 "ab": "verbatim abundance phrase or empty",
 "fl": "verbatim flowering/fruiting phrase or empty", "fm": [flowering months 1-12],
 "loc": [[verbatim place text, standard English name, feature_type, region/country code or "", "stated" or "inferred"]],
 "hab": "verbatim habitat phrase or empty",
 "el": [low, high, "m" or "ft", "verbatim elevation text"],
 "other": "text about other species, or empty", "notes": ""}}

Rules for "p" (be exhaustive):
- One row per bearer-quality pair.
- Habit and life-span words (tree/arbre/árbol, shrub/arbuste/arbusto, herb/herbe/hierba, liana/liane,
  perennial/vivace/perenne, annual/annuel/anual, dioecious/dioïque) go on entity "whole plant".
- Measurements: quality is "height", "length", "width", "diameter" or "depth"; unit is "m", "cm" or
  "mm"; `source_en` is the exact verbatim measurement substring from the entry text.
- Counts ("5 sépales", "étamines 10-12", "2-4 graines par loge"): entity is the counted part in
  English (sepal, stamen, seed), quality "number", value_low/value_high the count, unit the English
  plural noun ("sepals", "stamens", "seeds"), and `source_en` the exact verbatim phrase.
- Absence ("pétales absents", "sans stipules", "dépourvu d'épines", "pétalos ausentes"): entity is
  the part in English (petal, stipule, spine), quality "present", negated true, `source_en` the
  verbatim phrase including the negation word ("sans", "non", "dépourvu", "absent", "sin").

Taxon: {taxon} ({family})
Entry text:
<<<
{text}
>>>"""

LANG_NAMES = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "de": "German",
    "la": "Latin",
}


def build_prompt(segment: dict, flora_title: str = "") -> str:
    lang = (segment.get("language") or "en").lower()
    text = segment["text"]
    # Truncate extremely long monograph treatments (> 3200 chars) at sentence boundary to keep JSON compact
    if len(text) > 3200:
        cut = text.rfind(".", 0, 3200)
        text = text[: cut + 1 if cut > 1500 else 3200]
    template = INSTRUCTIONS_EN if lang == "en" else INSTRUCTIONS_MULTILINGUAL
    return (
        template.replace("{flora_title}", flora_title or segment.get("source", "Flora"))
        .replace("{lang_name}", LANG_NAMES.get(lang, lang))
        .replace("{taxon}", segment.get("taxon", ""))
        .replace("{family}", segment.get("taxon_family", ""))
        .replace("{text}", text)
    )


def _header(segment: dict, model: str, thinking: bool) -> dict:
    return {
        "source": segment["source"],
        "source_id": segment["source_id"],
        "taxon": segment.get("taxon", ""),
        "family": segment.get("taxon_family", ""),
        "taxon_rank": segment.get("taxon_rank", ""),
        "language": segment.get("language", "en"),
        "segment_text": segment["text"],
        "transcription": {"model": model, "prompt_id": PROMPT_ID, "thinking": thinking},
    }


# Seconds to wait after each failed attempt; the last entry is the final attempt's wait (unused).
RETRY_PAUSES = (10, 30, 60, 120, 0)


def transcribe_segment(
    segment: dict,
    *,
    flora_title: str,
    base_url: str,
    model: str,
    key: str,
    thinking: bool = False,
) -> dict:
    prompt = build_prompt(segment, flora_title=flora_title)
    last_error = ""
    for attempt, pause in enumerate(RETRY_PAUSES):
        try:
            # A long treatment can need more than 4,000 output tokens; a cut-off answer has no
            # closing brace and fails to parse, so each retry allows more (within the 32k window).
            content, usage = call(
                prompt, base_url=base_url, model=model, key=key, thinking=thinking,
                max_tokens=min(4000 * (attempt + 1), 16000),
            )
            record = expand(parse_json(content))
            if not isinstance(record.get("phenotypes"), list):
                raise ValueError("no phenotypes list")
            break
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            # Gateway errors (502/504 from the unimatrix proxy, 429) last longer than a parse slip:
            # wait longer for those before trying again.
            gateway = isinstance(exc, urllib.error.HTTPError) and exc.code in {429, 500, 502, 503, 504}
            time.sleep(pause if gateway else min(pause, 2 * (attempt + 1)))
    else:
        return {**_header(segment, model, thinking), "error": last_error}
    return {**_header(segment, model, thinking), **record, "usage": usage}


def run_transcription(
    source_key: str,
    *,
    segments_path: Path | None = None,
    out_path: Path | None = None,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    key_file: str = DEFAULT_KEY_FILE,
    workers: int = 16,
    limit: int = 0,
    thinking: bool = False,
    only: list[str] | None = None,
) -> Path:
    seg_file = segments_path or (CORPORA_DIR / source_key / f"{source_key}-segments.jsonl")
    out_file = out_path or (CORPORA_DIR / source_key / "raw" / f"{source_key}-qwen.jsonl")
    flora_title = FLORA_SOURCES.get(source_key, {}).get("title", source_key)

    segments = [json.loads(line) for line in seg_file.open(encoding="utf-8")]
    if limit:
        segments = segments[:limit]
    out_file.parent.mkdir(parents=True, exist_ok=True)
    done: set[str] = set()
    if out_file.exists():
        for line in out_file.open(encoding="utf-8"):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "error" not in row:
                done.add(row["source_id"])
    todo = [s for s in segments if s["source_id"] not in done]
    if only:
        todo = [s for s in segments if s["source_id"] in set(only)]
    if not todo:
        print(f"{source_key}: 0 todo ({len(done)} already cached in {out_file})", file=sys.stderr)
        return out_file

    key = _key(key_file)
    lock = threading.Lock()
    started = time.time()
    errors = 0
    with out_file.open("a", encoding="utf-8") as sink, ThreadPoolExecutor(workers) as pool:
        futures = {
            pool.submit(
                transcribe_segment,
                s,
                flora_title=flora_title,
                base_url=base_url,
                model=model,
                key=key,
                thinking=thinking,
            ): s
            for s in todo
        }
        for count, future in enumerate(as_completed(futures), 1):
            record = future.result()
            errors += "error" in record
            with lock:
                # A source text with an undecodable byte carries it as a lone surrogate, which
                # UTF-8 cannot encode; write it as "?" instead of losing the run.
                line = json.dumps(record, ensure_ascii=False)
                sink.write(line.encode("utf-8", "replace").decode("utf-8") + "\n")
                sink.flush()
            if count % 25 == 0 or count == len(todo):
                rate = count / max(time.time() - started, 1e-6)
                print(
                    f"[{source_key}] {count}/{len(todo)} done, {errors} errors, {rate:.2f}/s",
                    file=sys.stderr,
                    flush=True,
                )
    return out_file


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Flora source key (e.g. eflora-fna, powo-fz, wfo, plazi)")
    parser.add_argument("--segments", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args(argv)
    run_transcription(
        args.source,
        segments_path=args.segments,
        out_path=args.out,
        base_url=args.base_url,
        model=args.model,
        key_file=args.key_file,
        workers=args.workers,
        limit=args.limit,
        thinking=args.thinking,
        only=args.only,
    )


if __name__ == "__main__":
    main()
