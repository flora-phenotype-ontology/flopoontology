"""Deterministic recovery of residual head-bearer ``explicit_disjunction`` value unions.

Residual target
---------------
After the v1/v2 explicit-union passes (:mod:`recover_explicit_unions`,
:mod:`recover_explicit_unions_v2`), the Opus logical-operand pass, and the machine-reviewed
one-of campaign (:mod:`recover_llm_one_of_expressions`), 27,861 ``explicit_disjunction`` spans
remain.  Re-running the v2 decision procedure over the stage-22 corpus shows why: 33,063 of its
connector edges fail as ``ungrounded_operand`` because v2 grounds operands *only* from baseline
``candidate_pato_id`` target spans (a 25-cue vocabulary).  The partner of a flagged value is very
often an ordinary PATO value outside that cue list (``white or pink``, ``hairy or glabrous``,
``sessiles ou pédicellées``, ``bleues ou violettes``).

This module targets that residue with a *closed, reviewed* bilingual (EN/FR) value table whose
every identifier exists in ``config/pato_lexicon.tsv`` and a *strict clause-head bearer* rule:

* The union is a maximal comma/``or``/``ou`` coordination whose every member is exactly one
  table value (no degree modifier, no compound, no parenthesis).  A non-first member may carry a
  frequency hedge (``or rarely pubescent``); it is still a stated alternative of the union.
* All operands share one reviewed character sub-family (colour, pilosity, texture, erectness,
  attachment, branchiness, outline, solid shape, curvature) and PATO 2-D/3-D dimensions do not mix
  (the guard adopted by the v2 correction pass).
* The union is source-exhaustive: no other value of the same sub-family (from the table or from a
  broad "unsupported same-family" cue list, e.g. ``whitish``, ``pilose``, ``ovale``) occurs
  anywhere else in the clause, and the member left of the coordination is a measurement, a value
  of another family, or the head itself.
* The bearer is the clause-initial organ noun (Kew ``Petals white or pink``, FDAC ``Fleurs
  sessiles ou pédicellées``) from the audited baseline local-bearer cues plus the reviewed
  ``config/reviewed_local_bearers.tsv`` aliases.  Everything between the head and the union must
  be measurements or adjectival members; any other noun, preposition, colon or parenthesis
  blocks.  Generic lamina/limb heads are accepted only inside leaf-scoped records.
* The clause must not carry developmental, transitional, locative-scope, comparative, negation
  or uncertainty cues (these are other categories' residuals).

Outputs are a DELTA (one line per touched segment) plus a data-model validation of the patched
corpus; the input corpus is never modified.  No identifier is minted: bearers are PO classes,
values are PATO ``value_slim`` classes, the top-level quality is the reviewed ``attribute_slim``
root, and the class description is the stable FAC IRI computed by
:func:`flopo2.owl.annotation_class.ensure_annotation_class_iri`.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from flopo2.annotation.operands import make_operand, parse_qualifier_cue
from flopo2.annotation.provenance import FREQUENCY_ALIASES, ensure_source_statements
from flopo2.extract import baseline
from flopo2.extract.leaflet_context import leaflet_bearer
from flopo2.owl.annotation_class import ensure_annotation_class_iri
from flopo2.verify.gates import (
    check_assertion,
    load_catalog_ids,
    load_combinations,
    load_eq_registry,
    load_flopo_ids,
    load_pato_attribute_terms,
    load_signature_registry,
)
from flopo2.verify.local_bearer_table import load_reviewed_bearers

TARGET_REASON = "explicit_disjunction"
EXTRACTOR = "claude_explicit_disjunction_head_union_v1"

# --------------------------------------------------------------------------------------------- #
# Closed value table.  (pato_id, sub-family, PATO 2d/3d dimension or "").
# Sub-families are narrower than the v2 character families so that, e.g., leaf outline and apex
# shape can never be united.  Apex/base and margin shapes are deliberately absent: in flora prose
# they attach to an apex/base/margin subpart, not to the clause-head organ.
# --------------------------------------------------------------------------------------------- #

ATTRIBUTE_BY_SUBFAMILY = {
    "colour": "PATO_0000014",
    "pilosity": "PATO_0000066",
    "texture": "PATO_0000150",
    "erectness": "PATO_0000140",
    "attachment": "PATO_0001435",
    "branchiness": "PATO_0002009",
    "outline": "PATO_0000052",
    "solid": "PATO_0000052",
    "curvature": "PATO_0000052",
}

_V: dict[str, tuple[str, str]] = {}


def _add(pato_id: str, subfamily: str, *forms: str) -> None:
    for form in forms:
        key = _norm(form)
        if key in _V and _V[key] != (pato_id, subfamily):
            raise ValueError(f"conflicting value form {form!r}")
        _V[key] = (pato_id, subfamily)


def _norm(value: str) -> str:
    return re.sub(r"[\s\-‐–—]+", " ", value.casefold()).strip()


def _fr(stem: str, endings: Iterable[str]) -> list[str]:
    return [stem + ending for ending in endings]


_ADJ_E = ("", "e", "s", "es")  # vert/verte/verts/vertes
_ADJ_EE = ("é", "ée", "és", "ées")  # dressé/dressée/...
_ADJ_S = ("", "s")  # jaune/jaunes
_ADJ_EUX = ("eux", "euse", "euses")

# colour ------------------------------------------------------------------------------------
_add("PATO_0000323", "colour", "white", *_fr("blanc", ("", "he", "hes", "s")))
_add("PATO_0000324", "colour", "yellow", *_fr("jaune", _ADJ_S))
_add("PATO_0000322", "colour", "red", *_fr("rouge", _ADJ_S))
_add("PATO_0000320", "colour", "green", *_fr("vert", _ADJ_E))
_add("PATO_0000952", "colour", "brown", *_fr("brun", _ADJ_E))
_add("PATO_0000317", "colour", "black", *_fr("noir", _ADJ_E))
_add("PATO_0000954", "colour", "pink", *_fr("rose", _ADJ_S))
_add("PATO_0000951", "colour", "purple", *_fr("pourpre", _ADJ_S))
_add("PATO_0000953", "colour", "orange", "oranges", *_fr("orang", _ADJ_EE))
_add("PATO_0000318", "colour", "blue", *_fr("bleu", _ADJ_E))
_add("PATO_0000950", "colour", "grey", "gray", "gris", "grise", "grises")
_add("PATO_0001424", "colour", "violet", "violets", "violette", "violettes")
_add("PATO_0104031", "colour", "cream", "creamy", "crème", "crèmes")
_add("PATO_0104314", "colour", "crimson")
_add("PATO_0104317", "colour", "scarlet", "écarlate", "écarlates")
_add("PATO_0000321", "colour", "magenta")
_add("PATO_0001943", "colour", "lilac", "lilas")
_add("PATO_0001426", "colour", "maroon")
_add("PATO_0001287", "colour", "reddish brown", "reddish-brown", "red-brown", "red brown")
_add("PATO_0001245", "colour", "dark brown")
_add("PATO_0001246", "colour", "light brown")
_add("PATO_0001268", "colour", "pale brown")
_add("PATO_0001249", "colour", "dark green")
_add("PATO_0001250", "colour", "light green")
_add("PATO_0001272", "colour", "pale green")
_add("PATO_0001286", "colour", "pale yellow")
_add("PATO_0001264", "colour", "light yellow")
_add("PATO_0001261", "colour", "dark red")
_add("PATO_0001259", "colour", "dark purple")
_add("PATO_0104067", "colour", "greenish white", "greenish-white")
_add("PATO_0104013", "colour", "greenish yellow", "greenish-yellow")
_add("PATO_0104114", "colour", "yellowish green", "yellowish-green")
_add("PATO_0104059", "colour", "pinkish white", "pinkish-white")
_add("PATO_0104311", "colour", "purplish red", "purplish-red")
_add("PATO_0104079", "colour", "reddish purple", "reddish-purple")
_add("PATO_0104157", "colour", "purplish black", "purplish-black")
_add("PATO_0001941", "colour", "yellow-green", "yellow green")
_add("PATO_0001944", "colour", "yellow-orange", "yellow orange")
_add("PATO_0104112", "colour", "orange-red", "orange red")
_add("PATO_0104054", "colour", "orange-yellow", "orange yellow")
_add("PATO_0104007", "colour", "grey-green", "gray-green", "greyish green", "grayish green")
_add("PATO_0002411", "colour", "yellow-brown", "yellow brown")
# pilosity ----------------------------------------------------------------------------------
_add("PATO_0000453", "pilosity", "glabrous", "glabre", "glabres")
_add("PATO_0001320", "pilosity", "pubescent", *_fr("pubescent", _ADJ_E))
_add("PATO_0002341", "pilosity", "tomentose", *_fr("tomenteu", ("x", "se", "ses")))
_add("PATO_0000454", "pilosity", "hairy", *_fr("poilu", _ADJ_E))
_add("PATO_0002339", "pilosity", "hispid", "hispide", "hispides")
_add("PATO_0002340", "pilosity", "hispidulous")
_add("PATO_0002289", "pilosity", "setose")
_add("PATO_0104041", "pilosity", "velutinous", "velvety", *_fr("velout", _ADJ_EE))
# texture -----------------------------------------------------------------------------------
_add("PATO_0000701", "texture", "smooth", "lisse", "lisses")
_add("PATO_0000700", "texture", "rough", *_fr("rugu", _ADJ_EUX))
_add("PATO_0104032", "texture", "coriaceous", "leathery", "coriace", "coriaces")
_add(
    "PATO_0104010",
    "texture",
    "chartaceous",
    "papery",
    "papyraceous",
    *_fr("papyrac", _ADJ_EE),
    *_fr("chartac", _ADJ_EE),
    *_fr("cartac", _ADJ_EE),
)
_add("PATO_0001810", "texture", "wrinkled")
_add("PATO_0001804", "texture", "scaly")
# erectness (PATO position family) ---------------------------------------------------------
_add("PATO_0000622", "erectness", "erect", "upright", *_fr("dress", _ADJ_EE))
_add("PATO_0000631", "erectness", "prostrate")
_add("PATO_0002343", "erectness", "decumbent")
_add("PATO_0104035", "erectness", "pendent")
_add("PATO_0002389", "erectness", "procumbent")
# attachment --------------------------------------------------------------------------------
_add("PATO_0001436", "attachment", "sessile", "sessiles")
_add("PATO_0001438", "attachment", "pedicellate", *_fr("pédicell", _ADJ_EE))
# branchiness -------------------------------------------------------------------------------
_add("PATO_0000402", "branchiness", "branched", *_fr("ramifi", _ADJ_EE))
_add("PATO_0000414", "branchiness", "unbranched")
# 2-D outline (dimension decided from PATO below) -------------------------------------------
_add("PATO_0000947", "outline", "elliptic", "elliptical", "elliptique", "elliptiques")
_add("PATO_0000946", "outline", "oblong", *_fr("oblong", ("ue", "s", "ues")))
_add("PATO_0001891", "outline", "ovate", *_fr("ov", _ADJ_EE))
_add("PATO_0001936", "outline", "obovate", *_fr("obov", _ADJ_EE))
_add("PATO_0001877", "outline", "lanceolate", *_fr("lancéol", _ADJ_EE))
_add("PATO_0002330", "outline", "oblanceolate", *_fr("oblancéol", _ADJ_EE))
_add("PATO_0001199", "outline", "linear", "linéaire", "linéaires")
_add("PATO_0001934", "outline", "orbicular", "orbiculaire", "orbiculaires")
_add("PATO_0001937", "outline", "spathulate", "spatulate", *_fr("spatul", _ADJ_EE))
_add("PATO_0001875", "outline", "triangular", "deltoid", "triangulaire", "triangulaires")
_add("PATO_0001871", "outline", "reniform", "réniforme", "réniformes")
_add("PATO_0001938", "outline", "rhomboid")
_add("PATO_0001954", "outline", "subulate", *_fr("subul", _ADJ_EE))
_add("PATO_0000411", "outline", "circular", "circulaire", "circulaires")
# 3-D solid shape ---------------------------------------------------------------------------
_add("PATO_0001499", "solid", "globose", "globular", "spherical", *_fr("globul", _ADJ_EUX))
_add("PATO_0005014", "solid", "subglobose", "subspherical", *_fr("subglobul", _ADJ_EUX))
_add("PATO_0001873", "solid", "cylindrical", "cylindrique", "cylindriques")
_add("PATO_0002226", "solid", "subcylindrical", "subcylindrique", "subcylindriques")
_add("PATO_0002400", "solid", "fusiform", "fusiforme", "fusiformes")
_add("PATO_0001883", "solid", "clavate", "club-shaped")
_add("PATO_0002021", "solid", "conical", "conique", "coniques")
_add("PATO_0002347", "solid", "obconical", "obconique", "obconiques")
# curvature ---------------------------------------------------------------------------------
_add("PATO_0002180", "curvature", "straight")
_add("PATO_0000406", "curvature", "curved", *_fr("courb", _ADJ_EE))
_add("PATO_0002211", "curvature", "recurved")

VALUE_TABLE: dict[str, tuple[str, str]] = dict(_V)

# ``ovate``/``obovate`` inherit PATO convex 3-D shape while ``elliptic``/``oblong`` are 2-D; the
# v2 correction pass quarantined unions that mix the two, and so does this pass.
DIMENSION = {
    "PATO_0000947": "2d",
    "PATO_0000946": "2d",
    "PATO_0001934": "2d",
    "PATO_0001937": "2d",
    "PATO_0001875": "2d",
    "PATO_0001938": "2d",
    "PATO_0000411": "2d",
    "PATO_0001891": "3d",
    "PATO_0001936": "3d",
    "PATO_0001499": "3d",
    "PATO_0005014": "3d",
    "PATO_0001873": "3d",
    "PATO_0002226": "3d",
    "PATO_0002400": "3d",
    "PATO_0002021": "3d",
    "PATO_0002347": "3d",
}

# Broad same-family cues that are *not* table values.  Their presence elsewhere in the clause
# means a stated alternative would be dropped (or a second, sub-part-scoped list exists).
UNSUPPORTED_SAME_FAMILY = {
    "colour": re.compile(
        r"\w+(?:ish|âtre|âtres)\b|\b(?:colou?r(?:ed|s)?|couleur|tinged|teint[ée]e?s?|"
        r"mauve|ochre|ochraceous|fulvous|rufous|ferrugineous|ferruginous|stramineous|"
        r"straw|olive|olivaceous|glaucous|hyaline|translucent|purpurescent|roux|rousses?|"
        r"fauves?|ivoire|carmin|vermillon\w*|bordeaux|saumon\w*|cannelle|ros[ée]e?s?|"
        r"pourpr\w+|blanc\w*|jaun\w*|verd\w*|argent\w*|silvery|golden|dor[ée]e?s?|"
        r"spotted|mottled|variegated|striped|tach\w+|panach\w+|lined|veined|dark|pale|"
        r"light|bright|deep|dull|fonc[ée]e?s?|clair\w*|p[âa]le\w*|vif|vive)\b",
        re.IGNORECASE,
    ),
    "pilosity": re.compile(
        r"\b(?:pilose|pilosulous|pileu\w*|villous|villose|velu\w*|puberul\w*|pub[ée]rul\w*|"
        r"hirsut\w*|hirtell\w*|strigos\w*|strigu\w*|sericeous|soyeu\w*|glabresc\w*|"
        r"glabrate|subglab\w*|tomentell\w*|tomentul\w*|lanate|lanug\w*|floccose|"
        r"arachno\w*|aranéeu\w*|scabr\w*|scabrid\w*|ciliat\w*|cili[ée]e?s?|hairs?|"
        r"poils?|indument\w*|pubescence|tomentum|setul\w*|sétul\w*|stellate|"
        r"lepidot\w*|glandul\w*|papill\w*|hispidul\w*|barbu\w*|bearded|woolly|laineu\w*|"
        r"farinose|furfurac\w*|pruin\w*|scal[ey]\w*|écailles?)\b",
        re.IGNORECASE,
    ),
    "texture": re.compile(
        r"\b(?:membran\w*|herbac\w*|succulent\w*|charnu\w*|fleshy|woody|ligneu\w*|"
        r"subcoriac\w*|papyrac\w*|rugos\w*|rugul\w*|verruc\w*|tubercul\w*|striat\w*|"
        r"stri[ée]e?s?|ridged|shin\w*|glossy|lustrous|luisant\w*|brillant\w*|mat|dull|"
        r"coriac\w*|scabr\w*|rough\w*|smooth\w*|crustac\w*|cartilag\w*|spongy|corky|"
        r"subéreu\w*|fibrous|fibreu\w*|pitted|foveol\w*|reticul\w*|rid[ée]e?s?)\b",
        re.IGNORECASE,
    ),
    "erectness": re.compile(
        r"\b(?:spreading|patent\w*|ascending|ascendant\w*|pendulous|pendant\w*|"
        r"drooping|nodding|reflexed|r[ée]fl[ée]chi\w*|étal[ée]\w*|couch[ée]\w*|"
        r"retombant\w*|horizontal\w*|oblique\w*|creeping|rampant\w*|scandent|"
        r"climbing|grimpant\w*|twining|volubil\w*|suberect|sub-erect|arching|"
        r"inclin\w*|deflexed|recurved|incurved|erect\w*|dress\w*)\b",
        re.IGNORECASE,
    ),
    "attachment": re.compile(
        r"\b(?:subsessile\w*|sub-sessile|stalked|pedunculate|p[ée]doncul[ée]\w*|"
        r"petiolate|p[ée]tiol[ée]\w*|shortly|briefly|stipitate|stipit[ée]\w*|"
        r"clawed|onguicul\w*|unguicul\w*|sessile\w*|pedicell\w*|p[ée]dicell\w*)\b",
        re.IGNORECASE,
    ),
    "branchiness": re.compile(
        r"\b(?:simple|forked|fourchu\w*|divided|divis[ée]\w*|dichotom\w*|"
        r"unbranched|branch\w*|ramifi\w*|ramif\w*|ramified)\b",
        re.IGNORECASE,
    ),
    "outline": re.compile(
        r"\b(?:oval\w*|ovale\w*|oboval\w*|obovoid\w*|ovoid\w*|ovo[ïi]d\w*|ellipsoid\w*|"
        r"ellipso[ïi]d\w*|rotund\w*|round\w*|arrondi\w*|suborbic\w*|subrotund\w*|"
        r"rhomb\w*|lanc\w*|oblanc\w*|ob\w*ate|elliptic\w*|ellipti\w*|oblong\w*|"
        r"ovat\w*|ov[ée]e?s?|obov\w*|linear\w*|lin[ée]ai\w*|spath\w*|spatul\w*|"
        r"triang\w*|delt\w*|renif\w*|r[ée]nif\w*|cordat\w*|cord[ée]\w*|cordiform\w*|"
        r"subulat\w*|subul[ée]\w*|falcat\w*|falciform\w*|sagitt\w*|hastat\w*|"
        r"panduri\w*|flabell\w*|cuneiform\w*|cun[ée]if\w*|obdelt\w*|circular\w*|"
        r"circulaire\w*|orbic\w*|filiform\w*|acicular\w*|aciculaire\w*|ligul\w*|"
        r"strap\w*|ensiform\w*|peltate|pelt[ée]\w*|lobed|lob[ée]\w*|shaped|forme\w*)\b",
        re.IGNORECASE,
    ),
    "solid": re.compile(
        r"\b(?:ovoid\w*|ovo[ïi]d\w*|obovoid\w*|obovo[ïi]d\w*|ellipsoid\w*|ellipso[ïi]d\w*|"
        r"glob\w*|subglob\w*|spheric\w*|sph[ée]ri\w*|cylindr\w*|subcylindr\w*|"
        r"fusiform\w*|clav\w*|conic\w*|coniq\w*|obconi\w*|turbinat\w*|turbin[ée]\w*|"
        r"pyriform\w*|piriform\w*|lenticular\w*|lenticul\w*|discoid\w*|disco[ïi]d\w*|"
        r"campanul\w*|urceol\w*|infundib\w*|tubular\w*|tubul\w*|reniform\w*|"
        r"r[ée]niform\w*|angular\w*|angul\w*|compress\w*|flatten\w*|apla\w*|"
        r"lens-shaped|shaped|forme\w*|oblong\w*|round\w*|arrondi\w*|obpyrami\w*|"
        r"pyrami\w*|trigon\w*|tetragon\w*|quadrang\w*)\b",
        re.IGNORECASE,
    ),
    "curvature": re.compile(
        r"\b(?:straight\w*|droit\w*|curv\w*|courb\w*|arcuat\w*|arqu[ée]\w*|recurv\w*|"
        r"incurv\w*|falcat\w*|flexuous|flexueu\w*|sinuous|sinueu\w*|twisted|tordu\w*|"
        r"hooked|crochu\w*|bent|coud[ée]\w*|geniculat\w*|genouill\w*|reflexed|"
        r"coiled|enroul\w*|circinat\w*|undulat\w*|ondul\w*|wavy)\b",
        re.IGNORECASE,
    ),
}

# Clause-level cues that belong to other residual categories or make a flat union unsafe.
_BLOCKING_CLAUSE_CUE = re.compile(
    r"\b(?:becom\w*|turn\w*|devenant|deviennent|devient|devenir|when|lorsqu\w*|quand|"
    r"young|jeunes?|mature|maturity|maturit[ée]|adult\w*|âg[ée]\w*|older|aging|ageing|"
    r"dry|dried|drying|sec|s[èe]che?s?|s[ée]ch\w*|fresh|frais|fra[îi]che?s?|living|vivants?|"
    r"in\s+fruit|in\s+flower|en\s+fruit|en\s+fleurs?|later|finally|ultimately|enfin|"
    r"ensuite|puis|then|at\s+first|at\s+length|au\s+d[ée]but|d'abord|initially|"
    r"with\s+age|herbarium|herbier|in\s+sicco|in\s+vivo|"
    r"respectively|respectivement|or\s+not|ou\s+non|possibly|perhaps|peut-[êe]tre)\b|[?]",
    re.IGNORECASE,
)

_CONNECTOR = re.compile(r"\s+(?:or|ou)\s+", re.IGNORECASE)
_LEADING_CONNECTOR = re.compile(r"(?:or|ou)\s+", re.IGNORECASE)  # used with .match(pos)
_HEDGE = re.compile(  # used with .match(text, pos): no ``^`` anchor
    r"(?:(?:more\s+|much\s+|plus\s+|very\s+|très\s+)?"
    r"(?:rarely|sometimes|occasionally|often|usually|frequently|seldom|commonly|"
    r"parfois|rarement|souvent|quelquefois|occasionnellement|fréquemment|généralement|"
    r"exceptionnellement|exceptionally))\s+",
    re.IGNORECASE,
)
_FREQUENCY_ONLY = re.compile(
    r"^(?:usually|often|sometimes|generally|mostly|commonly|frequently|typically|normally|"
    r"parfois|souvent|généralement|generalement|habituellement|le\s+plus\s+souvent|"
    r"en\s+général|fréquemment)$",
    re.IGNORECASE,
)
_MEASUREMENT = re.compile(
    r"^(?:(?:c\.|ca\.?|to|up\s+to|jusqu['’]à|atteignant|de|d['’]|env\.?|environ|about|"
    r"mesurant|±|d['’]environ|de\s+±|de\s+c\.)\s*)*"
    r"[\d(][\d\s.,·()\-–—×x+?/]*\s*"
    r"(?:(?:mm|cm|dm|m|µm|μm)\.?\s*)?"
    r"(?:(?:de\s+)?(?:long|longs?|longues?|large|larges|wide|broad|high|tall|haut\w*|"
    r"diam\.?|diameter|diamètre|thick|épais\w*|across|in\s+diam\.?|en\s+diam\.?)\.?\s*)?"
    r"(?:(?:and|et|by|×|x)\s*[\d(][\d\s.,·()\-–—×x+?/]*\s*(?:(?:mm|cm|dm|m)\.?\s*)?"
    r"(?:(?:de\s+)?(?:long|large|wide|broad|high|diam\.?)\.?\s*)?)?$",
    re.IGNORECASE,
)
_ADJECTIVE_WORD = re.compile(
    r"^(?:\d+(?:[-–]\d+)?[-–])?[A-Za-zÀ-ÖØ-öø-ÿ]+(?:ate|ous|ose|al|ar|ed|ent|ic|ical|ile|oid|"
    r"ular|ine|é|ée|és|ées|eux|euse|euses|aire|aires|ique|iques|ale|ales|aux|oïde|oïdes|"
    r"ente|entes|ents|if|ive|ives|ifs|iles|ues|us)$",
    re.IGNORECASE,
)
GAP_ADJECTIVES = frozenset(
    """slender stout thin thick small large big long short narrow broad wide entire persistent
    deciduous caducous solitary paired few many numerous fragrant scented alternate opposite
    whorled terminal axillary free united connate equal unequal subequal compound stiff rigid
    soft firm hollow solid dense lax open compact bisexual unisexual actinomorphic zygomorphic
    regular irregular conspicuous inconspicuous showy minute tiny obscure prominent distinct
    grêle grêles épais épaisse épaisses petit petite petits petites grand grande grands grandes
    long longue longs longues court courte courts courtes étroit étroite étroits étroites large
    larges entier entière entiers entières persistant persistante persistants persistantes
    caduc caduque caducs caduques libre libres alterne alternes opposé opposée opposés opposées
    odorant odorante odorants odorantes dense denses lâche lâches rigide rigides mince minces
    charnu charnue charnus charnues nombreux nombreuse nombreuses""".split()
)
_NUMERIC_WORD = re.compile(r"^[\d(][\d\s.,·()\-–—+?]*$")

_GAP_BLOCKING_WORDS = re.compile(
    r"\b(?:with|without|avec|sans|of|de|du|des|à|au|aux|in|on|at|en|sur|dans|to|from|by|"
    r"per|each|chaque|par|the|a|an|le|la|les|un|une|its|their|leur|leurs|which|qui|"
    r"that|and|et|or|ou|but|mais|not|non|ne|when|quand|if|si|than|que|as|comme)\b",
    re.IGNORECASE,
)

# Nouns that are *not* bearers but end in adjective-like suffixes.
_SUFFIX_FALSE_ADJECTIVES = re.compile(
    r"^(?:petiole|petioles|pedicel|pedicels|involucre|capsule|capsules|pétiole|pétioles|"
    r"bracteole|bracteoles|bractéoles?|stipule|stipules|glume|glumes|ligule|ligules|"
    r"auricle|auricles|valve|valves|nervure|nervures|panicule|panicules|ombelle|ombelles|"
    r"tube|tubes|lobule|lobules|nodule|nodules|capitule|capitules|feuille|feuilles|"
    r"tige|tiges|graine|graines|racine|racines|épine|épines|ramille|ramilles|pore|pores|"
    r"base|bases|marge|marges|sommet|carène|carènes|gaine|gaines|écaille|écailles|"
    r"article|articles|étamine|étamines|anthère|anthères|corolle|corolles|pétale|pétales|"
    r"sépale|sépales|foliole|folioles|drupe|drupes|baie|baies|rachis|axis|axes|"
    r"disc|disk|spine|spines|gland|glands|glande|glandes|surface|surfaces|face|faces|"
    r"style|styles|stigmate|stigmates|ovaire|ovaires|ovule|ovules|pollen|arille|arilles)$",
    re.IGNORECASE,
)

# Generic lamina/limb surfaces are leaf lamina only inside leaf-scoped records.
_LEAF_SCOPED_ONLY = re.compile(r"^(?:limbes?|lamina|laminae)$", re.IGNORECASE)
_LEAF_RECORD_BEARERS = frozenset({"PO_0009025", "PO_0020039", "PO_0020049"})


@dataclass(frozen=True)
class Operand:
    start: int
    end: int
    text: str
    pato_id: str
    subfamily: str
    hedge: str = ""
    modifier: str = ""
    full_start: int = -1


@dataclass
class Candidate:
    record_key: tuple[str, str, int]
    clause_start: int
    clause_end: int
    start: int
    end: int
    operands: list[Operand]
    subfamily: str
    bearer_po: str = ""
    bearer_start: int = -1
    bearer_end: int = -1
    bearer_text: str = ""
    bearer_method: str = ""
    target_indexes: list[int] = field(default_factory=list)


def _record_key(record: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(record.get("source", "") or ""),
        str(record.get("source_id", "") or ""),
        int(record.get("source_segment_index", 0) or 0),
    )


def lookup_value(surface: str) -> tuple[str, str] | None:
    return VALUE_TABLE.get(_norm(surface))


# --------------------------------------------------------------------------------------------- #
# Clause segmentation.
# --------------------------------------------------------------------------------------------- #


def _members(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Top-level comma members of ``text[start:end]`` (decimal commas and parentheses kept)."""

    members: list[tuple[int, int]] = []
    depth = 0
    member_start = start
    for index in range(start, end):
        char = text[index]
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            if (
                index > start
                and index + 1 < end
                and text[index - 1].isdigit()
                and text[index + 1].isdigit()
            ):
                continue
            members.append((member_start, index))
            member_start = index + 1
    members.append((member_start, end))
    return members


