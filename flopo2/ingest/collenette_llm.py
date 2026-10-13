"""Transcribe Collenette's Saudi field-guide entries into NCVC-style phenotype records with an LLM.

Each OCR segment from ``collenette-saudi-segments.jsonl`` is sent to an OpenAI-compatible endpoint
(by default the Qwen model on unimatrix01) with the extraction rules of the NCVC brief.  The model
returns one JSON object per entry: phenotype rows (entity, quality, numeric value, verbatim
``source_en`` span and qualifiers), abundance, habitat, elevation, flowering time and localities.
Nothing is grounded here: ``flopo2.ingest.collenette_annotate`` anchors every row on the segment
text and grounds it deterministically against PO/PATO/FLOPO, exactly as for the NCVC guide.

The run is resumable: finished ``source_id`` values in the output file are skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://unimatrix01.kaust.edu.sa:8000/v1"
DEFAULT_MODEL = "qwen3.8-27b"
DEFAULT_KEY_FILE = "~/.config/borg-llm/api-key"
PROMPT_ID = "collenette_phenotype_transcription_v2"

SYSTEM = """You transcribe botanical field-guide entries into structured trait records.
Return ONLY one JSON object, no prose."""

INSTRUCTIONS = """The entry below is OCR text of one species entry from S. Collenette, "An illustrated
guide to the flowers of Saudi Arabia" (1985). It names the taxon and family. The entry usually
reads: habit and morphology; scent; flowering time; abundance; locality; habitat; elevation in
feet. OCR from the two-column layout sometimes interleaves fragments of a NEIGHBOURING entry or a
family introduction (general remarks about other species, often naming other genera). Use only
text that describes the named taxon; put interleaved/other-species text in "other_species_text".

Return this compact JSON object (arrays keep the output short; no indentation):
{"p": [[entity, quality, value_low, value_high, unit, source_en, negated, stage, frequency, [alternatives]]],
 "ab": "verbatim abundance phrase or empty, e.g. Very common in scattered localities",
 "fl": "verbatim flowering-time phrase or empty", "fm": [flowering months 1-12],
 "loc": [[verbatim place text, standard English name, feature_type, region ISO code or "", "stated" or "inferred"]],
 "hab": "verbatim habitat phrase or empty, e.g. in a rocky wadi",
 "el": [low, high, "ft", "verbatim elevation text"],
 "other": "interleaved text of other entries, or empty", "notes": ""}
A "p" row: entity = plant part, singular (whole plant, leaf, flower, petal, fruit, stem, spine ...);
quality = one quality (shrub, perennial, erect, ovate, yellow, hairy, aromatic, or for numbers
height/length/width/diameter/depth); value_low/value_high numbers or null; unit "m", "cm", "mm" or "";
source_en = EXACT verbatim substring of the entry text; negated true/false; stage, frequency strings
or ""; alternatives a list of strings.
feature_type is one of mountain, wadi, city, town, village, island, natural_region, desert, plateau,
coast, harrah, road, other.

Rules for "phenotypes" (the most important part; be exhaustive):
- One row per bearer-quality pair. Split "a stiffly erect dark green leafy shrub 3.5 m high" into:
  whole plant / shrub; whole plant / erect (frequency or degree words such as "stiffly" stay in
  source_en only); whole plant / leafy; leaf / dark green; whole plant / height 3.5-3.5 m.
- Habit words (herb, shrub, shrublet, undershrub, tree, climber, annual, perennial, woody,
  succulent, grass, cushion-like, tufted, prostrate, creeping, bushy, twiggy, spiny) are rows on
  entity "whole plant".  "woody-based" = stem base / woody.
- Colours: quality_en is the colour exactly as written ("orange-red", "pale yellow", "rosy-lilac",
  "creamy-white"). Spots, blotches, veins, honey guides, throats, eyes: use that part as the entity
  ("throat" of a flower => entity "corolla throat", quality the colour).
