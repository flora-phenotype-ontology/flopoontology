"""The annotation design patterns (``docs/odp/``) as ``patterns.json`` for the atlas's Patterns page.

Each pattern file becomes one entry with its HTML, and with a SPARQL selection (``SELECTORS``) by
which the page finds records of that pattern in the atlas: the property that only records of the
pattern have. The introduction is the catalogue (``docs/odp/README.md``) without its table.

The Markdown of these files is simple (headings, paragraphs, lists, tables, fenced code, inline
code, emphasis, links), so it is converted here rather than with a library.

    python -m tools.atlas_patterns [-o web/saudi/patterns.json]
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

ODP = Path("docs/odp")
REPO = "https://github.com/flora-phenotype-ontology/flopoontology/blob/master/"
# Triple patterns over ?r (a fb:TraitRecord) that only records of the pattern match.
SELECTORS = {
    "00": "?r fb:bearer ?b ; fb:quality ?q . FILTER NOT EXISTS { ?r fb:qualifier ?x } FILTER NOT EXISTS { ?r fb:bearerState ?y } FILTER NOT EXISTS { ?r fb:valueOperator ?z }",
    "01": '?r fb:qualifier "approximately" .',
    "02": "{ ?r fb:highExclusive true } UNION { ?r fb:lowExclusive true }",
    "03": '?r fb:container ?container ; fb:unitSymbol "count" .',
    "04": "?r fb:bearerState ?state .",
    "05": "{ ?r fb:minExtreme ?extreme } UNION { ?r fb:maxExtreme ?extreme }",
    "06": "?r fb:specimenCondition ?condition .",
    "07": '?r fb:valueOperator "one_of" .',
    "08": "?r fb:alternative ?alternative . ?alternative fb:frequency ?frequency .",
    "09": "?r fb:towards ?other ; fb:comparison ?comparison . FILTER NOT EXISTS { ?r fb:ratioLow ?ratio }",
    "10": "?r fb:ratioLow ?ratio .",
    "11": "?r fb:ratioNumerator ?numerator .",
    "12": "?r fb:wholeQuality ?wholeQuality .",
    "13": "?r fb:countWord ?word .",
    "14": "?r fb:countPosition ?position .",
    "15": "?r fb:negated true ; fb:quality <http://purl.obolibrary.org/obo/PATO_0000467> . FILTER NOT EXISTS { ?r fb:partQuality ?x }",
    "16": "?r fb:carrier ?carrier .",
    "17": "",  # a pattern for defining value classes: no record carries it
}


def inline(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        part = html.escape(part, quote=False)
        part = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", part)
        part = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", part)

        def link(m: re.Match) -> str:
            label, target = m.group(1), m.group(2)
            num = re.match(r"(\d\d)-[\w-]+\.md$", target)
            if num:
                href = f"#/patterns/{num.group(1)}"
            elif target.endswith("README.md") and "/" not in target:
                href = "#/patterns"
            elif re.match(r"https?://", target):
                href = target
            else:
                href = REPO + "docs/odp/" + target
            ext = "" if href.startswith("#") else ' target="_blank" rel="noopener"'
            return f'<a href="{html.escape(href)}"{ext}>{label}</a>'

        part = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, part)
        part = re.sub(r"(?<![\"=])(https?://[^\s<)]+[^\s<).,;])", r'<a href="\1" target="_blank" rel="noopener">\1</a>', part)
        out.append(part)
    return "".join(out)


def to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            lang = line[3:].strip()
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            out.append(f'<pre class="code" data-lang="{html.escape(lang)}"><code>{html.escape(chr(10).join(block))}</code></pre>')
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)", line)
        if heading:
            level = min(len(heading.group(1)) + 1, 5)  # the page has its own h1
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            body = [r for r in rows[1:] if not all(re.fullmatch(r":?-+:?", c) for c in r)]
            head = "".join(f"<th>{inline(c)}</th>" for c in rows[0])
            cells = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
            out.append(f'<div class="tablewrap"><table class="results"><thead><tr>{head}</tr></thead><tbody>{cells}</tbody></table></div>')
            continue
        bullet = re.match(r"^(\s*)([*-]|\d+\.)\s+(.*)", line)
        if bullet:
            ordered = bullet.group(2)[0].isdigit()
            items = []
            while i < len(lines):
                m = re.match(r"^(\s*)([*-]|\d+\.)\s+(.*)", lines[i])
                if m:
                    items.append(m.group(3))
                elif lines[i].startswith("  ") and lines[i].strip() and items:
                    items[-1] += " " + lines[i].strip()
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(item)}</li>" for item in items) + f"</{tag}>")
            continue
        if line.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i].lstrip("> ").rstrip())
                i += 1
            out.append(f"<blockquote>{to_html(chr(10).join(quote))}</blockquote>")
            continue
        if not line.strip():
            i += 1
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|```|\||\s*([*-]|\d+\.)\s|>)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(' '.join(para))}</p>")
    return "\n".join(out)


def build(odp: Path = ODP) -> dict:
    patterns = []
    for path in sorted(odp.glob("[0-9][0-9]-*.md")):
        text = path.read_text(encoding="utf-8")
        num = path.name[:2]
        title = re.match(r"#\s+\d+\.\s+(.*)", text).group(1).strip()
        head = re.search(r"\*\*Intent\.\*\*(.*?)(?:\n\s*\n|$)", text, re.S)  # the opening paragraph
        lead = " ".join(head.group(0).split()) if head else ""
        intent = re.search(r"\*\*Intent\.\*\*\s+(.*?)(?=\*\*Wording|$)", lead)
        wording = re.search(r"\*\*Wording\.\*\*\s+(.*)", lead)
        body = re.sub(r"^#\s+.*\n", "", text, count=1)
        if head:
            body = body.replace(head.group(0), "", 1)
        patterns.append({
            "id": num, "title": title,
            "intent": inline(intent.group(1).strip()) if intent else "",
            "wording": inline(wording.group(1).strip()) if wording else "",
            "html": to_html(body),
            "selector": SELECTORS.get(num, ""),
            "source": REPO + "docs/odp/" + path.name,
        })
    readme = (odp / "README.md").read_text(encoding="utf-8")
    readme = re.sub(r"^#\s+.*\n", "", readme, count=1)
    readme = re.sub(r"\n\|[^\n]*\n(\|[^\n]*\n)+", "\n", readme, count=1)  # the table of patterns: the page lists them itself
    readme = readme.split("\n## ", 1)[1] if "\n## " in readme else readme  # the opening speaks of files; the page has its own
    readme = "## " + readme
    return {"intro": to_html(readme), "patterns": patterns}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("-o", "--output", type=Path, default=Path("web/saudi/patterns.json"))
    args = parser.parse_args()
    args.output.write_text(json.dumps(build(), ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