def _strip_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _split_operands(text: str, start: int, end: int) -> list[tuple[int, int]] | None:
    """Split a member at ``or``/``ou`` connectors; ``None`` when it has no connector."""

    pieces: list[tuple[int, int]] = []
    cursor = start
    found = False
    for match in _CONNECTOR.finditer(text, start, end):
        found = True
        pieces.append(_strip_bounds(text, cursor, match.start()))
        cursor = match.end()
    pieces.append(_strip_bounds(text, cursor, end))
    if not found:
        return None
    return pieces


# Intensity modifiers whose modified value is *entailed* by the bare PATO value (``sparsely
# pubescent`` is pubescent; ``narrowly elliptic`` is elliptic).  Approximators (``±``, ``nearly``,
# ``sub-``) and hue shifts (``-ish``) are not entailing and stay residual.
ENTAILING_MODIFIERS = {
    "pilosity": re.compile(
        r"^(?:(?:very|très|rather|assez)\s+)?(?:sparsely|densely|shortly|minutely|finely|"
        r"sparingly|thinly|softly|closely|slightly|laxly|loosely|evenly|éparsement|densément|densement|"
        r"courtement|finement|brièvement|légèrement|legerement|faiblement)\s+",
        re.IGNORECASE,
    ),
    "outline": re.compile(
        r"^(?:narrowly|broadly|widely|étroitement|etroitement|largement)\s+", re.IGNORECASE
    ),
    "branchiness": re.compile(
        r"^(?:much|sparsely|sparingly|densely|richly|abundantly|little|slightly|peu|"
        r"abondamment|richement|très|tres|faiblement)\s+",
        re.IGNORECASE,
    ),
    "curvature": re.compile(
        r"^(?:slightly|strongly|légèrement|legerement|fortement|faiblement)\s+",
        re.IGNORECASE,
    ),
    "colour": re.compile(r"^(?:bright)\s+", re.IGNORECASE),
    "texture": re.compile(
        r"^(?:thinly|thickly|slightly|very|très|tres|légèrement|legerement|finely|finement)\s+",
        re.IGNORECASE,
    ),
}

