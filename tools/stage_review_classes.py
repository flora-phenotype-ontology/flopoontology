"""Stage the new classes proposed by the second-model review (tools/llm_candidate_review.py).

Quality values go to ``config/flopo_flora_value_terms.tsv`` (FLOPO:0991nnn) and plant parts to
``curation/flopo_anatomy_support_classes_20260918.tsv`` with an identifier in
``config/flopo_anatomy_support_id_registry.tsv`` (FLOPO:0986nnn). The module builders and the
release passes then make the classes.

Proposals for one concept under several source words ("callose", "callous", "calloused") are
merged. A proposal is dropped when PATO, PO or FLOPO already has its label, when its parent is
not a live class, or when fewer than ``--min-statements`` statements use it. Everything that was
decided is written to ``<review dir>/staged-classes.tsv``.

    python -m tools.stage_review_classes [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from flopo2.ingest import ncvc_annotate as na
from flopo2.saudi.vocab import parse_obo

REVIEW = Path("curation/opus-review-2026-11-14")
VALUE_SPEC = Path("config/flopo_flora_value_terms.tsv")
ANATOMY_SPEC = Path("curation/flopo_anatomy_support_classes_20260918.tsv")
ANATOMY_REGISTRY = Path("config/flopo_anatomy_support_id_registry.tsv")
CANDIDATES = Path("curation/candidates")
DATE = "2026-11-14"
NOTE = f"{DATE}: proposed by the second-model review (Claude Opus) and checked (AI review, Claude Fable 5.2)"
ID_RE = re.compile(r"\b(PATO|PO|FLOPO|GO)[_:](\d{7})\b")
# Parts that are generic (they need the organ they belong to) or stand outside PO
SKIP_PART_LABELS = {"wing", "trigone"}
# Labels that an existing class covers under another name: word -> existing class
SKIP_VALUE_LABELS = {
    "suffrutescent": "FLOPO:0987003 suffrutescent habit",
    # reproductive modes: PATO 'reproductive quality' is under no attribute of the annotation
    # model, and they are not characters of form
    "sexually reproducing": "not staged: a reproductive mode",
    "apomictic": "not staged: a reproductive mode",
    "polycarpic": "not staged: a reproductive mode",
}
# PATO 'organismal quality' is under no attribute; the trophic siblings (autotrophic,
# hemiparasitic) are under PATO:0000056 trophic quality
PARENT_OVERRIDE = {"parasitic": ("PATO:0000056", "A trophic quality inhering in a plant")}
# one concept under two labels where only one proposal names the other (checked by hand)
MERGE = [("mamillose", "mammillose"), ("tumid", "turgid"), ("phyllodioicous", "pseudautoicous")]
ONE_WAY: list[tuple[str, str]] = []
_OPPOSITE = re.compile(r"^(?:un|non|not |without |in(?=distinct)|e(?=glandular))", re.IGNORECASE)


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9à-ÿ]+", " ", text.lower()).strip()


def _split(text: str) -> list[str]:
    return [s.strip() for s in (text or "").split("|") if s.strip()]


def _same_word(name: str, label: str) -> bool:
    import difflib

    return difflib.SequenceMatcher(None, _norm(name), _norm(label)).ratio() >= 0.75


def clusters(rows: list[dict]) -> list[list[dict]]:
    """Proposals grouped by label; two groups join when one's label is a synonym of the other."""

    by_label: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_label[_norm(row["label"])].append(row)
    parent = {label: label for label in by_label}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    names = {
        label: {_norm(re.sub(r"\s*\(.*?\)", "", n)) for row in members for n in [row["word"], *_split(row["synonyms"])]}
        for label, members in by_label.items()
    }
    for label in by_label:
        for other in names[label]:
            # joined only when each names the other: "margined" lists "unbordered" as a word it
            # was asked about, not as a synonym
            if other in by_label and other != label and label in names[other]:
                if find(other) != find(label):
                    parent[find(other)] = find(label)
            elif other in by_label and other != label:
                ONE_WAY.append((label, other))
    for one, two in MERGE:
        if one in by_label and two in by_label and find(one) != find(two):
            parent[find(one)] = find(two)
    groups: dict[str, list[dict]] = defaultdict(list)
    for label, members in by_label.items():
        groups[find(label)].extend(members)
    return list(groups.values())