- Measurements: quality_en is "height", "length", "width", "diameter" or "depth"; numbers go in
  value_low/value_high (same number twice for a single value), unit exactly m, cm or mm. "X cm wide"
  of a flower => entity "flower", quality "width" (flower diameter).  "stems to 50 cm long" =>
  value_low null, value_high 50.
- Scent: "no scent" => entity "flower", quality "scented", negated true; "aromatic" (plant) =>
  entity "whole plant", quality "aromatic"; "foetid smell" => quality "foetid".
- Hairiness/surface: hairy, downy, glabrous, glandular, sticky, spiny, prickly, woolly, silvery ...
- Fruit/inflorescence types (pod, capsule, berry, spike, umbel, raceme, head) => entity is that
  structure, quality "present".
- Alternatives ("white or pink", "pink to purple") => ONE row with the first value as quality_en and
  the others in qualifiers.alternatives.  Stage words ("young shoots", "when dry", "in fruit") go in
  qualifiers.stage.  "usually", "often", "sometimes" go in qualifiers.frequency.
- source_en MUST be copied character-for-character from the entry text (including OCR errors) and
  must contain the quality word (and the numbers for a measurement).
- Do not invent traits that are not in the text. Do not output rows for other species.

Rules for places: localities are named places (Jabal ..., Wadi ..., towns, roads "Jiddah-Taif road",
"10 km SW of Abha"). Map to Saudi ISO 3166-2 regions only when certain: SA-01 Riyadh, SA-02 Makkah
(Jiddah, Taif, Makkah, Al Hada, Al Lith, Qunfudhah), SA-03 Al Madinah (Madinah, Yanbu, Al Ula,
Khaybar), SA-04 Eastern Province (Dhahran, Dammam, Hofuf, Al Hasa, Jubail), SA-05 Al Qassim
(Buraydah, Unayzah), SA-06 Ha'il, SA-07 Tabuk, SA-08 Northern Borders (Arar, Turayf, Rafha),
SA-09 Jazan (Jizan, Abu Arish, Sabya, Farasan), SA-10 Najran, SA-11 Al Bahah, SA-12 Al Jawf
(Sakakah), SA-14 Asir (Abha, Khamis Mushayt, Bishah, An Namas). region_basis "inferred" when you
derived it from a town. "the south", "the north" etc. are not localities; keep them in abundance.