# ``simple`` is context dependent; in ``simple or branched`` it denotes unbranched.
_SIMPLE = re.compile(r"^simples?$", re.IGNORECASE)
SIMPLE_MARKER = "SIMPLE_CONTEXTUAL"


def _ground_operand(
    text: str, start: int, end: int, *, allow_hedge: bool, allow_modifier: bool = True
) -> Operand | None:
    start, end = _strip_bounds(text, start, end)
    if start >= end:
        return None
    full_start = start
    hedge = ""
    match = _HEDGE.match(text, start, end) if allow_hedge else None
    if match:
        hedge = text[start : match.end()].strip()
        start = match.end()
    # A value must be a whole lexical unit (no hyphen/slash compound touching it).
    if full_start > 0 and text[full_start - 1] in "-‐–—/":
        return None
    if end < len(text) and text[end] in "-‐–—/":
        return None
    surface = text[start:end]
    if _SIMPLE.match(surface):
        return Operand(start, end, surface, SIMPLE_MARKER, "branchiness", hedge, "", full_start)
    value = lookup_value(surface)
    if value is not None:
        return Operand(start, end, surface, value[0], value[1], hedge, "", full_start)
    if not allow_modifier:
        return None
    for subfamily, pattern in ENTAILING_MODIFIERS.items():
        modifier = pattern.match(surface)
        if not modifier:
            continue
        head = surface[modifier.end() :]
        value = lookup_value(head)
        if value is not None and value[1] == subfamily:
            return Operand(
                start + modifier.end(),
                end,
                head,
                value[0],
                value[1],
                hedge,
                surface[: modifier.end()].strip(),
                full_start,
            )
    return None