def _best(members: list[dict]) -> dict:
    rank = {"high": 2, "medium": 1, "low": 0}
    return max(members, key=lambda r: (rank.get(r["confidence"], 0), int(r["statements"] or 0)))


def value_bearers() -> dict[str, list[str]]:
    counts: dict[str, Counter] = defaultdict(Counter)
    for path in CANDIDATES.glob("*/value_term_candidates.tsv"):
        for row in _rows(path):
            for bearer in _split(row.get("bearers", "")):
                counts[_norm(row["candidate_label"])][bearer.replace("_", ":")] += int(row["count"] or 0)
    import json

    for path in (REVIEW / "batches" / "values").glob("[0-9]*.json"):
        if path.name.count(".") != 1:
            continue
        for item in json.loads(path.read_text(encoding="utf-8")):
            for position, text in enumerate(item.get("with") or []):
                for prefix, number in ID_RE.findall(text):
                    if prefix in ("PO", "FLOPO"):
                        counts[_norm(item["word"])][f"{prefix}:{number}"] += max(1, int(item.get("statements") or 1) // (position + 2))
    return {word: [b for b, _ in c.most_common(8)] for word, c in counts.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--min-statements", type=int, default=20)
    parser.add_argument("--min-part-statements", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--review-dir", type=Path, help="a later review round (its date is taken from the folder name)")
    parser.add_argument("--accept", type=Path,
                        help="labels accepted by hand, one per line: only these are staged, whatever their count")
    args = parser.parse_args()
    global REVIEW, DATE, NOTE
    if args.review_dir:
        REVIEW = args.review_dir
        DATE = REVIEW.name.removeprefix("opus-review-")
        NOTE = f"{DATE}: proposed by the second-model review (Claude Opus) and accepted one by one (AI review, Claude Fable 5.2)"
    accepted = {_norm(line) for line in args.accept.read_text(encoding="utf-8").splitlines() if line.strip()} if args.accept else None
    res = na.load_resources()
    pato = parse_obo(Path("ont/quality.obo"))
    spec = _rows(VALUE_SPEC)
    spec_fields = list(spec[0])
    taken_words: dict[str, str] = {}
    for name, ids in res.pato_lexicon.items():
        taken_words[_norm(name)] = ids[0]
    for row in spec:
        for name in [row["label"], *_split(row["exact_synonyms"]), *_split(row.get("rule_words", ""))]:
            taken_words[_norm(name)] = row["flopo_id"]
    for table in ("flopo2/ingest/collenette_normalization.tsv", "flopo2/ingest/ncvc_normalization.tsv"):
        for rule in na.load_normalization_rules(Path(table)):
            if rule.match_field == "quality":
                taken_words.setdefault(_norm(rule.match_key), rule.rule_id)
    flopo_names = {_norm(label): identifier for identifier, label in res.flopo_labels.items()}
    staged_values = {_norm(row["label"]): row["flopo_id"] for row in spec if row.get("added") == DATE}
    bearers = value_bearers()
    decided: list[dict] = []
    stats: Counter = Counter()

    # ---- quality values ----
    proposals = [r for r in _rows(REVIEW / "values.tsv") if r["decision"] == "new_class" and r["confidence"] != "low"]
    groups = sorted(clusters(proposals), key=lambda g: -sum(int(r["statements"] or 0) for r in g))
    next_id = max(int(r["flopo_id"].split(":")[1]) for r in spec) + 1
    new_spec: list[dict] = []
    labels_new: dict[str, str] = {}
    pending: list[tuple[dict, list[dict], int]] = []
    for members in groups:
        best = _best(members)
        total = sum(int(r["statements"] or 0) for r in members)
        label = best["label"].strip()

        def drop(why: str, queue: str = "values", members=members, label=label, total=total) -> None:
            stats[f"{queue}: {why.split(':')[0]}"] += 1
            for row in members:
                decided.append({"queue": queue, "word": row["word"], "label": label, "flopo_id": "",
                                "statements": total, "outcome": why})

        if _norm(label) in staged_values:
            # staged by an earlier run of this tool: the same class
            for row in members:
                decided.append({"queue": "values", "word": row["word"], "label": label,
                                "flopo_id": staged_values[_norm(label)], "statements": total, "outcome": "new class"})
            continue
        if accepted is not None and _norm(label) not in accepted:
            drop("not accepted in the review by hand")
            continue
        if accepted is None and total < args.min_statements:
            drop("fewer statements than the bar")
            continue
        existing = taken_words.get(_norm(label)) or flopo_names.get(_norm(label)) or SKIP_VALUE_LABELS.get(_norm(label))
        if existing:
            drop(f"the label exists: {existing}")
            continue
        if _norm(label) in PARENT_OVERRIDE:
            new_parent, genus = PARENT_OVERRIDE[_norm(label)]
            best["parent"] = new_parent
            best["definition"] = re.sub(r"^An? [a-z -]+? quality inhering in a plant", genus, best["definition"])
        ids = ID_RE.findall(best["parent"])
        if len(ids) != 1 or ids[0][0] not in ("PATO", "FLOPO"):
            drop(f"no single parent: {best['parent'][:60]}")
            continue
        pending.append((best, members, total))
    spec_ids = {r["flopo_id"] for r in spec}
    for best, members, total in pending:
        labels_new[_norm(best["label"])] = f"FLOPO:{next_id + len(labels_new):07d}"
    for best, members, total in pending:
        label = best["label"].strip()
        prefix, number = ID_RE.findall(best["parent"])[0]
        parent = f"{prefix}:{number}"
        if prefix == "PATO" and parent not in pato:
            stats["values: parent is not a live PATO class"] += 1
            decided += [{"queue": "values", "word": r["word"], "label": label, "flopo_id": "", "statements": total,
                         "outcome": f"parent {parent} is not a live PATO class"} for r in members]
            del labels_new[_norm(label)]
            continue
        if prefix == "FLOPO" and parent not in spec_ids:
            stats["values: parent is not a FLOPO flora value"] += 1
            decided += [{"queue": "values", "word": r["word"], "label": label, "flopo_id": "", "statements": total,
                         "outcome": f"parent {parent} is not a FLOPO flora value"} for r in members]
            del labels_new[_norm(label)]
            continue
    # identifiers in order, without gaps, after the drops
    order = [(_norm(b["label"]), b, m, t) for b, m, t in pending if _norm(b["label"]) in labels_new]
    used_words: set[str] = set()
    for index, (key, best, members, total) in enumerate(order):
        flopo_id = f"FLOPO:{next_id + index:07d}"
        labels_new[key] = flopo_id
    for key, best, members, total in order:
        flopo_id = labels_new[key]
        label = best["label"].strip()
        prefix, number = ID_RE.findall(best["parent"])[0]
        names: list[str] = []
        related: list[str] = []
        for row in members:
            for name in [row["word"], row["label"], *_split(row["synonyms"])]:
                if "(RELATED)" in name or "(" in name:
                    related.append(re.sub(r"\s*\(.*?\)", "", name).strip())
                else:
                    names.append(name.strip())
        words, exact = [], []
        source_words = {_norm(r["word"]) for r in members}
        for name in dict.fromkeys(names):
            n = _norm(name)
            if not n or n == _norm(label) or n in used_words:
                continue
            if n in taken_words or n in flopo_names or (n in labels_new and labels_new[n] != flopo_id):
                if n not in source_words:
                    related.append(name)
                    continue
            used_words.add(n)
            # the words the floras use are rule words; other names are synonyms
            if n in source_words and (
                (_OPPOSITE.match(name) and not _OPPOSITE.match(label)) or (n.startswith("sub") and not _norm(label).startswith("sub"))
            ):
                continue  # the opposite, or "sub-" (read as "approximately" by the annotator)
            (words if n in source_words else exact).append(name)
        used_words.add(_norm(label))
        definition = re.sub(r"\s+", " ", best["definition"]).strip()
        note = ""
        if " NOTE:" in definition:
            definition, note = definition.split(" NOTE:", 1)
        row_bearers: Counter = Counter()
        for row in members:
            for position, bearer in enumerate(bearers.get(_norm(row["word"]), [])):
                row_bearers[bearer] += 8 - position
        new_spec.append({
            **dict.fromkeys(spec_fields, ""),
            "flopo_id": flopo_id, "label": label, "parent": f"{prefix}:{number}",
            "definition": definition.strip(),
            "exact_synonyms": "|".join(dict.fromkeys(exact)),
            "related_synonyms": "|".join(dict.fromkeys(r for r in related if r and _norm(r) != _norm(label))),
            "bearers": "|".join(b for b, _ in row_bearers.most_common(12) if re.fullmatch(r"(?:PO|FLOPO):\d{7}", b))[:0]
                       or "|".join([b for b, _ in row_bearers.most_common(12) if re.fullmatch(r"(?:PO|FLOPO):\d{7}", b)][:8]),
            "source_words": f"{'/'.join(sorted(source_words))}: {total} statements "
                            f"(second-model review {DATE})",
            "rule_words": "|".join(dict.fromkeys(words)),
            "added": DATE,
            "review_note": (NOTE + "." + (" " + note.strip() if note.strip() else "")).strip(),
        })
        stats["values: new class"] += 1
        for row in members:
            decided.append({"queue": "values", "word": row["word"], "label": label, "flopo_id": flopo_id,
                            "statements": total, "outcome": "new class"})

    # ---- plant parts ----
    anatomy = _rows(ANATOMY_SPEC)
    anatomy_fields = list(anatomy[0])
    registry = _rows(ANATOMY_REGISTRY)
    live_po = res.po_catalog
    anatomy_ids = {r["flopo_id"] for r in registry}
    po_names = {_norm(name) for name in res.po_lexicon}
    proposals = [r for r in _rows(REVIEW / "bearers.tsv") if r["decision"] == "new_class" and r["confidence"] != "low"]
    groups = sorted(clusters(proposals), key=lambda g: -sum(int(r["statements"] or 0) for r in g))
    # FLOPO:0986056-0986062 were withdrawn before release (8be100d) and are not used again
    next_part = max(max(int(r["flopo_id"].split("_")[1]) for r in registry) + 1, 986063)
    part_names: set[str] = set()
    allocated = {r["proposal_key"]: r["flopo_id"] for r in registry}
    staged_parts = {_norm(r["label"]): r for r in anatomy if DATE in (r.get("note") or "")}
    for r in staged_parts.values():
        part_names.update(_norm(n) for f in ("exact_synonyms_en", "related_synonyms_en", "exact_synonyms_fr") for n in _split(r[f]))
    new_anatomy: list[dict] = []
    new_registry: list[dict] = []
    for members in groups:
        best = _best(members)
        total = sum(int(r["statements"] or 0) for r in members)
        label = best["label"].strip()

        def drop(why: str, members=members, label=label, total=total) -> None:
            stats[f"parts: {why.split(':')[0]}"] += 1
            for row in members:
                decided.append({"queue": "bearers", "word": row["word"], "label": label, "flopo_id": "",
                                "statements": total, "outcome": why})

        if _norm(label) in staged_parts:
            spec_row = staged_parts[_norm(label)]
            names = [n for f in ("exact_synonyms_en", "related_synonyms_en", "exact_synonyms_fr") for n in _split(spec_row[f])]
            for row in members:
                decided.append({"queue": "bearers", "word": row["word"], "label": label,
                                "flopo_id": allocated[spec_row["proposal_key"]], "statements": total,
                                "outcome": "new class", "names": "|".join(dict.fromkeys([row["word"], *names]))})
            continue
        if accepted is not None and _norm(label) not in accepted:
            drop("not accepted in the review by hand")
            continue
        if accepted is None and total < args.min_part_statements:
            drop("fewer statements than the bar")
            continue
        if _norm(label) in SKIP_PART_LABELS:
            drop("a generic part or outside PO")
            continue
        if _norm(label) in po_names or _norm(label) in flopo_names:
            drop(f"the label exists: {label}")
            continue
        text = best["parent"]
        is_a = re.search(r"is_a\b[^;]*?\b((?:PO|FLOPO)[_:]\d{7})", text)
        part_of = re.search(r"part_of\b[^;]*?\b((?:PO|FLOPO)[_:]\d{7})", text)
        if not is_a or "GO" in [p for p, _ in ID_RE.findall(text)]:
            drop(f"no PO parent: {text[:60]}")
            continue
        tokens = [m.group(1).replace(":", "_") for m in (is_a, part_of) if m]
        if any(t not in live_po and t not in anatomy_ids and t not in res.flopo_catalog for t in tokens):
            drop(f"parent or whole is not a live class: {tokens}")
            continue
        key = "FLOPO_LOCAL:" + re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        flopo_id = f"FLOPO_{next_part + len(new_registry):07d}"
        names = []
        for row in members:
            names += [row["word"], *_split(row["synonyms"])]
        french = [n for n in dict.fromkeys(names) if re.search(r"[àâçéèêëîïôûùüœ]|^(?:lèvre|limbe|gorge|pied|axe|aile)\b| d[eu] | des ", n)]
        english, related = [], []
        for n in dict.fromkeys(names):
            key_n = _norm(n)
            if n in french or key_n == _norm(label) or "(" in n or key_n in po_names or key_n in part_names:
                continue
            part_names.add(key_n)
            # an exact synonym is another form of the label or a full name; a bare word the
            # floras use for it ("trap", "throat", "plica") is a related synonym
            if len(key_n.split()) > 1 and set(key_n.split()) != set(_norm(label).split()) - {"of", "the"} or _same_word(n, label):
                english.append(n)
            else:
                related.append(n)
        french = [n for n in french if _norm(n) not in part_names and not part_names.add(_norm(n))]
        part_names.add(_norm(label))
        definition = re.sub(r"\s+", " ", best["definition"]).strip()
        note = ""
        if " NOTE:" in definition:
            definition, note = definition.split(" NOTE:", 1)
        new_anatomy.append({
            **dict.fromkeys(anatomy_fields, ""),
            "proposal_key": key, "action": "new_flopo_local", "label": label,
            "is_a": tokens[0], "part_of": tokens[1] if part_of else "",
            "definition": definition.strip(),
            "exact_synonyms_en": "|".join(english), "exact_synonyms_fr": "|".join(french),
            "related_synonyms_en": "|".join(related),
            "po_check": re.sub(r"\s+", " ", best["reason"]).strip(),
            "note": f"{NOTE}; {total} statements use {'/'.join(sorted({r['word'] for r in members}))}."
                    + (" " + note.strip() if note.strip() else ""),
        })
        new_registry.append({"proposal_key": key, "flopo_id": flopo_id, "label": label,
                             "kind": "supporting_entity", "provisional_for": "PO"})
        stats["parts: new class"] += 1
        for row in members:
            decided.append({"queue": "bearers", "word": row["word"], "label": label, "flopo_id": flopo_id,
                            "statements": total, "outcome": "new class",
                            "names": "|".join(dict.fromkeys([row["word"], *english, *related, *french]))})

    for key in sorted(stats):
        print(f"{stats[key]:5d}  {key}")
    staged = {_norm(r["label"]) for r in new_spec} | {_norm(r["label"]) for r in new_anatomy}
    for label, other in sorted(set(ONE_WAY)):
        if label in staged and other in staged:
            print(f"  near: {label!r} names {other!r}, not the reverse")
    if args.dry_run:
        for row in new_spec:
            print(row["flopo_id"], row["label"], row["parent"], "|", row["rule_words"], "|", row["exact_synonyms"], "|", row["bearers"][:50])
        for row, reg in zip(new_anatomy, new_registry):
            print(reg["flopo_id"], row["label"], row["is_a"], row["part_of"], "|", row["exact_synonyms_en"][:90], "|", row["related_synonyms_en"][:60], "|", row["exact_synonyms_fr"][:40])
        return
    for path, fields, new in ((p, f, n) for p, f, n in (
        (VALUE_SPEC, spec_fields, new_spec), (ANATOMY_SPEC, anatomy_fields, new_anatomy),
        (ANATOMY_REGISTRY, list(registry[0]), new_registry),
    ) if n):
        with path.open("a", encoding="utf-8", newline="") as fh:
            csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n").writerows(new)
    fields = ["queue", "word", "label", "flopo_id", "statements", "outcome", "names"]
    with (REVIEW / "staged-classes.tsv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(decided)


if __name__ == "__main__":
    main()
