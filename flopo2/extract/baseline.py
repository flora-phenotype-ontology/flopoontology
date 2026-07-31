"""Deterministic baseline extractor for full-corpus rehearsals.

This is not the final FLOPO v2 extraction engine. It exists so the rebuilt Phase 6-8 workflow can
be exercised over a real Flora when OpenRouter credentials are absent. It emits grounded
PO/PATO assertions from exact lexical cues:

* the FlorML organ heading supplies the anatomical entity;
* source text must be a verbatim substring;
* qualities are limited to high-confidence botanical morphology cues and measurements.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from flopo2.extract.ground import load_lexicons
from flopo2.extract.measurement import parse_measurements


@dataclass(frozen=True)
class Cue:
    pato_id: str
    pattern: re.Pattern[str]


QUALITY_CUES = [
    ("PATO_0000453", r"\bglab(?:re|res|rous)\b"),
    ("PATO_0001320", r"\bpubesc(?:ent|ente|ents|entes)\b|\bdowny\b"),
    ("PATO_0002341", r"\btoment(?:eux|euse|euses|ose|ous)\b"),
    ("PATO_0000701", r"\bliss(?:e|es)\b|\bsmooth\b"),
    # PATO currently reuses oval/ovoid with conflicting synonym scopes under elliptic and ovate.
    # Botanical standards distinguish oval/ovate (2-D) from ovoid (3-D), so the deterministic
    # baseline accepts only the unambiguous preferred terms and leaves the others to curation.
    ("PATO_0000947", r"\bellipti(?:que|ques|c|cal)\b"),
    ("PATO_0000946", r"\boblong(?:ue|ues|s)?\b"),
    ("PATO_0001891", r"\bovate\b"),
    ("PATO_0001877", r"\blanc(?:eolate|éol(?:é|ée|és|ées))\b"),
    ("PATO_0001199", r"\blin[ée]aire(?:s)?\b|\blinear\b"),
    ("PATO_0002228", r"\bacumin[ée](?:e?s?)?\b|\bacuminate\b"),
    ("PATO_0001982", r"\batt[ée]nu[ée](?:e?s?)?\b|\battenuate\b"),
    # Do not map botanical acute to PATO:0000389 (a process-duration quality), or force the
    # broader PATO:0001419 sharp without an explicit apex/base context.
    ("PATO_0001935", r"\bobtus(?:e|es)?\b|\bobtuse\b"),
    ("PATO_0005014", r"\bsubglobul(?:eux|euse|euses)\b|\bsubglobose\b|\bsubspherical\b"),
    ("PATO_0001499", r"\bglobul(?:eux|euse|euses)\b|\bglobose\b|\bglobular\b|\bspherical\b"),
    ("PATO_0000322", r"\brouge(?:s)?\b|\bred\b"),
    ("PATO_0000324", r"\bjaune(?:s)?\b|\byellow\b"),
    ("PATO_0000323", r"\bblanc(?:he|hes|s)?\b|\bwhite\b"),
    ("PATO_0000320", r"\bvert(?:e|es|s)?\b|\bgreen\b"),
    # Brownish/blackish are RELATED, not exact, PATO synonyms and need their own value model.
    ("PATO_0000952", r"\bbrun(?:e|es|s)?\b|\bbrown\b"),
    ("PATO_0000317", r"\bnoir(?:e|es|s)?\b|\bblack\b"),
    ("PATO_0104032", r"\bcoriace(?:s)?\b|\bcoriaceous\b|\bleathery\b"),
    ("PATO_0002358", r"\bc[ôo]tel[ée](?:e?s?)?\b|\bridged\b"),
    ("PATO_0000402", r"\bramifi[ée](?:e?s?)?\b|\bbranched\b"),
    # ``simple`` is context-dependent: in "simple or branched/forked" it denotes
    # unbranched (PATO:0000414), while in leaf morphology it can contrast with compound.
    # Do not choose either interpretation without a contextual rule.
    ("PATO_0001436", r"\bsessile(?:s)?\b"),
    # Organ caducous/persistent is not plant-level deciduous/non-deciduous.  No suitable atomic
    # PATO quality exists in the pinned release, so retain the text but do not auto-promote it.
    ("PATO_0000622", r"\bdress[ée](?:e?s?)?\b|\berect\b"),
]

ORGAN_OVERRIDES = {
    "habit": "PO_0000003",
    "tree": "PO_0000003",
    "shrub": "PO_0000003",
    "liana": "PO_0000003",
    "leaves": "PO_0009025",
    "leaf": "PO_0009025",
    "lamina": "PO_0020039",
    "flowers": "PO_0009046",
    "flower": "PO_0009046",
    "fruits": "PO_0009001",
    "fruit": "PO_0009001",
    "seeds": "PO_0009010",
    "seed": "PO_0009010",
    "stamens": "PO_0009029",
    "stamen": "PO_0009029",
    "anthers": "PO_0009066",
    "anther": "PO_0009066",
    "ovary": "PO_0009072",
    "petiole": "PO_0020038",
    "petals": "PO_0009032",
    "petal": "PO_0009032",
    "sepals": "PO_0009031",
    "sepal": "PO_0009031",
    "calyx": "PO_0009060",
    "corolla": "PO_0009059",
    "inflorescences": "PO_0009049",
    "inflorescence": "PO_0009049",
    # A bare pedicel heading does not establish that the organ is specifically an
    # inflorescence flower pedicel (PO:0009052).  Use the generic anatomical class;
    # narrower pedicel types require an explicit contextual bearer.
    "pedicels": "PO_0030112",
    "pedicel": "PO_0030112",
    "peduncle": "PO_0009053",
    "bracts": "PO_0009055",
    "bract": "PO_0009055",
    "bracteoles": "PO_0009043",
    "bracteole": "PO_0009043",
    "style": "PO_0009074",
    "stigma": "PO_0009073",
}

# Exact FDAC section headings are French, while the PO lexicon is predominantly English.  Keep
# these mappings closed and deliberately conservative: when a heading names a growth form, an
# inflorescence architecture, or a fruit type, use the broad bearer that is true of every member
# rather than committing the extracted quality to a narrow subtype.  More specific composition
# belongs in the contextual extractor and curation workflow.
_FDAC_WHOLE_PLANT_HEADINGS = {
    "annuelle",
    "arbre",
    "arbres",
    "arbrisseau",
    "arbrisseaux",
    "arbuste",
    "arbustes",
    "buisson",
    "frutex",
    "géofrutex",
    "grand arbre",
    "grand arbuste",
    "grande herbe",
    "grande liane",
    "grands arbustes",
    "grosse liane",
    "herbe",
    "herbes",
    "liane",
    "lianes",
    "petit arbre",
    "petit arbuste",
    "petite herbe",
    "petite liane",
    "petite plante",
    "plante",
    "plante annuelle",
    "plante herbacée",
    "plante vivace",
    "plantes",
    "port",
    "sous-arbrisseau",
    "sous-arbuste",
    "suffrutex",
    "vivace",
}

_FDAC_INFLORESCENCE_HEADINGS = {
    "capitule",
    "capitules",
    "cyme",
    "cymes",
    "cymules",
    "épis",
    "fascicules",
    "glomérule",
    "glomérules",
    "grappes",
    "ombelles",
    "panicule",
    "panicules",
    "pseudo-ombelles",
    "racème",
    "racèmes",
}

_FDAC_FRUIT_HEADINGS = {
    "akène",
    "akènes",
    "baies",
    "capsule",
    "capsules",
    "drupe",
    "drupes",
    "follicules",
    "gousses",
    "samares",
    "silicules",
    "siliques",
    "syncarpe",
    "tétradrupes",
}

FDAC_FRENCH_ORGAN_OVERRIDES = {
    **{heading: "PO_0000003" for heading in _FDAC_WHOLE_PLANT_HEADINGS},
    **{heading: "PO_0009049" for heading in _FDAC_INFLORESCENCE_HEADINGS},
    **{heading: "PO_0009001" for heading in _FDAC_FRUIT_HEADINGS},
    "drupe": "PO_0030103",
    "drupes": "PO_0030103",
    "follicules": "PO_0030105",
    "boutons": "PO_0000056",
    "bractées": "PO_0009055",
    "feuilles": "PO_0009025",
    "fleur": "PO_0009046",
    "fleurs": "PO_0009046",
    "fleurs chasmogames": "PO_0009046",
    "fleurs cleistogames": "PO_0009046",
    "folioles": "PO_0020049",
    "graine": "PO_0009010",
    "graines": "PO_0009010",
    "limbes": "PO_0020039",
    "méricarpe": "PO_0020075",
    "méricarpes": "PO_0020075",
    "ovaire": "PO_0009072",
    "périgone": "PO_0009058",
    "périgones": "PO_0009058",
    "plantule": "PO_0008037",
    "plantules": "PO_0008037",
    "rameaux": "PO_0025073",
    "ramilles": "PO_0025073",
    "sépales": "PO_0009031",
    "tige": "PO_0009047",
    "tiges": "PO_0009047",
    "tronc": "PO_0009047",
}

# Kew's Access export contains one treatment-wide ``description`` segment rather than FlorML
# organ-scoped blocks.  For that source the deterministic rehearsal can only make an assertion
# when a common bearer is explicit in the same sentence/semicolon-delimited clause as the cue.
# Keep this deliberately closed and conservative: the LLM extractor remains responsible for
# resolving less direct and nested botanical descriptions.
LOCAL_BEARER_CUES = [
    ("PO_0000056", r"\bflower\s+buds?\b"),
    ("PO_0009052", r"\binflorescence\s+flower\s+pedicels?\b"),
    ("PO_0030113", r"\bflower\s+pedicels?\b"),
    ("PO_0030114", r"\bfruit\s+pedicels?\b"),
    ("PO_0030107", r"\bachenes?\b"),
    ("PO_0030091", r"\bcapsules?\b"),
    ("PO_0030108", r"\bberries\b|\bberry\b"),
    ("PO_0020049", r"\bleaflets?\b"),
    # PO treats "leaf blade" as related rather than exactly synonymous with lamina;
    # only the unambiguous preferred term is automatically grounded here.
    ("PO_0020039", r"\blamina\b|\blaminae\b"),
    ("PO_0025060", r"\bblades?\b"),
    ("PO_0025073", r"\bbranches?\b|\bbranchlets?\b|\btwigs?\b"),
    ("PO_0009049", r"\binflorescences?\b"),
    ("PO_0009046", r"\bflowers?\b"),
    # Reviewed exact aliases are also recorded in config/reviewed_local_bearers.tsv so recovery
    # and logical passes can consume the same evidence instead of inheriting a broad heading.
    ("PO_0000013", r"\bfeuilles?\s+caulinaires?\b|\bcauline\s+leaves?\b"),
    ("PO_0009025", r"\bleaf\b(?!\s+blades?\b)|\bleaves\b"),
    ("PO_0009047", r"\bstems?\b|\btrunks?\b|\bboles?\b|\bculms?\b"),
    ("PO_0009005", r"\broots?\b"),
    ("PO_0009001", r"\bfruits?\b"),
    ("PO_0009010", r"\bseeds?\b"),
    ("PO_0009029", r"\bstamens?\b"),
    ("PO_0009066", r"\banthers?\b|\banth[èe]res?\b"),
    ("PO_0009072", r"\bovary\b|\bovaries\b"),
    ("PO_0020038", r"\bpetioles?\b"),
    ("PO_0009032", r"\bpetals?\b"),
    ("PO_0009031", r"\bsepals?\b"),
    ("PO_0009060", r"\bcalyces\b|\bcalyx\b"),
    ("PO_0009059", r"\bcorollas?\b"),
    ("PO_0030112", r"\bpedicels?\b"),
    ("PO_0009053", r"\bpeduncles?\b"),
    ("PO_0009055", r"\bbracts?\b"),
    ("PO_0009043", r"\bbracteoles?\b"),
    ("PO_0009074", r"\bstyles?\b"),
    ("PO_0009073", r"\bstigmas?\b|\bstigmata\b"),
    ("PO_0009030", r"\bcarpels?\b"),
    ("PO_0009067", r"\bfilaments?\b"),
    ("PO_0004518", r"\bbark\b"),
    ("PO_0004542", r"\brhizomes?\b|\brootstocks?\b"),
    ("PO_0020041", r"\bstipules?\b"),
    ("PO_0020055", r"\bleaf\s+rh?achis\b"),
    ("PO_0020122", r"\binflorescence\s+(?:axis|rh?achis)\b"),
    ("PO_0009058", r"\bperianths?\b"),
    ("PO_0009033", r"\btepals?\b"),
    ("PO_0009068", r"\bconnectives?\b"),
    ("PO_0009077", r"\bstaminodes?\b"),
    ("PO_0009084", r"\bpericarps?\b"),
    ("PO_0009085", r"\bexocarps?\b"),
    ("PO_0009088", r"\bseed\s+coats?\b"),
    ("PO_0009090", r"\barils?\b"),
    ("PO_0020060", r"\bcaruncles?\b"),
    ("PO_0020057", r"\btestas?\b"),
    ("PO_0025078", r"\bplacentas?\b"),
    ("PO_0025228", r"\bvalves?\b"),
    ("PO_0025281", r"\bpollen\b"),
    ("PO_0025359", r"\bsori\b|\bsorus\b"),
    ("PO_0000003", r"\bplants?\b|\btrees?\b|\bshrubs?\b|\bherbs?\b|\blianas?\b|\bvines?\b"),
    # Explicit French bearers occurring inside FDAC clauses.  These mirror the closed,
    # audited heading mappings above and allow a nearer organ to override a broad section
    # heading such as ``port`` or ``inflorescences``.
    ("PO_0000056", r"\bboutons?\b"),
    ("PO_0020049", r"\bfolioles?\b"),
    ("PO_0020039", r"\blimbes?\b"),
    ("PO_0025073", r"\brameaux\b|\bramilles?\b"),
    ("PO_0009049", r"\binflorescences?\b|\brac[eè]mes?\b|\bpanicules?\b|\bcymes?\b|\bcapitules?\b|\b[ée]pis\b"),
    ("PO_0009046", r"\bfleurs?\b"),
    ("PO_0009025", r"\bfeuilles?\b"),
    ("PO_0009047", r"\btiges?\b|\btroncs?\b"),
    ("PO_0030103", r"\bdrupes?\b"),
    ("PO_0030105", r"\bfollicules?\b"),
    ("PO_0009001", r"\bfruits?\b|\bgousses?\b|\bcapsules?\b|\bbaies?\b"),
    ("PO_0009010", r"\bgraines?\b"),
    ("PO_0009072", r"\bovaires?\b"),
    ("PO_0020038", r"\bp[ée]tioles?\b"),
    ("PO_0009032", r"\bp[ée]tales?\b"),
    ("PO_0009031", r"\bs[ée]pales?\b"),
    ("PO_0009060", r"\bcalices?\b"),
    ("PO_0009059", r"\bcorolles?\b"),
    ("PO_0009064", r"\br[ée]ceptacles?\b"),
    ("PO_0030112", r"\bp[ée]dicelles?\b"),
    ("PO_0009053", r"\bp[ée]doncules?\b"),
    ("PO_0009055", r"\bbract[ée]es?\b"),
    ("PO_0009043", r"\bbract[ée]oles?\b"),
    ("PO_0009074", r"\bstyles?\b"),
    ("PO_0009073", r"\bstigmates?\b"),
    ("PO_0009030", r"\bcarpelles?\b"),
    ("PO_0009067", r"\bfilets?\b"),
    ("PO_0020075", r"\bm[ée]ricarpes?\b"),
    ("PO_0009058", r"\bp[ée]rigones?\b"),
    ("PO_0008037", r"\bplantules?\b"),
    ("PO_0004518", r"\b[ée]corces?\b"),
    ("PO_0004542", r"\brhizomes?\b"),
    ("PO_0020041", r"\bstipules?\b"),
    ("PO_0009033", r"\bt[ée]pales?\b"),
    ("PO_0009068", r"\bconnectifs?\b"),
    ("PO_0009061", r"\bandroc[ée]es?\b"),
    ("PO_0009077", r"\bstaminodes?\b"),
    ("PO_0009084", r"\bp[ée]ricarpes?\b"),
    ("PO_0009085", r"\bexocarpes?\b"),
    ("PO_0009086", r"\bendocarpes?\b"),
    ("PO_0009087", r"\bm[ée]socarpes?\b"),
    ("PO_0009088", r"\bt[ée]guments?\s+de\s+la\s+graine\b"),
    ("PO_0009090", r"\barilles?\b"),
    ("PO_0025324", r"\b[ée]tendards?\b"),
    ("PO_0020057", r"\btestas?\b"),
    ("PO_0025078", r"\bplacentas?\b"),
    ("PO_0025228", r"\bvalves?\b"),
    ("PO_0025281", r"\bpollen\b"),
    ("PO_0025359", r"\bsores?\b"),
]

# These nested structures are safe only for a tightly scoped quality family.  For example,
# ``brown hairs`` licenses trichome colour, while ``hairs pubescent`` must not become "trichome
# pubescent".  A disallowed nearby contextual bearer blocks fallback to the section heading.
COLOR_PATO_IDS = frozenset({
    "PATO_0000317",
    "PATO_0000320",
    "PATO_0000322",
    "PATO_0000323",
    "PATO_0000324",
    "PATO_0000952",
})
SHAPE_PATO_IDS = frozenset({
    "PATO_0000946",
    "PATO_0000947",
    "PATO_0001199",
    "PATO_0001499",
    "PATO_0001877",
    "PATO_0001891",
    "PATO_0001935",
    "PATO_0001982",
    "PATO_0002228",
    "PATO_0005014",
})
CONTEXTUAL_BEARER_CUES = [
    ("PO_0020063", r"\bhilum\b|\bhila\b|\bhiles?\b", COLOR_PATO_IDS),
    ("PO_0000282", r"\bhairs?\b|\btrichomes?\b|\bpoils?\b", COLOR_PATO_IDS),
    ("PO_0025327", r"\bkeels?\b|\bcar[èe]nes?\b", COLOR_PATO_IDS),
]

# Context-dependent subparts/modifiers must not silently inherit the broad section bearer.  They
# remain unresolved until a dedicated contextual rule can select the correct PO class.
UNRESOLVED_BEARER_CUES = [
    r"\bleaf\s+blades?\b",
    r"\b(?:upper|lower|inner|outer|adaxial|abaxial)\s+"
    r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+\b|"
    r"\b(?:sup[ée]rieur|inf[ée]rieur|interne|externe)(?:e|es|s)?\s+"
    r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+\b",
    # These explicit nested/source bearers must block a broader section-heading fallback.
    # They require either a reviewed local alias/PO extension or an attachment expression.
    r"\brhizophores?\b|\bparois?\b|\bwalls?\b|\bsporocarpes?\b|\bsporocarps?\b|"
    r"\bpulp\b|\bpulpe\b|\baxes?\b|\baxis\b",
    r"\b(?:receptacle|r[ée]ceptacle|anthers?|anth[èe]res?)\s+"
    r"(?:(?:with|à)\s+)?(?:tubes?|thecae?|th[èe]ques?)\b",
    r"\b(?:at|near|towards?|vers|près\s+de)\s+(?:the\s+|du\s+|la\s+|l['’])?"
    r"(?:apex|base|tip|margin|sommet|marge)\b",
    r"\bveins?\b|\bveined\b|\bnerves?\b|\bnervures?\b|\bray[ée](?:e?s?)?\b|\bstriped\b",
    r"\blobes?\b|\bparaphyses?\b|\bacumens?\b|\blocules?\b|\bloges?\b|"
    r"\bsarcocarpes?\b|\bsarcocarps?\b|\bangles?\b|\barticles?\b|"
    r"\bscales?\b|\bpaillettes?\b|\bbristles?\b|\bawns?\b|\bar[êe]tes?\b|"
    r"\bdepressions?\b|\btest\b",
    r"\bmargins?\b|\bborders?\b|\bedges?\b|\bfringes?\b|\bfringed\b|\bfrang[ée](?:e?s?)?\b",
    r"\bthroats?\b|\bgorges?\b|\bcent(?:er|re)s?\b",
    r"\b(?:upper|lower)\s+(?:surfaces?|faces?)\b|\bfaces?\s+(?:sup[ée]rieures?|inf[ée]rieures?)\b",
    r"\btomentum\b|\bpubescence\b|\bvelours\b",
    r"\bspots?\b|\bspotted\b|\bpatch(?:es)?\b|\bblotches?\b|\bblotched\b|"
    r"\bstreaks?\b|\bbands?\b|\bmottl(?:e|ed|es|ing)\b|"
    r"\btaches?\b|\bbandes?\b|\bstries?\b|\bmouchet[ée](?:e?s?)?\b",
]


def _compile(cues: list[tuple[str, str]]) -> list[Cue]:
    return [Cue(pato, re.compile(pattern, re.IGNORECASE)) for pato, pattern in cues]


QUALITY_PATTERNS = _compile(QUALITY_CUES)
LOCAL_BEARER_PATTERNS = [
    (po_id, re.compile(pattern, re.IGNORECASE)) for po_id, pattern in LOCAL_BEARER_CUES
]
CONTEXTUAL_BEARER_PATTERNS = [
    (po_id, re.compile(pattern, re.IGNORECASE), allowed)
    for po_id, pattern, allowed in CONTEXTUAL_BEARER_CUES
]
UNRESOLVED_BEARER_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in UNRESOLVED_BEARER_CUES
]

QUALITY_FAMILY = {
    **{pato_id: "colour" for pato_id in COLOR_PATO_IDS},
    **{pato_id: "shape" for pato_id in SHAPE_PATO_IDS},
    **{
        pato_id: "pilosity"
        for pato_id in {"PATO_0000453", "PATO_0001320", "PATO_0002341"}
    },
}

# A source disjunction is a class description over values of an attribute, not two atomic
# assertions.  These PATO attribute-slim terms are the reusable traits under which the currently
# audited deterministic value cues can be combined.  The source OWL builder renders ``one_of`` as
# ``owl:unionOf``; it never mints the particular disjunction in FLOPO.
ATTRIBUTE_BY_FAMILY = {
    "colour": "PATO_0000014",
    "shape": "PATO_0000052",
    "pilosity": "PATO_0000066",
}

UNSUPPORTED_FAMILY_TERMS = {
    "colour": re.compile(
        r"(?:grey|gray|gris(?:e|es)?|orange|violet(?:te|tes)?|purple|blue|bleu(?:e|es)?|"
        r"pink|rose(?:s)?|cream(?:y)?|whitish|yellowish|greenish|reddish|brownish|blackish|"
        r"roux|rousse(?:s)?|bleu[âa]tre|cannelle|"
        r"saumon(?:é|ée|és|ées)|vermillon(?:ne|nes|s)?|"
        r"blanch[âa]tre|jaun[âa]tre|verd[âa]tre|rouge[âa]tre|brun[âa]tre|noir[âa]tre)",
        re.IGNORECASE,
    ),
    "shape": re.compile(
        r"(?:oval(?:e|es)?|ovoid|ovo[ïi]de|obovate|oboval(?:e|es)?|obovoid|"
        r"orbicular|lance-?ovate|ellipsoid)",
        re.IGNORECASE,
    ),
    "pilosity": re.compile(
        r"(?:hairy|hirsute|setose|pilose|villous|pub[ée]rulent(?:e|es)?|glabrescent)",
        re.IGNORECASE,
    ),
}


def _organ_to_po(organ: str) -> str:
    po_lex, _ = load_lexicons()
    key = (organ or "").strip().lower()
    if key in ORGAN_OVERRIDES:
        return ORGAN_OVERRIDES[key]
    if key in FDAC_FRENCH_ORGAN_OVERRIDES:
        return FDAC_FRENCH_ORGAN_OVERRIDES[key]
    return po_lex.ground(key) or po_lex.ground(key.rstrip("s")) or ""


def _span(text: str, match: re.Match[str]) -> str:
    # Strip only at the edges. Internal whitespace must remain verbatim so provenance checks can
    # always find this exact span in the source segment.
    return match.group(0).strip(" \t\r\n,;")


def _is_sentence_period(text: str, position: int) -> bool:
    """Return whether a period is a sentence boundary rather than a decimal/abbreviation."""

    if text[position] != ".":
        return False
    if (
        position > 0
        and position + 1 < len(text)
        and text[position - 1].isdigit()
        and text[position + 1].isdigit()
    ):
        return False
    following = position + 1
    while following < len(text) and text[following].isspace():
        following += 1
    return following >= len(text) or text[following].isupper()


def _clause_at(text: str, position: int) -> tuple[str, int]:
    """Return a semicolon/sentence clause without splitting decimals or ``cm. long``."""

    boundaries = [idx for idx, char in enumerate(text) if char == ";"]
    boundaries.extend(
        idx for idx, char in enumerate(text)
        if char == "." and _is_sentence_period(text, idx)
    )
    left = max((idx for idx in boundaries if idx < position), default=-1) + 1
    right = min((idx for idx in boundaries if idx >= position), default=len(text))
    return text[left:right], left


_MODALITY_ALIASES = {
    "frequency_qualifier": {
        "always": "universal",
        "invariably": "universal",
        "toujours": "universal",
        "usually": "usually",
        "generally": "usually",
        "typically": "usually",
        "normally": "usually",
        "mostly": "usually",
        "ordinarily": "usually",
        "most often": "usually",
        "almost always": "usually",
        "généralement": "usually",
        "generalement": "usually",
        "en général": "usually",
        "en general": "usually",
        "le plus souvent": "usually",
        "presque toujours": "usually",
        "often": "often",
        "frequently": "often",
        "commonly": "often",
        "souvent": "often",
        "fréquemment": "often",
        "frequemment": "often",
        "sometimes": "sometimes",
        "parfois": "sometimes",
        "occasionally": "occasionally",
        "occasionnellement": "occasionally",
        "rarely": "rarely",
        "seldom": "rarely",
        "rarement": "rarely",
    },
    "epistemic_modality": {
        "probably": "probable",
        "presumably": "probable",
        "probablement": "probable",
        "vraisemblablement": "probable",
        "sans doute": "probable",
        "possibly": "possible",
        "perhaps": "possible",
        "peut-être": "possible",
        "peut-etre": "possible",
        "possiblement": "possible",
        "reportedly": "reported",
    },
    "value_qualifier": {
        "nearly": "nearly",
        "almost": "almost",
        "presque": "almost",
        "more or less": "approximately",
        "plus ou moins": "approximately",
        "±": "approximately",
    },
    "degree_qualifier": {
        "slightly": "slightly",
        "légèrement": "slightly",
        "legerement": "slightly",
        "un peu": "slightly",
        "moderately": "moderately",
        "modérément": "moderately",
        "moderement": "moderately",
        "very": "very",
        "très": "very",
        "tres": "very",
        "extremely": "extremely",
        "extrêmement": "extremely",
        "extremement": "extremely",
        "completely": "completely",
        "entirely": "completely",
        "complètement": "completely",
        "completement": "completely",
    },
}


_QUALIFIER_BRIDGE = (
    r"(?:very|extremely|slightly|moderately|somewhat|rather|densely|sparsely|"
    r"très|tres|extrêmement|extremement|légèrement|legerement|modérément|moderement|"
    r"un\s+peu|assez|nettement|densément|densement|presque|nearly|almost|"
    r"completely|entirely|compl[èe]tement|±)"
)


def _preceding_alias(prefix: str, aliases: dict[str, str]) -> tuple[int, int, str] | None:
    """Return the closest qualifier that can govern the following trait cue."""

    candidates: list[tuple[int, int, int, int, str]] = []
    for alias, normalized in aliases.items():
        match = re.search(
            rf"(?<!\w)(?P<phrase>(?P<cue>{re.escape(alias)})(?!\w)"
            rf"(?:[\s\-–—]+{_QUALIFIER_BRIDGE}){{0,2}})[\s\-–—]*$",
            prefix,
            re.IGNORECASE,
        )
        if match:
            candidates.append(
                (
                    match.start("cue"),
                    match.end("cue"),
                    match.start("phrase"),
                    match.end("phrase"),
                    normalized,
                )
            )
    if not candidates:
        return None
    closest_end = max(item[1] for item in candidates)
    _cue_start, _cue_end, phrase_start, phrase_end, normalized = min(
        (item for item in candidates if item[1] == closest_end),
        key=lambda item: item[0],
    )
    return phrase_start, phrase_end, normalized


def _modality_context(text: str, position: int) -> tuple[dict[str, str], int, str]:
    """Extract orthogonal qualifier axes and their exact shared source phrase."""

    clause, left = _clause_at(text, position)
    prefix = clause[: position - left]
    fields: dict[str, str] = {}
    starts: list[int] = []
    ends: list[int] = []
    for field, aliases in _MODALITY_ALIASES.items():
        match = _preceding_alias(prefix, aliases)
        if match:
            local_start, local_end, normalized = match
            fields[field] = normalized
            starts.append(left + local_start)
            ends.append(left + local_end)
    if not starts:
        return fields, position, ""
    start = min(starts)
    end = max(ends)
    return fields, start, text[start:end]


_NAMED_SEASONS = (
    (
        "FLOPOANN:spring_season",
        re.compile(r"(?<!\w)(?:spring|printemps)(?!\w)", re.IGNORECASE),
    ),
    (
        "FLOPOANN:summer_season",
        re.compile(r"(?<!\w)(?:summer|été)(?!\w)", re.IGNORECASE),
    ),
    (
        "FLOPOANN:autumn_season",
        re.compile(r"(?<!\w)(?:autumn|automne)(?!\w)", re.IGNORECASE),
    ),
    (
        "FLOPOANN:winter_season",
        re.compile(r"(?<!\w)(?:winter|hiver)(?!\w)", re.IGNORECASE),
    ),
    (
        "FLOPOANN:wet_season",
        re.compile(
            r"(?<!\w)(?:wet season|rainy season|saison des pluies|saison pluvieuse)(?!\w)",
            re.IGNORECASE,
        ),
    ),
    (
        "FLOPOANN:dry_season",
        re.compile(r"(?<!\w)(?:dry season|saison sèche)(?!\w)", re.IGNORECASE),
    ),
    (
        "ENVO:03000097",
        re.compile(r"(?<!\w)(?:warm season|saison chaude)(?!\w)", re.IGNORECASE),
    ),
    (
        "ENVO:03000098",
        re.compile(r"(?<!\w)(?:cold season|saison froide)(?!\w)", re.IGNORECASE),
    ),
    (
        "ENVO:03000129",
        re.compile(r"(?<!\w)(?:monsoon season|saison de la mousson)(?!\w)", re.IGNORECASE),
    ),
)

_MONTHS = {
    "january": 1,
    "jan": 1,
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "mars": 3,
    "april": 4,
    "apr": 4,
    "avril": 4,
    "may": 5,
    "mai": 5,
    "june": 6,
    "jun": 6,
    "juin": 6,
    "july": 7,
    "jul": 7,
    "juillet": 7,
    "august": 8,
    "aug": 8,
    "août": 8,
    "aout": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "septembre": 9,
    "october": 10,
    "oct": 10,
    "octobre": 10,
    "november": 11,
    "nov": 11,
    "novembre": 11,
    "december": 12,
    "dec": 12,
    "décembre": 12,
    "decembre": 12,
}
_MONTH_TOKEN = "|".join(sorted((re.escape(name) for name in _MONTHS), key=len, reverse=True))
_MONTH_RANGE = re.compile(
    rf"(?<!\w)(?P<start>{_MONTH_TOKEN})\.?(?:\s*(?:[-–—]|to|through|à|au)\s*)"
    rf"(?P<end>{_MONTH_TOKEN})\.?(?!\w)",
    re.IGNORECASE,
)


def _season_context(
    text: str,
    trait_start: int,
    trait_end: int,
) -> tuple[list[dict[str, object]], str, int, int]:
    """Return nearby, same-clause season constraints without inferring hemisphere."""

    clause, left = _clause_at(text, trait_start)
    candidates: list[dict[str, object]] = []
    for season_term, pattern in _NAMED_SEASONS:
        for match in pattern.finditer(clause):
            if season_term == "FLOPOANN:summer_season" and match.group(0).lower() == "été":
                # French ``été`` is also the past participle of *être*.  Do not turn
                # ``a/ont été observé`` into a summer restriction.
                before = clause[max(0, match.start() - 16): match.start()]
                if re.search(
                    r"\b(?:a|as|avons|avez|ont|avait|avaient|fut|furent|est|sont|ayant)\s*$",
                    before,
                    re.IGNORECASE,
                ):
                    continue
            start, end = left + match.start(), left + match.end()
            distance = max(start - trait_end, trait_start - end, 0)
            if distance <= 96:
                candidates.append(
                    {
                        "season_term": season_term,
                        "season_text": text[start:end],
                        "start": start,
                        "end": end,
                        "temporal_relation": "present_during",
                        "_distance": distance,
                    }
                )
    for match in _MONTH_RANGE.finditer(clause):
        start, end = left + match.start(), left + match.end()
        distance = max(start - trait_end, trait_start - end, 0)
        if distance <= 96:
            candidates.append(
                {
                    "season_text": text[start:end],
                    "start": start,
                    "end": end,
                    "start_month": _MONTHS[match.group("start").lower()],
                    "end_month": _MONTHS[match.group("end").lower()],
                    "temporal_relation": "present_during",
                    "_distance": distance,
                }
            )
    candidates.sort(key=lambda row: (int(row["start"]), int(row["end"])))
    if not candidates:
        return [], "atomic", trait_start, trait_end

    operator = "atomic"
    selected = candidates
    if len(candidates) > 1:
        between = text[int(candidates[0]["end"]): int(candidates[-1]["start"])]
        connector = re.search(r"\b(or|ou|and|et)\b", between, re.IGNORECASE)
        residue = re.sub(
            r"\b(?:or|ou|and|et|in|during|pendant|en)\b|[\s,;/()\[\]-]+",
            "",
            between,
            flags=re.IGNORECASE,
        )
        if connector and not residue:
            operator = "one_of" if connector.group(1).lower() in {"or", "ou"} else "all_of"
        else:
            selected = [min(candidates, key=lambda row: int(row["_distance"]))]
    for row in selected:
        row.pop("_distance", None)
    return (
        selected,
        operator,
        min(trait_start, *(int(row["start"]) for row in selected)),
        max(trait_end, *(int(row["end"]) for row in selected)),
    )


def _in_disjunctive_clause(text: str, position: int) -> bool:
    """True when the local source clause states an explicit English/French alternative.

    The deterministic baseline cannot encode ``one_of`` composition.  Emitting either lexical
    component as an atomic assertion would turn a source disjunction into an asserted fact, so
    retain such clauses for the contextual extractor and curation queue instead.
    """
    clause, _ = _clause_at(text, position)
    # These are degree hedges, not logical alternatives.
    clause = re.sub(
        r"\bmore\s+or\s+less\b|\bplus\s+ou\s+moins\b",
        "",
        clause,
        flags=re.IGNORECASE,
    )
    # A disjunction between temporal contexts belongs to the season expression, not to the
    # phenotype value itself (``green in spring or summer``).
    season = (
        r"(?:spring|summer|autumn|winter|printemps|été|automne|hiver|"
        r"wet season|rainy season|dry season|saison des pluies|saison pluvieuse|saison sèche)"
    )
    clause = re.sub(
        rf"(?<!\w){season}(?:\s*(?:or|ou)\s*{season})+(?!\w)",
        "",
        clause,
        flags=re.IGNORECASE,
    )
    return re.search(r"\b(?:or|ou)\b", clause, re.IGNORECASE) is not None


_DISJUNCTION_SIDE_FILLER = re.compile(
    r"(?:"
    r"\s|[,()\[\]{}:;±+]|"
    r"\b(?:en|de|du|des|un|une|peu|tr[èe]s|l[ée]g[èe]rement|bri[èe]vement|"
    r"more|less|very|slightly|somewhat|nearly|almost)\b"
    r")+",
    re.IGNORECASE,
)

_DEGREE_OR_IDIOM = re.compile(
    r"\b(?:more\s+or\s+less|plus\s+ou\s+moins)\b",
    re.IGNORECASE,
)


def _clean_disjunction_gap(value: str) -> bool:
    """Return whether text between a value and ``or/ou`` is only harmless filler."""

    if not value:
        return True
    return not _DISJUNCTION_SIDE_FILLER.sub("", value).strip()


def _adjacent_disjunction(text: str, start: int, end: int) -> bool:
    """Detect an ``or/ou`` immediately attached to one side of a source span."""

    clause, left = _clause_at(text, start)
    local_start = start - left
    local_end = end - left
    before = _DEGREE_OR_IDIOM.sub("", clause[max(0, local_start - 40) : local_start])
    after = _DEGREE_OR_IDIOM.sub("", clause[local_end : min(len(clause), local_end + 40)])
    before_match = re.search(r"\b(?:or|ou)\b(?P<gap>[^.;:]*)$", before, re.IGNORECASE)
    after_match = re.match(r"(?P<gap>[^.;:]*?)\b(?:or|ou)\b", after, re.IGNORECASE)
    return bool(
        (before_match and _clean_disjunction_gap(before_match.group("gap")))
        or (after_match and _clean_disjunction_gap(after_match.group("gap")))
    )


def _quality_disjunction_groups(
    text: str,
    matches: list[tuple[Cue, re.Match[str], str]],
) -> list[list[tuple[Cue, re.Match[str], str]]]:
    """Group directly attached, grounded alternatives into source ``one_of`` assertions.

    Values must share both a bearer and a reviewed PATO attribute family.  This prevents a nearby
    alternative on a different subpart from being folded into the same class description.  A
    final comma-delimited value is included for lists such as ``red, white or yellow``.
    """

    ordered = sorted(matches, key=lambda row: (row[1].start(), row[1].end(), row[0].pato_id))
    edges: dict[int, set[int]] = {}

    def compatible(first: int, second: int) -> bool:
        left_row, right_row = ordered[first], ordered[second]
        left_family = QUALITY_FAMILY.get(left_row[0].pato_id, "")
        return bool(
            left_row[2]
            and left_row[2] == right_row[2]
            and left_family
            and left_family == QUALITY_FAMILY.get(right_row[0].pato_id, "")
            and left_family in ATTRIBUTE_BY_FAMILY
            and not _negated_or_hedged(text, left_row[1].start())
            and not _negated_or_hedged(text, right_row[1].start())
            and not _compound_edge(text, left_row[1])
            and not _compound_edge(text, right_row[1])
            and not _unsupported_family_neighbor(text, left_row[1], left_family)
            and not _unsupported_family_neighbor(text, right_row[1], left_family)
        )

    def connect(first: int, second: int) -> None:
        edges.setdefault(first, set()).add(second)
        edges.setdefault(second, set()).add(first)

    for connector in re.finditer(r"\b(?:or|ou)\b", text, re.IGNORECASE):
        idiom = next(
            (
                match
                for match in _DEGREE_OR_IDIOM.finditer(
                    text[max(0, connector.start() - 12) : connector.end() + 12]
                )
                if match.start() <= min(12, connector.start()) <= match.end()
            ),
            None,
        )
        if idiom:
            continue
        clause, clause_start = _clause_at(text, connector.start())
        clause_end = clause_start + len(clause)
        left_candidates = [
            index
            for index, (_cue, match, _po_id) in enumerate(ordered)
            if clause_start <= match.start() and match.end() <= connector.start()
        ]
        right_candidates = [
            index
            for index, (_cue, match, _po_id) in enumerate(ordered)
            if connector.end() <= match.start() < clause_end
        ]
        if not left_candidates or not right_candidates:
            continue
        left_index = left_candidates[-1]
        right_index = right_candidates[0]
        left_match = ordered[left_index][1]
        right_match = ordered[right_index][1]
        if not (
            _clean_disjunction_gap(text[left_match.end() : connector.start()])
            and _clean_disjunction_gap(text[connector.end() : right_match.start()])
            and compatible(left_index, right_index)
        ):
            continue
        connect(left_index, right_index)

        # Include preceding comma-list members that have the same bearer and attribute.
        cursor = left_index
        while cursor > 0:
            previous = cursor - 1
            separator = text[ordered[previous][1].end() : ordered[cursor][1].start()]
            if not re.fullmatch(r"\s*,\s*", separator) or not compatible(previous, cursor):
                break
            connect(previous, cursor)
            cursor = previous

    groups: list[list[tuple[Cue, re.Match[str], str]]] = []
    visited: set[int] = set()
    for root in sorted(edges):
        if root in visited:
            continue
        stack = [root]
        component: set[int] = set()
        while stack:
            index = stack.pop()
            if index in component:
                continue
            component.add(index)
            stack.extend(edges.get(index, ()))
        visited.update(component)
        values = [ordered[index] for index in sorted(component)]
        if len({row[0].pato_id for row in values}) >= 2:
            groups.append(values)
    return groups


def _adjacent_transition(text: str, match: re.Match[str]) -> bool:
    """Detect an alternative/range endpoint when its counterpart is not mapped.

    Looking only between two recognized PATO cues leaks cases such as ``elliptic or oval`` and
    ``yellow to orange``. Restrict this fallback to connectors immediately adjacent to the cue;
    broader attachment uses of ``to`` remain available to ordinary assertions.
    """

    clause, left = _clause_at(text, match.start())
    start = match.start() - left
    end = match.end() - left
    before = clause[max(0, start - 32) : start]
    after = clause[end : min(len(clause), end + 32)]
    connector = r"(?:or|ou|to|through|à|au)"
    return bool(
        re.search(rf"\b{connector}\s*$", before, re.IGNORECASE)
        or re.match(rf"^\s*{connector}\b", after, re.IGNORECASE)
    )


def _match_gap(
    match: re.Match[str],
    position: int,
    cue_end: int | None = None,
) -> tuple[int, int, int]:
    cue_end = position if cue_end is None else cue_end
    if match.end() <= position:
        return position - match.end(), 0, -len(match.group(0))
    if match.start() >= cue_end:
        return match.start() - cue_end, 1, -len(match.group(0))
    return 0, 0, -len(match.group(0))


def _local_bearer(
    text: str,
    position: int,
    default_po_id: str,
    pato_id: str = "",
    cue_end: int | None = None,
) -> str:
    """Return a nearby explicit bearer, or nothing when a treatment block is ambiguous.

    Search the sentence/semicolon clause containing the trait cue and select the closest explicit
    bearer mention.  Fall back to the FlorML/FDAC organ-heading prior only when the clause does not
    name a bearer.  This prevents a broad heading (for example ``habit`` or ``inflorescences``)
    from masking a nearer branch, bract, flower, or other nested organ, while retaining support
    for terse organ-scoped clauses.
    """
    clause, left = _clause_at(text, position)
    local_position = position - left
    local_end = (cue_end if cue_end is not None else position) - left
    candidates: list[tuple[int, int, int, int, str]] = []
    for po_id, pattern in LOCAL_BEARER_PATTERNS:
        for match in pattern.finditer(clause):
            gap, side, length = _match_gap(match, local_position, local_end)
            candidates.append((gap, 1, side, length, po_id))
    for po_id, pattern, allowed_pato_ids in CONTEXTUAL_BEARER_PATTERNS:
        for match in pattern.finditer(clause):
            resolved = po_id if pato_id in allowed_pato_ids else ""
            gap, side, length = _match_gap(match, local_position, local_end)
            candidates.append((gap, 0, side, length, resolved))
    for pattern in UNRESOLVED_BEARER_PATTERNS:
        for match in pattern.finditer(clause):
            gap, side, length = _match_gap(match, local_position, local_end)
            candidates.append((gap, 0, side, length, ""))
    if not candidates:
        return default_po_id
    selected = min(candidates)[-1]
    # ``blade`` is a safe PO lamina cue in ordinary leaf prose, but not in algal/fungal
    # constructions such as ``paraphyses with peltate blades``.  Those need a reviewed bearer.
    if selected == "PO_0025060" and re.search(r"(?<!\w)paraphyses?(?!\w)", clause, re.I):
        return ""
    return selected


def _negated_or_hedged(text: str, position: int) -> str:
    clause, left = _clause_at(text, position)
    prefix = clause[: position - left]
    if re.search(
        r"\b(?:resembl(?:e|es|ing)|similar\s+to|like|"
        r"(?:larger|smaller|longer|shorter|broader|narrower)\s+than|"
        r"ressembl(?:e|ant|ant\s+à)|comme|plus\s+[\wÀ-ÖØ-öø-ÿ'’-]+\s+que)\b",
        clause,
        re.IGNORECASE,
    ):
        return "comparative_context"
    if re.search(
        r"(?:\bnot|\bnever|\bno|\bwithout|\bnon|\bsans|\bni|\bpas|\bjamais)"
        r"(?:\s+|[-–—])(?:[\w'’-]+\s+){0,2}$",
        prefix,
        re.IGNORECASE,
    ) or re.search(r"\bne\b.{0,24}\bpas\b\s*$", prefix, re.IGNORECASE):
        return "negated_context"
    stage_clause = re.sub(
        r"\b(?:dry season|saison sèche)\b",
        "",
        clause,
        flags=re.IGNORECASE,
    )
    if re.search(
        r"\b(?:young(?:er|est)?|old(?:er|est)?|juvenile|immature|mature|"
        r"when\s+young|at\s+maturity|when\s+mature|when\s+dry|when\s+fresh|"
        r"drying|dried|later|eventually|becoming|"
        r"jeunes?|vieil(?:le|les)?|vieux|âg[ée](?:e?s?)?|"
        r"juv[ée]nile|immature|mature|m[ûu]r(?:e|es|s)?|sec|s[èe]che|"
        r"devenant|plus\s+tard|à\s+maturit[ée]|"
        r"lorsqu(?:e|'|\u2019)\s*jeune)\b",
        stage_clause,
        re.IGNORECASE,
    ):
        return "developmental_stage_context"
    return ""


_UNMODELLED_BEARER_CATEGORY = re.compile(
    r"(?<!\w)(?:♂|♀|male|female|staminate|pistillate|masculin(?:e|es|s)?|"
    r"m[âa]le(?:s)?|femelle(?:s)?|sterile|st[ée]rile(?:s)?|fertile(?:s)?)(?!\w)",
    re.IGNORECASE,
)


def _comma_member_at(text: str, position: int) -> tuple[str, int]:
    """Return one comma member without treating a French decimal comma as punctuation."""

    clause, left = _clause_at(text, position)
    local = position - left
    commas = [
        match.start()
        for match in re.finditer(",", clause)
        if not (
            match.start() > 0
            and match.end() < len(clause)
            and clause[match.start() - 1].isdigit()
            and clause[match.end()].isdigit()
        )
    ]
    member_left = max((offset for offset in commas if offset < local), default=-1) + 1
    member_right = min((offset for offset in commas if offset >= local), default=len(clause))
    return clause[member_left:member_right], left + member_left


def _unmodelled_bearer_category(text: str, position: int) -> bool:
    """Return whether the local bearer is restricted by an unencoded sex/category qualifier."""

    member, _left = _comma_member_at(text, position)
    if _UNMODELLED_BEARER_CATEGORY.search(member):
        return True
    # Flora descriptions also use a leading sex symbol (or a labelled ``male:``/``female:``
    # head) for every comma member in the clause.  The symbol is not repeated before each value.
    clause, _clause_left = _clause_at(text, position)
    return bool(
        re.match(
            r"^\s*(?:♂|♀|male|female|m[âa]le|femelle)\s*(?::|\s)",
            clause,
            re.IGNORECASE,
        )
    )


_UNSUPPORTED_NUMERIC_COMPARATOR = re.compile(
    r"(?:"
    r"(?<!\w)(?:more|less|greater|fewer)\s+than|"
    r"(?<!\w)at\s+(?:least|most)|"
    r"(?<!\w)(?:over|under|above|below)|"
    r"(?<!\w)(?:not\s+)?exceed(?:ing|s)?|"
    r"(?<!\w)(?:minimum|maximum)\s+of|"
    r"(?<!\w)(?:plus|moins)\s+de|"
    r"(?<!\w)au\s+(?:moins|plus)|"
    r"(?<!\w)(?:sup[ée]rieur|inf[ée]rieur)(?:e|es|s)?\s+[àa]|"
    r"[<>≤≥]"
    r")\s*$",
    re.IGNORECASE,
)


def _unsupported_numeric_comparator(text: str, position: int) -> bool:
    """Return whether a parsed number has an exclusive/otherwise unsupported bound."""

    return bool(
        _UNSUPPORTED_NUMERIC_COMPARATOR.search(text[max(0, position - 48) : position])
    )


def _compound_edge(text: str, match: re.Match[str]) -> bool:
    before = text[max(0, match.start() - 12) : match.start()]
    after = text[match.end() : min(len(text), match.end() + 12)]
    return bool(
        re.search(r"\w\s*[-–—/]\s*$", before)
        or re.search(r"\w\s*\(\s*[-–—/]\s*$", before)
        or re.match(r"^\s*[-–—/]\s*\w", after)
        or re.match(r"^\s*\(\s*[-–—/]\s*\w", after)
    )


def _connector_between(text: str, first: re.Match[str], second: re.Match[str]) -> str:
    left, right = sorted((first, second), key=lambda item: item.start())
    return text[left.end() : right.start()]


def _unsupported_family_neighbor(
    text: str,
    match: re.Match[str],
    family: str,
) -> bool:
    pattern = UNSUPPORTED_FAMILY_TERMS.get(family)
    if pattern is None:
        return False
    clause, left = _clause_at(text, match.start())
    start = match.start() - left
    end = match.end() - left
    before = clause[max(0, start - 36):start]
    after = clause[end:min(len(clause), end + 36)]
    joiner = r"(?:\s|,|[-–—/]|\b(?:and|et|or|ou|to|through|à|au)\b)*"
    return bool(
        re.search(rf"(?:{pattern.pattern}){joiner}$", before, re.IGNORECASE)
        or re.match(rf"^{joiner}(?:{pattern.pattern})\b", after, re.IGNORECASE)
    )


def _quality_context_reason(
    text: str,
    cue: Cue,
    match: re.Match[str],
    po_id: str,
    matches: list[tuple[Cue, re.Match[str], str]],
) -> str:
    if _unmodelled_bearer_category(text, match.start()):
        return "unmodelled_bearer_category"
    contextual = _negated_or_hedged(text, match.start())
    if contextual:
        return contextual
    if _compound_edge(text, match):
        return "hyphenated_or_slash_compound"
    if _adjacent_disjunction(text, match.start(), match.end()):
        return "explicit_disjunction"
    if _adjacent_transition(text, match):
        return "unsupported_alternative_or_transition"
    if _cross_comma_value_alternative(text, match.end()):
        return "explicit_disjunction"
    clause, clause_start = _clause_at(text, match.start())
    clause_end = clause_start + len(clause)
    family = QUALITY_FAMILY.get(cue.pato_id, "")
    if family and _unsupported_family_neighbor(text, match, family):
        return "unsupported_same_attribute_neighbor"
    for other_cue, other, other_po_id in matches:
        if other is match or other_po_id != po_id:
            continue
        if not clause_start <= other.start() < clause_end:
            continue
        connector = _connector_between(text, match, other)
        connector_match = re.fullmatch(
            r"(?:\s|[,()\[\]{}:;±+])*\b(?:or|ou)\b"
            r"(?:\s|[,()\[\]{}:;±+])*",
            connector,
            re.IGNORECASE,
        )
        if connector_match:
            return "explicit_disjunction"
        if (
            family
            and QUALITY_FAMILY.get(other_cue.pato_id) == family
            and (
                re.search(r"\b(?:to|through|and|et|à|au)\b|/", connector, re.IGNORECASE)
                or not connector.strip(" \t\r\n,()[]")
            )
        ):
            return "same_attribute_composite_or_transition"
    return ""


def _cross_comma_value_alternative(text: str, end: int) -> bool:
    """Detect an immediate alternative in the next comma member.

    This covers source lists whose alternative terms are not yet all present in the deterministic
    PATO lexicon, such as ``ovate, triangular or subhastate``.  The first recognized value must not
    escape as an atomic assertion merely because the comma delimits the local phrase.
    """

    suffix = text[end : min(len(text), end + 96)]
    if re.match(
        r"^\s*,\s*(?:more\s+or\s+less|plus\s+ou\s+moins)(?!\w)",
        suffix,
        re.IGNORECASE,
    ):
        return False
    return bool(
        re.match(
            r"^\s*,\s*(?:\([^)]{1,24}\)\s*)?"
            r"[A-Za-zÀ-ÖØ-öø-ÿ'’–-]+"
            r"(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ'’–-]+){0,3}\s+"
            r"(?:or|ou)\s+[A-Za-zÀ-ÖØ-öø-ÿ'’–-]+",
            suffix,
            re.IGNORECASE,
        )
    )


def _unresolved(
    source: str,
    start: int,
    end: int,
    reason: str,
    pato_id: str,
) -> dict:
    return {
        "start": start,
        "end": end,
        "surface_form": source,
        "reason": reason,
        "candidate_pato_id": pato_id,
        "extractor": "deterministic_baseline",
    }


def extract_segment_with_unresolved(
    obj: dict,
    max_assertions: int | None = None,
) -> tuple[list[dict], list[dict]]:
    default_po_id = _organ_to_po(obj.get("organ", ""))
    text = obj.get("text", "")
    assertions = []
    unresolved: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for measurement in parse_measurements(text, obj.get("language", "")):
        reason = ""
        if _unmodelled_bearer_category(text, measurement.start):
            reason = "unmodelled_bearer_category"
        elif _unsupported_numeric_comparator(text, measurement.start):
            reason = "unsupported_numeric_comparator"
        else:
            reason = _negated_or_hedged(text, measurement.start)
        if not reason and _adjacent_disjunction(text, measurement.start, measurement.end):
            reason = "explicit_disjunction"
        if reason:
            unresolved.append(_unresolved(
                measurement.source_text,
                measurement.start,
                measurement.end,
                reason,
                measurement.attribute_id,
            ))
            continue
        po_id = _local_bearer(
            text,
            measurement.start,
            default_po_id,
            measurement.attribute_id,
            measurement.end,
        )
        if not po_id:
            unresolved.append(_unresolved(
                measurement.source_text,
                measurement.start,
                measurement.end,
                "missing_or_unsupported_bearer",
                measurement.attribute_id,
            ))
            continue
        qualifier_fields, qualifier_start, qualifier_text = _modality_context(
            text, measurement.start
        )
        seasons, season_operator, season_start, season_end = _season_context(
            text, measurement.start, measurement.end
        )
        source_start = min(measurement.start, qualifier_start, season_start)
        source_end = max(measurement.end, season_end)
        source = text[source_start:source_end]
        key = (po_id, measurement.attribute_id, source.lower())
        if key in seen:
            continue
        seen.add(key)
        assertion = {
            "po_id": po_id,
            "pato_id": measurement.attribute_id,
            "negated": False,
            "organ": obj.get("organ", ""),
            "source_text": source,
            "source_start": source_start,
            "source_end": source_end,
            "value_low": measurement.value_low,
            "value_high": measurement.value_high,
            "value_low_inclusive": measurement.value_low_inclusive,
            "value_high_inclusive": measurement.value_high_inclusive,
            "unit": measurement.unit_text,
            "modifier": measurement.modifier,
            "value_qualifier": (
                "approximately" if measurement.modifier == "approximately" else "exact"
            ),
            "modality_text": qualifier_text or measurement.modifier_text,
            "season_contexts": seasons,
            "season_operator": season_operator,
            "value_text": "",
            "extractor": "deterministic_measurement",
            **qualifier_fields,
        }
        if qualifier_text and measurement.modifier_text:
            modality_end = measurement.start + len(measurement.modifier_text)
            assertion["modality_text"] = text[qualifier_start:modality_end]
        assertions.append(assertion)
        if max_assertions is not None and len(assertions) >= max_assertions:
            return assertions, unresolved
    quality_matches = [
        (
            cue,
            match,
            _local_bearer(text, match.start(), default_po_id, cue.pato_id, match.end()),
        )
        for cue in QUALITY_PATTERNS
        for match in cue.pattern.finditer(text)
    ]
    consumed_disjunction_matches: set[int] = set()
    for group in _quality_disjunction_groups(text, quality_matches):
        first_match = group[0][1]
        last_match = group[-1][1]
        # A disjunction over a sex/category-restricted bearer needs that restriction in its class
        # description.  Let the atomic loop retain each grounded span until the bearer expression
        # can encode it; do not emit a disjunction over the unqualified generic organ.
        if _unmodelled_bearer_category(text, first_match.start()):
            continue
        family = QUALITY_FAMILY[group[0][0].pato_id]
        po_id = group[0][2]
        value_terms = list(dict.fromkeys(row[0].pato_id for row in group))
        qualifier_fields, qualifier_start, qualifier_text = _modality_context(
            text, first_match.start()
        )
        seasons, season_operator, season_start, season_end = _season_context(
            text, first_match.start(), last_match.end()
        )
        source_start = min(first_match.start(), qualifier_start, season_start)
        source_end = max(last_match.end(), season_end)
        source = text[source_start:source_end]
        key = (po_id, ATTRIBUTE_BY_FAMILY[family], source.lower())
        if key in seen:
            continue
        seen.add(key)
        assertions.append({
            "po_id": po_id,
            "pato_id": ATTRIBUTE_BY_FAMILY[family],
            "negated": False,
            "organ": obj.get("organ", ""),
            "source_text": source,
            "source_start": source_start,
            "source_end": source_end,
            "value_text": text[first_match.start() : last_match.end()],
            "value_operator": "one_of",
            "value_terms": value_terms,
            "modality_text": qualifier_text,
            "season_contexts": seasons,
            "season_operator": season_operator,
            "normalization_status": "compositional",
            "mapping_provenance": ["deterministic_disjunction_parse"],
            "extractor": "deterministic_baseline",
            **qualifier_fields,
        })
        consumed_disjunction_matches.update(id(row[1]) for row in group)
        if max_assertions is not None and len(assertions) >= max_assertions:
            return assertions, unresolved
    for cue, match, po_id in quality_matches:
        if id(match) in consumed_disjunction_matches:
            continue
        reason = _quality_context_reason(text, cue, match, po_id, quality_matches)
        if not po_id and not reason:
            reason = "missing_or_unsupported_bearer"
        if reason:
            unresolved.append(_unresolved(
                _span(text, match), match.start(), match.end(), reason, cue.pato_id
            ))
            continue
        qualifier_fields, qualifier_start, qualifier_text = _modality_context(
            text, match.start()
        )
        seasons, season_operator, season_start, season_end = _season_context(
            text, match.start(), match.end()
        )
        source_start = min(match.start(), qualifier_start, season_start)
        source_end = max(match.end(), season_end)
        source = text[source_start:source_end]
        if not source:
            continue
        key = (po_id, cue.pato_id, source.lower())
        if key in seen:
            continue
        seen.add(key)
        assertions.append({
            "po_id": po_id,
            "pato_id": cue.pato_id,
            "negated": False,
            "organ": obj.get("organ", ""),
            "source_text": source,
            "source_start": source_start,
            "source_end": source_end,
            "modality_text": qualifier_text,
            "season_contexts": seasons,
            "season_operator": season_operator,
            "extractor": "deterministic_baseline",
            **qualifier_fields,
        })
        if max_assertions is not None and len(assertions) >= max_assertions:
            return assertions, unresolved
    return assertions, unresolved


def extract_segment(obj: dict, max_assertions: int | None = None) -> list[dict]:
    assertions, _ = extract_segment_with_unresolved(obj, max_assertions=max_assertions)
    return assertions


def run_file(
    input_path: Path,
    out_path: Path,
    limit: int | None = None,
    max_assertions: int | None = None,
) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    segments = 0
    with_assertions = 0
    assertion_count = 0
    by_pato: Counter[str] = Counter()
    unresolved_count = 0
    unresolved_reasons: Counter[str] = Counter()
    source_positions: Counter[tuple[str, str]] = Counter()
    with Path(input_path).open(encoding="utf-8") as inp, out_path.open("w", encoding="utf-8") as out:
        for line in inp:
            if limit is not None and segments >= limit:
                break
            if not line.strip():
                continue
            obj = json.loads(line)
            source_key = (obj.get("source", ""), obj.get("source_id", ""))
            obj.setdefault("source_segment_index", source_positions[source_key])
            source_positions[source_key] += 1
            assertions, unresolved = extract_segment_with_unresolved(
                obj, max_assertions=max_assertions
            )
            rec = dict(obj)
            rec["assertions"] = assertions
            rec["unresolved_spans"] = unresolved
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            segments += 1
            if assertions:
                with_assertions += 1
                assertion_count += len(assertions)
                by_pato.update(a["pato_id"] for a in assertions)
            unresolved_count += len(unresolved)
            unresolved_reasons.update(row["reason"] for row in unresolved)
    return {
        "segments": segments,
        "segments_with_assertions": with_assertions,
        "assertions": assertion_count,
        "unresolved_spans": unresolved_count,
        "unresolved_reasons": dict(sorted(unresolved_reasons.items())),
        "top_pato": by_pato.most_common(12),
        "out": str(out_path),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Deterministic baseline extraction for rehearsals.")
    ap.add_argument("input", type=Path, help="ingested TextSegment JSONL")
    ap.add_argument("-o", "--out", type=Path, default=Path("scratchpad/baseline_assertions.jsonl"))
    ap.add_argument("--limit", type=int)
    ap.add_argument(
        "--max-assertions",
        type=int,
        help="optional per-segment safety cap (default: retain every supported assertion)",
    )
    args = ap.parse_args()
    if args.max_assertions is not None and args.max_assertions < 1:
        ap.error("--max-assertions must be positive")
    print(json.dumps(
        run_file(args.input, args.out, args.limit, args.max_assertions),
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