def _resolve_simple(operands: list[Operand]) -> list[Operand] | None:
    """Map contextual ``simple`` to unbranched only when coordinated with ``branched``."""

    if not any(op.pato_id == SIMPLE_MARKER for op in operands):
        return operands
    others = [op for op in operands if op.pato_id != SIMPLE_MARKER]
    if not others or any(op.pato_id != "PATO_0000402" for op in others):
        return None
    return [
        Operand(
            op.start, op.end, op.text, "PATO_0000414", op.subfamily, op.hedge,
            op.modifier, op.full_start,
        )
        if op.pato_id == SIMPLE_MARKER
        else op
        for op in operands
    ]


# Heads the baseline cues do not cover.  ``leaf blade`` is only a RELATED synonym of PO leaf
# lamina, so the blade is grounded to the generic PO ``lamina`` class (``blade`` is EXACT there),
# exactly as the baseline grounds a bare ``blade``.
EXTRA_HEAD_PATTERNS = [
    ("PO_0025060", re.compile(r"\bleaf[- ](?:blades?|laminae?)\b", re.IGNORECASE)),
]
_STANDARD_HEAD = re.compile(r"^(?:standards?|vexill(?:um|a))$", re.IGNORECASE)
PAPILIONOID_FAMILIES = frozenset({"fabaceae", "leguminosae", "papilionaceae"})


def _bearer_patterns() -> list[tuple[str, re.Pattern[str]]]:
    patterns = list(EXTRA_HEAD_PATTERNS) + list(baseline.LOCAL_BEARER_PATTERNS)
    patterns.append(("PO_0025324", re.compile(r"\b(?:standards?|vexill(?:um|a))\b", re.I)))
    path = Path("config/reviewed_local_bearers.tsv")
    if path.exists():
        # Exact aliases of live PO classes and of released FLOPO-local support classes (calyx
        # lobe, leaflet lamina, indumentum, ...); contextual rows are never unconditional.
        for row in load_reviewed_bearers(path):
            surface = str(row.get("surface_form", "") or "").strip()
            po_id = str(row.get("po_id", "") or "").strip()
            if surface and po_id:
                patterns.append(
                    (po_id, re.compile(rf"\b{re.escape(surface)}\b", re.IGNORECASE))
                )
    return patterns


_BEARER_PATTERNS: list[tuple[str, re.Pattern[str]]] | None = None
LAST_DETAIL: list[str] = [""]  # diagnostic only: surface of the last ungrounded operand


@dataclass(frozen=True)
class HeadBearer:
    po_id: str
    start: int
    end: int
    method: str
    surface: str


GENERIC_PO_HEADS = frozenset(
    """apex base margin lobe surface tube limb wing scale hair vein tip axis stalk cell tissue
    portion sheath cup disc disk plant shoot bud receptacle tendril lip keel part segment body
    column head neck beak spur claw blade lamina leaf flower fruit seed ligule grain kernel
    cereal pale propagule diaspore core cane stalk scape""".split()
)


def _load_po_exact_heads() -> dict[str, set[str]]:
    """PO preferred labels plus English EXACT synonyms -> PO ids (multi-id surfaces kept)."""

    heads: defaultdict[str, set[str]] = defaultdict(set)
    lexicon = Path("config/po_lexicon.tsv")
    if lexicon.exists():
        with lexicon.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row.get("namespace") != "plant_anatomy":
                    continue
                heads[_norm(row["label"])].add(row["id"])
    obo = Path("ont/plant_ontology.obo")
    if obo.exists():
        current = ""
        for line in obo.open(encoding="utf-8"):
            if line.startswith("id: PO:"):
                current = line[4:].strip().replace(":", "_")
            elif line.startswith("[") and not line.startswith("[Term]"):
                current = ""
            elif current and line.startswith("synonym:"):
                match = re.match(r'synonym: "([^"]+)" EXACT \[', line)
                if match:
                    surface = re.sub(r"\s*\((?:exact|narrow|related|broad)[^)]*\)", "",
                                     match.group(1))
                    if re.fullmatch(r"[A-Za-z][A-Za-z \-]*", surface):
                        heads[_norm(surface)].add(current)
    return dict(heads)


