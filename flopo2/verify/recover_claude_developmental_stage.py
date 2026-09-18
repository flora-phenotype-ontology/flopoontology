"""Recover ``developmental_stage_context`` residuals by explicit clause-scope analysis.

The deterministic baseline withholds *every* value in a semicolon/sentence clause that mentions an
age, maturity, specimen-state, or transition word.  The earlier v3 developmental-stage pass
(:mod:`flopo2.extract.developmental_stage_recovery`) could only promote values whose bearer was
found by the closed lexical resolvers, so ~19k residual spans remained without a bearer although
flora prose names it explicitly as the clause subject (``Leaves ..., ..., pubescent when young``).

This pass models the telegraphic flora clause directly:

* The **subject** of a value is the bearer noun that opens its comma member (``petiole
  pubescent``) or, failing that, the noun that opens the clause (``Leaves elliptic, ...``).  The
  subject is accepted only when it is a closed baseline bearer cue or a unique exact PO form, and
  only when no other structure noun, relative clause, ``with``-phrase, or sub-subject member lies
  between the subject and the value.  A structured organ heading is admitted only for the first
  clause of a segment that names no structure before the value.
* Route **S1 — stage-bound value.**  An age/maturity cue that directly binds the subject
  (``young leaves``, ``jeunes rameaux``) or directly follows/precedes the value inside its own
  comma member (``pubescent when young``, ``rouges à maturité``) is added as a conjunctive
  ``bearer_context_qualities`` PATO quality (young/old/juvenile/mature only; ``immature`` is
  never promoted because it frequently heads the bearer noun phrase).
* Route **S2 — stage provably out of scope.**  The value's comma member carries no conditioning
  cue; every cue in the clause sits in another member that contains its own value, does not open a
  sub-subject between the subject and this value, is not a bare forward-scoping stage member, and
  does not condition a value of the *same attribute family* (``green, ..., red at maturity`` keeps
  ``green`` residual because it is the implicit immature colour).  The value is recovered without
  a stage as ``normalization_status = context_override``.

* **E3 positional scope (v3).**  A value blocked only by an attached surface cue (``glabre
  dessus``), region cue (``acuminé au sommet``, ``dans la partie inférieure``) or hair cue
  (``brown hairy``, ``poils bruns``) is re-analysed with the cue blanked; the bearer is then the
  reviewed PO surface/region class (``bearer_scope``, :mod:`flopo2.annotation.positional`), a pinned
  BSPO region part restriction, or a trichome part carrying the hair colour.

Specimen state (``when dry``), reproductive phase, transitions (the transitioning member and the
member it transitions from), disjunctions, comparatives, locative sub-regions, and every span
whose subject is not provable remain residual.  No identifier is minted: bearers come from the
baseline cue table or exact PO forms, qualities from the baseline candidate PATO id, and a
recovery is emitted only when the assertion passes the composition check and the production gate
as ``accepted`` with an ``allowed`` PO–PATO combination.

The input corpus is never modified.  :func:`build_delta` writes a per-segment delta, and
:func:`apply_delta` materializes it onto a distinct copy for validation.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import re
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterator

from flopo2.annotation.positional import (
    BSPO_APICAL_REGION,
    BSPO_BASAL_REGION,
    BSPO_MARGIN,
    HAS_PART,
    TRICHOME,
    find_surface_cues,
    po_scope_within,
    surface_scope,
)
from flopo2.annotation.provenance import ensure_source_statements
from flopo2.extract import baseline
from flopo2.extract.compose import check_assertion as compose_check
from flopo2.extract.compose import _assertions_from_json
from flopo2.extract import context_recovery as cr
from flopo2.extract.context_recovery import (
    COMPARATIVE_CONTEXT,
    UNSCOPED_BEARER_BLOCKER,
    BearerMatch,
    _assertion,
)
from flopo2.extract.developmental_stage_recovery import (
    COMPARATIVE_STAGE,
    CONDITIONING_CUE,
    _preposed_paren_caveat,
    _real_disjunction,
)
from flopo2.extract.ground import load_lexicons
from flopo2.extract.leaflet_context import leaflet_bearer
from flopo2.owl.annotation_class import ensure_annotation_class_iri
from flopo2.verify.gates import (
    check_assertion as gate_check,
    load_catalog_ids,
    load_combinations,
    load_eq_registry,
    load_flopo_ids,
    load_pato_attribute_terms,
    load_signature_registry,
)
from flopo2.verify.missing_bearers import _fold, _po_exact_forms

TARGET_REASON = "developmental_stage_context"
EXTRACTOR = "claude_developmental_stage_scope_recovery_v1"
CATEGORY = "developmental_stage"

# --- Stage cues --------------------------------------------------------------------------------
# PATO ids exactly as used by the audited v3 module (owl-review/pato_axes.tsv): young, old,
# juvenile, mature.  ``immature`` is deliberately absent (conditional in the axis review).
STAGE_PATO = {
    "young": "PATO_0000309",
    "old": "PATO_0000308",
    "juvenile": "PATO_0001190",
    "mature": "PATO_0001701",
}

# Prenominal/postnominal age adjective directly binding a subject noun.
AGE_ADJECTIVE = re.compile(
    r"(?P<young>young(?:er|est)?|jeunes?)|(?P<old>old(?:er|est)?|vieux|vieil(?:le|les)?)|"
    r"(?P<juvenile>juvenile|juv[ée]niles?)|(?P<mature>mature)",
    re.IGNORECASE,
)

# A predicate stage phrase binding the adjacent value in the same comma member.
AGE_PREDICATE = re.compile(
    r"(?<!\w)(?:"
    r"(?P<young>when\s+young|while\s+young|[àa]\s+l['’]état\s+jeune|lorsqu(?:e|'|’)\s*jeunes?|"
    r"au\s+jeune\s+âge|dans\s+le\s+jeune\s+âge)|"
    r"(?P<old>when\s+old|[àa]\s+l['’]état\s+âgé(?:e|s|es)?)|"
    r"(?P<mature>when\s+mature|at\s+maturity|[àa]\s+maturit[ée]|[àa]\s+l['’]état\s+adulte|"
    r"au\s+stade\s+(?:mature|adulte))"
    r")(?!\w)",
    re.IGNORECASE,
)
PREDICATE_BRIDGE = re.compile(
    r"^\s*(?:(?:even|already|only|still|m[êe]me|d[ée]j[àa]|seulement|encore)\s+)?$",
    re.IGNORECASE,
)

# Every cue that made the baseline withhold the clause (mirrors ``baseline._negated_or_hedged``),
# plus French ``à l'état`` constructions.  Used to locate the conditioning members of a clause.
ANY_STAGE_CUE = re.compile(
    r"(?<!\w)(?:young(?:er|est)?|old(?:er|est)?|juvenile|immature|mature|adults?|adultes?|"
    r"ripe|unripe|seedlings?|saplings?|plantules?|"
    r"when\s+young|at\s+maturity|when\s+mature|when\s+dry|when\s+fresh|"
    r"drying|dried|later|eventually|becoming|"
    r"jeunes?|vieil(?:le|les)?|vieux|âg[ée](?:e?s?)?|"
    r"juv[ée]niles?|m[ûu]r(?:e|es|s)?|sec|s[èe]che|"
    r"devenant|plus\s+tard|[àa]\s+maturit[ée]|[àa]\s+l['’]état\s+\w+|"
    r"lorsqu(?:e|'|’)\s*jeunes?)(?!\w)",
    re.IGNORECASE,
)
TRANSITION_CUE = re.compile(
    r"(?<!\w)(?:later|eventually|becoming|becomes?|turning|turns?|going|goes|changing|then|at\s+length|"
    r"at\s+first|initially|soon|quickly|rapidly|early|finally|devenant|devient|puis|plus\s+tard|"
    r"d['’]abord|rapidement|bient[ôo]t|vite|t[ôo]t|"
    r"ensuite|finalement|tardivement|glabrescent|glabrescents?|glabrescentes?|caducous|"
    r"caduques?)(?!\w)",
    re.IGNORECASE,
)

# A comma member consisting solely of a stage cue forward/back-scopes ambiguously.
BARE_STAGE_MEMBER = re.compile(
    r"^\s*[(\[]?\s*(?:(?:very|très|tres|when|while|lorsqu[e'’]|[àa]\s+l['’]état(?:\s+de)?|"
    r"au\s+stade|at|even|m[êe]me|only|seulement|especially|surtout|particularly)\s+)*"
    r"(?:young(?:er|est)?|old(?:er|est)?|juvenile|immature|mature|maturity|jeunes?|vieux|"
    r"vieilles?|âg[ée]e?s?|adultes?|maturit[ée]|jeunesse|dry|fresh|sec|frais)"
    r"\s*[)\]]?\s*$",
    re.IGNORECASE,
)

ALTERNATIVE_OPENER = re.compile(
    r"^\s*(?:[(\[]\s*)?(?:or|ou|sometimes|occasionally|rarely|seldom|often|usually|mostly|"
    r"parfois|rarement|souvent|quelquefois|occasionnellement|g[ée]n[ée]ralement|"
    r"ordinairement|habituellement|plus\s+rarement|but|mais|ou\s+bien|either|soit)(?!\w)",
    re.IGNORECASE,
)
SHAPE_MODIFIER_BEFORE = re.compile(
    r"(?<!\w)(?:depressed|d[ée]prim[ée]\w*|compressed|comprim[ée]\w*|flattened|aplati\w*|"
    r"obliquely|obliquement|irregularly|irr[ée]guli[èe]rement|asymmetrically)\s+$",
    re.IGNORECASE,
)
SHAPE_MODIFIER_AFTER = re.compile(
    r"^\s+(?:(?:±|\+/-|more\s+or\s+less|plus\s+ou\s+moins|slightly|légèrement|un\s+peu|"
    r"somewhat|often|souvent|très|very)\s+)*"
    r"(?:depressed|d[ée]prim[ée]\w*|compressed|comprim[ée]\w*|flattened|aplati\w*)(?!\w)",
    re.IGNORECASE,
)
# ``(sub)globose`` / ``(ob)ovate`` denote a two-value alternative, not the bare value.
PARENTHETICAL_PREFIX = re.compile(r"\(\s*[A-Za-zÀ-ÖØ-öø-ÿ]{1,14}\s*[-–]?\s*\)\s*[-–]?\s*$")
# Reproductive-phase cues: not recovered here, but a value of the same family elsewhere in the
# clause is phase-dependent (``sepals 6-9 mm long, ..., in fruit 9-18 mm long``).
PHASE_CUE = re.compile(
    r"(?<!\w)(?:in\s+fruit|in\s+flower|in\s+bud|at\s+anthesis|after\s+anthesis|"
    r"at\s+flowering|in\s+fruiting|fruiting|accrescent|enlarg\w*|en\s+fruits?|"
    r"en\s+fleurs?|en\s+bouton|[àa]\s+l['’]anth[èe]se|apr[èe]s\s+l['’]anth[èe]se|"
    r"[àa]\s+la\s+(?:floraison|fructification)|accrescent\w*|ripening|ripens?|"
    r"in\s+age|with\s+age|avec\s+l['’]âge)(?!\w)",
    re.IGNORECASE,
)
SUB_PREFIX = re.compile(r"(?<!\w)(?:sub|ob|semi|demi|sous|sesqui|hemi)[-–\s]*$", re.IGNORECASE)
SEX_CATEGORY = re.compile(
    r"[♂♀⚥☿]|(?<!\w)(?:male|female|staminate|pistillate|hermaphrodite|bisexual|sterile|fertile|"
    r"m[âa]les?|femelles?|st[ée]riles?|fertiles?|hermaphrodites?)(?!\w)",
    re.IGNORECASE,
)
POSITIONAL_CATEGORY = re.compile(
    r"(?<!\w)(?:basal|basilaires?|radical\w*|cauline|caulinaires?|upper|lower|uppermost|"
    r"lowermost|middle|median\w*|médian\w*|sup[ée]rieur\w*|inf[ée]rieur\w*|terminal\w*|"
    r"lateral\w*|latéra\w*|apical\w*|distal\w*|proximal\w*|inner|outer|internes?|externes?|"
    r"primary|secondary|primaires?|secondaires?|ultimate|ultimes?|floral\w*|"
    r"florifères?|fertile\w*|sterile\w*|vegetative|végétati\w*|interior|exterior)(?!\w)",
    re.IGNORECASE,
)
SPECIMEN_PREDICATE = re.compile(
    r"(?:when\s+(?:dry|dried|fresh|living)|on\s+drying|in\s+(?:the\s+)?(?:dry|dried|fresh)\s+"
    r"(?:state|material|specimens?)|in\s+sicco|in\s+vivo|[àa]\s+l['’]état\s+(?:sec|frais)|"
    r"[àa]\s+sec|sur\s+le\s+(?:sec|frais|vif|vivant)|[àa]\s+frais|[àa]\s+la\s+dessiccation)(?!\w)",
    re.IGNORECASE,
)
IMMATURE_CAVEAT = re.compile(
    r"(?<!\w)(?:immature|unripe|not\s+(?:yet\s+)?(?:mature|ripe)|non\s+(?:encore\s+)?m[ûu]r\w*|"
    r"pas\s+(?:encore\s+)?m[ûu]r\w*|encore\s+jeunes?|seen\s+only|only\s+known|"
    r"imparfaitement\s+connu\w*|incompl[èe]te?ment\s+connu\w*)(?!\w)",
    re.IGNORECASE,
)
# Sub-regional scope words the audited SURFACE_LOCATIVE list does not cover (``pubescent
# outside``, ``glabrous within``): the quality belongs to a surface/part, not the whole bearer.
REGION_WORD = re.compile(
    r"(?<!\w)(?:outside|inside|within|without|outwardly|inwardly|dorsally|ventrally|"
    r"at\s+the\s+(?:base|apex|tip|top|margins?|nodes?|mouth|throat)|near\s+the\s+\w+|"
    r"towards?\s+the\s+\w+|on\s+the\s+(?:\w+\s+)?(?:side|face|surface|margins?|nerves?|veins?|midrib)s?|"
    r"along\s+the\s+\w+|in\s+the\s+(?:upper|lower|basal|apical)\s+\w+|"
    r"en\s+dehors|en\s+dedans|à\s+l['’](?:intérieur|extérieur)|intérieurement|extérieurement|"
    r"dorsalement|ventralement|[àa]\s+la\s+(?:base|marge|gorge)|au\s+(?:sommet|bord|niveau)|"
    r"aux\s+(?:n[œo]uds|bords|aisselles)|sur\s+(?:la|les|le)\s+\w+|dans\s+(?:la|les|le)\s+"
    r"(?:partie|parties|moitié)\s+\w+)(?!\w)",
    re.IGNORECASE,
)
COMPARATIVE_BEFORE = re.compile(
    r"(?<!\w)(?:plus|moins|more|less|rather\s+more|much\s+more|bien\s+plus|aussi|as|"
    r"too|trop)\s+$",
    re.IGNORECASE,
)
# A value whose own member opens with a frequency adverb (``sometimes glabrous``) is itself the
# qualified alternative; the frequency qualifier is captured by the modality parser.
FREQUENCY_OPENER = re.compile(
    r"^\s*(?:sometimes|rarely|occasionally|seldom|parfois|rarement|plus\s+rarement|"
    r"quelquefois|occasionnellement)(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ]+ly|\s+l[ée]g[èe]rement|\s+un\s+peu|"
    r"\s+only|\s+seulement)*\s*$",
    re.IGNORECASE,
)
COLOUR_SHADE = re.compile(
    r"(?:golden|gold|dor[ée]\w*|rich|deep|dull|vivid|intense|coppery|copper|metallic|silvery|"
    r"argent\w*|cuivr\w*|chestnut|ivory|straw|sombre|vif|vive|terne|light|lighter|darker|"
    r"bright|brilliant|matt|mat|brick|wine|lemon|bluish|pinkish|dirty|sale|leaden|livid)",
    re.IGNORECASE,
)
# Whole-plant (habit) measurements are admitted only for height; ``tree reaching 30 cm diam.``
# is a trunk diameter, not a whole-plant diameter.
WHOLE_PLANT_MEASURES = {"PATO_0000119"}

# --- Attribute families for the same-family contrast rule --------------------------------------
OUTLINE_PATO = {
    "PATO_0000946",
    "PATO_0000947",
    "PATO_0001199",
    "PATO_0001499",
    "PATO_0001877",
    "PATO_0001891",
    "PATO_0005014",
}
TIP_PATO = {"PATO_0001935", "PATO_0001982", "PATO_0002228"}
FAMILY = {
    **{pato: "colour" for pato in baseline.COLOR_PATO_IDS},
    **{pato: "outline" for pato in OUTLINE_PATO},
    **{pato: "tip" for pato in TIP_PATO},
    "PATO_0000453": "pilosity",
    "PATO_0001320": "pilosity",
    "PATO_0002341": "pilosity",
    "PATO_0000701": "texture",
    "PATO_0002358": "texture",
    "PATO_0104032": "consistency",
    "PATO_0000402": "branching",
    "PATO_0001436": "attachment",
    "PATO_0000622": "orientation",
}
# Coarse families for the "conditioned elsewhere" rule: any stage-conditioned shape or surface
# word elsewhere in the clause blocks a plain value of that coarse family.
COARSE = {"outline": "shape", "tip": "shape", "pilosity": "surface", "texture": "surface"}
FAMILY_WORDS = {
    "colour": re.compile(
        r"(?<!\w)(?:white|black|red|green|yellow|brown|grey|gray|orange|purple|violet|pink|"
        r"cream|blue|crimson|scarlet|purplish|reddish|brownish|greenish|yellowish|whitish|"
        r"blackish|greyish|coloured|colored|pale|dark|glaucous|ferrugineous|rusty|"
        r"blanc\w*|noir\w*|rouge\w*|vert\w*|jaune\w*|brun\w*|gris\w*|orang\w*|pourpre\w*|"
        r"violac\w*|ros[ée]\w*|roux|rousse\w*|bleu\w*|fonc[ée]\w*|clair\w*|p[âa]le\w*|"
        r"sombre\w*|olive\w*|couleur|color|colour|verd\w*|jaun\w*|ferrugin\w*|marron\w*|"
        r"olivac\w*|olivâtre\w*|purpurin\w*|écarlate\w*|pink\w*|rosy|mauve\w*)(?!\w)",
        re.IGNORECASE,
    ),
    "pilosity": re.compile(
        r"(?<!\w)(?:glab\w*|pub\w*|toment\w*|hair\w*|hirsut\w*|pilos\w*|villo\w*|velut\w*|"
        r"veluti\w*|sericeous|silky|scabr\w*|strigos\w*|strigu\w*|hisp\w*|lanate|woolly|"
        r"floccose|farinose|lepidote|scaly|velvety|puberul\w*|velout\w*|soyeu\w*|poilu\w*|"
        r"velu\w*|pubérul\w*|hérissé\w*|ciliat\w*|cili[ée]\w*|indument\w*|pubescence|"
        r"squam\w*|écaill\w*|hirtell\w*|setul\w*|setose|glandular|glanduleu\w*|laineu\w*|"
        r"cotonneu\w*|furfurac\w*|arachn\w*)(?!\w)",
        re.IGNORECASE,
    ),
    "texture": re.compile(
        r"(?<!\w)(?:smooth|rough|rugose|rugulose|lisses?|rugueu\w*|papill\w*|verruc\w*|warty|"
        r"ridged|c[ôo]tel\w*|striat\w*|stri[ée]\w*|wrinkled|rid[ée]\w*|shiny|glossy|dull|"
        r"lustrous|luisant\w*|brillant\w*|mat|mate|mates|tubercul\w*|granul\w*|pitted|"
        r"grooved|sillonn\w*|fissur\w*|cracked|crevass\w*|flaking|lenticell\w*)(?!\w)",
        re.IGNORECASE,
    ),
    "outline": re.compile(
        r"(?<!\w)(?:ellipt\w*|oblong\w*|ovat\w*|obov\w*|oval\w*|ov[ée]\w*|ovoid\w*|ovoïd\w*|"
        r"lanc\w*|linea\w*|linéa\w*|globo\w*|globul\w*|subglob\w*|spheric\w*|"
        r"sph[ée]ri\w*|orbicul\w*|suborbicul\w*|ellipsoid\w*|fusiform\w*|cylindri\w*|"
        r"terete|oblanc\w*|spathul\w*|falci\w*|rhomb\w*|deltoid\w*|triangul\w*|"
        r"reniform\w*|cordiform\w*|pyriform\w*|piriform\w*|clavate|claviform\w*|"
        r"conic\w*|coniqu\w*|campanul\w*|tubular|tubuleu\w*|infundibul\w*|urceol\w*|"
        r"shape\w*|forme|outline|contour)(?!\w)",
        re.IGNORECASE,
    ),
    "tip": re.compile(
        r"(?<!\w)(?:acumin\w*|attenuat\w*|atténu\w*|obtus\w*|acute|aigu\w*|subaigu\w*|"
        r"subacute|round\w*|arrondi\w*|cordate|cord[ée]\w*|subcord\w*|cuneate|cun[ée]\w*|"
        r"truncate|tronqu\w*|emargin\w*|échancr\w*|mucron\w*|apicul\w*|caudate|cuspid\w*|"
        r"pointed|pointu\w*|retuse|rétus\w*|décurrent\w*|decurrent|acuminate|aristate)(?!\w)",
        re.IGNORECASE,
    ),
    "consistency": re.compile(
        r"(?<!\w)(?:coria\w*|chartac\w*|papyrac\w*|membran\w*|herbac\w*|fleshy|charnu\w*|"
        r"woody|ligneu\w*|succulent\w*|thick\w*|thin|épais\w*|mince\w*|leathery|firm|"
        r"hard|dur\w*|soft|mou|molle\w*|spongy|corky|subéreu\w*|crustac\w*)(?!\w)",
        re.IGNORECASE,
    ),
    "branching": re.compile(r"(?<!\w)(?:branch\w*|ramifi\w*|simple\w*)(?!\w)", re.IGNORECASE),
    "attachment": re.compile(r"(?<!\w)(?:sessil\w*|stalked|pédicell\w*|petiolat\w*)(?!\w)", re.I),
    "orientation": re.compile(
        r"(?<!\w)(?:erect\w*|dress[ée]\w*|spreading|étal[ée]\w*|reflexed|réfléchi\w*|"
        r"pendulous|pendant\w*|ascending|ascendant\w*|patent\w*|deflexed|recurved|"
        r"recourb\w*|drooping|nodding)(?!\w)",
        re.IGNORECASE,
    ),
    "size": re.compile(
        r"\d|(?<!\w)(?:long|wide|broad|thick|diam\w*|large\w*|longs?|longues?|épais\w*|"
        r"enlarg\w*|accrescent\w*|elongat\w*|allong\w*|haut\w*|tall|high|small|big|larger|"
        r"smaller|longer|shorter|petit\w*|grand\w*|size|taille)(?!\w)",
        re.IGNORECASE,
    ),
}

# --- Subject / structure nouns ------------------------------------------------------------------
LEADING_FILLER = re.compile(
    r"(?:\s|[-–—•*:]|(?:the|a|an|les?|la|l['’]|des?|du|all|tous|toutes)\s+)*",
    re.IGNORECASE,
)
# Structure nouns that are not bearers in the closed cue table but open a sub-subject or a nested
# structure.  A value separated from its subject by one of these is not attributable.
STRUCTURE_NOUN = re.compile(
    r"(?<!\w)(?:hairs?|trichomes?|poils?|setae?|soies?|bristles?|scales?|écailles?|"
    r"glands?|glandes?|veins?|nerves?|nervures?|midribs?|costae?|margins?|marges?|bords?|"
    r"apex|apices|tips?|sommets?|pointes?|bases?|lobes?|teeth|tooth|dents?|surfaces?|faces?|"
    r"sides?|ribs?|côtes?|wings?|ailes?|spines?|épines?|prickles?|aiguillons?|lenticels?|"
    r"lenticelles?|indumentum|tomentum|pubescence|velours|cells?|cellules?|spots?|taches?|"
    r"lines?|stripes?|bands?|dots?|points?|patches?|stalks?|tubes?|throats?|gorges?|limb|"
    r"crown|couronne|disc|disque|lip|lèvres?|keels?|carènes?|awns?|arêtes?|pits?|"
    r"domatia|domaties?|parts?|parties?|portions?|ones?|areas?|zones?|portion|region|"
    r"joints?|nodes?|n[œo]uds?|internodes?|entre-n[œo]uds|stipes?|claws?|onglets?|"
    r"sutures?|beaks?|becs?|segments?|divisions?|pinnae?|pinnules?|rachis|rhachis|axis|axes|"
    r"sheaths?|gaines?|ligules?|auricles?|oreillettes?|flesh|chair|pulp|pulpe|embryos?|"
    r"cotyledons?|cotylédons?|albumen|endosperm|hilum|hile|funicles?|funicules?|"
    r"stones?|noyaux?|pyrenes?|pyrènes?|arils?|arilles?|coats?|tégument\w*|"
    r"ovules?|locules?|loges?|placentas?|columns?|colonnes?|columella|spurs?|éperons?|"
    r"calyx|calyces|corolla|anthers?|filaments?|stamens?|styles?|stigmas?|ovary|ovaries)(?!\w)",
    re.IGNORECASE,
)
SUBJECT_SHIFT = re.compile(
    r"(?<!\w)(?:which|that|whose|where|those|these|each|qui|que|dont|lequel|laquelle|"
    r"lesquel(?:le)?s|celles?|ceux|celui|chaque|with|avec|without|sans|bearing|having|"
    r"covered|couvert\w*|garni\w*|muni\w*|pourvu\w*|portant|except|sauf|but|mais|"
    r"than|que|as|like|comme|between|entre|of|de|des|du|d['’]|in|on|dans|sur|at|au|aux|"
    r"à|to|towards?|vers|near|près|below|beneath|above|under|sous|par|by|from|en)(?!\w)",
    re.IGNORECASE,
)
# Locative phrases that restrict *their own* member only (``cordate at the base``).  When such a
# member opens with a value, the clause subject continues past it.
OWN_MEMBER_LOCATIVE = re.compile(
    r"(?<!\w)(?:at|near|towards?|to)\s+(?:the\s+)?(?:apex|base|tip|summit|top|margins?)|"
    r"(?:[àa]\s+la|vers\s+la|près\s+de\s+la)\s+base|(?:au|vers\s+le)\s+sommet|"
    r"[àa]\s+l['’](?:apex|extrémité)|(?:on|sur)\s+(?:both|the\s+two|les\s+(?:2|deux))\s+"
    r"(?:surfaces|sides|faces)|(?:above|beneath|below|en\s+dessus|en\s+dessous)(?!\w)",
    re.IGNORECASE,
)
ADVERB = (
    r"(?:very|rather|quite|somewhat|slightly|densely|sparsely|shortly|finely|minutely|"
    r"thinly|thickly|softly|closely|usually|often|sometimes|always|generally|mostly|"
    r"entirely|completely|strongly|weakly|distinctly|conspicuously|±|more\s+or\s+less|"
    r"très|tres|assez|un\s+peu|peu|légèrement|densément|finement|brièvement|courtement|"
    r"souvent|parfois|toujours|généralement|entièrement|complètement|nettement|"
    r"plus\s+ou\s+moins|fort|bien)"
)


@dataclass(frozen=True)
class Subject:
    po_id: str
    surface: str
    start: int
    end: int
    method: str
    stage: str = ""  # STAGE_PATO key bound adjectivally to the subject
    stage_start: int = -1
    stage_end: int = -1


@dataclass(frozen=True)
class ScopeCue:
    """A positional cue directly attached to the value (E3): a surface side or a region."""

    kind: str  # "surface" | "region"
    name: str  # surface: adaxial/abaxial/outside/inside; region: apex/base/margin
    start: int  # verbatim cue offsets (without an absorbed preposition)
    end: int
    mask_start: int  # span blanked for clause analysis (cue plus a preceding ``à``/``with``)
    mask_end: int


@dataclass(frozen=True)
class Decision:
    route: str  # "S1" | "S2" | ""
    reason: str
    subject: Subject | None = None
    stage: str = ""
    stage_start: int = -1
    stage_end: int = -1
    scope: ScopeCue | None = None


def _members(text: str, clause_left: int, clause: str) -> list[tuple[int, int]]:
    """Absolute bounds of comma members, not splitting French decimal commas or parentheses."""

    bounds: list[tuple[int, int]] = []
    depth = 0
    prev = 0
    for idx, char in enumerate(clause):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            if (
                0 < idx < len(clause) - 1
                and clause[idx - 1].isdigit()
                and clause[idx + 1].isdigit()
            ):
                continue
            bounds.append((clause_left + prev, clause_left + idx))
            prev = idx + 1
    bounds.append((clause_left + prev, clause_left + len(clause)))
    return bounds


def _member_index(bounds: list[tuple[int, int]], position: int) -> int:
    for index, (low, high) in enumerate(bounds):
        if low <= position < high or (position == high and index == len(bounds) - 1):
            return index
    return -1


def _paren_depth(text: str, low: int, position: int) -> int:
    depth = 0
    for char in text[low:position]:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
    return depth


ADJECTIVE_SUFFIX = re.compile(
    r"(?:ous|ate|ated|ed|al|ic|ical|ose|oid|ish|ar|ent|ant|ile|ing|less|ful|ary|ive|ly|form|"
    r"like|id|ular|y|é|ée|és|ées|eux|euse|euses|aire|aires|ique|iques|if|ive|ifs|ives|ale|"
    r"aux|ales|ante|ants|antes|ente|ents|entes|iles|âtre|âtres|ine|ines|formes|u|ue|us|ues)$",
    re.IGNORECASE,
)
NON_ADJECTIVE_WORDS = re.compile(
    r"(?:ring|rings|body|bodies|cavity|cavities|wing|wings|seed|seeds|opening|openings|"
    r"covering|lining|segment|segments|tégument|téguments|integument|filament|filaments|"
    r"ovaire|ovary|plant|plants|pedicel|petal|sepal|tepal|interval|stalk|base|bases|rim|"
    r"acumen|acumens|apicule|mucro|mucron|cupule|cupules|cup|cups|gland|glands|pore|pores|"
    r"ostiole|ostioles|stipe|stipes|beak|bec|column|colonne|crest|crête|collar|collerette|"
    r"annulus|anneau|appendage|appendice|appendices|process|processes|valve|valves|"
    r"columella|flange|lamella|lamelle|lamelles|margin|marge|bord|apex|sommet|tip|pointe)$",
    re.IGNORECASE,
)
VALUE_OPENER_SKIP = re.compile(
    rf"(?:\s|[(±~≈]|c\.|ca\.|{ADVERB}(?!\w)|(?:up\s+to|to|jusqu['’]à|atteignant|reaching|"
    r"at|when|while|lorsqu(?:e|['’])|[àa]|au|aux|en|in|on|sur|near|towards?|vers|from|de|d['’]|"
    r"not|non|pas|ne|but|mais|and|et|with|avec|sans|without)(?!\w))*",
    re.IGNORECASE,
)


def _opens_like_value(text: str, low: int, high: int) -> bool:
    """Whether a comma member opens with a value (not a possible sub-subject noun)."""

    segment = text[low:high]
    stripped = segment.lstrip(" \t\n-–—")
    if not stripped:
        return True
    if re.match(
        r"(?:the|les|la|le|l['’]|those|these|some|certain\w*|each|chaque|other\w*|"
        r"autres?|d['’]autres|one|ones|all|tous|toutes|most|many|plusieurs|quelques)(?!\w)",
        stripped,
        re.IGNORECASE,
    ):
        return False
    offset = low + (len(segment) - len(stripped))
    skip = VALUE_OPENER_SKIP.match(text, offset, high)
    position = skip.end() if skip else offset
    rest = text[position:high]
    if not rest.strip() or re.match(r"\s*[\d(]", rest):
        return True
    if any(cue.pattern.match(text, position, high) for cue in baseline.QUALITY_PATTERNS):
        return True
    word = re.match(r"([A-Za-zÀ-ÖØ-öø-ÿ'’]+)", rest)
    if not word:
        return True
    token = word.group(1)
    if NON_ADJECTIVE_WORDS.fullmatch(token) or STRUCTURE_NOUN.fullmatch(token):
        return False
    if any(pattern.match(token) and pattern.fullmatch(token) for pattern in FAMILY_WORDS.values()):
        return True
    return bool(ADJECTIVE_SUFFIX.search(token))


class SubjectResolver:
    """Resolve the noun opening a member/clause to exactly one PO id, or nothing."""

    def __init__(self, exact_po_forms: dict[tuple[str, ...], set[str]]) -> None:
        self.exact = exact_po_forms

    def _exact_form(self, text: str, start: int) -> tuple[str, int] | None:
        tokens = list(
            re.finditer(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]*", text[start : start + 80])
        )
        best: tuple[str, int] | None = None
        for width in range(1, min(4, len(tokens)) + 1):
            chosen = tokens[:width]
            if chosen[0].start() != 0:
                return None
            if (
                width > 1
                and text[
                    start + chosen[width - 2].end() : start + chosen[width - 1].start()
                ].strip()
            ):
                break
            folded = tuple(_fold(match.group(0)) for match in chosen)
            ids = set(self.exact.get(folded, ()))
            if not ids and folded[-1].endswith("s"):
                ids = set(self.exact.get((*folded[:-1], folded[-1][:-1]), ()))
            if len(ids) == 1:
                best = (next(iter(ids)), start + chosen[-1].end())
        return best

    def at(self, text: str, start: int, limit: int, *, introduced: bool = False) -> Subject | None:
        """Return the subject noun phrase starting at ``start`` (after fillers/stage adjective).

        With ``introduced``, a member may open with ``à``/``avec``/``with`` + subject (French
        ``à rameaux pubescents``); the subject must then be a closed baseline bearer cue.
        """

        filler = LEADING_FILLER.match(text, start, limit)
        position = filler.end() if filler else start
        via_introducer = False
        if introduced:
            intro = re.compile(r"(?:à|avec|with)\s+", re.IGNORECASE).match(text, position, limit)
            if intro:
                position = intro.end()
                via_introducer = True
        stage = ""
        stage_start = stage_end = -1
        adjective = AGE_ADJECTIVE.match(text, position, limit)
        if adjective and re.match(r"\s+\S", text[adjective.end() : limit]):
            stage = next(name for name, value in adjective.groupdict().items() if value)
            stage_start, stage_end = adjective.start(), adjective.end()
            position = adjective.end()
            position += len(text[position:limit]) - len(text[position:limit].lstrip())
        elif re.match(r"immature\s", text[position:limit], re.IGNORECASE):
            return None
        best: tuple[int, str, str] | None = None
        for po_id, pattern in baseline.LOCAL_BEARER_PATTERNS:
            match = pattern.match(text, position, limit)
            if match and (best is None or match.end() > best[0]):
                best = (match.end(), po_id, "clause_subject_baseline_cue")
        exact = None if via_introducer else self._exact_form(text[:limit], position)
        if exact and (best is None or exact[1] > best[0]):
            best = (exact[1], exact[0], "clause_subject_exact_po_form")
        if best is None:
            return None
        end, po_id, method = best
        if via_introducer:
            method = "member_subject_introduced"
        # A French postnominal stage adjective (``rameaux jeunes``) also binds the subject.
        if not stage:
            post = re.match(r"\s+(jeunes?|âg[ée]e?s?|vieux|adultes?)(?!\w)", text[end:limit], re.I)
            if post:
                word = post.group(1).casefold()
                if word.startswith("jeune"):
                    stage = "young"
                elif word.startswith("adulte"):
                    stage = "mature"
                else:
                    stage = "old"
                stage_start, stage_end = end + post.start(1), end + post.end(1)
        # The subject must be a complete noun phrase: reject ``leaf sheath`` read as ``leaf``.
        tail_end = stage_end if stage_end > end else end
        following = text[tail_end:limit]
        if re.match(r"\s*[-–]?\s*[A-Za-zÀ-ÖØ-öø-ÿ]", following):
            nxt = re.match(r"\s*([A-Za-zÀ-ÖØ-öø-ÿ'’-]+)", following)
            if nxt and (
                STRUCTURE_NOUN.fullmatch(nxt.group(1))
                or any(p.fullmatch(nxt.group(1)) for _i, p in baseline.LOCAL_BEARER_PATTERNS)
                or re.fullmatch(
                    r"(?:of|de|des|du|d['’].*|and|et|or|ou|with|avec|à|in|on)", nxt.group(1), re.I
                )
            ):
                return None
        if re.match(r"\s*[-–]", following) and not re.match(r"\s*[-–]\s*\d", following):
            return None
        surface = text[position:end]
        if re.search(
            r"(?<!\w)(?:male|female|staminate|pistillate|sterile|fertile|m[âa]les?|"
            r"femelles?|st[ée]riles?|fertiles?|lateral|terminal|basal|apical|upper|"
            r"lower|inner|outer|primary|secondary|latérales?|terminales?|"
            r"supérieures?|inférieures?|internes?|externes?)(?!\w)",
            text[max(start, position - 24) : min(limit, end + 24)],
            re.IGNORECASE,
        ):
            return None
        return Subject(po_id, surface, position, end, method, stage, stage_start, stage_end)


def _atomic_safe(text: str, start: int, end: int, pato_id: str) -> str:
    """The audited ``context_recovery._candidate_atomic_safe`` checks, minus two over-broad ones.

    ``_cross_comma_transition`` rejects any value followed within ~100 characters by a transition
    word; this module replaces it with member-precise transition scoping.  The French ``A à B``
    range guard additionally exempts the age predicates ``à l'état jeune/adulte/âgé``.
    Returns the failing check name, or ``""`` when safe.
    """

    phrase, _left = cr._comma_phrase(text, start)
    checks = (
        ("member_transition", cr.TRANSITION.search(phrase)),
        ("member_disjunction", cr.DISJUNCTIVE_BRIDGE.search(phrase)),
        ("member_range", cr.VALUE_RANGE_BRIDGE.search(phrase)),
        ("unmodelled_condition", cr.UNMODELLED_CONDITION.search(phrase)),
        ("comparative", cr.COMPARATIVE_CONTEXT.search(phrase)),
        ("exception", cr.EXCEPTION_CONTEXT.search(phrase)),
        ("hedged", cr.HEDGED_CONTEXT.search(phrase)),
        ("surface_locative", cr.SURFACE_LOCATIVE.search(phrase)),
        ("approximate", cr.APPROXIMATE_VALUE.search(text[max(0, start - 24) : start])),
        ("numeric_comparator", cr._unsupported_numeric_comparator(text, start)),
        ("unmodelled_bearer", cr._unmodelled_bearer_category(text, start)),
        ("postposed_parenthetical_stage", cr._postposed_parenthetical_stage(text, end)),
        ("questioned", cr._questioned_value(text, start, end)),
        ("compound", cr._compound_value(text, start, end, pato_id)),
        ("colour_alternative", cr._cross_comma_colour_alternative(text, end, pato_id)),
        ("value_alternative", cr._cross_comma_value_alternative(text, end)),
    )
    for name, failed in checks:
        if failed:
            return name
    pilosity = {"PATO_0000453", "PATO_0001320", "PATO_0002341"}
    if pato_id in pilosity and (
        cr.REGIONAL_PILOSITY.search(phrase) or cr.PILOSITY_TRANSITION.search(phrase)
    ):
        return "regional_or_transition_pilosity"
    if pato_id in cr.REGION_SCOPED_SHAPE_IDS and cr.REGIONAL_PILOSITY.search(phrase):
        return "region_scoped_shape"
    if pato_id in baseline.SHAPE_PATO_IDS and cr.SHAPE_COMPOUND_NEIGHBOR.search(
        text[max(0, start - 32) : start]
    ):
        return "shape_compound_neighbor"
    before = text[max(0, start - 48) : start]
    after = text[end : min(len(text), end + 48)]
    if re.search(
        r"\b[\wÀ-ÖØ-öø-ÿ'’-]+\s+à\s+"
        r"(?:(?:très|tres|un\s+peu|longuement|courtement|largement|étroitement|"
        r"obtusément|brusquement|et)\s+){0,4}$",
        before,
        re.IGNORECASE,
    ):
        return "french_range_before"
    if re.match(
        r"^\s+à\s+(?!maturit[ée]\b|l['’]état\s+(?:sec|jeune|adulte|âgé)\b)[A-Za-zÀ-ÖØ-öø-ÿ]",
        after,
        re.IGNORECASE,
    ):
        return "french_range_after"
    if pato_id in baseline.COLOR_PATO_IDS:
        prior_word = re.search(r"([A-Za-zÀ-ÖØ-öø-ÿ'’-]+)\s*$", before)
        next_word = re.match(r"^\s*([A-Za-zÀ-ÖØ-öø-ÿ'’-]+)", after)
        neighbors = " ".join(m.group(1) for m in (prior_word, next_word) if m is not None)
        neighborhood = f"{before[-48:]} {after[:48]}"
        if any(
            pattern.search(value)
            for pattern in (cr.PILOSITY_NEIGHBOR, cr.PATTERN_NEIGHBOR)
            for value in (neighbors, neighborhood)
        ):
            return "colour_near_indumentum_or_pattern"
    return ""


def _value_matches(text: str, low: int, high: int) -> list[tuple[int, int, str]]:
    return [
        (match.start(), match.end(), cue.pato_id)
        for cue in baseline.QUALITY_PATTERNS
        for match in cue.pattern.finditer(text, low, high)
    ]


def _member_has_value(text: str, low: int, high: int) -> bool:
    member = text[low:high]
    if _value_matches(text, low, high):
        return True
    return any(pattern.search(member) for pattern in FAMILY_WORDS.values())


def _families_in(text: str, low: int, high: int) -> set[str]:
    member = text[low:high]
    families = {name for name, pattern in FAMILY_WORDS.items() if pattern.search(member)}
    families.update(FAMILY.get(pato, "") for _s, _e, pato in _value_matches(text, low, high))
    families.discard("")
    families.update(COARSE[f] for f in list(families) if f in COARSE)
    return families


def _coarse(family: str) -> str:
    return COARSE.get(family, family)


def _french_number(word: str) -> str:
    """Return ``sg``/``pl`` for a French noun/adjective, or ``""`` when undecidable."""

    token = word.strip().split()[-1].casefold() if word.strip() else ""
    if not token or re.search(r"\d", word):
        return ""
    if re.search(r"(?:eux|oux|us|is|as|ès|ux|os|x)$", token) and not re.search(
        r"(?:eaux|aux)$", token
    ):
        return ""  # tomenteux, obtus, gris, roux: singular and plural coincide
    if token.endswith(("s", "aux", "eaux")):
        return "pl"
    if token in {"marron", "orange", "olive", "paille", "crème", "creme"}:
        return ""
    return "sg"


def _number_mismatch(subject_surface: str, value_surface: str) -> bool:
    subject_number = _french_number(subject_surface)
    value_number = _french_number(value_surface)
    return bool(subject_number and value_number and subject_number != value_number)


def _value_family(pato_id: str, surface: str) -> str:
    if pato_id in FAMILY:
        return FAMILY[pato_id]
    if re.search(r"\d", surface):
        return "size"
    return "other"


def _stage_of_predicate(match: re.Match[str]) -> str:
    return next(name for name, value in match.groupdict().items() if value)


# --- E3 positional scope ------------------------------------------------------------------------
# Values whose own comma member ends with a surface cue (``glabre en dessus``) or a region cue
# (``acuminate at the apex``), or opens with a surface noun phrase (``face inférieure
# pubescente``), are recovered on the scoped bearer.  Only surface-appropriate families take a
# surface scope; region scope admits apex/base shapes, pilosity, colour and texture.
SURFACE_FAMILIES = frozenset({"pilosity", "colour", "texture"})
REGION_FAMILIES = {
    "apex": frozenset({"tip", "pilosity", "colour", "texture"}),
    "base": frozenset({"tip", "pilosity", "colour", "texture"}),
    "margin": frozenset({"pilosity", "colour"}),
    "upper": frozenset({"pilosity", "colour"}),
    "lower": frozenset({"pilosity", "colour"}),
}
REGION_CUE = re.compile(
    r"(?P<apex>at\s+(?:the\s+)?(?:apex|tip)|au\s+sommet|[àa]\s+l['’]apex)|"
    r"(?P<base>at\s+(?:the\s+)?base|[àa]\s+la\s+base)|"
    r"(?P<margin>(?:at|on)\s+the\s+margins?|sur\s+(?:les\s+|la\s+)?(?:bords?|marges?))|"
    r"(?P<upper>in\s+the\s+upper\s+(?:half|part|portion)|"
    r"dans\s+la\s+(?:partie|moitié)\s+sup[ée]rieure)|"
    r"(?P<lower>in\s+the\s+lower\s+(?:half|part|portion)|"
    r"dans\s+la\s+(?:partie|moitié)\s+inf[ée]rieure)",
    re.IGNORECASE,
)
_CUE_PREPOSITION = re.compile(r"(?:(?<!\w)(?:à|a|with|avec|on|sur)\s+(?:the\s+|la\s+)?)$", re.I)
# Reviewed organ -> PO region class table (PO first); other organs take a pinned BSPO region.
REGION_PO = {
    "PO_0025034": {"apex": "PO_0020137", "base": "PO_0020040", "margin": "PO_0020128"},
    "PO_0009025": {"apex": "PO_0020137", "base": "PO_0020040", "margin": "PO_0020128"},
    "PO_0020039": {"apex": "PO_0020137", "base": "PO_0008019", "margin": "PO_0025009"},
    "PO_0020049": {"apex": "FLOPO_0986000", "base": "FLOPO_0986001", "margin": "PO_0006034"},
    "PO_0009031": {"apex": "PO_0025145", "base": "PO_0025147", "margin": "PO_0005021"},
    "PO_0009032": {"apex": "PO_0025144", "base": "PO_0025146", "margin": "PO_0025008"},
    "PO_0009033": {"apex": "PO_0025143", "base": "PO_0025148", "margin": "PO_0025015"},
    "PO_0009055": {"apex": "PO_0025154", "base": "PO_0025155", "margin": "PO_0025011"},
    "PO_0009047": {"base": "PO_0008039"},
}
REGION_BSPO = {
    "apex": BSPO_APICAL_REGION,
    "base": BSPO_BASAL_REGION,
    "margin": BSPO_MARGIN,
    "upper": "BSPO_0000031",  # upper region (pinned)
    "lower": "BSPO_0000032",  # lower region (pinned)
}
# Indumentum colour: a colour directly bound to a hair noun or hair-presence adjective describes the
# hairs (PO:0000282 trichome), never the organ.  The hair word fixes the top-level pilosity value.
HAIR_AFTER = re.compile(r"\s+(?P<word>hairs?|hairy)(?!\w)", re.IGNORECASE)
HAIR_BEFORE = re.compile(r"(?:(?<!\w)(?:à|with|avec)\s+)?(?<!\w)(?P<word>poils?)\s+$", re.IGNORECASE)
HAIRY = "PATO_0000454"
# Region-restricted values: presence of hairs somewhere entails a hairy organ; every other value
# is carried by the part only, with the family attribute at top level.
HAIR_PRESENCE = frozenset({"PATO_0001320", "PATO_0002341", "PATO_0000454"})
FAMILY_ATTRIBUTE = {
    "pilosity": "PATO_0000066",
    "colour": "PATO_0000014",
    "tip": "PATO_0000052",
    "texture": "PATO_0000150",
}
SCOPE_PROVENANCE = "bearer_scope:E3"
LEAF_SURFACE_BEARERS = frozenset(
    {"PO_0025034", "PO_0009025", "PO_0020039", "PO_0020049", "FLOPO_0986002"}
)
BARE_SIDE = re.compile(
    r"above|below|beneath|underneath|(?:en\s+)?dessus|(?:en\s+)?dessous", re.IGNORECASE
)


def _member_bounds_at(text: str, position: int) -> tuple[int, int]:
    clause, clause_left = baseline._clause_at(text, position)
    bounds = _members(text, clause_left, clause)
    index = _member_index(bounds, position)
    return bounds[index] if index >= 0 else (clause_left, clause_left + len(clause))


def _scope_cue(text: str, start: int, end: int, pato: str) -> ScopeCue | None:
    """The single surface/region cue attached to the value inside its comma member."""

    family = FAMILY.get(pato, "")
    m_low, m_high = _member_bounds_at(text, start)
    found: list[ScopeCue] = []
    tail = re.match(r"\s+", text[end:m_high])
    if tail:
        cue_start = end + tail.end()
        rest_ok = lambda cue_end: not text[cue_end:m_high].strip(" .;:")  # noqa: E731
        for side, c_start, c_end in find_surface_cues(text, cue_start, min(m_high, cue_start + 40)):
            if c_start == cue_start and rest_ok(c_end) and family in SURFACE_FAMILIES:
                found.append(ScopeCue("surface", side, c_start, c_end, c_start, c_end))
        region = REGION_CUE.match(text, cue_start, m_high)
        if region and rest_ok(region.end()):
            name = next(k for k, v in region.groupdict().items() if v)
            if family in REGION_FAMILIES[name]:
                found.append(
                    ScopeCue("region", name, region.start(), region.end(), region.start(), region.end())
                )
    if family == "colour":
        after = HAIR_AFTER.match(text, end, m_high)
        if after:
            found.append(
                ScopeCue("indumentum", HAIRY, after.start("word"), after.end("word"), end, after.end())
            )
        elif tail:
            p_start = end + tail.end()
            for quality in baseline.QUALITY_PATTERNS:
                if quality.pato_id not in HAIR_PRESENCE:
                    continue
                match = quality.pattern.match(text, p_start, m_high)
                if match:
                    found.append(
                        ScopeCue(
                            "indumentum", quality.pato_id, match.start(), match.end(), end, match.end()
                        )
                    )
                    break
        before = HAIR_BEFORE.search(text[m_low:start])
        if before:
            found.append(
                ScopeCue(
                    "indumentum",
                    HAIRY,
                    m_low + before.start("word"),
                    m_low + before.end("word"),
                    m_low + before.start(),
                    start,
                )
            )
    head = re.search(r"\s+$", text[m_low:start])
    if head and family in SURFACE_FAMILIES:
        cue_end = m_low + head.start()
        for side, c_start, c_end in find_surface_cues(text, max(m_low, cue_end - 40), cue_end):
            if c_end != cue_end or not re.search(r"(?:face|surface|side)s?$", text[c_start:c_end], re.I):
                continue
            prep = _CUE_PREPOSITION.search(text[m_low:c_start])
            mask_start = m_low + prep.start() if prep else c_start
            found.append(ScopeCue("surface", side, c_start, c_end, mask_start, c_end))
    unique = {(cue.start, cue.end): cue for cue in found}
    return next(iter(unique.values())) if len(unique) == 1 else None


def _masked_text(text: str, value_start: int, cue: ScopeCue, *, colour: bool = False) -> str:
    """Blank the cue and every other comma member scoped to another surface or region.

    ``glabre dessus, paucipubescent dessous`` and ``obtus à la base, acuminé au sommet``: the other
    member describes another surface/region, not an alternative of the first value, so it must not
    trigger the same-attribute series guards.
    """

    chars = list(text)
    for index in range(cue.mask_start, cue.mask_end):
        chars[index] = " "
    if cue.kind not in {"surface", "region"}:
        return "".join(chars)
    clause, clause_left = baseline._clause_at(text, value_start)
    for low, high in _members(text, clause_left, clause):
        if low <= value_start < high:
            continue
        # A specimen-state/stage cue in the other member may also govern a colour (``grisâtre
        # dessus à sec, brun dessous``); keep it visible so the stage guards still apply.
        if cue.kind == "surface" and colour and ANY_STAGE_CUE.search(text[low:high]):
            continue
        if cue.kind == "surface":
            names = {side for side, _s, _e in find_surface_cues(text, low, high)}
        else:
            names = {
                next(k for k, v in match.groupdict().items() if v)
                for match in REGION_CUE.finditer(text, low, high)
            }
        if names and cue.name not in names:
            for index in range(low, high):
                chars[index] = " "
    return "".join(chars)


class ClauseAnalyzer:
    def __init__(self, resolver: SubjectResolver) -> None:
        self.resolver = resolver

    def decide(self, record: dict[str, Any], span: dict[str, Any]) -> Decision:
        """Clause-scope decision; a value blocked only by an attached E3 scope cue is retried.

        The unscoped analysis runs first, so every value it recovers is unchanged.  When it fails
        and the value carries exactly one attached surface or region cue, the cue (and any other
        comma member that is scoped to the opposite surface) is blanked and the same analysis
        decides the bearer and stage; the cue then scopes the bearer (see :func:`_apply_scope`).
        """

        decision = self._decide_core(record, span)
        if decision.route:
            return decision
        text = str(record.get("text", "") or "")
        start, end = int(span["start"]), int(span["end"])
        if text[start:end] != str(span.get("surface_form", "") or ""):
            return decision
        pato = str(span.get("candidate_pato_id", "") or "")
        cue = _scope_cue(text, start, end, pato)
        if cue is None:
            return decision
        masked = _masked_text(text, start, cue, colour=FAMILY.get(pato, "") == "colour")
        scoped = self._decide_core({**record, "text": masked}, span)
        if not scoped.route:
            return Decision("", f"{cue.kind}_scope:{scoped.reason}")
        subject = scoped.subject
        if subject is not None and subject.start < cue.mask_end and cue.mask_start < subject.end:
            return Decision("", f"{cue.kind}_scope:subject_overlaps_cue")
        return replace(scoped, scope=cue)

    def _decide_core(self, record: dict[str, Any], span: dict[str, Any]) -> Decision:
        text = str(record.get("text", "") or "")
        start, end = int(span["start"]), int(span["end"])
        pato = str(span.get("candidate_pato_id", "") or "")
        surface = str(span.get("surface_form", "") or "")
        if text[start:end] != surface:
            return Decision("", "span_not_verbatim")
        clause, clause_left = baseline._clause_at(text, start)
        clause_right = clause_left + len(clause)
        bounds = _members(text, clause_left, clause)
        index = _member_index(bounds, start)
        if index < 0 or end > bounds[index][1]:
            return Decision("", "value_crosses_member")
        m_low, m_high = bounds[index]
        member = text[m_low:m_high]
        if _paren_depth(text, clause_left, start):
            return Decision("", "value_inside_parenthesis")
        if baseline._unmodelled_bearer_category(
            text, start
        ) or baseline._unsupported_numeric_comparator(text, start):
            return Decision("", "unmodelled_bearer_category_or_comparator")
        if _preposed_paren_caveat(text, start):
            return Decision("", "preposed_parenthetical_caveat")
        if re.search(r"\([^)]*\)", clause[: start - clause_left]) and re.search(
            r"\((?:[^)]*(?:young|old|mature|immature|jeune|adulte|dry|sec|fresh|frais|"
            r"juvenile|vieux|âgé|when|lorsque|état))[^)]*\)",
            clause[: start - clause_left],
            re.IGNORECASE,
        ):
            return Decision("", "preposed_parenthetical_stage")
        if COMPARATIVE_STAGE.search(member) or COMPARATIVE_CONTEXT.search(member):
            return Decision("", "comparative_member")
        if SHAPE_MODIFIER_BEFORE.search(
            text[max(0, start - 24) : start]
        ) or SHAPE_MODIFIER_AFTER.match(text[end : end + 24]):
            return Decision("", "modified_shape_value")
        if pato in OUTLINE_PATO | TIP_PATO:
            after_word = re.match(r"\s+([A-Za-zÀ-ÖØ-öø-ÿ'’-]+)", text[end : end + 40])
            before_word = re.search(
                r"([A-Za-zÀ-ÖØ-öø-ÿ'’-]+)\s+$", text[max(0, start - 40) : start]
            )
            shape_words = (FAMILY_WORDS["outline"], FAMILY_WORDS["tip"])
            if any(
                word and any(pattern.fullmatch(word.group(1)) for pattern in shape_words)
                for word in (after_word, before_word)
            ):
                return Decision("", "unhyphenated_shape_compound")
        if pato in baseline.COLOR_PATO_IDS:
            previous = re.search(
                r"([A-Za-zÀ-ÖØ-öø-ÿ'’-]+)\s+$", text[max(m_low, start - 32) : start]
            )
            following = re.match(r"\s+([A-Za-zÀ-ÖØ-öø-ÿ'’-]+)", text[end : min(m_high, end + 32)])
            if any(
                word
                and (
                    FAMILY_WORDS["colour"].fullmatch(word.group(1))
                    or COLOUR_SHADE.fullmatch(word.group(1))
                )
                for word in (previous, following)
            ):
                return Decision("", "colour_shade_compound")
        if COMPARATIVE_BEFORE.search(text[max(0, start - 24) : start]):
            return Decision("", "comparative_degree")
        if PARENTHETICAL_PREFIX.search(text[max(0, start - 16) : start]) or SUB_PREFIX.search(
            text[max(0, start - 12) : start]
        ):
            return Decision("", "prefixed_value_alternative")
        if SEX_CATEGORY.search(clause[: start - clause_left]) or SEX_CATEGORY.search(
            str(record.get("organ", "") or "")
        ):
            return Decision("", "sex_or_category_restricted_bearer")
        if any(
            ANY_STAGE_CUE.search(paren.group(0)) or PHASE_CUE.search(paren.group(0))
            for paren in re.finditer(r"\([^()]*\)", clause)
        ):
            return Decision("", "parenthetical_stage_caveat_in_clause")
        unsafe = _atomic_safe(text, start, end, pato)
        if unsafe:
            return Decision("", f"not_atomic:{unsafe}")
        if REGION_WORD.search(member):
            return Decision("", "region_scoped_value")
        # Disjunction/alternative in the value's own member or in a nearby member of the same
        # attribute family (``elliptic, subobovate, or oblanceolate``; ``glabre, parfois
        # pubescent``): the value is one alternative of a series, not an atomic assertion.
        family = _value_family(pato, surface)
        following = bounds[index + 1] if index + 1 < len(bounds) else None
        if _real_disjunction(member) or (
            following and _real_disjunction(text[following[0] : following[1]])
        ):
            return Decision("", "disjunctive_value_series")
        for other in range(max(0, index - 2), min(len(bounds), index + 4)):
            if other == index:
                continue
            o_low, o_high = bounds[other]
            other_text = text[o_low:o_high]
            other_families = _families_in(text, o_low, o_high)
            if _coarse(family) in other_families and (
                _real_disjunction(other_text) or ALTERNATIVE_OPENER.match(other_text)
            ):
                return Decision("", "alternative_value_series")
            # Comma-listed values of one attribute (``ovale, elliptique, oblong``) enumerate
            # alternatives; none of them is an unconditional atomic value.
            if (
                abs(other - index) == 1
                and family not in {"size", "other"}
                and not FREQUENCY_OPENER.match(member[: start - m_low])
            ):
                tail_low = o_low
                opener = self.resolver.at(text, o_low, o_high, introduced=True)
                if opener is not None:
                    if other > index:
                        continue  # a new subject starts; not part of this value series
                    tail_low = max(opener.end, opener.stage_end)
                if family in _families_in(text, tail_low, o_high) and _opens_like_value(
                    text, tail_low, o_high
                ):
                    return Decision("", "adjacent_same_attribute_series")

        for caveat in IMMATURE_CAVEAT.finditer(text, clause_left, clause_right):
            # Only ``<colour> when immature`` is a self-contained predicate; any other immature /
            # "seen only" remark may describe the material the whole clause is based on.
            c_index = _member_index(bounds, caveat.start())
            c_low = bounds[c_index][0] if c_index >= 0 else clause_left
            if not (
                re.search(
                    r"(?:when|lorsqu\w*)\s+$",
                    text[max(c_low, caveat.start() - 12) : caveat.start()],
                    re.I,
                )
                and FAMILY_WORDS["colour"].search(text[c_low : caveat.start()])
            ):
                return Decision("", "immature_material_caveat")

        # --- subject -----------------------------------------------------------------------------
        # The subject is the nearest member (at or before the value) that opens with a bearer
        # noun; failing that, a structured organ heading for the segment's first clause.
        subject = None
        subject_member = index
        for candidate_member in range(index, -1, -1):
            c_low, c_high = bounds[candidate_member]
            limit = start if candidate_member == index else c_high
            subject = self.resolver.at(text, c_low, limit, introduced=True)
            if subject is not None:
                subject_member = candidate_member
                break
        if subject is None:
            subject = self._heading(record, text, clause_left, start)
            if subject is None:
                return Decision("", "no_provable_subject")
            subject_member = 0
        if subject.end > start:
            return Decision("", "subject_after_value")
        if subject.po_id == "PO_0020105" and not re.search(
            r"(?<!\w)(?:leaf|leaves|sheaths?|feuilles?|gaines?)(?!\w)", clause, re.IGNORECASE
        ):
            return Decision("", "ligule_not_leaf_context")
        if str(record.get("language", "")).lower().startswith("fr") and _number_mismatch(
            subject.surface, surface
        ):
            return Decision("", "french_number_agreement_mismatch")
        # Everything between the subject and the value must keep that subject in force.
        reason = self._intervening(text, bounds, subject, subject_member, index, start)
        if reason:
            return Decision("", reason)
        # The value's member must not name another structure between member start and value, nor
        # a covering/appendage anywhere (``white hairs``), nor a relational construction.
        own_prefix_low = subject.end if subject_member == index else m_low
        own_prefix = text[own_prefix_low:start]
        own_suffix = text[end:m_high]
        if (
            STRUCTURE_NOUN.search(own_prefix)
            or STRUCTURE_NOUN.search(own_suffix)
            or UNSCOPED_BEARER_BLOCKER.search(member)
            or any(
                p.search(own_prefix) or p.search(own_suffix)
                for _i, p in baseline.LOCAL_BEARER_PATTERNS
            )
        ):
            return Decision("", "structure_noun_in_value_member")
        if SUBJECT_SHIFT.search(own_prefix):
            return Decision("", "relational_prefix_in_value_member")
        if (
            subject_member != index
            and own_prefix.strip()
            and not _opens_like_value(text, m_low, start)
        ):
            return Decision("", "value_member_possible_sub_subject")
        if re.match(
            r"^\s*(?:with|avec|of|de|des|du|d['’]|à|in|on|sur|dans)\b", own_suffix, re.I
        ) and not AGE_PREDICATE.match(own_suffix.strip()):
            return Decision("", "relational_suffix_in_value_member")

        if subject.po_id == "PO_0000003" and pato not in WHOLE_PLANT_MEASURES and family == "size":
            return Decision("", "whole_plant_non_height_measure")
        # --- stage bound to this value ------------------------------------------------------------
        own_stage = self._own_predicate_stage(text, m_low, m_high, start, end)
        if own_stage == "ambiguous":
            return Decision("", "value_member_conditioned")
        subject_stage = subject.stage if subject.stage in STAGE_PATO else ""
        if subject.stage and not subject_stage:
            return Decision("", "unsupported_subject_stage")
        if isinstance(own_stage, tuple):
            stage_name, cue_start, cue_end = own_stage
            if subject_stage and subject_stage != stage_name:
                return Decision("", "conflicting_stages")
            reason = self._transition_scope(text, bounds, index, family, allow_own=True)
            if reason:
                return Decision("", reason)
            return Decision(
                "S1", "own_member_predicate_stage", subject, stage_name, cue_start, cue_end
            )

        # No own predicate: the member must be unconditioned apart from the subject's adjective.
        own_text = text[m_low:m_high]
        if subject_member == index and subject.stage_start >= 0:
            own_text = (
                text[m_low : subject.stage_start]
                + " " * (subject.stage_end - subject.stage_start)
                + text[subject.stage_end : m_high]
            )
        if (
            CONDITIONING_CUE.search(own_text)
            or TRANSITION_CUE.search(own_text)
            or ANY_STAGE_CUE.search(own_text)
        ):
            return Decision("", "value_member_conditioned")
        reason = self._transition_scope(text, bounds, index, family, allow_own=False)
        if reason:
            return Decision("", reason)
        if subject_stage:
            if subject.stage_start < 0:
                return Decision("", "subject_stage_without_offsets")
            reason = self._other_cues_out_of_scope(
                text, bounds, index, family, subject, skip=(subject.stage_start, subject.stage_end)
            )
            if reason:
                return Decision("", reason)
            return Decision(
                "S1",
                "subject_stage_adjective",
                subject,
                subject_stage,
                subject.stage_start,
                subject.stage_end,
            )
        reason = self._other_cues_out_of_scope(text, bounds, index, family, subject, skip=None)
        if reason:
            return Decision("", reason)
        return Decision("S2", "stage_cues_out_of_scope", subject)

    # -- helpers ---------------------------------------------------------------------------------
    def _heading(
        self, record: dict[str, Any], text: str, clause_left: int, start: int
    ) -> Subject | None:
        organ = str(record.get("organ", "") or "").strip()
        if not organ or organ.casefold() == "description":
            return None
        if text[:clause_left].strip():
            return None  # only the first clause of a segment inherits the heading
        po_id = baseline._organ_to_po(organ)
        if not po_id:
            return None
        prefix = text[clause_left:start]
        if (
            POSITIONAL_CATEGORY.search(prefix)
            or STRUCTURE_NOUN.search(prefix)
            or any(p.search(prefix) for _i, p in baseline.LOCAL_BEARER_PATTERNS)
            or any(p.search(prefix) for p in baseline.UNRESOLVED_BEARER_PATTERNS)
            or any(p.search(prefix) for _i, p, _a in baseline.CONTEXTUAL_BEARER_PATTERNS)
            or ANY_STAGE_CUE.search(prefix)
        ):
            return None
        return Subject(po_id, organ, start, start, "organ_heading")

    def _intervening(
        self,
        text: str,
        bounds: list[tuple[int, int]],
        subject: Subject,
        subject_member: int,
        index: int,
        start: int,
    ) -> str:
        for position in range(subject_member, index):
            low, high = bounds[position]
            if position == subject_member:
                low = max(low, subject.end if subject.method != "organ_heading" else low)
            segment = text[low:high]
            if position > subject_member:
                # A member opening with a noun starts a sub-subject (``apex acuminate``).
                if self.resolver.at(text, bounds[position][0], high) is not None:
                    return "intervening_sub_subject"
                if not _opens_like_value(text, bounds[position][0], high):
                    return "intervening_possible_sub_subject"
                opening = re.match(
                    r"\s*(?:[-–(]\s*)?([A-Za-zÀ-ÖØ-öø-ÿ'’-]+)", text[bounds[position][0] : high]
                )
                if opening and (
                    STRUCTURE_NOUN.fullmatch(opening.group(1))
                    or any(
                        p.fullmatch(opening.group(1)) for _i, p in baseline.LOCAL_BEARER_PATTERNS
                    )
                ):
                    return "intervening_sub_subject"
            stripped = OWN_MEMBER_LOCATIVE.sub(" ", segment)
            if position > subject_member and not _member_has_value(text, bounds[position][0], high):
                if STRUCTURE_NOUN.search(stripped) or SUBJECT_SHIFT.search(stripped):
                    return "intervening_relational_member"
            if (
                STRUCTURE_NOUN.search(stripped)
                or any(p.search(stripped) for _i, p in baseline.LOCAL_BEARER_PATTERNS)
                or any(p.search(stripped) for _i, p, _a in baseline.CONTEXTUAL_BEARER_PATTERNS)
            ):
                return "intervening_structure_noun"
            if re.search(
                r"(?<!\w)(?:which|that|whose|qui|dont|lequel|laquelle|with|avec|bearing|having|"
                r"covered|couvert\w*|garni\w*|muni\w*|pourvu\w*|portant|except|sauf|"
                r"than|like|comme|resembling|ressemblant)(?!\w)",
                stripped,
                re.IGNORECASE,
            ):
                return "intervening_relational_member"
            if "(" in segment and ")" not in segment:
                return "intervening_open_parenthesis"
            if position > subject_member and BARE_STAGE_MEMBER.match(
                text[bounds[position][0] : high]
            ):
                return "preceding_bare_stage_member"
            if (
                position > subject_member
                and AGE_ADJECTIVE.search(segment)
                and not AGE_PREDICATE.search(segment)
            ):
                return "intervening_adjectival_stage"
        # The subject member's own tail before the value must be plain (``Leaves when young,``).
        return ""

    def _own_predicate_stage(self, text: str, low: int, high: int, start: int, end: int):
        member = text[low:high]
        predicates = list(AGE_PREDICATE.finditer(text, low, high))
        if not predicates:
            return None
        if len(predicates) > 1:
            return "ambiguous"
        match = predicates[0]
        if match.start() >= end:
            bridge = text[end : match.start()]
        elif match.end() <= start:
            bridge = text[match.end() : start]
        else:
            return "ambiguous"
        bridge_clean = re.sub(rf"(?<!\w){ADVERB}(?!\w)", " ", bridge, flags=re.IGNORECASE)
        if not PREDICATE_BRIDGE.match(bridge_clean):
            return "ambiguous"
        # No other conditioning cue anywhere in the member.
        masked = (
            text[low : match.start()]
            + " " * (match.end() - match.start())
            + text[match.end() : high]
        )
        if CONDITIONING_CUE.search(masked) or TRANSITION_CUE.search(masked):
            return "ambiguous"
        # Only one value in the member (``glabrous and shiny when young`` stays residual).
        values = [
            row
            for row in _value_matches(text, low, high)
            if not (row[0] == start and row[1] == end)
        ]
        if (
            values
            or _real_disjunction(member)
            or re.search(
                r"(?<!\w)(?:and|et|to|à\s+(?!l['’]état|maturit))(?!\w)",
                member.replace(match.group(0), " "),
                re.I,
            )
        ):
            return "ambiguous"
        return (_stage_of_predicate(match), match.start(), match.end())

    def _transition_scope(
        self, text: str, bounds: list[tuple[int, int]], index: int, family: str, *, allow_own: bool
    ) -> str:
        """Reject the source state of a transition and anything following a transition."""

        for position, (low, high) in enumerate(bounds):
            if position == index:
                continue
            segment = text[low:high]
            if not (TRANSITION_CUE.search(segment) or PHASE_CUE.search(segment)):
                continue
            if position == index + 1:
                return "transition_source_member"
            if position > index and any(
                _coarse(family) in _families_in(text, *bounds[later])
                for later in range(position, len(bounds))
            ):
                return "transition_same_family"
            if position < index:
                return "follows_transition"
        return ""

    def _other_cues_out_of_scope(
        self,
        text: str,
        bounds: list[tuple[int, int]],
        index: int,
        family: str,
        subject: Subject,
        skip: tuple[int, int] | None,
    ) -> str:
        for position, (low, high) in enumerate(bounds):
            if position == index:
                continue
            segment = text[low:high]
            cues = [
                match
                for match in ANY_STAGE_CUE.finditer(text, low, high)
                if skip is None or not (match.start() >= skip[0] and match.end() <= skip[1])
            ]
            if not cues:
                continue
            if BARE_STAGE_MEMBER.match(segment):
                return "bare_stage_member_in_clause"
            if not _member_has_value(text, low, high):
                return "cue_member_without_own_value"
            families = _families_in(text, low, high)
            if _coarse(family) in families:
                return "same_family_conditioned_elsewhere"
            if (
                abs(position - index) == 1
                and _coarse(family) in {"surface", "colour"}
                and families & {"surface", "colour"}
            ):
                return "adjacent_related_family_conditioned"
            if position < index:
                # A cue before the value may only be a self-contained predicate on a value of its
                # own member (``orange-yellow when mature``, ``drying brown``); anything else
                # (``Fruit probably immature``, ``young ones``) may scope over the clause.
                member_low = max(low, subject.end) if position == 0 and subject.end > low else low
                for match in cues:
                    before = text[member_low : match.start()]
                    after = text[match.end() : high]
                    predicate = AGE_PREDICATE.match(
                        text, match.start(), high
                    ) or SPECIMEN_PREDICATE.match(text, match.start(), high)
                    if predicate and (
                        _value_matches(text, member_low, match.start())
                        or any(pattern.search(before) for pattern in FAMILY_WORDS.values())
                    ):
                        continue
                    if re.fullmatch(r"drying|dried|dries|dry", match.group(0), re.I) and any(
                        pattern.match(after.strip()) for pattern in FAMILY_WORDS.values()
                    ):
                        continue
                    return "preceding_unbound_stage_cue"
        return ""


# --- materialization ----------------------------------------------------------------------------


@dataclass
class Resources:
    analyzer: ClauseAnalyzer
    po_lex: Any
    pato_lex: Any
    combos: Any
    registry: Any
    signature_registry: Any
    attribute_ids: set[str]
    pato_ids: set[str]
    po_ids: set[str]
    flopo_ids: set[str]


def load_resources(
    *,
    po_obo: Path = Path("ont/plant_ontology.obo"),
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
    registry_path: Path = Path("config/flopo_id_registry.tsv"),
    combinations_path: Path = Path("config/valid_combinations.tsv"),
) -> Resources:
    po_lex, pato_lex = load_lexicons()
    return Resources(
        analyzer=ClauseAnalyzer(SubjectResolver(_po_exact_forms(po_obo))),
        po_lex=po_lex,
        pato_lex=pato_lex,
        combos=load_combinations(combinations_path),
        registry=load_eq_registry(registry_path),
        signature_registry=load_signature_registry(registry_path),
        attribute_ids=load_pato_attribute_terms(pato_lexicon),
        pato_ids=load_catalog_ids(pato_lexicon),
        po_ids=load_catalog_ids(po_lexicon),
        flopo_ids=load_flopo_ids(registry_path),
    )


def _build_assertion(
    record: dict[str, Any], span: dict[str, Any], decision: Decision
) -> dict[str, Any]:
    subject = decision.subject
    assert subject is not None
    bearer = BearerMatch(
        subject.po_id,
        subject.surface,
        subject.start if subject.method != "organ_heading" else int(span["start"]),
        subject.end if subject.method != "organ_heading" else int(span["end"]),
        subject.method,
    )
    assertion = _assertion(record, span, bearer, context=None)
    text = str(record.get("text", "") or "")
    provenance = list(assertion["mapping_provenance"])
    if decision.route == "S1":
        stage_pato = STAGE_PATO[decision.stage]
        start = min(int(assertion["source_start"]), decision.stage_start)
        end = max(int(assertion["source_end"]), decision.stage_end)
        stage_text = text[decision.stage_start : decision.stage_end]
        assertion.update(
            {
                "source_start": start,
                "source_end": end,
                "source_text": text[start:end],
                "bearer_context_qualities": [stage_pato],
                "normalization_status": "compositional",
            }
        )
        provenance += [f"bearer_context:{stage_pato}", f"context_text:{stage_text}"]
    provenance.append(f"dev_stage_scope_route:{decision.route}:{decision.reason}")
    assertion["mapping_provenance"] = provenance
    assertion["extractor"] = EXTRACTOR
    assertion.setdefault("developmental_stage_contexts", [])
    assertion.setdefault("developmental_stage_operator", "atomic")
    if subject.method != "organ_heading":
        assertion["bearer_start"] = subject.start
        assertion["bearer_end"] = subject.end
        assertion["raw_entity_text"] = text[subject.start : subject.end]
    return assertion


def _apply_scope(
    record: dict[str, Any], assertion: dict[str, Any], cue: ScopeCue
) -> tuple[dict[str, Any] | None, str]:
    """Scope the bearer of a recovered value (E3); ``(None, reason)`` when not representable."""

    text = str(record.get("text", "") or "")
    outer = str(assertion["po_id"])
    # Leaf-part subjects in a leaflet description (``folioles ...; limbe ...``) are leaflet parts.
    guarded = leaflet_bearer(outer, text, cue.start)
    if guarded != outer:
        assertion["mapping_provenance"] = [
            *assertion["mapping_provenance"],
            f"leaflet_context_bearer:{outer}->{guarded}",
        ]
        outer = guarded
        assertion["po_id"] = outer
    pato = str(assertion["pato_id"])
    family = FAMILY.get(pato, "")
    cue_text = text[cue.start : cue.end]
    scope: dict[str, Any]
    if cue.kind == "surface":
        # Bare ``above``/``below``/``dessus``/``dessous`` name the adaxial/abaxial surface only on
        # leaves and leaflets; on bracts and perianth members they usually mean the upper/lower
        # part (``bracts green below, becoming brown above``).
        if outer not in LEAF_SURFACE_BEARERS and BARE_SIDE.fullmatch(cue_text):
            return None, f"bare_side_cue_on_non_leaf:{outer}"
        mapped = surface_scope(outer, cue.name, cue.start, cue.end)
        if mapped is None:
            return None, f"surface_scope_unmapped:{outer}:{cue.name}"
        assertion["po_id"] = mapped.scope_class
        scope = {"outer_bearer": outer, "scope_class": mapped.scope_class, "mode": mapped.mode}
        note = f"surface:{cue.name}->{mapped.scope_class}"
    elif cue.kind == "indumentum":
        # ``white hairs``, ``à poils roux``, ``brown tomentose``: the colour is the colour of the
        # hairs (trichome part); the organ bears the hair-presence value named by the hair word.
        assertion["pato_id"] = cue.name
        assertion["part_restrictions"] = [
            {
                "property": HAS_PART,
                "filler_class": TRICHOME,
                "qualities": [pato],
                "part_text": cue_text,
                "part_start": cue.start,
                "part_end": cue.end,
            }
        ]
        start = min(int(assertion["source_start"]), cue.start)
        end = max(int(assertion["source_end"]), cue.end)
        assertion.update({"source_start": start, "source_end": end, "source_text": text[start:end]})
        assertion["mapping_provenance"] = [
            *assertion["mapping_provenance"],
            SCOPE_PROVENANCE,
            f"indumentum_colour:{pato}->{TRICHOME};top={cue.name}:{cue_text}",
        ]
        return assertion, ""
    else:
        region_po = REGION_PO.get(outer, {}).get(cue.name)
        # PO first, but only where PO itself places the region class in the named organ (leaf
        # apex is part of the leaf, not of the leaf lamina); otherwise a pinned BSPO region.
        if region_po and po_scope_within(region_po, outer):
            assertion["po_id"] = region_po
            scope = {"outer_bearer": outer, "scope_class": region_po, "mode": "substituted_bearer"}
            note = f"region:{cue.name}->{region_po}"
        else:
            if not outer.startswith(("PO_", "FLOPO_")):
                return None, f"region_scope_unsupported_bearer:{outer}"
            filler = REGION_BSPO[cue.name]
            top = pato if pato in HAIR_PRESENCE else FAMILY_ATTRIBUTE.get(family, "")
            if not top:
                return None, f"region_scope_no_attribute:{pato}"
            assertion["pato_id"] = top
            assertion["part_restrictions"] = [
                {
                    "property": HAS_PART,
                    "filler_class": filler,
                    "qualities": [pato],
                    "part_text": cue_text,
                    "part_start": cue.start,
                    "part_end": cue.end,
                }
            ]
            scope = {"outer_bearer": outer, "scope_class": filler, "mode": "part_restriction"}
            note = f"region:{cue.name}->{filler}(part_restriction,top={top})"
    scope.update({"scope_text": cue_text, "scope_start": cue.start, "scope_end": cue.end})
    assertion["bearer_scope"] = scope
    start = min(int(assertion["source_start"]), cue.start)
    end = max(int(assertion["source_end"]), cue.end)
    assertion.update({"source_start": start, "source_end": end, "source_text": text[start:end]})
    assertion["mapping_provenance"] = [
        *assertion["mapping_provenance"],
        SCOPE_PROVENANCE,
        f"bearer_scope_cue:{note}:{cue_text}",
    ]
    return assertion, ""


# Gate reasons that only reflect the absence of a curator-reviewed pair for a scoped bearer.
SCOPED_REVIEW_REASONS = frozenset(
    {"po_pato_novel", "nested_po_pato_novel", "pato_attribute_trait_manual_review"}
)


def _compose(record: dict[str, Any], assertion: dict[str, Any], res: Resources) -> dict[str, Any]:
    probe = {
        "text": record.get("text", ""),
        "assertions": [assertion],
        "organ": record.get("organ", ""),
    }
    parsed = _assertions_from_json(probe)[0]
    decision = compose_check(
        str(record.get("text", "")),
        parsed,
        res.po_lex,
        res.pato_lex,
        language=str(record.get("language", "")),
    )
    return {
        "status": decision.status,
        "confidence": decision.confidence,
        "reasons": list(decision.reasons),
        "entity_label": decision.entity_label,
        "quality_label": decision.quality_label,
        "clause": decision.clause,
    }


def _overlaps_existing(
    record: dict[str, Any], assertion: dict[str, Any], start: int, end: int
) -> bool:
    for other in record.get("assertions", []) or []:
        o_start, o_end = other.get("source_start"), other.get("source_end")
        if not isinstance(o_start, int) or not isinstance(o_end, int):
            continue
        if (
            other.get("pato_id") == assertion["pato_id"]
            and other.get("po_id") == assertion["po_id"]
            and o_start <= start
            and end <= o_end
        ):
            return True
    return False


def recover_record(
    record: dict[str, Any], res: Resources
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Return (delta or None, audit rows) for one segment."""

    text = str(record.get("text", "") or "")
    audit: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    working = copy.deepcopy(record)
    for span in record.get("unresolved_spans", []) or []:
        if span.get("reason") != TARGET_REASON:
            continue
        decision = res.analyzer.decide(record, span)
        row = {
            "source": record.get("source", ""),
            "source_id": record.get("source_id", ""),
            "source_segment_index": record.get("source_segment_index", 0),
            "language": record.get("language", ""),
            "start": span["start"],
            "end": span["end"],
            "surface_form": span.get("surface_form", ""),
            "candidate_pato_id": span.get("candidate_pato_id", ""),
            "route": decision.route,
            "reason": decision.reason,
            "po_id": decision.subject.po_id if decision.subject else "",
            "subject": decision.subject.surface if decision.subject else "",
            "subject_method": decision.subject.method if decision.subject else "",
            "stage": decision.stage,
            "outcome": "retained",
        }
        if decision.route:
            assertion = _build_assertion(record, span, decision)
            scope_reason = ""
            outer_composition = None
            if decision.scope is not None:
                # The composition check verifies the verbatim bearer and value evidence, so it runs
                # on the value as extracted (outer organ); the scope class label is never in the
                # source text.
                outer_composition = _compose(record, assertion, res)
                outer_composition["reasons"] = [
                    *outer_composition["reasons"],
                    "composition_checked_on_outer_bearer_before_E3_scope",
                ]
                assertion, scope_reason = _apply_scope(record, assertion, decision.scope)
                row["scope"] = f"{decision.scope.kind}:{decision.scope.name}"
            if assertion is None:
                row["reason"] = scope_reason
            elif _overlaps_existing(working, assertion, int(span["start"]), int(span["end"])):
                row["outcome"] = "retained"
                row["reason"] = "duplicate_existing_assertion"
            else:
                assertion["composition"] = outer_composition or _compose(record, assertion, res)
                gate = gate_check(
                    text,
                    assertion,
                    res.combos,
                    res.registry,
                    res.signature_registry,
                    res.attribute_ids,
                    taxon_provenance=record.get("taxon") if "taxon" in record else None,
                    pato_catalog_ids=res.pato_ids,
                    flopo_catalog_ids=res.flopo_ids,
                    po_catalog_ids=res.po_ids,
                )
                scoped_review = (
                    decision.scope is not None
                    and gate.status == "review"
                    and set(gate.reasons) <= SCOPED_REVIEW_REASONS
                )
                if assertion["composition"]["status"] != "accept":
                    row["reason"] = "composition_review"
                    row["composition_reasons"] = assertion["composition"]["reasons"]
                elif not scoped_review and (
                    gate.status != "accepted" or gate.po_pato_status != "allowed"
                ):
                    row["reason"] = (
                        f"gate_{gate.status}:{'|'.join(gate.reasons) or gate.po_pato_status}"
                    )
                else:
                    assertion["gate"] = asdict(gate)
                    ensure_annotation_class_iri(assertion)
                    working["assertions"] = [*working.get("assertions", []), assertion]
                    upgraded = ensure_source_statements(working)
                    materialized = upgraded["assertions"][-1]
                    materialized["gate"]["assertion_index"] = len(upgraded["assertions"]) - 1
                    working = upgraded
                    added.append(materialized)
                    removed.append(
                        {
                            "start": span["start"],
                            "end": span["end"],
                            "reason": TARGET_REASON,
                            "surface_form": span.get("surface_form", ""),
                        }
                    )
                    row["outcome"] = "recovered"
                    row["source_text"] = materialized["source_text"]
                    row["po_id"] = materialized["po_id"]
                    row["gate_status"] = materialized["gate"]["status"]
                    if materialized.get("bearer_scope"):
                        row["bearer_scope"] = materialized["bearer_scope"]
                        row["part_restrictions"] = materialized.get("part_restrictions", [])
                        row["pato_id"] = materialized["pato_id"]
        audit.append(row)
    if not added:
        return None, audit
    existing_ids = {s.get("statement_id") for s in record.get("source_statements", []) or []}
    needed = {a["source_statement_id"] for a in added}
    new_statements = [
        s
        for s in working.get("source_statements", [])
        if s.get("statement_id") in needed - existing_ids
    ]
    delta = {
        "key": {
            k: record.get(k)
            for k in (
                "source",
                "source_id",
                "source_segment_index",
                "taxon",
                "organ",
                "char_start",
                "char_end",
            )
        },
        "add_source_statements": new_statements,
        "add_assertions": added,
        "remove_unresolved": removed,
    }
    return delta, audit


