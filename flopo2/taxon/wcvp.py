"""Standardize printed taxon names to IPNI through Kew's World Checklist of Vascular Plants (WCVP).

WCVP (the checklist behind Plants of the World Online) lists every vascular plant name with its IPNI
identifier, its taxonomic status and, for synonyms, the accepted name.  Each printed flora name is
matched here to one WCVP name record:

1. the name is reduced to a key of its epithets (genus, species, infraspecific epithet; rank words,
   hybrid signs and authors dropped), taken from the spelling WFO verified when WFO matched it, and
   from the cleaned printed name otherwise;
2. names that share the key (homonyms, or one name at several ranks) are told apart by the printed
   authors, then by family, then by preferring an accepted name;
3. the matched record gives the IPNI ID of the name as used, and its accepted record gives the
   accepted name, authors and IPNI ID, which is the taxon's identity.

WCVP is a local download (``local-corpora/wcvp/raw/wcvp_names.csv``, pipe-separated); nothing is
fetched per name.  Bryophytes and algae are not in WCVP; those names keep no IPNI match.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

WCVP_NAMES = Path("local-corpora/wcvp/raw/wcvp_names.csv")
RANK_WORDS = {"subsp", "ssp", "var", "f", "forma", "subvar", "subf", "nothosubsp", "nothovar", "convar", "agg", "s.l", "s.str"}
STATUS_ORDER = {"Accepted": 0, "Synonym": 1, "Illegitimate": 2, "Invalid": 3, "Misapplied": 4, "Orthographic": 1, "Artificial Hybrid": 2, "Unplaced": 3, "Local Biotype": 5}


@dataclass
class IpniMatch:
    name: str  # printed name
    key: str = ""  # epithet key used for the lookup
    how: str = "none"  # exact-author | single | family | accepted | ambiguous | none
    ipni_id: str = ""  # IPNI ID of the name as used
    wcvp_id: str = ""
    matched_name: str = ""
    matched_authors: str = ""
    status: str = ""
    accepted_ipni_id: str = ""
    accepted_wcvp_id: str = ""
    accepted_name: str = ""
    accepted_authors: str = ""
    family: str = ""
    rank: str = ""
    candidates: int = 0


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def name_key(text: str) -> str:
    """Epithets only, lower case: 'Abutilon angulatum var. angulatum' -> 'abutilon angulatum angulatum'."""

    text = _ascii(re.sub(r"<[^>]+>", " ", text)).replace("×", " ").lower()
    words = []
    for word in re.findall(r"[a-z][a-z.\-]*", text):
        bare = word.rstrip(".")
        if bare in RANK_WORDS or word in {"x", "×"}:
            continue
        if word.endswith("."):
            break  # an abbreviated author ("L.", "Mast.") ends the name
        words.append(bare)
    return " ".join(words)


RANK_MARKERS = {"subsp": "subsp.", "ssp": "subsp.", "var": "var.", "f": "f.", "forma": "f.", "subvar": "subvar.", "subf": "subf."}


def printed_rank(printed: str) -> str:
    """The last infraspecific rank word of a printed name, in WCVP's spelling ("ssp." -> "subsp.")."""

    found = [RANK_MARKERS[w.lower()] for w in re.findall(r"\b(subsp|ssp|var|forma|f|subvar|subf)\.?\s+(?!(?:ex|in|et|non|nom|sensu)\b)[a-z]", re.sub(r"<[^>]+>", " ", printed))]
    return found[-1] if found else ""


def split_name(printed: str) -> tuple[str, str]:
    """(epithet key, author string) of a printed name; authors start at the first capital after the genus."""

    text = re.sub(r"<[^>]+>", " ", printed)
    text = re.sub(r"^[^A-Za-z]+", "", re.sub(r"\s+", " ", text)).strip()
    tokens = text.split(" ")
    name_tokens, author_tokens = tokens[:1], []
    for token in tokens[1:]:
        bare = token.strip(".,;:()'\"").lower()
        if not author_tokens and (token[:1].islower() or bare in RANK_WORDS or token in {"x", "×"}):
            if bare in RANK_WORDS or token in {"x", "×"}:
                continue
            name_tokens.append(token)
        else:
            author_tokens.append(token)
            if bare in RANK_WORDS:  # authors of the species, then "var. angulatum": keep the infraspecies
                author_tokens = []
    return name_key(" ".join(name_tokens)), " ".join(author_tokens).strip(" ,")


ENDINGS = ("iae", "ium", "ius", "ia", "ea", "eum", "eus", "ii", "ae", "us", "um", "is", "es", "a", "e", "i", "o", "on")