_PO_EXACT_HEADS: dict[str, set[str]] | None = None
_HEAD_PHRASE = re.compile(r"[A-Za-z]+(?:[- ][A-Za-z]+){0,2}")


def _singulars(phrase: str) -> list[str]:
    forms = [phrase]
    if phrase.endswith("ies"):
        forms.append(phrase[:-3] + "y")
    if phrase.endswith("es"):
        forms.append(phrase[:-2])
    if phrase.endswith("s"):
        forms.append(phrase[:-1])
    if phrase.endswith("a"):
        forms.append(phrase[:-1] + "um")
    return forms


def _po_label_head(text: str, clause_start: int, clause_end: int) -> HeadBearer | None:
    """Clause-initial noun phrase that is exactly one PO label/EXACT synonym."""

    global _PO_EXACT_HEADS
    if _PO_EXACT_HEADS is None:
        _PO_EXACT_HEADS = _load_po_exact_heads()
    start, _ = _strip_bounds(text, clause_start, clause_end)
    match = _HEAD_PHRASE.match(text, start, clause_end)
    if not match:
        return None
    words = re.split(r"([- ])", match.group(0))
    tokens = words[0::2]
    for count in range(len(tokens), 0, -1):
        phrase_text = "".join(words[: 2 * count - 1])
        end = start + len(phrase_text)
        if end < clause_end and not (text[end].isspace() or text[end] == ","):
            continue
        for form in _singulars(_norm(phrase_text)):
            ids = _PO_EXACT_HEADS.get(form)
            if not ids:
                continue
            if len(ids) != 1 or form in GENERIC_PO_HEADS:
                return None
            return HeadBearer(next(iter(ids)), start, end, "po_exact_label_head", phrase_text)
    return None


_ORGAN_SCOPED_SOURCES = frozenset({"fdac", "flora-gabon", "flora-malesiana"})


def _organ_heading_bearer(
    record: dict[str, Any], text: str, clause_start: int
) -> HeadBearer | None:
    """Organ heading of a FlorML/FDAC segment, only for its first, noun-less clause."""

    if str(record.get("source", "")) not in _ORGAN_SCOPED_SOURCES:
        return None
    if text[:clause_start].strip():
        return None
    organ = str(record.get("organ", "") or "").strip()
    key = organ.casefold()
    po_id = baseline.ORGAN_OVERRIDES.get(key) or baseline.FDAC_FRENCH_ORGAN_OVERRIDES.get(key)
    if not po_id:
        global _PO_EXACT_HEADS
        if _PO_EXACT_HEADS is None:
            _PO_EXACT_HEADS = _load_po_exact_heads()
        for form in _singulars(_norm(organ)):
            ids = _PO_EXACT_HEADS.get(form)
            if ids and len(ids) == 1 and form not in GENERIC_PO_HEADS:
                po_id = next(iter(ids))
                break
    if not po_id:
        return None
    start, _ = _strip_bounds(text, clause_start, len(text))
    return HeadBearer(po_id, start, start, "organ_heading", organ)


_GROWTH_FORM_TAIL = re.compile(
    r"\s+(?:(?:annual|perennial|woody|small|large|robust|slender|tall|stout|tufted|"
    r"dioecious|monoecious|evergreen|aromatic|rhizomatous|stoloniferous|caespitose)\s+){0,3}"
    r"(?P<noun>herbs?|shrubs?|subshrubs?|shrublets?|undershrubs?|trees?|treelets?|"
    r"climbers?|lianas?|plants?)(?=[\s,.;]|$)",
    re.IGNORECASE,
)
_GROWTH_FORM_FAMILIES = frozenset({"erectness", "pilosity", "branchiness"})


def _head_bearer(
    record: dict[str, Any], text: str, clause_start: int, clause_end: int
) -> HeadBearer | None:
    """Return the clause-initial organ noun ``(po_id, start, end)`` when it is unambiguous."""

    global _BEARER_PATTERNS
    if _BEARER_PATTERNS is None:
        _BEARER_PATTERNS = _bearer_patterns()
    start, _ = _strip_bounds(text, clause_start, clause_end)
    best: tuple[str, int, int] | None = None
    for po_id, pattern in _BEARER_PATTERNS:
        match = pattern.match(text, start, clause_end)
        if not match or match.start() != start:
            continue
        if best is None or match.end() > best[2]:
            best = (po_id, match.start(), match.end())
    if best is None:
        return _po_label_head(text, clause_start, clause_end)
    po_id, bstart, bend = best
    # The head must be a whole noun: ``Leaf-blades`` or ``flower-buds`` are other bearers.
    if bend < clause_end and not (text[bend].isspace() or text[bend] == ","):
        return None
    surface = text[bstart:bend]
    if _LEAF_SCOPED_ONLY.match(surface):
        organ_po = baseline._organ_to_po(str(record.get("organ", "") or ""))
        if organ_po in _LEAF_RECORD_BEARERS:
            po_id = "PO_0020039"
        elif surface.casefold().startswith("lamina"):
            po_id = "PO_0025060"  # generic PO lamina; the leaf is not established
        else:
            return None
    if po_id == "PO_0025324" or _STANDARD_HEAD.match(surface):
        # Banner petal only in papilionoid legumes (Impatiens has a non-homologous "étendard").
        family = str(record.get("taxon_family", "") or "").casefold()
        if family not in PAPILIONOID_FAMILIES:
            return None
    # Ambiguous container-specific heads (v2 correction pass).
    if surface.casefold() in {"receptacle", "receptacles"}:
        return None
    return HeadBearer(po_id, bstart, bend, "clause_head_noun", surface)


def _bearerless_head(
    text: str, members: list[tuple[int, int]], final: int, clause_start: int
) -> HeadBearer | None:
    """Zero-width placeholder head that ends where the union's first operand begins.

    When the connector member is the clause's first member, its first ``or`` piece is
    ``<bearer phrase> <value>``; the placeholder ends at the longest word suffix of that piece
    that grounds as one operand, so the bearer phrase is excluded from the union.  Otherwise
    the placeholder sits at the clause start and left extension over earlier members applies.
    """

    start, _ = _strip_bounds(text, clause_start, len(text))
    if final != 0:
        return HeadBearer("", start, start, "bearerless", "")
    ms, me = _strip_bounds(text, *members[0])
    connector = _CONNECTOR.search(text, ms, me)
    if connector is None:
        return None
    piece_start, piece_end = _strip_bounds(text, ms, connector.start())
    words = [match.start() for match in re.finditer(r"\S+", text[piece_start:piece_end])]
    for offset in words:
        begin = piece_start + offset
        if _ground_operand(text, begin, piece_end, allow_hedge=False) is not None:
            return HeadBearer("", start, begin, "bearerless", text[start:begin].strip())
    return None


def _gap_ok(text: str, start: int, end: int) -> bool:
    """Whether the text between head and union is only measurements/adjectival members."""

    gap = text[start:end]
    if not gap.strip():
        return True
    if re.search(r"[:;()\[\]/?]", gap):
        # Parenthesised numeric ranges are common; allow only purely numeric parentheses.
        stripped = re.sub(r"\([\d\s.,·\-–—×x+?]*\)", "", gap)
        if re.search(r"[:;()\[\]/?]", stripped):
            return False
        gap = stripped
    for item_start, item_end in _members(gap, 0, len(gap)):
        item = gap[item_start:item_end].strip()
        if not item:
            continue
        if _MEASUREMENT.match(item):
            continue
        if _FREQUENCY_ONLY.match(item):
            continue
        words = item.split()
        if len(words) > 3:
            return False
        for word in words:
            bare = word.strip(".")
            if _GAP_BLOCKING_WORDS.fullmatch(bare):
                return False
            if lookup_value(bare) or _NUMERIC_WORD.match(bare):
                continue
            if _FREQUENCY_ONLY.match(bare):
                continue
            if bare.casefold() in GAP_ADJECTIVES:
                continue
            parts = [part for part in re.split(r"[-‐–—]", bare) if part]
            if len(parts) > 1 and all(
                lookup_value(part)
                or _NUMERIC_WORD.match(part)
                or part.casefold() in GAP_ADJECTIVES
                or (_ADJECTIVE_WORD.match(part) and not _SUFFIX_FALSE_ADJECTIVES.match(part))
                for part in parts
            ):
                continue
            if _SUFFIX_FALSE_ADJECTIVES.match(bare):
                return False
            if (
                _ADJECTIVE_WORD.match(bare)
                and not _bearer_like(bare)
                and not bare.casefold().endswith("ment")  # FR scope adverbs (intérieurement)
            ):
                continue
            return False
    return True


def _bearer_like(word: str) -> bool:
    global _BEARER_PATTERNS
    if _BEARER_PATTERNS is None:
        _BEARER_PATTERNS = _bearer_patterns()
    return any(pattern.fullmatch(word) for _, pattern in _BEARER_PATTERNS)


# --------------------------------------------------------------------------------------------- #
# Candidate construction.
# --------------------------------------------------------------------------------------------- #