def iter_records(path: Path) -> Iterator[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def build_delta(input_path: Path, out_dir: Path, *, res: Resources | None = None) -> dict[str, Any]:
    res = res or load_resources()
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    by_language: Counter[str] = Counter()
    by_route: Counter[str] = Counter()
    target = 0
    assertions = 0
    with (
        (out_dir / "delta.jsonl").open("w", encoding="utf-8") as delta_out,
        (out_dir / "audit.jsonl").open("w", encoding="utf-8") as audit_out,
    ):
        for record in iter_records(input_path):
            if not any(
                s.get("reason") == TARGET_REASON for s in record.get("unresolved_spans", []) or []
            ):
                continue
            delta, audit = recover_record(record, res)
            for row in audit:
                target += 1
                counts[f"{row['outcome']}:{row['reason']}"] += 1
                if row["outcome"] == "recovered":
                    by_language[row["language"]] += 1
                    by_route[row["route"]] += 1
                audit_out.write(json.dumps(row, ensure_ascii=False) + "\n")
            if delta:
                assertions += len(delta["add_assertions"])
                delta_out.write(json.dumps(delta, ensure_ascii=False) + "\n")
    recovered = sum(v for k, v in counts.items() if k.startswith("recovered:"))
    report = {
        "input": str(input_path),
        "target_spans": target,
        "recovered_spans": recovered,
        "assertions_added": assertions,
        "retained_spans": target - recovered,
        "recovered_by_language": dict(by_language),
        "recovered_by_route": dict(by_route),
        "dispositions": dict(counts.most_common()),
    }
    (out_dir / "build-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


def _key(record: dict[str, Any]) -> tuple:
    return tuple(
        record.get(k)
        for k in (
            "source",
            "source_id",
            "source_segment_index",
            "taxon",
            "organ",
            "char_start",
            "char_end",
        )
    )


def apply_delta_record(record: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(record)
    statement_ids = {s.get("statement_id") for s in out.get("source_statements", []) or []}
    for statement in delta.get("add_source_statements", []):
        if statement["statement_id"] not in statement_ids:
            out.setdefault("source_statements", []).append(statement)
            statement_ids.add(statement["statement_id"])
    for assertion in delta.get("add_assertions", []):
        if assertion.get("source_statement_id") not in statement_ids:
            raise ValueError(
                f"assertion references unknown statement {assertion.get('source_statement_id')}"
            )
        out.setdefault("assertions", []).append(assertion)
    remove = Counter(
        (r["start"], r["end"], r["reason"], r["surface_form"])
        for r in delta.get("remove_unresolved", [])
    )
    kept = []
    for span in out.get("unresolved_spans", []) or []:
        key = (span.get("start"), span.get("end"), span.get("reason"), span.get("surface_form"))
        if remove[key]:
            remove[key] -= 1
            continue
        kept.append(span)
    if sum(remove.values()):
        raise ValueError(f"delta removes unresolved spans absent from segment {_key(record)}")
    out["unresolved_spans"] = kept
    for index, assertion in enumerate(out.get("assertions", [])):
        if isinstance(assertion.get("gate"), dict):
            assertion["gate"]["assertion_index"] = index
    return out


def apply_delta(input_path: Path, delta_path: Path, output_path: Path) -> dict[str, int]:
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("apply output must differ from input")
    deltas: dict[tuple, dict[str, Any]] = {}
    for delta in iter_records(delta_path):
        key = tuple(
            delta["key"].get(k)
            for k in (
                "source",
                "source_id",
                "source_segment_index",
                "taxon",
                "organ",
                "char_start",
                "char_end",
            )
        )
        if key in deltas:
            raise ValueError(f"duplicate delta key {key}")
        deltas[key] = delta
    applied = 0
    with Path(output_path).open("w", encoding="utf-8") as out:
        for record in iter_records(input_path):
            delta = deltas.pop(_key(record), None)
            if delta is not None:
                record = apply_delta_record(record, delta)
                applied += 1
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
    if deltas:
        raise ValueError(f"{len(deltas)} delta keys matched no segment")
    return {"segments_patched": applied}


def sample_recovered(audit_path: Path, n: int, seed: int) -> list[dict[str, Any]]:
    rows = [row for row in iter_records(audit_path) if row["outcome"] == "recovered"]
    strata: dict[tuple, list[dict[str, Any]]] = {}
    for row in rows:
        strata.setdefault((row["route"], row["language"]), []).append(row)
    rng = random.Random(seed)
    total = len(rows)
    picked: list[dict[str, Any]] = []
    for key in sorted(strata):
        bucket = strata[key]
        quota = max(8, round(n * len(bucket) / total))
        picked.extend(rng.sample(bucket, min(quota, len(bucket))))
    return picked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("input", type=Path)
    build.add_argument("--out-dir", type=Path, required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("input", type=Path)
    apply.add_argument("--delta", type=Path, required=True)
    apply.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(build_delta(args.input, args.out_dir), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(apply_delta(args.input, args.delta, args.output), indent=2))


if __name__ == "__main__":
    main()
