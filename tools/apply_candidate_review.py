"""Turn the second-model review (tools/llm_candidate_review.py collect) into rule-table rows.

Reads ``curation/opus-review-2026-11-14/{values,bearers,unions}.tsv`` and writes

- ``flopo2/ingest/flora_review_rules.tsv``: quality and bearer rules to existing classes,
- rows of ``config/flora_union_pairs.tsv`` and ``config/flora_rejected_bearer_words.tsv``,
- ``<review dir>/not-applied.tsv``: every answer that was not turned into a rule, with the reason.

A rule is written only when the answer names exactly one target class, the identifier is in the
live catalogs and the label given with it is the label (or a lexicon synonym) of that class: a
wrong identifier next to a right name is the usual way a model's answer fails. Answers with low
confidence are left out. Words that already have a reviewed rule are left alone.

    python -m tools.apply_candidate_review [--review-dir DIR] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

from flopo2.ingest import ncvc_annotate as na

REVIEW = Path("curation/opus-review-2026-11-14")
RULES = Path("flopo2/ingest/flora_review_rules.tsv")
REVIEWED_TABLES = [
    Path("flopo2/ingest/flora_value_term_rules.tsv"),
    Path("flopo2/ingest/collenette_normalization.tsv"),
    Path("flopo2/ingest/ncvc_normalization.tsv"),
]
UNION_PAIRS = Path("config/flora_union_pairs.tsv")
REJECTED_BEARERS = Path("config/flora_rejected_bearer_words.tsv")
VALUE_TERMS = Path("config/flopo_flora_value_terms.tsv")
FIELDS = [
    "rule_id", "match_field", "match_key", "bearer_constraint", "kind", "po_id", "pato_id",
    "value_term", "flopo_class", "target_label", "evidence", "review_status", "container_id",
]
STAMP = "2026-11-14 AI review (Claude Opus, second model)"
ID_RE = re.compile(r"\b(PATO|PO|FLOPO)[_:](\d{7})\b")
TARGET_RE = re.compile(
    r"^(?:not\s+)?(?P<label>.+?)\s*\((?P<id>(?:PATO|PO|FLOPO)[_:]\d{7})\)"
    r"(?:\s+(?P<state>present|absent))?(?:\s*\[(?P<bearers>[^\]]+)\])?\s*$",
    re.IGNORECASE,
)
UNION_ACCEPT_MIN = 0.6
# one-word names of the new anatomy classes that mean other things on other organs: related
# synonyms in the ontology, but no rule
GENERIC_PART_WORDS = {"beak", "orifice", "article", "bladder", "callus", "diaphragm", "commissure", "fig", "massue", "gorge", "rostrum", "bec"}
# quality words that name a part, checked by hand (2026-11-14); fruit and inflorescence kinds
# are taken by their PO label
PART_AS_QUALITY = {
    "taproot", "corm", "aril", "lenticels", "midrib", "midvein", "lateral vein", "lateral veins",
    "lateral nerves", "central strand", "root-stock", "indument", "phyllodial", "unifacial",
    "protonematous", "perigonial",
}


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


class Catalog:
    def __init__(self) -> None:
        self.res = na.load_resources()
        self.names: dict[str, set[str]] = {}
        for lexicon in (self.res.po_lexicon, self.res.pato_lexicon):
            for name, ids in lexicon.items():
                for identifier in ids:
                    self.names.setdefault(identifier, set()).add(_norm(name))
        for labels in (self.res.po_labels, self.res.pato_labels, self.res.flopo_labels):
            for identifier, label in labels.items():
                self.names.setdefault(identifier, set()).add(_norm(label))
        self.flopo_names = {_norm(label) for label in self.res.flopo_labels.values()}
        self.value_parent: dict[str, str] = {}
        for table in REVIEWED_TABLES:
            for rule in na.load_normalization_rules(table):
                if rule.value_term and rule.pato_id:
                    self.value_parent.setdefault(rule.value_term, rule.pato_id)
        for row in _rows(VALUE_TERMS):
            identifier = row["flopo_id"].replace(":", "_")
            self.names.setdefault(identifier, set()).add(_norm(row["label"]))
            for synonym in (row.get("exact_synonyms") or "").split("|"):
                if synonym.strip():
                    self.names[identifier].add(_norm(synonym))

    def known(self, identifier: str) -> bool:
        res = self.res
        return (
            identifier in res.po_catalog or identifier in res.pato_catalog or identifier in res.flopo_labels
        )

    def check(self, identifier: str, label: str) -> str:
        """'' when the identifier exists and carries the label; else why not."""

        if not self.known(identifier):
            return f"unknown identifier {identifier}"
        label = re.sub(r"^not\s+", "", label.strip(), flags=re.IGNORECASE)
        names = self.names.get(identifier, set())
        if _norm(label) not in names and not any(_norm(label) in n or n in _norm(label) for n in names if len(n) > 3):
            return f"label {label!r} is not a name of {identifier} ({sorted(names)[:3]})"
        return ""

    def label(self, identifier: str) -> str:
        return na._label(self.res, identifier)


def _variant(synonym: str, word: str) -> bool:
    """A one-word synonym is taken only as another spelling or number of the word itself
    ("cocci" for "coccus"); a different word ("fall" for an iris tepal, "bloom" for wax) is too
    easily a different thing elsewhere."""

    import difflib

    return any(
        difflib.SequenceMatcher(None, _norm(synonym), token).ratio() >= 0.7
        for token in [_norm(word), *_norm(word).split()]
    )


def _bearer_constraint(text: str | None) -> str:
    words = [w.strip() for w in (text or "").split("|") if w.strip()]
    return "|".join(re.escape(w) for w in words)


def value_rule(catalog: Catalog, row: dict) -> tuple[dict | None, str]:
    decision = row["decision"]
    target = row["target"].strip()
    if decision == "rule:negated_value":
        # "sheathing (FLOPO:0991105), negated"; "not mucronate (negation of mucronate FLOPO:0991054)"
        target = re.sub(r",\s*negated$", "", target)
        inner = re.fullmatch(r"not\s+(.+?)\s*\(negation of\s+\1\s+((?:PATO|PO|FLOPO)[_:]\d{7})\)", target)
        if inner:
            target = f"{inner[1]} ({inner[2]})"
    if len(set(ID_RE.findall(target))) != 1:
        return None, "the target does not name exactly one class"
    match = TARGET_RE.match(target)
    if not match:
        return None, "the target has more than a class (and its bearers)"
    identifier = match["id"].replace(":", "_")
    problem = catalog.check(identifier, match["label"])
    if problem:
        return None, problem
    rule = dict.fromkeys(FIELDS, "")
    rule.update(match_field="quality", bearer_constraint=_bearer_constraint(match["bearers"]))
    prefix = identifier.split("_")[0]
    label = catalog.label(identifier)
    if decision in ("rule:pato", "rule:flopo_value", "rule:negated_value"):
        if match["state"]:
            return None, "a value rule with present/absent"
        if prefix == "PO":
            return None, "a plant part as the value"
        if decision == "rule:pato" and prefix != "PATO":
            decision = "rule:flopo_value"
        if decision == "rule:flopo_value" and prefix == "PATO":
            decision = "rule:pato"
        if prefix == "FLOPO":
            parent = catalog.value_parent.get(identifier)
            if not parent:
                return None, f"{identifier} is not a FLOPO value with a rule (a phenotype class?)"
            rule.update(pato_id=parent, value_term=identifier)
        else:
            if identifier in catalog.res.attribute_ids:
                return None, f"{identifier} is an attribute, not a value"
            rule.update(pato_id=identifier)
        if decision == "rule:negated_value":
            rule.update(kind="negated_value", target_label=f"not {label}")
        else:
            rule.update(kind="flopo_value" if prefix == "FLOPO" else "pato", target_label=label)
    elif decision in ("rule:entity_presence", "rule:entity_absence", "rule:bearer"):
        if prefix == "PATO":
            return None, "a quality as the part"
        if identifier not in catalog.res.po_catalog and identifier not in catalog.res.flopo_catalog:
            return None, f"{identifier} is not a bearer class"
        absent = decision == "rule:entity_absence"
        if decision == "rule:bearer":
            # "fruit capsular", "inflorescence a catkin": the word names the kind of the part, which
            # is stated as that kind being present. Not for a measurement split off its part
            # ("awn length") or a word that is a part only next to another ("ray", "stem").
            label_now = catalog.label(identifier)
            if not (
                label_now.endswith((" fruit", " inflorescence")) or na.normalize_key(row["word"]) in PART_AS_QUALITY
            ) or re.search(r"\b(length|width|colou?r|shape|size)\b", row["word"]):
                return None, "a part named by the quality word: not one of the reviewed kinds"
        if decision != "rule:bearer" and (match["state"] or "").lower() != ("absent" if absent else "present"):
            return None, "present/absent missing or against the decision"
        rule.update(
            kind="entity_absence" if absent else "entity_presence", po_id=identifier,
            pato_id=na.PATO_PRESENT, target_label=f"{label} {'absent' if absent else 'present'}",
        )
    else:
        return None, "no rule for this decision"
    return rule, ""


def bearer_rule(catalog: Catalog, row: dict) -> tuple[dict | None, str]:
    target = row["target"].strip()
    match = TARGET_RE.match(target)
    if len(set(ID_RE.findall(target))) != 1 or not match or match["state"] or match["bearers"]:
        return None, "the target has more than one class"
    identifier = match["id"].replace(":", "_")
    problem = catalog.check(identifier, match["label"])
    if problem:
        return None, problem
    if identifier not in catalog.res.po_catalog and identifier not in catalog.res.flopo_catalog:
        return None, f"{identifier} is not a bearer class"
    rule = dict.fromkeys(FIELDS, "")
    rule.update(match_field="bearer", kind="bearer", po_id=identifier, target_label=catalog.label(identifier))
    return rule, ""


_PART_OF = re.compile(
    r"^(?P<part>[^()]+?)\s*\(?(?P<part_id>(?:PO|FLOPO)[_:]\d{7})\)?[,;]?\s*(?:as\s+)?part[_ ]of\s+(?:the\s+|an?\s+)?"
    r"(?P<whole>[^()]+?)\s*\(?(?P<whole_id>(?:PO|FLOPO)[_:]\d{7})\)?(?P<rest>.*)$",
    re.IGNORECASE,
)
NON_VASCULAR_LEAF, LEAF = "PO_0025075", "PO_0025034"
# Words that do not name the whole (a "basal cell" is not always that of a leaf), words with a
# class of their own since this review, and phrases that are not a part (checked by hand)
PART_OF_SKIP = {
    "basal cell", "basal cells", "median cell", "adaxial cell", "distal cells", "apical cells", "lower cell",
    "flowers per head", "male glume", "guide cell", "guide-cell", "stereid bands", "adaxial stereid band",
    "dorsal stereid band", "marginal cell", "marginal cells", "marginal gland", "cortical cell",
}


def part_of_rule(catalog: Catalog, row: dict) -> tuple[dict | None, str]:
    """"colleter (FLOPO_0986023) part_of stipule (PO_0020041)": the part with its whole."""

    if na.normalize_key(row["word"]) in PART_OF_SKIP:
        return None, "the word does not name its whole, or has a class of its own"
    match = _PART_OF.match(row["target"].strip())
    if not match or ID_RE.search(match["rest"]):
        return None, "not of the form: part (id) part_of whole (id)"
    part, whole = match["part_id"].replace(":", "_"), match["whole_id"].replace(":", "_")
    for identifier, label in ((part, match["part"]), (whole, match["whole"])):
        problem = catalog.check(identifier, re.sub(r"^(?:a|an|the)\s+", "", label.strip()))
        if problem:
            return None, problem
        if identifier not in catalog.res.po_catalog and identifier not in catalog.res.flopo_catalog:
            return None, f"{identifier} is not a bearer class"
    if whole == NON_VASCULAR_LEAF:
        whole = LEAF  # the word is used of vascular leaves too: "cell of a leaf" holds for both
    if part == whole:
        return None, "part and whole are one class"
    rule = dict.fromkeys(FIELDS, "")
    rule.update(match_field="bearer", kind="bearer", po_id=part, container_id=whole,
                target_label=f"{catalog.label(part)} part of {catalog.label(whole)}")
    return rule, ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--review-dir", type=Path, default=REVIEW)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    catalog = Catalog()
    taken = {
        (rule.match_field, rule.match_key)
        for table in REVIEWED_TABLES
        for rule in na.load_normalization_rules(table)
    }
    out: list[dict] = []
    skipped: list[dict] = []
    stats: Counter = Counter()

    def add(queue: str, row: dict, rule: dict | None, why: str, words: list[str]) -> None:
        if rule is None:
            skipped.append({"queue": queue, "word": row["word"], "decision": row["decision"],
                            "target": row["target"], "why": why, "statements": row["statements"]})
            stats[f"{queue} {row['decision']} not applied"] += 1
            return
        written = 0
        for word in words:
            key = na.normalize_key(word)
            if not key or (rule["match_field"], key) in taken:
                continue
            # a word that the lexicon already grounds to the same class needs no rule
            taken.add((rule["match_field"], key))
            evidence = (
                f"{row['reason'].strip()} ({row['statements']} statements in {row['floras']} floras; "
                f"confidence {row['confidence']}; batch {row['batch']})"
            )
            out.append({**rule, "match_key": key, "evidence": re.sub(r"\s+", " ", evidence),
                        "review_status": "second_model_reviewed"})
            written += 1
        stats[f"{queue} {row['decision']} rules"] += written
        if not written:
            stats[f"{queue} {row['decision']} already ruled"] += 1

    for row in _rows(args.review_dir / "values.tsv"):
        if not row["decision"].startswith("rule:"):
            continue
        if row["confidence"] == "low":
            add("values", row, None, "low confidence", [])
            continue
        rule, why = value_rule(catalog, row)
        add("values", row, rule, why, [row["word"]])
    rejected_new: list[dict] = []
    part_rows: list[dict] = []
    known_rejected = {r["word"] for r in _rows(REJECTED_BEARERS)}
    for row in _rows(args.review_dir / "bearers.tsv"):
        if row["decision"] == "rule:bearer":
            if row["confidence"] == "low":
                add("bearers", row, None, "low confidence", [])
                continue
            rule, why = bearer_rule(catalog, row)
            # A synonym that is a part of the word ("ray" for "umbel ray", "perianth" for
            # "perianth part") is a wider word; one that PO already knows keeps its PO class.
            head = set(_norm(row["word"]).split())
            synonyms = [
                s for s in row["synonyms"].split("|")
                if len(s.strip()) > 3 and not set(_norm(s).split()) < head
                and (len(s.split()) > 1 or _variant(s, row["word"]))
                and na.normalize_key(s) not in catalog.res.po_lexicon
                and _norm(s) not in catalog.flopo_names
            ]
            if len(na.normalize_key(row["word"])) < 4:
                add("bearers", row, None, "too short a word to stand for a part everywhere", [])
                continue
            if na.normalize_key(row["word"]) in catalog.res.po_lexicon:
                add("bearers", row, None, "PO has the word as a label or exact synonym", [])
                continue
            add("bearers", row, rule, why, [row["word"], *synonyms])
        elif row["decision"] == "rule:bearer_part":
            part_rows.append(row)  # after the other rules, so that their numbers stay
        elif row["decision"] in ("not_a_part", "rejected") and row["confidence"] != "low":
            if row["word"] not in known_rejected:
                known_rejected.add(row["word"])
                rejected_new.append({
                    "word": row["word"],
                    "reason": re.sub(r"\s+", " ", ("not a part: " if row["decision"] == "not_a_part" else "") + row["reason"]),
                    "statements": row["statements"], "floras": row["floras"], "reviewed": STAMP,
                })
    # the plant parts that became FLOPO classes (tools/stage_review_classes.py): their words
    staged = args.review_dir / "staged-classes.tsv"
    if staged.exists():
        for row in _rows(staged):
            if row["queue"] != "bearers" or not row["flopo_id"]:
                continue
            identifier = row["flopo_id"]
            if identifier not in catalog.res.flopo_catalog:
                stats["bearers new class not in the registry yet"] += 1
                continue
            rule = dict.fromkeys(FIELDS, "")
            rule.update(match_field="bearer", kind="bearer", po_id=identifier, target_label=row["label"])
            for word in row["names"].split("|"):
                key = na.normalize_key(word)
                if not key or len(key) < 4 or ("bearer", key) in taken or key in catalog.res.po_lexicon or key in GENERIC_PART_WORDS:
                    continue
                taken.add(("bearer", key))
                out.append({**rule, "match_key": key, "review_status": "second_model_reviewed",
                            "evidence": f"{identifier.replace('_', ':')} {row['label']}: new FLOPO anatomy class of "
                                        f"the second-model review ({row['statements']} statements)"})
                stats["bearers new class rules"] += 1
    for row in part_rows:
        if row["confidence"] == "low":
            add("bearers", row, None, "low confidence", [])
            continue
        rule, why = part_of_rule(catalog, row)
        add("bearers", row, rule, why, [row["word"]])
    for index, rule in enumerate(out, 1):
        rule["rule_id"] = f"R{index:04d}"

    pairs = _rows(UNION_PAIRS)
    known_pairs = {(p["value_a"], p["value_b"]) for p in pairs}
    pairs_new: list[dict] = []
    for row in _rows(args.review_dir / "unions.tsv"):
        try:
            confidence = float(row["confidence"])
        except ValueError:
            confidence = {"high": 0.9, "medium": 0.7, "low": 0.4}.get(row["confidence"], 0.0)
        pair = tuple(sorted((row["value_a"], row["value_b"])))
        if pair in known_pairs or row["decision"] not in ("accept", "reject"):
            stats[f"unions {row['decision']} left"] += 1
            continue
        if row["decision"] == "accept" and confidence < UNION_ACCEPT_MIN:
            stats["unions accept below the confidence bar"] += 1
            continue
        if not (catalog.known(pair[0]) and catalog.known(pair[1])):
            stats["unions unknown identifier"] += 1
            continue
        known_pairs.add(pair)
        labels = {row["value_a"]: row["label_a"], row["value_b"]: row["label_b"]}
        pairs_new.append({
            "value_a": pair[0], "value_b": pair[1], "label_a": labels[pair[0]], "label_b": labels[pair[1]],
            "decision": row["decision"], "example": row["example"],
            "note": re.sub(r"\s+", " ", row["reason"]),
            "reviewed": f"2026-11-14 AI review (Claude Sonnet, second model; confidence {row['confidence']})",
        })
        stats[f"unions {row['decision']}"] += 1

    for key in sorted(stats):
        print(f"{stats[key]:6d}  {key}")
    print(f"{len(out):6d}  rules in all; {len(rejected_new)} rejected bearer words; {len(pairs_new)} pairs")
    if args.dry_run:
        return
    with RULES.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(out)
    for path, new in ((UNION_PAIRS, pairs_new), (REJECTED_BEARERS, rejected_new)):
        if new:
            with path.open("a", encoding="utf-8", newline="") as fh:
                csv.DictWriter(fh, fieldnames=list(new[0]), delimiter="\t", lineterminator="\n").writerows(new)
    with (args.review_dir / "not-applied.tsv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(skipped[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(skipped)


if __name__ == "__main__":
    main()