def find_candidate(
    record: dict[str, Any], span_start: int, span_end: int, *, bearerless: bool = False
) -> tuple[Candidate | None, str]:
    """Return the union containing an unresolved span, or ``(None, residual_reason)``.

    With ``bearerless=True`` the clause-head bearer is not resolved: the union is located and
    every non-bearer guard (operands, exhaustiveness, context cues, modality) is applied, but the
    head noun and the head--union gap are left to an external bearer decision (the bearer
    attachment review).  The returned candidate then has an empty ``bearer_po``.
    """

    text = str(record.get("text", "") or "")
    clause, clause_start = baseline._clause_at(text, span_start)
    clause_end = clause_start + len(clause)
    members = _members(text, clause_start, clause_end)
    index = next(
        (i for i, (ms, me) in enumerate(members) if ms <= span_start and span_end <= me), None
    )
    if index is None:
        return None, "span_crosses_member_boundary"

    # Locate the member carrying the connector (the span's own member or the next one when the
    # span is an earlier comma-listed operand).
    final = None
    for j in range(index, len(members)):
        ms, me = members[j]
        stripped_start, stripped_end = _strip_bounds(text, ms, me)
        if _split_operands(text, stripped_start, stripped_end) is not None or _LEADING_CONNECTOR.match(
            text, stripped_start, stripped_end
        ):
            final = j
            break
        if j > index:
            # intermediate member must itself be a plain value
            if _ground_operand(text, ms, me, allow_hedge=False) is None:
                return None, "no_connector_in_coordination"
    if final is None:
        return None, "no_connector_in_coordination"

    if bearerless:
        head = _bearerless_head(text, members, final, clause_start)
        if head is None:
            return None, "ungrounded_or_modified_operand"
    else:
        head = _head_bearer(record, text, clause_start, clause_end)
        if head is None:
            head = _organ_heading_bearer(record, text, clause_start)
    ms, me = members[final]
    ms, me = _strip_bounds(text, ms, me)
    # First member may start with the head noun, or end with a growth-form noun.
    if final == 0:
        if head is None:
            tail = _GROWTH_FORM_TAIL.search(text, ms, me)
            if tail is None:
                return None, "no_clause_head_bearer"
            head = HeadBearer(
                "PO_0000003",
                tail.start("noun"),
                tail.end("noun"),
                "post_union_growth_form",
                tail.group("noun"),
            )
            me = tail.start()
        else:
            ms, me = _strip_bounds(text, head.end, me)
    oxford = _LEADING_CONNECTOR.match(text, ms, me)
    if oxford:
        first_piece = _strip_bounds(text, oxford.end(), me)
        pieces = [first_piece]
        more = _split_operands(text, first_piece[0], first_piece[1])
        if more is not None:
            pieces = more
        oxford_hedged = True
    else:
        pieces = _split_operands(text, ms, me) or []
        oxford_hedged = False
    operands: list[Operand] = []
    for position, (ps, pe) in enumerate(pieces):
        allow_hedge = position > 0 or oxford_hedged
        operand = _ground_operand(text, ps, pe, allow_hedge=allow_hedge)
        if operand is None:
            LAST_DETAIL[0] = text[ps:pe]
            return None, "ungrounded_or_modified_operand"
        operands.append(operand)
    # Extend left over plain comma-listed same-family members.
    subfamilies = {operand.subfamily for operand in operands}
    if len(subfamilies) != 1:
        return None, "mixed_subfamily"
    subfamily = next(iter(subfamilies))
    j = final - 1
    left_items: list[Operand] = []
    while j >= 0:
        ls, le = members[j]
        if j == 0:
            if head is None:
                return None, "no_clause_head_bearer"
            if head.method == "post_union_growth_form":
                break
            ls = head.end
        ls, le = _strip_bounds(text, ls, le)
        if ls >= le:
            break
        operand = _ground_operand(text, ls, le, allow_hedge=False)
        if operand is not None and operand.subfamily == subfamily:
            left_items.insert(0, operand)
            j -= 1
            continue
        break
    if oxford and not left_items:
        return None, "dangling_leading_connector"
    operands = left_items + operands
    resolved = _resolve_simple(operands)
    if resolved is None:
        return None, "contextual_simple_without_branched"
    operands = resolved
    if head is None:
        return None, "no_clause_head_bearer"
    # Everything between the head noun and the first operand must be adjectival/measurement.
    union_start = operands[0].full_start
    union_end = operands[-1].end
    if head.method == "bearerless":
        pass  # the bearer (and hence the head--union gap) is decided by review
    elif head.method == "post_union_growth_form":
        if subfamily not in _GROWTH_FORM_FAMILIES:
            return None, "growth_form_bearer_wrong_family"
        if text[clause_start:union_start].strip():
            return None, "unsafe_gap_between_head_and_union"
    else:
        if head.end > union_start:
            return None, "head_inside_union"
        if not _gap_ok(text, head.end, union_start):
            return None, "unsafe_gap_between_head_and_union"
    # Frequency cue before the union must be the *only* qualifier.
    fields, _q_start, _q_text = baseline._modality_context(text, union_start)
    if set(fields) - {"frequency_qualifier"}:
        return None, "non_frequency_qualifier_on_union"
    # Member after the union must not be another same-family alternative.
    if final + 1 < len(members):
        ns, ne = members[final + 1]
        nxt = _ground_operand(text, ns, ne, allow_hedge=True)
        if nxt is not None and nxt.subfamily == subfamily:
            return None, "trailing_same_family_alternative"
    candidate = Candidate(
        record_key=_record_key(record),
        clause_start=clause_start,
        clause_end=clause_end,
        start=union_start,
        end=union_end,
        operands=operands,
        subfamily=subfamily,
    )
    reason = _semantic_guard(text, candidate)
    if reason:
        return None, reason
    if head.method == "bearerless":
        return candidate, ""
    candidate.bearer_po = head.po_id
    candidate.bearer_start, candidate.bearer_end = head.start, head.end
    candidate.bearer_text = head.surface
    candidate.bearer_method = head.method
    return candidate, ""


def _semantic_guard(text: str, candidate: Candidate) -> str:
    ids = [operand.pato_id for operand in candidate.operands]
    if len(set(ids)) != len(ids):
        return "non_distinct_operands"
    if len(ids) < 2:
        return "single_operand"
    dims = {DIMENSION.get(pato_id, "") for pato_id in ids}
    dims.discard("")
    if len(dims) > 1:
        return "mixed_pato_shape_dimensions"
    if _BLOCKING_CLAUSE_CUE.search(_mask_union(text, candidate)):
        return "clause_scope_or_context_cue"
    # Exhaustiveness: no other same-family value or unsupported same-family cue in the clause.
    masked = _mask_union(text, candidate)
    if _family_value_pattern(candidate.subfamily).search(masked):
        return "other_same_family_value_in_clause"
    pattern = UNSUPPORTED_SAME_FAMILY.get(candidate.subfamily)
    if pattern is not None and pattern.search(masked):
        return "unsupported_same_family_cue_in_clause"
    if candidate.subfamily in {"outline", "solid"}:
        other = UNSUPPORTED_SAME_FAMILY["solid" if candidate.subfamily == "outline" else "outline"]
        if other.search(masked):
            return "other_shape_cue_in_clause"
    if "(" in text[candidate.start : candidate.end]:
        return "parenthesis_inside_union"
    return ""


_FAMILY_VALUE_PATTERNS: dict[str, re.Pattern[str]] = {}


def _family_value_pattern(subfamily: str) -> re.Pattern[str]:
    """Any table form of ``subfamily``, also inside hyphenated compounds (``ashy-brown``)."""

    if subfamily not in _FAMILY_VALUE_PATTERNS:
        forms = sorted(
            (form for form, (_pato, fam) in VALUE_TABLE.items() if fam == subfamily),
            key=len,
            reverse=True,
        )
        alternatives = [
            r"[\s\-‐–—]+".join(re.escape(part) for part in form.split(" ")) for form in forms
        ]
        _FAMILY_VALUE_PATTERNS[subfamily] = re.compile(
            r"(?<!\w)(?:" + "|".join(alternatives) + r")(?!\w)", re.IGNORECASE
        )
    return _FAMILY_VALUE_PATTERNS[subfamily]


def _mask_union(text: str, candidate: Candidate) -> str:
    """Clause text with the union (and the head noun) blanked out."""

    chars = list(text[candidate.clause_start : candidate.clause_end])
    offset = candidate.clause_start
    for index in range(candidate.start - offset, candidate.end - offset):
        chars[index] = " "
    return "".join(chars)


# --------------------------------------------------------------------------------------------- #
# Assertion construction.
# --------------------------------------------------------------------------------------------- #


@dataclass
class GateContext:
    combinations: dict
    registry: dict
    signature_registry: dict
    attribute_ids: set[str]
    pato_ids: set[str]
    po_ids: set[str]
    flopo_ids: set[str]

    @classmethod
    def load(cls) -> "GateContext":
        return cls(
            combinations=load_combinations(Path("config/valid_combinations.tsv")),
            registry=load_eq_registry(Path("config/flopo_id_registry.tsv")),
            signature_registry=load_signature_registry(Path("config/flopo_id_registry.tsv")),
            attribute_ids=load_pato_attribute_terms(Path("config/pato_lexicon.tsv")),
            pato_ids=load_catalog_ids(Path("config/pato_lexicon.tsv")),
            po_ids=load_catalog_ids(Path("config/po_lexicon.tsv")),
            flopo_ids=load_flopo_ids(Path("config/flopo_id_registry.tsv")),
        )