def stem_key(key: str) -> str:
    """Epithets without their Latin ending, so gender and spelling variants meet ("nervosum" / "nervosa")."""

    words = key.split()
    stems = [words[0]] if words else []
    for word in words[1:]:
        for ending in ENDINGS:
            if word.endswith(ending) and len(word) - len(ending) >= 3:
                word = word[: -len(ending)]
                break
        stems.append(word)
    return " ".join(stems)


def _ortho(word: str) -> str:
    word = word.replace("ae", "e").replace("oe", "e").replace("ph", "f").replace("th", "t").replace("k", "c").replace("y", "i")
    return re.sub(r"(.)\1+", r"\1", word)


def ortho_key(key: str) -> str:
    """Genus plus the consonant skeleton of each epithet (k/c, y/i, ae/i, ph/f, doubled letters aside)."""

    words = key.split()
    return " ".join(words[:1] + [re.sub(r"[aeiou]", "", _ortho(w)) for w in words[1:]])


def ortho_close(a: str, b: str) -> bool:
    """Two epithet keys that differ only in spelling: same skeleton, same first three letters, similar length."""

    wa, wb = a.split(), b.split()
    if len(wa) != len(wb) or wa[:1] != wb[:1]:
        return False
    for x, y in zip(wa[1:], wb[1:]):
        x, y = _ortho(x), _ortho(y)
        if x == y:
            continue
        if x[:3] != y[:3] or abs(len(x) - len(y)) > 2 or re.sub(r"[aeiou]", "", x) != re.sub(r"[aeiou]", "", y):
            return False
    return True


def author_key(authors: str) -> str:
    authors = re.sub(r"\(.*?\)", " ", _ascii(authors))  # the parenthetical (basionym) author varies most
    authors = re.sub(r"\bex\b.*?(?=$)", "", authors) if " ex " in authors else authors
    return re.sub(r"[^a-z]", "", authors.lower())


