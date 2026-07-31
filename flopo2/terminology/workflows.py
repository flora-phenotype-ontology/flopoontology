"""Coverage reports, curation queues, and deterministic gold-set sampling."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from flopo2.terminology.annotate import TerminologyIndex
from flopo2.terminology.model import RegistryEntry
from flopo2.terminology.normalize import fold, text_tokens
from flopo2.terminology.registry import read_registry, write_registry

_CONTENT_STOP = {
    "about", "also", "and", "are", "avec", "dans", "des", "elle", "elles", "est", "for",
    "from", "have", "its", "les", "mais", "not", "often", "que", "qui", "sur", "than", "that",
    "the", "their", "these", "this", "those", "une", "usually", "very", "when", "which", "with",
}


def _iter_jsonl(path: Path):
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def coverage_report(
    corpus: Path,
    index: TerminologyIndex,
    update_registry: Path | None = None,
    residual_limit: int = 200,
) -> dict:
    term_counts: Counter[str] = Counter()
    surface_counts: Counter[str] = Counter()
    residual_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    segments = mapped_segments = eligible_segments = trusted_segments = 0
    mentions_total = longest_total = mapped_total = eligible_total = trusted_total = 0
    ambiguous_total = nil_total = 0

    for row in _iter_jsonl(corpus):
        text = row.get("text", "")
        mentions = index.annotate(
            text,
            language=row.get("language", ""),
            organ_context=row.get("organ", ""),
            keep_overlaps=True,
        )
        segments += 1
        mentions_total += len(mentions)
        mapped_this_segment = False
        eligible_this_segment = False
        trusted_this_segment = False
        covered: list[tuple[int, int]] = []
        for mention in mentions:
            if not mention.longest_match:
                continue
            longest_total += 1
            covered.append((mention.start, mention.end))
            surface_counts[mention.normalized_form] += 1
            term_counts.update(mention.registry_term_ids)
            if not mention.candidates:
                nil_total += 1
                status_counts["nil"] += 1
                continue
            mapped_total += 1
            mapped_this_segment = True
            top = mention.candidates[0]
            status_counts[top.mapping_status or "retrieved"] += 1
            eligible = (
                top.score >= 0.72
                and top.mapping_relation in {"", "skos:exactMatch", "skos:closeMatch"}
            )
            if eligible:
                eligible_total += 1
                eligible_this_segment = True
            if eligible and top.mapping_status in {"reviewed", "accepted", "auto"}:
                trusted_total += 1
                trusted_this_segment = True
            if len(mention.candidates) > 1 and top.score - mention.candidates[1].score < 0.05:
                ambiguous_total += 1
        if mapped_this_segment:
            mapped_segments += 1
        if eligible_this_segment:
            eligible_segments += 1
        if trusted_this_segment:
            trusted_segments += 1
        for normalized, _, start, end in text_tokens(text):
            if any(left <= start and end <= right for left, right in covered):
                continue
            if len(normalized) >= 4 and normalized not in _CONTENT_STOP and not normalized.isdigit():
                residual_counts[normalized] += 1

    residuals = []
    for token, frequency in residual_counts.most_common(residual_limit):
        candidates = index.retriever.retrieve(token, role="ambiguous", k=3)
        if not candidates or candidates[0].score < 0.72:
            continue
        residuals.append(
            {
                "surface": token,
                "frequency": frequency,
                "candidate_ids": [candidate.target_id for candidate in candidates],
                "candidate_labels": [candidate.label for candidate in candidates],
                "candidate_scores": [candidate.score for candidate in candidates],
            }
        )

    if update_registry:
        entries = read_registry(update_registry)
        for entry in entries:
            entry.corpus_frequency = term_counts[entry.term_id]
        write_registry(entries, update_registry)

    return {
        "corpus": str(corpus),
        "segments": segments,
        "segments_with_mapped_terminology": mapped_segments,
        "segments_with_eligible_terminology": eligible_segments,
        "segments_with_reviewed_or_auto_terminology": trusted_segments,
        "segment_coverage": round(mapped_segments / segments, 4) if segments else 0.0,
        "mentions_including_overlaps": mentions_total,
        "longest_mentions": longest_total,
        "mapped_mentions": mapped_total,
        "eligible_mentions": eligible_total,
        "reviewed_or_auto_mentions": trusted_total,
        "eligible_candidate_only_mentions": eligible_total - trusted_total,
        "low_confidence_or_non_equivalent_candidate_mentions": mapped_total - eligible_total,
        "nil_mentions": nil_total,
        "ambiguous_mentions": ambiguous_total,
        "mention_mapping_rate": round(mapped_total / longest_total, 4) if longest_total else 0.0,
        "eligible_mention_rate": round(eligible_total / longest_total, 4) if longest_total else 0.0,
        "trusted_mention_rate": round(trusted_total / longest_total, 4) if longest_total else 0.0,
        "mapping_statuses": dict(status_counts),
        "distinct_registry_terms_observed": len(term_counts),
        "top_observed_surfaces": surface_counts.most_common(100),
        "candidate_residual_tokens": residuals,
    }


def write_review_queue(entries: list[RegistryEntry], output: Path) -> int:
    fields = [
        "priority", "term_id", "surface_form", "language", "semantic_role", "category",
        "organ_context", "corpus_frequency", "review_status", "target_id", "target_label",
        "mapping_relation", "mapping_confidence", "candidate_ids", "candidate_labels",
        "candidate_scores", "component_ids", "logical_operator", "attribute_id", "source_id",
        "source_url", "evidence", "curator_decision", "curator_notes",
    ]
    queue = []
    for entry in entries:
        if entry.review_status in {"reviewed", "accepted", "rejected"}:
            continue
        ambiguity = 20 if len(entry.candidate_id_list) > 1 else 0
        nil = 30 if not entry.candidate_ids else 0
        proposed = 10 if entry.review_status in {"review", "proposed"} else 0
        priority = min(entry.corpus_frequency, 1000) * 100 + nil + ambiguity + proposed
        row = entry.to_row()
        row.update(priority=priority, curator_decision="", curator_notes="")
        queue.append(row)
    queue.sort(key=lambda row: (-int(row["priority"]), row["source_id"], row["term_id"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(queue)
    return len(queue)


def apply_review_queue(
    entries: list[RegistryEntry],
    review_path: Path,
    catalog,
    curator_orcid: str,
    mapping_date: str,
) -> dict:
    """Apply explicit curator decisions; automated tools cannot call a proposal reviewed."""
    by_id = {entry.term_id: entry for entry in entries}
    accepted = rejected = unmapped = skipped = 0
    valid_relations = {
        "skos:exactMatch",
        "skos:closeMatch",
        "skos:relatedMatch",
        "skos:broadMatch",
        "skos:narrowMatch",
        "flopo:compositionalMatch",
        "flopo:unmapped",
    }
    with Path(review_path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            decision = (row.get("curator_decision") or "").strip().lower()
            if not decision:
                skipped += 1
                continue
            entry = by_id.get(row.get("term_id", ""))
            if entry is None:
                raise ValueError(f"unknown registry term in review queue: {row.get('term_id', '')}")
            if decision in {"reject", "rejected"}:
                entry.review_status = "rejected"
                entry.target_id = ""
                entry.target_label = ""
                entry.target_namespace = ""
                entry.component_ids = ""
                entry.logical_operator = ""
                entry.attribute_id = ""
                entry.mapping_relation = "flopo:unmapped"
                entry.mapping_confidence = 0.0
                entry.mapping_method = "manual_mapping_curation"
                rejected += 1
            elif decision in {"unmapped", "nil"}:
                entry.review_status = "reviewed"
                entry.target_id = ""
                entry.target_label = ""
                entry.target_namespace = ""
                entry.component_ids = ""
                entry.logical_operator = ""
                entry.attribute_id = ""
                entry.mapping_relation = "flopo:unmapped"
                entry.mapping_confidence = 1.0
                entry.mapping_method = "manual_mapping_curation"
                unmapped += 1
            elif decision in {"accept", "accepted", "reviewed"}:
                target_id = (row.get("target_id") or entry.target_id).strip()
                components = (row.get("component_ids") or entry.component_ids).strip()
                operator = (row.get("logical_operator") or entry.logical_operator or "atomic").strip()
                relation = (row.get("mapping_relation") or entry.mapping_relation).strip()
                if relation not in valid_relations:
                    raise ValueError(f"invalid mapping relation for {entry.term_id}: {relation}")
                if components:
                    component_ids = [value for value in components.split("|") if value]
                    if operator not in {"one_of", "all_of"} or len(component_ids) < 2:
                        raise ValueError(f"invalid compositional mapping for {entry.term_id}")
                    missing = [value for value in component_ids if value not in catalog.terms]
                    if missing:
                        raise ValueError(f"unknown mapping components for {entry.term_id}: {missing}")
                    entry.component_ids = "|".join(component_ids)
                    entry.logical_operator = operator
                    entry.mapping_relation = "flopo:compositionalMatch"
                    if target_id in catalog.terms:
                        target = catalog.terms[target_id]
                        entry.target_id = target_id
                        entry.target_label = target.label
                        entry.target_namespace = target.namespace
                    else:
                        entry.target_id = ""
                        entry.target_label = ""
                        entry.target_namespace = ""
                else:
                    if target_id not in catalog.terms:
                        raise ValueError(f"unknown mapping target for {entry.term_id}: {target_id}")
                    target = catalog.terms[target_id]
                    entry.target_id = target_id
                    entry.target_label = target.label
                    entry.target_namespace = target.namespace
                    entry.mapping_relation = relation
                    entry.logical_operator = "atomic"
                    entry.component_ids = ""
                try:
                    entry.mapping_confidence = float(row.get("mapping_confidence") or 1.0)
                except ValueError:
                    entry.mapping_confidence = 1.0
                entry.mapping_method = "manual_mapping_curation"
                entry.review_status = "reviewed"
                accepted += 1
            else:
                raise ValueError(f"unsupported curator_decision for {entry.term_id}: {decision}")
            entry.curator_orcid = curator_orcid
            entry.mapping_date = mapping_date
            note = (row.get("curator_notes") or "").strip().replace("\t", " ")
            if note:
                entry.notes = f"{entry.notes}; {note}".strip("; ")
    return {"accepted": accepted, "rejected": rejected, "reviewed_unmapped": unmapped, "skipped": skipped}


def _round_robin(groups: dict[tuple, list[RegistryEntry]], n: int, seed: int) -> list[RegistryEntry]:
    rng = random.Random(seed)
    values = []
    for group in groups.values():
        rng.shuffle(group)
        values.append(group)
    rng.shuffle(values)
    out = []
    while values and len(out) < n:
        remaining = []
        for group in values:
            if group and len(out) < n:
                out.append(group.pop())
            if group:
                remaining.append(group)
        values = remaining
    return out


def _balanced_source_language(
    entries: list[RegistryEntry], n: int, seed: int
) -> list[RegistryEntry]:
    """Balance sources/languages first, then roles/categories within each source slice."""
    outer: dict[tuple[str, str], list[RegistryEntry]] = defaultdict(list)
    for entry in entries:
        outer[(entry.source_id, entry.language)].append(entry)
    prepared: dict[tuple, list[RegistryEntry]] = {}
    for offset, key in enumerate(sorted(outer)):
        inner: dict[tuple, list[RegistryEntry]] = defaultdict(list)
        for entry in outer[key]:
            inner[(entry.semantic_role, entry.category, entry.organ_context)].append(entry)
        prepared[key] = _round_robin(inner, len(outer[key]), seed + offset + 1)

    rng = random.Random(seed)
    keys = sorted(prepared)
    rng.shuffle(keys)
    selected: list[RegistryEntry] = []
    while keys and len(selected) < n:
        remaining = []
        for key in keys:
            if prepared[key] and len(selected) < n:
                selected.append(prepared[key].pop(0))
            if prepared[key]:
                remaining.append(key)
        keys = remaining
    return selected


def _gold_split_group(entry: RegistryEntry) -> str:
    """Group obvious synonyms/translations so they cannot leak across evaluation splits."""
    mapped_ids = sorted({entry.target_id, *entry.components} - {""})
    if mapped_ids:
        return "concept:" + "|".join(mapped_ids)
    if entry.translation_group:
        return "translation:" + entry.translation_group
    return f"surface:{entry.language}:{fold(entry.normalized_form or entry.surface_form)}"


def _gold_split(group: str, seed: int) -> str:
    bucket = int.from_bytes(
        hashlib.sha256(f"{seed}\t{group}".encode()).digest()[:8], "big"
    ) % 100
    if bucket < 60:
        return "train"
    if bucket < 80:
        return "dev"
    return "test"


def sample_alignment_gold(
    entries: list[RegistryEntry],
    output: Path,
    n: int = 400,
    corpus_n: int | None = None,
    seed: int = 20260714,
) -> int:
    corpus_n = min(n, corpus_n if corpus_n is not None else n // 2)
    attested = [entry for entry in entries if entry.corpus_frequency > 0]
    glossary_only = [entry for entry in entries if entry.corpus_frequency == 0]
    selected = _balanced_source_language(attested, corpus_n, seed)
    selected.extend(
        _balanced_source_language(glossary_only, n - len(selected), seed + 1)
    )
    fields = [
        "term_id", "surface_form", "language", "semantic_role", "category", "organ_context",
        "source_id", "translation_group", "corpus_frequency", "split_group", "split",
        "candidate_ids", "candidate_labels", "candidate_scores",
        "predicted_target_id", "predicted_relation", "predicted_status", "gold_target_ids",
        "gold_relation", "gold_is_nil", "gold_semantic_role", "gold_logical_operator",
        "gold_attribute_id", "curator_notes",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for entry in selected:
            split_group = _gold_split_group(entry)
            writer.writerow(
                {
                    "term_id": entry.term_id,
                    "surface_form": entry.surface_form,
                    "language": entry.language,
                    "semantic_role": entry.semantic_role,
                    "category": entry.category,
                    "organ_context": entry.organ_context,
                    "source_id": entry.source_id,
                    "translation_group": entry.translation_group,
                    "corpus_frequency": entry.corpus_frequency,
                    "split_group": split_group,
                    "split": _gold_split(split_group, seed),
                    "candidate_ids": entry.candidate_ids,
                    "candidate_labels": entry.candidate_labels,
                    "candidate_scores": entry.candidate_scores,
                    "predicted_target_id": entry.target_id,
                    "predicted_relation": entry.mapping_relation,
                    "predicted_status": entry.review_status,
                    "gold_target_ids": "",
                    "gold_relation": "",
                    "gold_is_nil": "",
                    "gold_semantic_role": "",
                    "gold_logical_operator": "",
                    "gold_attribute_id": "",
                    "curator_notes": "",
                }
            )
    return len(selected)


def resplit_alignment_gold(
    source: Path,
    output: Path,
    seed: int = 20260714,
) -> dict[str, object]:
    """Reassign curated gold rows by connected surface/translation/target components."""
    with Path(source).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if "term_id" not in fields:
        raise ValueError(f"{source}: missing term_id column")
    for field in ("split_group", "split"):
        if field not in fields:
            fields.append(field)

    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    owner: dict[str, int] = {}
    row_keys: list[set[str]] = []
    for index, row in enumerate(rows):
        keys = set()
        surface = fold(row.get("surface_form") or "")
        language = (row.get("language") or "").strip()
        if surface:
            keys.add(f"surface:{language}:{surface}")
        translation = (row.get("translation_group") or "").strip()
        if translation:
            keys.add(f"translation:{translation}")
        for target_id in (row.get("gold_target_ids") or "").split("|"):
            if target_id:
                keys.add(f"gold_target:{target_id}")
        row_keys.append(keys)
        for key in sorted(keys):
            if key in owner:
                union(index, owner[key])
            else:
                owner[key] = index

    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(rows)):
        components[find(index)].append(index)
    split_counts: Counter[str] = Counter()
    for indices in components.values():
        signature_parts = sorted(
            {key for index in indices for key in row_keys[index]}
            | {f"term:{rows[index].get('term_id', '')}" for index in indices}
        )
        digest = hashlib.sha256("\n".join(signature_parts).encode()).hexdigest()[:16]
        split_group = f"gold-component:{digest}"
        split = _gold_split(split_group, seed)
        split_counts[split] += len(indices)
        for index in indices:
            rows[index]["split_group"] = split_group
            rows[index]["split"] = split

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return {
        "rows": len(rows),
        "components": len(components),
        "split_counts": dict(sorted(split_counts.items())),
        "out": str(output),
    }


def sample_low_yield_segments(
    corpus: Path,
    assertions_tsv: Path,
    output: Path,
    n: int = 200,
    seed: int = 20260714,
) -> int:
    counts: Counter[str] = Counter()
    with Path(assertions_tsv).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            counts[row.get("source_id", "")] += 1
    rows = list(_iter_jsonl(corpus))
    low = [row for row in rows if counts[row.get("source_id", "")] <= 1]
    normal = [row for row in rows if counts[row.get("source_id", "")] > 1]
    rng = random.Random(seed)
    rng.shuffle(low)
    rng.shuffle(normal)
    selected = low[: n // 2] + normal[: n - min(n // 2, len(low))]
    rng.shuffle(selected)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in selected:
            record = dict(row)
            record["current_assertion_count"] = counts[row.get("source_id", "")]
            record["gold_assertions"] = []
            record["curator_notes"] = ""
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(selected)