# Frequency hedges accepted by ``_HEDGE`` that the shared provenance aliases do not cover.
_EXTRA_HEDGE_FREQUENCY = {
    "quelquefois": "sometimes",
    "occasionnellement": "occasionally",
    "fréquemment": "often",
    "frequemment": "often",
    "exceptionnellement": "rarely",
    "exceptionally": "rarely",
}


def _hedge_frequency(hedge: str) -> str:
    for word in reversed(re.findall(r"[^\W\d_]+", hedge.lower())):
        frequency = FREQUENCY_ALIASES.get(word) or _EXTRA_HEDGE_FREQUENCY.get(word)
        if frequency:
            return frequency
    return "unspecified"


def operand_records(
    text: str, operands: list[Operand], assertion_frequency: str = "unspecified"
) -> tuple[list[dict[str, Any]], list[str]]:
    """Per-operand qualifier records (schema extension E2) and provenance notes.

    The operand spans its hedge and modifier cues (``rarely sparsely hairy``).  The degree is the
    DegreeQualifier of the modifier word nearest the value (``very sparsely`` is sparsely); a
    modifier that maps to no DegreeQualifier (``softly``, ``evenly``, ``bright``) stays a
    generalized entailing modifier recorded in provenance only.  A frequency hedge becomes the
    operand's frequency qualifier unless it would contradict an assertion-level frequency.
    """

    records: list[dict[str, Any]] = []
    notes: list[str] = []
    for index, op in enumerate(operands):
        full_start = op.full_start if op.full_start >= 0 else op.start
        degree = parse_qualifier_cue(op.modifier)["degree_qualifier"] if op.modifier else "unmodified"
        if op.modifier and degree == "unmodified":
            notes.append(f"operand_entailing_modifier_generalized:{op.modifier} {op.text}->{op.pato_id}")
        frequency = _hedge_frequency(op.hedge) if op.hedge else "unspecified"
        if op.hedge and frequency == "unspecified":
            notes.append(f"operand_frequency_hedge_unmapped_retained_in_source:{op.hedge}")
        if (
            frequency != "unspecified"
            and assertion_frequency not in {"unspecified", ""}
            and frequency != assertion_frequency
        ):
            notes.append(
                f"operand_frequency_hedge_conflicts_with_assertion_frequency:{op.hedge}"
            )
            frequency = "unspecified"
        qualified = degree != "unmodified" or frequency != "unspecified"
        # The cue runs from the hedge through the mapped degree word; an unmapped modifier
        # (``bright``) is not a qualifier cue, so then only the hedge is cited.
        cue_end = op.start if degree != "unmodified" else full_start + len(op.hedge)
        while cue_end > full_start and text[cue_end - 1].isspace():
            cue_end -= 1
        records.append(
            make_operand(
                index,
                op.pato_id,
                text,
                full_start,
                op.end,
                qualifier_start=full_start if qualified and cue_end > full_start else None,
                qualifier_end=cue_end if qualified and cue_end > full_start else None,
                degree_qualifier=degree,
                frequency_qualifier=frequency,
            )
        )
    return records, notes


def operand_is_marked(row: dict[str, Any]) -> bool:
    return row["degree_qualifier"] != "unmodified" or row["frequency_qualifier"] != "unspecified"


def build_assertion(record: dict[str, Any], candidate: Candidate) -> dict[str, Any]:
    text = str(record.get("text", "") or "")
    fields, q_start, q_text = baseline._modality_context(text, candidate.start)
    heading = candidate.bearer_method == "organ_heading"
    source_start = min(candidate.start, q_start) if heading else min(
        candidate.bearer_start, candidate.start, q_start
    )
    source_end = candidate.end if heading else max(candidate.end, candidate.bearer_end)
    value_operands, operand_notes = operand_records(
        text, candidate.operands, fields.get("frequency_qualifier", "unspecified")
    )
    provenance = [
        "claude_explicit_disjunction:closed_bilingual_value_table",
        f"subfamily:{candidate.subfamily}",
        (
            f"bearer:organ_heading {candidate.bearer_text!r} (first noun-less clause)"
            if heading
            else f"bearer:{candidate.bearer_method} {candidate.bearer_text!r} "
            f"[{candidate.bearer_start},{candidate.bearer_end})"
        ),
        "PATO union operands:" + "|".join(op.pato_id for op in candidate.operands),
        "operand surfaces:" + "|".join(op.text for op in candidate.operands),
    ]
    if any(operand_is_marked(row) for row in value_operands):
        provenance.append(
            "operand_qualifiers:E2:"
            + "|".join(
                f"{row['operand_index']}:{row['degree_qualifier']}/{row['frequency_qualifier']}"
                for row in value_operands
                if operand_is_marked(row)
            )
        )
    provenance.extend(operand_notes)
    assertion: dict[str, Any] = {
        "po_id": candidate.bearer_po,
        "pato_id": ATTRIBUTE_BY_SUBFAMILY[candidate.subfamily],
        "negated": False,
        "negation_scope": "",
        "organ": record.get("organ", ""),
        "source_text": text[source_start:source_end],
        "source_start": source_start,
        "source_end": source_end,
        "bearer_start": None if heading else candidate.bearer_start,
        "bearer_end": None if heading else candidate.bearer_end,
        "raw_entity_text": candidate.bearer_text,
        "raw_quality_text": text[candidate.start : candidate.end],
        "value_text": text[candidate.start : candidate.end],
        "value_operator": "one_of",
        "value_terms": [op.pato_id for op in candidate.operands],
        "value_operands": value_operands,
        "part_restrictions": [],
        "bearer_context_qualities": [],
        "developmental_stage_contexts": [],
        "developmental_stage_operator": "atomic",
        "frequency_qualifier": fields.get("frequency_qualifier", "unspecified"),
        "epistemic_modality": "asserted",
        "value_qualifier": "exact",
        "degree_qualifier": "unmodified",
        "modality_text": q_text if fields else "",
        "season_contexts": [],
        "season_operator": "atomic",
        "normalization_status": "compositional",
        "mapping_provenance": provenance,
        "extractor": EXTRACTOR,
        "composition": {
            "status": "accept",
            "confidence": 0.85,
            "reasons": [f"deterministic_explicit_union:{candidate.bearer_method}"],
            "clause": text[candidate.clause_start : candidate.clause_end].strip(),
        },
    }
    if fields:
        assertion["modality_start"] = q_start
        assertion["modality_end"] = q_start + len(q_text)
    return assertion


def _overlaps_existing(record: dict[str, Any], candidate: Candidate) -> bool:
    for assertion in record.get("assertions", []) or []:
        start = assertion.get("source_start")
        end = assertion.get("source_end")
        if start is None or end is None:
            continue
        if start < candidate.end and candidate.start < end:
            return True
    return False