Taxon: {taxon} ({family})
Entry text:
<<<
{text}
>>>"""


def _key(path: str) -> str:
    return Path(os.path.expanduser(path)).read_text(encoding="utf-8").strip()


def call(
    prompt: str,
    *,
    base_url: str,
    model: str,
    key: str,
    thinking: bool,
    max_tokens: int = 4000,
    timeout: int = 600,
) -> tuple[str, dict]:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"] or "", payload.get("usage", {})


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_json(text: str) -> dict:
    text = _FENCE_RE.sub("", text.strip())
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])


def _row(values: list, names: list[str]) -> dict:
    values = list(values) + [None] * (len(names) - len(values))
    return dict(zip(names, values))


def expand(compact: dict) -> dict:
    """Expand the compact array answer into the NCVC-style record fields."""

    if "phenotypes" in compact:
        return compact
    phenotypes = []
    for row in compact.get("p") or []:
        if not isinstance(row, list) or len(row) < 6:
            continue
        r = _row(row, ["entity_en", "quality_en", "value_low", "value_high", "unit", "source_en",
                       "negated", "stage", "frequency", "alternatives"])
        phenotypes.append(
            {
                "entity_en": str(r["entity_en"] or ""),
                "quality_en": str(r["quality_en"] or ""),
                "value_low": r["value_low"],
                "value_high": r["value_high"],
                "unit": str(r["unit"] or ""),
                "source_en": str(r["source_en"] or ""),
                "qualifiers": {
                    "negated": bool(r["negated"]),
                    "stage": str(r["stage"] or ""),
                    "frequency": str(r["frequency"] or ""),
                    "alternatives": [str(a) for a in (r["alternatives"] or []) if a],
                },
            }
        )
    localities = []
    for row in compact.get("loc") or []:
        if isinstance(row, list) and row:
            r = _row(row, ["verbatim", "name_en", "feature_type", "region_iso_3166_2", "region_basis"])
            localities.append({k: str(v or "") for k, v in r.items()})
    el = _row(compact.get("el") or [], ["low", "high", "unit", "text"])
    return {
        "phenotypes": phenotypes,
        "abundance_en": compact.get("ab") or "",
        "flowering_text": compact.get("fl") or "",
        "flowering_months": compact.get("fm") or [],
        "localities": localities,
        "habitat_en": compact.get("hab") or "",
        "elevation": {"low": el["low"], "high": el["high"], "unit": el["unit"] or "ft", "text": el["text"] or ""},
        "other_species_text": compact.get("other") or "",
        "notes": compact.get("notes") or "",
    }


def build_prompt(segment: dict) -> str:
    return (
        INSTRUCTIONS.replace("{taxon}", segment.get("taxon", ""))
        .replace("{family}", segment.get("taxon_family", ""))
        .replace("{text}", segment["text"])
    )


def transcribe(segment: dict, *, base_url: str, model: str, key: str, thinking: bool) -> dict:
    prompt = build_prompt(segment)
    last_error = ""
    for attempt in range(3):
        try:
            content, usage = call(prompt, base_url=base_url, model=model, key=key, thinking=thinking)
            record = expand(parse_json(content))
            if not isinstance(record.get("phenotypes"), list):
                raise ValueError("no phenotypes list")
            break
        except Exception as exc:  # noqa: BLE001 - retried, then recorded
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(2 * (attempt + 1))
    else:
        return {**_header(segment, model, thinking), "error": last_error}
    return {**_header(segment, model, thinking), **record, "usage": usage}


def _header(segment: dict, model: str, thinking: bool) -> dict:
    return {
        "source": segment["source"],
        "source_id": segment["source_id"],
        "taxon": segment.get("taxon", ""),
        "family": segment.get("taxon_family", ""),
        "taxon_rank": segment.get("taxon_rank", ""),
        "segment_text": segment["text"],
        "transcription": {"model": model, "prompt_id": PROMPT_ID, "thinking": thinking},
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--segments",
        type=Path,
        default=Path("local-corpora/saudi-collenette/collenette-saudi-segments.jsonl"),
    )
    parser.add_argument(
        "--out", type=Path, default=Path("local-corpora/saudi-collenette/raw/collenette-qwen.jsonl")
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--only", nargs="*", default=[], help="source_ids to (re)run")
    args = parser.parse_args(argv)

    segments = [json.loads(line) for line in args.segments.open(encoding="utf-8")]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done: set[str] = set()
    if args.out.exists():
        for line in args.out.open(encoding="utf-8"):
            row = json.loads(line)
            if "error" not in row:
                done.add(row["source_id"])
    todo = [s for s in segments if s["source_id"] not in done]
    if args.only:
        todo = [s for s in segments if s["source_id"] in set(args.only)]
    if args.limit:
        todo = todo[: args.limit]
    key = _key(args.key_file)
    lock = threading.Lock()
    started = time.time()
    errors = 0
    with args.out.open("a", encoding="utf-8") as out, ThreadPoolExecutor(args.workers) as pool:
        futures = {
            pool.submit(
                transcribe, s, base_url=args.base_url, model=args.model, key=key, thinking=args.thinking
            ): s
            for s in todo
        }
        for count, future in enumerate(as_completed(futures), 1):
            record = future.result()
            errors += "error" in record
            with lock:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
            if count % 25 == 0 or count == len(todo):
                rate = count / (time.time() - started)
                print(
                    f"{count}/{len(todo)} done, {errors} errors, {rate:.2f}/s",
                    file=sys.stderr,
                    flush=True,
                )


if __name__ == "__main__":
    main()