class Wcvp:
    def __init__(self, path: Path = WCVP_NAMES):
        self.by_id: dict[str, dict] = {}
        self.by_key: dict[str, list[str]] = {}
        self.by_stem: dict[str, list[str]] = {}
        self.by_ortho: dict[str, list[str]] = {}
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="|", quoting=csv.QUOTE_NONE):
                pid = row["plant_name_id"]
                self.by_id[pid] = {k: row[k] for k in ("ipni_id", "taxon_rank", "taxon_status", "family", "taxon_name", "taxon_authors", "accepted_plant_name_id")}
                key = name_key(row["taxon_name"])
                self.by_key.setdefault(key, []).append(pid)
                self.by_stem.setdefault(stem_key(key), []).append(pid)
                self.by_ortho.setdefault(ortho_key(key), []).append(pid)

    def lookups(self, key: str, verified: str) -> list[tuple[str, str, list[str]]]:
        """(key, kind, WCVP ids) to try in order: as printed, as WFO verified it, an ending variant,
        and for an autonym ("X y var. y") the species."""

        keys = list(dict.fromkeys(k for k in (key, name_key(verified)) if k))
        out = [(k, "", self.by_key.get(k, [])) for k in keys]
        out += [(k, "variant-", self.by_stem.get(stem_key(k), [])) for k in keys]
        for k in keys:
            near = [pid for pid in self.by_ortho.get(ortho_key(k), []) if ortho_close(k, name_key(self.by_id[pid]["taxon_name"]))]
            if len({name_key(self.by_id[pid]["taxon_name"]) for pid in near}) == 1:  # one spelling only
                out.append((k, "spelling-", near))
        for k in keys:
            words = k.split()
            if len(words) == 3 and words[1] == words[2]:
                out.append((" ".join(words[:2]), "autonym-", self.by_key.get(" ".join(words[:2]), [])))
        return out

    def match(self, printed: str, verified: str = "", family: str = "", wfo_accepted: str = "") -> IpniMatch:
        key, authors = split_name(printed)
        result = IpniMatch(name=printed, key=key)
        for k, kind, ids in self.lookups(key, verified):
            if not ids:
                continue
            found = self._choose(printed, k, authors, ids, family, wfo_accepted)
            if found.how != "none":
                found.how = kind + found.how if found.how != "ambiguous" else "ambiguous"
                return found
            result = found
        return result

    def _choose(self, printed: str, key: str, authors: str, ids: list[str], family: str, wfo_accepted: str) -> IpniMatch:
        result = IpniMatch(name=printed, key=key)
        result.candidates = len(ids)
        rows = [(pid, self.by_id[pid]) for pid in ids]
        rank = printed_rank(printed)
        if rank:  # "subsp. raddiana" is not "var. raddiana"
            rows = [r for r in rows if f" {rank} " in r[1]["taxon_name"]] or rows
        elif len(key.split()) == 2:
            rows = [r for r in rows if r[1]["taxon_rank"] == "Species"] or rows
        akey = author_key(authors)
        chosen, how = None, ""
        if akey:
            same = [r for r in rows if author_key(r[1]["taxon_authors"]) == akey]
            if not same:  # "Mast." printed, "Mast. ex Hook." listed, or the reverse
                same = [r for r in rows if akey and (akey in author_key(r[1]["taxon_authors"]) or author_key(r[1]["taxon_authors"]) in akey) and author_key(r[1]["taxon_authors"])]
            if len({self._accepted(pid) for pid, _ in same}) == 1 and same:
                chosen, how = min(same, key=lambda r: STATUS_ORDER.get(r[1]["taxon_status"], 9)), "exact-author"
        if chosen is None and len({self._accepted(pid) for pid, _ in rows}) == 1:
            chosen, how = min(rows, key=lambda r: STATUS_ORDER.get(r[1]["taxon_status"], 9)), "single"
        if chosen is None and family:
            fam = [r for r in rows if r[1]["family"].lower() == family.lower()]
            if fam and len({self._accepted(pid) for pid, _ in fam}) == 1:
                chosen, how = min(fam, key=lambda r: STATUS_ORDER.get(r[1]["taxon_status"], 9)), "family"
        if chosen is None and wfo_accepted:  # WFO's accepted name decides between homonyms
            wkey = name_key(wfo_accepted)
            agree = [r for r in rows if name_key(self.by_id.get(self._accepted(r[0]), {}).get("taxon_name", "")) == wkey]
            if agree and len({self._accepted(pid) for pid, _ in agree}) == 1:
                chosen, how = min(agree, key=lambda r: STATUS_ORDER.get(r[1]["taxon_status"], 9)), "wfo-accepted"
        if chosen is None:
            accepted = [r for r in rows if r[1]["taxon_status"] == "Accepted"]
            if len(accepted) == 1 and not akey:
                chosen, how = accepted[0], "accepted"
        if chosen is None:
            result.how = "ambiguous"
            return result
        pid, row = chosen
        acc_id = self._accepted(pid)
        acc = self.by_id.get(acc_id, {})
        result.how = how
        result.wcvp_id, result.ipni_id = pid, row["ipni_id"]
        result.matched_name, result.matched_authors = row["taxon_name"], row["taxon_authors"]
        result.status, result.rank, result.family = row["taxon_status"], row["taxon_rank"], row["family"]
        if acc:
            result.accepted_wcvp_id, result.accepted_ipni_id = acc_id, acc["ipni_id"]
            result.accepted_name, result.accepted_authors = acc["taxon_name"], acc["taxon_authors"]
        return result

    def from_id(self, printed: str, pid: str, how: str) -> IpniMatch:
        """The match for a WCVP record chosen elsewhere (a reviewed pick between homonyms)."""

        row, acc_id = self.by_id[pid], self._accepted(pid)
        acc = self.by_id.get(acc_id, {})
        return IpniMatch(
            name=printed, key=name_key(row["taxon_name"]), how=how, ipni_id=row["ipni_id"], wcvp_id=pid,
            matched_name=row["taxon_name"], matched_authors=row["taxon_authors"], status=row["taxon_status"],
            accepted_ipni_id=acc.get("ipni_id", ""), accepted_wcvp_id=acc_id if acc else "",
            accepted_name=acc.get("taxon_name", ""), accepted_authors=acc.get("taxon_authors", ""),
            family=row["family"], rank=row["taxon_rank"], candidates=1,
        )

    def _accepted(self, pid: str) -> str:
        row = self.by_id[pid]
        return row["accepted_plant_name_id"] or (pid if row["taxon_status"] == "Accepted" else "")


def as_row(match: IpniMatch) -> dict:
    return asdict(match)


MATCH_DIR = Path("local-corpora/wcvp/match")
TABLE_FIELDS = ("how", "ipni_id", "wcvp_id", "matched_name", "matched_authors", "status", "accepted_ipni_id",
                "accepted_wcvp_id", "accepted_name", "accepted_authors", "family", "rank")


def load_ipni_table(directory: Path = MATCH_DIR) -> dict[str, dict]:
    """Printed name -> its WCVP/IPNI standard name: the direct matches, then the verified LLM repairs."""

    table: dict[str, dict] = {}
    matches, fixes = directory / "ipni-matches.tsv", directory / "ipni-llm-fixes.tsv"
    if matches.exists():
        with matches.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row["how"] not in ("none", "ambiguous"):
                    table[row["name"]] = {k: row[k] for k in TABLE_FIELDS}
    if fixes.exists():
        with fixes.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row.get("result_how") and row["name"] not in table:
                    table[row["name"]] = {k: row.get("result_" + k, "") for k in TABLE_FIELDS}
    return table