def recover_record(
    record: dict[str, Any], gate_context: GateContext
) -> tuple[dict[str, Any] | None, Counter[str], list[dict[str, Any]]]:
    """Return ``(delta_line_or_None, outcome_counts, audit_rows)`` for one segment."""

    outcomes: Counter[str] = Counter()
    audit: list[dict[str, Any]] = []
    unresolved = record.get("unresolved_spans", []) or []
    targets = [
        (i, span) for i, span in enumerate(unresolved) if span.get("reason") == TARGET_REASON
    ]
    if not targets:
        return None, outcomes, audit
    text = str(record.get("text", "") or "")
    candidates: dict[tuple[int, int], Candidate] = {}
    for index, span in targets:
        candidate, reason = find_candidate(record, int(span["start"]), int(span["end"]))
        if candidate is None:
            outcomes[f"residual:{reason}"] += 1
            audit.append({"status": "residual", "reason": reason, "span": span})
            continue
        key = (candidate.start, candidate.end)
        candidates.setdefault(key, candidate).target_indexes.append(index)
    working = copy.deepcopy(record)
    add_statements: list[dict[str, Any]] = []
    add_assertions: list[dict[str, Any]] = []
    remove: list[dict[str, Any]] = []
    for key in sorted(candidates):
        candidate = candidates[key]
        spans = [unresolved[i] for i in candidate.target_indexes]
        if _overlaps_existing(working, candidate):
            outcomes["residual:overlaps_existing_assertion"] += len(spans)
            audit.extend(
                {"status": "residual", "reason": "overlaps_existing_assertion", "span": s}
                for s in spans
            )
            continue
        # Every claimed span must lie inside an operand.
        if not all(
            any(op.start <= s["start"] and s["end"] <= op.end for op in candidate.operands)
            for s in spans
        ):
            outcomes["residual:span_outside_operands"] += len(spans)
            continue
        assertion = build_assertion(working, candidate)
        # Leaf-part bearers in a leaflet description are re-borne on the FLOPO leaflet part.
        leaflet_part = leaflet_bearer(assertion["po_id"], text, candidate.start)
        if leaflet_part != assertion["po_id"]:
            assertion["mapping_provenance"].append(
                f"leaflet_context_bearer:{assertion['po_id']}->{leaflet_part}"
            )
            assertion["po_id"] = leaflet_part
        gate = check_assertion(
            text,
            assertion,
            gate_context.combinations,
            gate_context.registry,
            gate_context.signature_registry,
            gate_context.attribute_ids,
            taxon_provenance=record.get("taxon") if "taxon" in record else None,
            pato_catalog_ids=gate_context.pato_ids,
            flopo_catalog_ids=gate_context.flopo_ids,
            po_catalog_ids=gate_context.po_ids,
        )
        if gate.status not in {"accepted", "review"}:
            outcomes["residual:gate_rejected"] += len(spans)
            audit.extend(
                {"status": "residual", "reason": "gate_rejected", "span": s} for s in spans
            )
            continue
        assertion["gate"] = asdict(gate)
        assertion["gate"]["assertion_index"] = len(working.get("assertions", []) or [])
        ensure_annotation_class_iri(assertion)
        probe = dict(working)
        probe["assertions"] = [*(working.get("assertions", []) or []), assertion]
        upgraded = ensure_source_statements(probe)
        materialized = upgraded["assertions"][-1]
        statement_id = materialized["source_statement_id"]
        existing_ids = {
            row.get("statement_id") for row in working.get("source_statements", []) or []
        }
        statement = next(
            row for row in upgraded["source_statements"] if row["statement_id"] == statement_id
        )
        if statement_id not in existing_ids:
            add_statements.append(statement)
        working["source_statements"] = upgraded["source_statements"]
        working["assertions"] = [*(working.get("assertions", []) or []), materialized]
        add_assertions.append(materialized)
        for s in spans:
            remove.append(
                {
                    "start": s["start"],
                    "end": s["end"],
                    "reason": s["reason"],
                    "surface_form": s.get("surface_form", ""),
                }
            )
        outcomes["resolved_spans"] += len(spans)
        outcomes["assertions"] += 1
        outcomes[f"gate:{gate.status}"] += 1
        outcomes[f"subfamily:{candidate.subfamily}"] += 1
        outcomes[f"arity:{len(candidate.operands)}"] += 1
        outcomes[f"language:{record.get('language', '')}"] += len(spans)
        audit.extend(
            {
                "status": "resolved",
                "span": s,
                "assertion": materialized,
                "clause": text[candidate.clause_start : candidate.clause_end],
            }
            for s in spans
        )
    if not add_assertions:
        return None, outcomes, audit
    delta = {
        "key": {
            "source": record.get("source"),
            "source_id": record.get("source_id"),
            "source_segment_index": record.get("source_segment_index"),
            "taxon": record.get("taxon"),
            "organ": record.get("organ"),
            "char_start": record.get("char_start"),
            "char_end": record.get("char_end"),
        },
        "add_source_statements": add_statements,
        "add_assertions": add_assertions,
        "remove_unresolved": remove,
    }
    return delta, outcomes, audit


# --------------------------------------------------------------------------------------------- #
# Delta application.
# --------------------------------------------------------------------------------------------- #


def delta_key(record: dict[str, Any]) -> tuple:
    return (
        record.get("source"),
        record.get("source_id"),
        record.get("source_segment_index"),
        record.get("taxon"),
        record.get("organ"),
        record.get("char_start"),
        record.get("char_end"),
    )


def apply_delta_to_record(record: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(record)
    statements = list(out.get("source_statements", []) or [])
    known = {row.get("statement_id") for row in statements}
    for statement in delta.get("add_source_statements", []):
        if statement["statement_id"] not in known:
            statements.append(statement)
            known.add(statement["statement_id"])
    assertions = list(out.get("assertions", []) or [])
    for assertion in delta.get("add_assertions", []):
        if assertion.get("source_statement_id") not in known:
            raise ValueError("delta assertion references an unknown source statement")
        assertions.append(assertion)
    removals = Counter(
        (row["start"], row["end"], row["reason"]) for row in delta.get("remove_unresolved", [])
    )
    kept = []
    for span in out.get("unresolved_spans", []) or []:
        key = (span.get("start"), span.get("end"), span.get("reason"))
        if removals.get(key, 0) > 0:
            removals[key] -= 1
            continue
        kept.append(span)
    if any(count > 0 for count in removals.values()):
        raise ValueError("delta removes an unresolved span that is not present")
    out["source_statements"] = statements
    out["assertions"] = assertions
    out["unresolved_spans"] = kept
    return out


def apply_delta_file(input_path: Path, delta_path: Path, output_path: Path) -> dict[str, int]:
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("patched output must be distinct from the input corpus")
    deltas: dict[tuple, dict[str, Any]] = {}
    with Path(delta_path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                key = tuple(row["key"][name] for name in (
                    "source", "source_id", "source_segment_index", "taxon", "organ",
                    "char_start", "char_end",
                ))
                if key in deltas:
                    raise ValueError(f"duplicate delta key {key}")
                deltas[key] = row
    applied = 0
    with Path(input_path).open(encoding="utf-8") as source, Path(output_path).open(
        "w", encoding="utf-8"
    ) as output:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            delta = deltas.get(delta_key(record))
            if delta is not None:
                record = apply_delta_to_record(record, delta)
                applied += 1
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    if applied != len(deltas):
        raise ValueError(f"applied {applied} of {len(deltas)} delta lines")
    return {"deltas": len(deltas), "applied": applied}


# --------------------------------------------------------------------------------------------- #
# Driver.
# --------------------------------------------------------------------------------------------- #


def run(
    input_path: Path, out_dir: Path, *, sample_size: int = 160, seed: int = 20260918
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    gate_context = GateContext.load()
    outcomes: Counter[str] = Counter()
    resolved_rows: list[dict[str, Any]] = []
    residual_examples: defaultdict[str, list[str]] = defaultdict(list)
    residual_by_language: Counter[str] = Counter()
    total_targets = 0
    with Path(input_path).open(encoding="utf-8") as source, (out_dir / "delta.jsonl").open(
        "w", encoding="utf-8"
    ) as delta_out:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            total_targets += sum(
                1
                for span in record.get("unresolved_spans", []) or []
                if span.get("reason") == TARGET_REASON
            )
            delta, record_outcomes, audit = recover_record(record, gate_context)
            outcomes.update(record_outcomes)
            text = str(record.get("text", "") or "")
            for row in audit:
                span = row["span"]
                if row["status"] == "resolved":
                    resolved_rows.append(
                        {
                            "key": f"{record['source']}:{record['source_id']}:"
                            f"{record['source_segment_index']}",
                            "language": record.get("language", ""),
                            "span": f"{span['start']}-{span['end']}:{span['surface_form']}",
                            "window": text[max(0, span["start"] - 90) : span["end"] + 60],
                            "assertion": _assertion_summary(row["assertion"]),
                            "subfamily": next(
                                p.split(":", 1)[1]
                                for p in row["assertion"]["mapping_provenance"]
                                if p.startswith("subfamily:")
                            ),
                        }
                    )
                else:
                    residual_by_language[f"{record.get('language', '')}:{row['reason']}"] += 1
                    if len(residual_examples[row["reason"]]) < 6:
                        residual_examples[row["reason"]].append(
                            text[max(0, span["start"] - 50) : span["end"] + 30]
                        )
            if delta is not None:
                delta_out.write(json.dumps(delta, ensure_ascii=False) + "\n")
    sample = _stratified_sample(resolved_rows, sample_size, seed)
    with (out_dir / "sample-review-draft.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["span", "text_window", "assertion", "verdict", "note", "key", "stratum"])
        for row in sample:
            writer.writerow(
                [
                    row["span"],
                    row["window"].replace("\t", " ").replace("\n", " "),
                    row["assertion"],
                    "",
                    "",
                    row["key"],
                    f"{row['language']}/{row['subfamily']}",
                ]
            )
    report = {
        "input": str(input_path),
        "target_spans": total_targets,
        "outcomes": dict(sorted(outcomes.items())),
        "residual_by_language_reason": dict(sorted(residual_by_language.items())),
        "residual_examples": dict(residual_examples),
        "resolved_rows": len(resolved_rows),
        "sample_size": len(sample),
    }
    (out_dir / "run-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return report


def _assertion_summary(assertion: dict[str, Any]) -> str:
    return (
        f"{assertion['po_id']}({assertion['raw_entity_text']}) {assertion['pato_id']} one_of "
        f"[{'|'.join(assertion['value_terms'])}] freq={assertion['frequency_qualifier']} "
        f"gate={assertion['gate']['status']}"
    )


def _stratified_sample(
    rows: list[dict[str, Any]], size: int, seed: int
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    strata: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strata[f"{row['language']}/{row['subfamily']}"].append(row)
    if not rows:
        return []
    chosen: list[dict[str, Any]] = []
    # Proportional allocation with at least two rows per stratum.
    for name in sorted(strata):
        members = strata[name]
        quota = max(2, round(size * len(members) / len(rows)))
        chosen.extend(rng.sample(members, min(quota, len(members))))
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("input", type=Path)
    run_parser.add_argument("out_dir", type=Path)
    run_parser.add_argument("--sample-size", type=int, default=160)
    run_parser.add_argument("--seed", type=int, default=20260918)
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("input", type=Path)
    apply_parser.add_argument("delta", type=Path)
    apply_parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        report = run(args.input, args.out_dir, sample_size=args.sample_size, seed=args.seed)
        print(json.dumps({k: report[k] for k in ("target_spans", "outcomes")}, indent=1))
    else:
        print(json.dumps(apply_delta_file(args.input, args.delta, args.output)))


if __name__ == "__main__":
    main()
