#!/usr/bin/env python3
"""Apply only the generic botanical colours to PATO's editable OBO source."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


TERM_ID = re.compile(r"^id: (PATO:\d+)$", re.MULTILINE)
PREVIOUSLY_MANAGED_IDS = {
    f"PATO:{number:07d}" for number in range(104312, 104346)
}


def _term_blocks(text: str) -> tuple[str, list[str], str]:
    first = text.find("[Term]\n")
    typedef = text.find("[Typedef]\n")
    if first < 0 or typedef < 0 or first >= typedef:
        raise ValueError("expected OBO header, term stanzas, and typedef stanzas")
    header = text[:first]
    terms_text = text[first:typedef].rstrip("\n")
    suffix = text[typedef:]
    return header, terms_text.split("\n\n"), suffix


def _id(block: str) -> str:
    match = TERM_ID.search(block)
    if match is None:
        raise ValueError("term stanza has no PATO identifier")
    return match.group(1)


def apply_terms(pato_edit: Path, module_path: Path) -> tuple[int, int, int]:
    text = pato_edit.read_text(encoding="utf-8")
    module = module_path.read_text(encoding="utf-8").strip()
    module_blocks = module.split("\n\n")
    replacements = {_id(block): block for block in module_blocks}
    if len(replacements) != len(module_blocks):
        raise ValueError("duplicate IDs in generated generic-colour module")
    if any(" sensu " in block.partition("\n")[2].split("\n", 2)[1] for block in module_blocks):
        raise ValueError("a source-qualified sensu label leaked into the PATO module")

    header, existing_blocks, suffix = _term_blocks(text)
    existing_ids = [_id(block) for block in existing_blocks]
    if len(existing_ids) != len(set(existing_ids)):
        raise ValueError("duplicate PATO term IDs in pato-edit.obo")

    replaced = 0
    removed = 0
    rendered: list[str] = []
    for block, pato_id in zip(existing_blocks, existing_ids, strict=True):
        if pato_id in replacements:
            rendered.append(replacements.pop(pato_id))
            replaced += 1
        elif pato_id in PREVIOUSLY_MANAGED_IDS:
            # Remove source-qualified terms from the earlier draft of this PR.
            removed += 1
        elif pato_id == "PATO:0001942":
            old = 'synonym: "olive green" EXACT []'
            new = 'synonym: "olive green" RELATED []'
            if old in block:
                block = block.replace(old, new, 1)
            elif new not in block:
                raise ValueError(
                    "PATO:0001942 no longer has its expected olive-green synonym"
                )
            rendered.append(block)
        else:
            rendered.append(block)

    inserted = len(replacements)
    rendered.extend(replacements.values())
    updated = header + "\n\n".join(rendered) + "\n\n" + suffix
    if replaced < 2:
        raise ValueError("expected to replace existing PATO:0001425 and PATO:0104031")
    for pato_id in {_id(block) for block in module_blocks}:
        if updated.count(f"id: {pato_id}\n") != 1:
            raise ValueError(f"expected exactly one stanza for {pato_id}")
    stale = PREVIOUSLY_MANAGED_IDS - {_id(block) for block in module_blocks}
    if any(f"id: {pato_id}\n" in updated for pato_id in stale):
        raise ValueError("a draft PATO sensu identifier remains after applying the split")
    if updated.count('synonym: "olive green" RELATED []') != 1:
        raise ValueError("olive-green synonym scope correction was not applied exactly once")
    pato_edit.write_text(updated, encoding="utf-8")
    return replaced, inserted, removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pato-edit", type=Path, required=True)
    parser.add_argument(
        "--module",
        type=Path,
        default=Path("curation/pato_botanical_colour_terms.obo"),
    )
    args = parser.parse_args()
    replaced, inserted, removed = apply_terms(args.pato_edit, args.module)
    print(f"replaced {replaced} existing generic PATO colours")
    print(f"inserted {inserted} new generic PATO colours")
    print(f"removed {removed} draft PATO source-qualified colours")


if __name__ == "__main__":
    main()
