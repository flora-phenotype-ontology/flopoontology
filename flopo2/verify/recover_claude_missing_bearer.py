"""Recover ``missing_or_unsupported_bearer`` spans whose bearer is syntactically unambiguous.

The deterministic baseline withholds a quality when neither the clause nor the FlorML/FDAC organ
heading yields a PO bearer.  Most withheld spans genuinely need attachment reasoning (``glabrous
on the veins``, ``margins ciliate``), but a large, safe subset has a single explicit subject:

* ``clause_head`` -- the clause opens with a bearer noun phrase (``Phyllaries 8, lanceolate``,
  ``Akènes de 1 mm de long, pubescents``) and *every* character between that head and the
  quality, plus the rest of the quality's comma member, is whitelisted filler: other recognised
  quality cues, parsed measurements, numbers, degree/frequency adverbs, units, and punctuation.
  Any other word (a nested noun, a preposition, an unrecognised adjective) blocks recovery, so a
  nested structure can never inherit the clause subject.
* ``record_heading`` -- the record's organ field maps to PO through the reviewed head table (or
  the baseline heading map) and the complete segment prefix before the quality is whitelisted
  filler, so the heading is the only possible subject.  The heading is recorded as non-verbatim
  bearer context, never inserted into the source statement.

Bearer nouns come from the baseline's own audited local cues and from an explicit reviewed table
(``reviewed_bearer_heads.tsv``) that maps English/French head nouns and headings only to IDs
already present in ``config/po_lexicon.tsv`` or ``config/flopo_id_registry.tsv``.  Every
candidate is re-checked with the baseline's negation, hedging, developmental-stage, compound,
disjunction, transition and same-attribute rules using the recovered bearer, then gated with
``flopo2.verify.gates.check_assertion``; only ``accepted``/``allowed`` assertions are emitted.

Output is a per-segment delta (source statements, assertions, removed unresolved spans); the
module also provides a streaming ``apply`` helper for validating the delta on a temporary copy.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import random
import re
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Iterator

from flopo2.annotation.positional import (
    BSPO_APICAL_REGION,
    BSPO_BASAL_REGION,
    BSPO_MARGIN,
    SURFACE_SCOPE,
    find_surface_cues,
    po_scope_within,
    surface_scope,
)
from flopo2.annotation.provenance import ensure_source_statements
from flopo2.extract import baseline
from flopo2.extract.compose import _clause_around
from flopo2.extract.leaflet_context import leaflet_bearer
from flopo2.extract.measurement import parse_measurements
from flopo2.owl.annotation_class import ensure_annotation_class_iri
from flopo2.verify.data_model import _has_real_disjunction
from flopo2.verify.local_bearer_table import load_reviewed_bearers
from flopo2.verify.gates import (
    check_assertion,
    load_catalog_ids,
    load_combinations,
    load_eq_registry,
    load_flopo_ids,
    load_pato_attribute_terms,
    load_signature_registry,
)

TARGET_REASON = "missing_or_unsupported_bearer"
EXTRACTOR = "claude_missing_bearer_recovery_v1"
DEFAULT_TABLE = Path(
    "scratchpad/flopo-claude-recovery-20260918/missing_bearer/reviewed_bearer_heads.tsv"
)
REVIEWED_LOCAL_SOURCE = "reviewed_local_bearers"

_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)
_ALLOWED_PUNCT = set(" \t\r\n,.;:()[]±+×–—-/'’\"°½¼¾·")
_FIGURE_REFERENCE = re.compile(
    r"\(?\b(?:figs?|pl|tab|t|plate)\.?\s*\d+[a-z]?(?:\s*[,:–-]\s*\d+[a-z]?)*\)?",
    re.IGNORECASE,
)
# Degree, frequency, approximation, dimension and unit words that never name a structure.
_FILLER_WORDS = frozenset(
    """
    very slightly somewhat rather more less often usually sometimes generally mostly
    occasionally rarely always frequently commonly typically mainly quite fairly nearly almost
    entirely completely wholly ca c about approx approximately up to and long wide broad across
    diam diameter thick high tall deep mm cm dm m µm μm by x in
    très tres peu un assez plus moins et presque tout fait bien env environ jusqu à a de d
    long longs longue longues large larges haut hauts haute hautes épais épaisse épaisses
    diamètre diametre longueur largeur hauteur épaisseur sur atteignant mesurant souvent
    parfois toujours sub pale dark bright light deep dull vivid outline
    """.split()
)
_HEDGE_BEFORE_VALUE = re.compile(
    r"(?<![\w-])(?:nearly|almost|practically|virtually|scarcely|hardly|barely|presque|quasi(?:ment)?|"
    r"[àa]\s+peine|not\s+quite)\s*$",
    re.IGNORECASE,
)
_BOUND_BEFORE_VALUE = re.compile(
    r"(?<![\w-])(?:atteign\w*|jusqu['’]?\s*[àa]|up\s+to|to|reaching|attaining|exceeding|"
    r"d[ée]passant|over|under|at\s+most|at\s+least|au\s+(?:plus|moins)|less\s+than|"
    r"more\s+than|moins\s+de|plus\s+de|rarely\s+(?:more|less)\s+than)\s*$",
    re.IGNORECASE,
)
# ``firmly chartaceous to thinly coriaceous``: the value is the end of a range or alternative.
_RANGE_BEFORE_VALUE = re.compile(
    r"(?<![\w-])(?:to|or|and/or|[àa]|ou|et/ou)\s+(?:[^\W\d_]+(?:ly|ment)\s+)?$",
    re.IGNORECASE,
)
# Alternatives inside an *earlier* comma member do not change the clause subject.
_EXEMPT_WORDS = frozenset({"or", "ou"})
_EN_ADJECTIVE_WORDS = frozenset(
    """
    acute obtuse entire simple dense sparse terete flat thin stout slender short narrow
    straight soft hard firm rigid smooth rough erect solitary free distinct many few numerous
    papery hairy woody fleshy leafy scaly glossy shiny waxy silky spongy corky bony horny
    milky powdery sticky stony velvety warty wiry woolly wooly downy mealy cottony leathery
    orange purple grey gray cream golden silvery pink mauve blue straw round convex concave
    subacute swollen shining persistent dehiscent indehiscent spreading ascending arching
    opposite alternate small large paler darker contrasting variable
    """.split()
)
_EN_ADVERB = re.compile(r"^[a-z]{3,}ly$")
_FR_ADVERB = re.compile(r"^[a-zàâçéèêëîïôûùüÿœ]{3,}(?:ement|amment|emment|ément)$")
_EN_ADJECTIVE = re.compile(
    r"^[a-z]{2,}(?:ate|ous|ose|oid|iform|ic|ical|al|ar|ary|ed|ile|less|escent|ulent|ish|ive)$"
)
_FR_ADJECTIVE = re.compile(
    r"^[a-zàâçéèêëîïôûùüÿœ]{2,}(?:é|ée|és|ées|eux|euse|euses|aire|aires|al|ale|ales|aux|"
    r"ique|iques|iforme|iformes|ile|iles|if|ifs|ive|ives|âtre|âtres|oïde|oïdes|ide|ides|"
    r"el|els|elle|elles|ble|bles|escent|escente|escents|escentes|ulent|ulente|ulents|"
    r"ulentes|ace|aces)$"
)
_FR_ADJECTIVE_WORDS = frozenset(
    """
    velu velue velus velues aigu aiguë aigus aiguës charnu charnue charnus charnues pointu
    pointue pointus pointues glauque glauques mince minces grêle grêles lisse lisses ferme
    fermes étroit étroite étroits étroites court courte courts courtes dense denses lâche
    lâches entier entière entiers entières simple simples concave concaves convexe convexes
    droit droite droits droites nu nue nus nues mou molle mous molles dur dure durs dures
    épars éparse éparses clair claire clairs claires foncé pâle pâles terne ternes mat mate
    mats mates luisant luisante luisants luisantes brillant brillante brillants brillantes
    arrondi arrondie arrondis arrondies subarrondi subarrondie subarrondis subarrondies
    épiphyte épiphytes terrestre terrestres grimpant grimpante grimpants grimpantes rampant
    rampante rampants rampantes lithophyte lithophytes robuste robustes sombre sombres roux
    rousse rousses paille mauve mauves orange orangé orangée rose roses pourpre pourpres
    violet violette violets violettes gris grise grises épaissi épaissie épaissis épaissies
    aplati aplatie aplatis aplaties rétréci rétrécie rétrécis rétrécies libre libres
    alterne alternes distant distante distants distantes
    """.split()
)
# Nouns that the adjective/adverb suffix heuristics would otherwise admit.
_NOUN_BLACKLIST = frozenset(
    """
    plate plates palate palates collar collars pillar pillars nectar tunic tunics spine spines
    line lines animal animals pedal portal hilum base bases apex tip tips side sides family
    lily belly assembly supply
    ombelle ombelles aisselle aisselles lamelle lamelles aile ailes stipelle stipelles
    tunique tuniques pyxide pyxides côté côtés moitié moitiés canal canaux rangée rangées
    écaille écailles cellule cellules élément éléments segment segments tégument téguments
    filament filaments indument renflement renflements prolongement prolongements
    étranglement rétrécissement ornement ornements épaississement épaississements
    sommet sommets bord bords marge marges face faces surface surfaces espace espaces place
    places trace traces
    dorsal ventral lateral laterals median terminal outer inner upper lower basal apical
    central marginal distal proximal abaxial adaxial posterior anterior outermost innermost
    uppermost lowermost médian médiane médians médianes latéral latérale latéraux latérales
    externe externes interne internes supérieur supérieure supérieurs supérieures inférieur
    inférieure inférieurs inférieures terminale terminaux terminales basale basaux basales
    apicale apicaux apicales dorsale dorsaux dorsales ventrale ventraux ventrales
    """.split()
)
_RECEPTACLE = "PO_0009064"
# Locative and temporal adverbs scope the value to a part or a time; they are never filler.
_SCOPING_ADVERBS = frozenset(
    """
    extérieurement intérieurement dorsalement ventralement latéralement basalement
    apicalement marginalement distalement proximalement terminalement centralement
    médianement initialement finalement tardivement ultérieurement anciennement
    abaxially adaxially externally internally outside inside dorsally ventrally laterally
    basally apically marginally distally proximally terminally centrally medially
    initially finally eventually ultimately subsequently early lately tardily previously
    above below beneath underneath within without inwardly outwardly
    """.split()
)
_RESTRICTING_MEMBER = re.compile(
    r"\s*(?:sauf|except[ée]?|excepting|but|mais|save|apart|hormis|à\s+l['’]exception|"
    r"with\s+the\s+exception|en\s+dehors|only|seulement|uniquement|surtout|particularly|"
    r"especially|notamment|principalement|mainly|chiefly|at\s+least|du\s+moins|"
    r"ailleurs|elsewhere|then|puis|later|becoming|devenant)(?![\w])",
    re.IGNORECASE,
)
_LOCATIVE = re.compile(
    r"(?<![\w])(?:"
    r"(?:at|towards?|near)\s+(?:the\s+)?(?:apex|base|tip|top|summit|middle|margins?|edges?|"
    r"ends?)|above|below|beneath|underneath|abaxially|adaxially|"
    r"(?:on|at)\s+(?:both|the\s+upper|the\s+lower|upper|lower)\s+(?:surfaces?|sides?|faces?)|"
    r"(?:au|vers\s+le|pr[èe]s\s+du|d[èe]s\s+le)\s+(?:sommet|milieu|bord)|"
    r"(?:à|vers|pr[èe]s\s+de|d[èe]s)\s+la\s+(?:base|marge|pointe)|"
    r"en\s+dessus|en\s+dessous|dessus|dessous|"
    r"(?:à|sur)\s+la\s+face\s+(?:sup[ée]rieure|inf[ée]rieure|interne|externe)|"
    r"sur\s+les\s+(?:2|deux)\s+faces|aux\s+(?:2|deux)\s+extr[ée]mit[ée]s"
    r")(?![\w])",
    re.IGNORECASE,
)
# --------------------------------------------------------------------- E3 positional scope
# ``glabrous above``/``pubescent beneath``/``à la face inférieure`` scope a value to one surface
# of a dorsiventral organ; ``hairy at the apex``/``au sommet`` to a region.  The cue must be
# adjacent to the value inside its comma member.  Surfaces map through the reviewed table of
# ``flopo2.annotation.positional`` (substituted PO epidermis bearer); regions use the organ's PO
# apex/base/margin class when PO has one, else a pinned BSPO region as a part restriction.
SCOPE_PROVENANCE = "bearer_scope:E3"
SURFACE_VALUE_FAMILIES = frozenset({"colour", "pilosity"})
SURFACE_TEXTURE_VALUES = frozenset({"PATO_0000701", "PATO_0000700"})  # smooth, rough
# Presence-of-hairs values: hairs on a region entail that the organ bears hairs.
HAIR_PRESENCE_VALUES = frozenset({"PATO_0001320", "PATO_0000454", "PATO_0002341"})
FAMILY_ATTRIBUTE = {
    "colour": "PATO_0000014",
    "pilosity": "PATO_0000066",
    "shape": "PATO_0000052",
    "texture": "PATO_0000150",
}
_REGION_CUE = re.compile(
    r"(?P<cue>(?:at|on)\s+(?:the\s+)?(?P<en>apex|apices|tip|tips|base|bases|summit|"
    r"margins?|edges?)|(?:au|aux)\s+(?P<fr1>sommets?|bords?)|"
    r"(?:à|a)\s+la\s+(?P<fr2>base|marge)|sur\s+les\s+(?P<fr3>bords|marges))(?![\w'’-])",
    re.IGNORECASE,
)
_REGION_KIND = {
    "apex": "apex", "apices": "apex", "tip": "apex", "tips": "apex", "summit": "apex",
    "sommet": "apex", "sommets": "apex", "base": "base", "bases": "base",
    "margin": "margin", "margins": "margin", "edge": "margin", "edges": "margin",
    "bord": "margin", "bords": "margin", "marge": "margin", "marges": "margin",
}
# Organ -> PO region class (PO first); organs absent here fall back to pinned BSPO regions.
REGION_PARTS: dict[str, dict[str, str]] = {
    "PO_0020039": {"apex": "PO_0025589", "base": "PO_0008019", "margin": "PO_0025009"},
    "PO_0025034": {"apex": "PO_0020137", "base": "PO_0020040", "margin": "PO_0020128"},
    "PO_0009025": {"apex": "PO_0020137", "base": "PO_0020040", "margin": "PO_0020128"},
    "PO_0020049": {"margin": "PO_0006034"},
    "PO_0009031": {"apex": "PO_0025145", "base": "PO_0025147", "margin": "PO_0005021"},
    "PO_0009032": {"apex": "PO_0025144", "base": "PO_0025146", "margin": "PO_0025008"},
    "PO_0009033": {"apex": "PO_0025143", "base": "PO_0025148", "margin": "PO_0025015"},
    "PO_0009055": {"apex": "PO_0025154", "base": "PO_0025155", "margin": "PO_0025011"},
    "PO_0020038": {"margin": "PO_0025010"},
    "PO_0020030": {"margin": "PO_0025012"},
    "PO_0009047": {"base": "PO_0008039"},
}
BSPO_REGIONS = {"apex": BSPO_APICAL_REGION, "base": BSPO_BASAL_REGION, "margin": BSPO_MARGIN}
# Leaf parts whose regions are the leaf's own (a leaflet apex is not a leaf apex): no BSPO
# fallback for them, the span stays unresolved until a reviewed class exists.
_NO_BSPO_REGION = frozenset({"PO_0020049", "FLOPO_0986002", "PO_0020038", "PO_0020030"})
_LEFT_CUE_PREFIX = frozenset({"à", "a", "sur", "on", "the", "la", "les", "en"})
# ``face supérieure glabre, plus rarement pubescente``: the next member is a hedged alternative
# of the scoped value, which an unqualified atomic assertion would lose.
_FREQUENCY_ALTERNATIVE_AFTER = re.compile(
    r"\s*(?:\(|,)\s*(?:(?:plus|more|less|moins|or|ou|mais|but)\s+)?"
    r"(?:rarement|rarely|parfois|sometimes|occasionally|souvent|often|quelquefois|usually|"
    r"généralement|generalement|or|ou)(?![\w])",
    re.IGNORECASE,
)
# ``feuilles de l'extrémité des rameaux ...; face supérieure ...``: a complement makes the
# previous clause subject a subset, so its surface cannot be carried to the organ.
_HEAD_COMPLEMENT = re.compile(
    r"\s+(?:de|des|du|d['’]|of|on|at|in|near|from|sur|au|aux)(?![\w])", re.IGNORECASE
)


@dataclass(frozen=True)
class ScopeCue:
    kind: str  # surface | region
    key: str  # adaxial/abaxial/outside/inside | apex/base/margin
    start: int
    end: int


TRICHOME = "PO_0000282"
# Qualities that describe the hairs themselves.  Pilosity values (glabrous, pubescent, ...)
# describe the organ *bearing* hairs and are never transferred to the trichome.
TRICHOME_QUALITIES = frozenset(
    {
        "PATO_0000622",  # erect
        "PATO_0000122",  # length
        "PATO_0000402",  # branched
        "PATO_0000404",  # coiled
        "PATO_0000405",  # curled
        "PATO_0000406",  # curved
        "PATO_0000701",  # smooth
    }
)
_TRICHOME_NOUN = re.compile(r"(?<![\w])(?:hairs?|trichomes?|poils?)(?![\w'’-])", re.IGNORECASE)
_TRICHOME_AFTER = re.compile(
    r"(?:\s+[^\W\d_]+){0,2}?\s+(?P<noun>hairs?|trichomes?)(?![\w'’-])", re.IGNORECASE
)
_ARTICLE = re.compile(r"(?:(?:les|la|le|the|a|an)\s+|l['’]\s*)", re.IGNORECASE)
_MEMBER_END = re.compile(r"[,;:()\[\]]|\.(?:\s|$)")


@dataclass(frozen=True)
class HeadEntry:
    head_id: str
    languages: frozenset[str]
    pattern: re.Pattern[str]
    po_id: str
    po_label: str
    families: frozenset[str]
    source: str


@dataclass(frozen=True)
class Bearer:
    rule: str
    po_id: str
    head_id: str
    surface: str
    start: int | None
    end: int | None
    category_in_head: bool


def load_head_table(path: Path) -> list[HeadEntry]:
    entries: list[HeadEntry] = []
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            head_id = (row.get("head_id") or "").strip()
            if not head_id:
                continue
            po_id = row["po_id"].strip()
            if not re.fullmatch(r"(?:PO|FLOPO)_\d{7}", po_id):
                raise ValueError(f"invalid bearer id in head table: {head_id}: {po_id}")
            entries.append(
                HeadEntry(
                    head_id=head_id,
                    languages=frozenset(
                        value.strip() for value in row["language"].split("|") if value.strip()
                    ),
                    pattern=re.compile(rf"(?:{row['pattern']})(?![\w'’-])", re.IGNORECASE),
                    po_id=po_id,
                    po_label=row.get("po_label", "").strip(),
                    families=frozenset(
                        value.strip()
                        for value in (row.get("family_filter") or "").split("|")
                        if value.strip()
                    ),
                    source="reviewed_head_table",
                )
            )
    return entries


def reviewed_local_bearer_entries(
    path: Path = Path("config/reviewed_local_bearers.tsv"),
    released_ids: set[str] | None = None,
) -> list[HeadEntry]:
    """Exact curator-reviewed aliases (live PO and released FLOPO-local support classes).

    Contextual rows (scale, bristle, awn, upper surface) are never unconditional heads.
    """

    entries: list[HeadEntry] = []
    if not Path(path).exists():
        return entries
    for row in load_reviewed_bearers(path, released_ids=released_ids):
        surface = str(row.get("surface_form", "") or "").strip()
        po_id = str(row.get("po_id", "") or "").strip()
        if not surface or not po_id:
            continue
        pattern = r"[\s-]+".join(re.escape(word) for word in re.split(r"[\s-]+", surface))
        entries.append(
            HeadEntry(
                head_id=f"reviewed_local_bearer:{row.get('language', '')}:{surface}",
                languages=frozenset({str(row.get("language", "") or "").strip()}),
                pattern=re.compile(rf"(?:{pattern})(?![\w'’-])", re.IGNORECASE),
                po_id=po_id,
                po_label=str(row.get("po_label", "") or "").strip(),
                families=frozenset(),
                source=REVIEWED_LOCAL_SOURCE,
            )
        )
    return entries


def baseline_head_entries() -> list[HeadEntry]:
    return [
        HeadEntry(
            head_id=f"baseline_local_cue:{po_id}:{index}",
            languages=frozenset({"en", "fr"}),
            pattern=pattern,
            po_id=po_id,
            po_label="",
            families=frozenset(),
            source="baseline_local_bearer_cue",
        )
        for index, (po_id, pattern) in enumerate(baseline.LOCAL_BEARER_PATTERNS)
    ]


class Recoverer:
    def __init__(
        self,
        table: list[HeadEntry],
        *,
        po_ids: set[str],
        pato_ids: set[str],
        flopo_ids: set[str],
        combinations: dict,
        registry: dict,
        signature_registry: dict,
        attribute_ids: set[str],
        po_labels: dict[str, str] | None = None,
        pato_labels: dict[str, str] | None = None,
    ) -> None:
        unknown = [
            entry.head_id
            for entry in table
            if entry.po_id not in po_ids and entry.po_id not in flopo_ids
        ]
        if unknown:
            raise ValueError(f"head table references unknown bearer ids: {unknown}")
        self.table = table
        self.heads = [*table, *baseline_head_entries()]
        self.po_ids = po_ids
        self.pato_ids = pato_ids
        self.flopo_ids = flopo_ids
        self.combinations = combinations
        self.registry = registry
        self.signature_registry = signature_registry
        self.attribute_ids = attribute_ids
        self.po_labels = po_labels or {}
        self.pato_labels = pato_labels or {}
        self.blockers = [
            *(pattern for _po, pattern, _allowed in baseline.CONTEXTUAL_BEARER_PATTERNS),
            *baseline.UNRESOLVED_BEARER_PATTERNS,
        ]
        self.all_bearer_patterns = [
            *self.blockers,
            *(entry.pattern for entry in self.heads),
        ]
        self.last_block = ""
        # E3: cue spans treated as filler while one scoped span is evaluated.
        self._scope_mask: list[tuple[int, int]] = []
        self._scope: ScopeCue | None = None
        self.po_words = frozenset(
            word
            for label in (po_labels or {}).values()
            for word in re.findall(r"[a-z]{3,}", label.lower())
        )

    @classmethod
    def from_config(
        cls,
        table_path: Path = DEFAULT_TABLE,
        *,
        po_lexicon: Path = Path("config/po_lexicon.tsv"),
        pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
        registry_path: Path = Path("config/flopo_id_registry.tsv"),
        combinations_path: Path = Path("config/valid_combinations.tsv"),
        reviewed_bearers_path: Path = Path("config/reviewed_local_bearers.tsv"),
    ) -> Recoverer:
        return cls(
            [*load_head_table(table_path), *reviewed_local_bearer_entries(reviewed_bearers_path)],
            po_ids=load_catalog_ids(po_lexicon),
            pato_ids=load_catalog_ids(pato_lexicon),
            flopo_ids=load_flopo_ids(registry_path),
            combinations=load_combinations(combinations_path),
            registry=load_eq_registry(registry_path),
            signature_registry=load_signature_registry(registry_path),
            attribute_ids=load_pato_attribute_terms(pato_lexicon),
            po_labels=_labels(po_lexicon),
            pato_labels=_labels(pato_lexicon),
        )

    # ------------------------------------------------------------------ bearer resolution
    def _entry_applies(self, entry: HeadEntry, record: dict) -> bool:
        language = str(record.get("language", "") or "")
        if (
            entry.source in {"reviewed_head_table", REVIEWED_LOCAL_SOURCE}
            and language not in entry.languages
        ):
            return False
        return _family_ok(entry, record)

    def clause_head(self, record: dict, clause: str, clause_start: int) -> Bearer | None:
        position = len(clause) - len(clause.lstrip())
        article = _ARTICLE.match(clause, position)
        if article:
            position = article.end()
        best: tuple[int, HeadEntry, re.Match[str]] | None = None
        for entry in self.heads:
            if not self._entry_applies(entry, record):
                continue
            match = entry.pattern.match(clause, position)
            if match and match.start() == position and match.end() > position:
                if best is None or match.end() > best[0]:
                    best = (match.end(), entry, match)
        if best is None:
            return None
        end, entry, match = best
        if entry.po_id == _RECEPTACLE:
            # Floras use "receptacle" for the capitulum/fig receptacle and for hypanthium-like
            # receptacle tubes (Cucurbitaceae, Chrysobalanaceae); none is safely PO's flower
            # receptacle without family-level review.
            return None
        # A longer (or equal) contextual/unresolved cue at the head (``leaf blade``, ``lower
        # glume``, ``hairs``) means the subject is a nested or qualified structure.
        for blocker in self.blockers:
            other = blocker.match(clause, position)
            if other and other.start() == position and other.end() >= end:
                return None
        head_text = clause[position:end]
        category = bool(baseline._UNMODELLED_BEARER_CATEGORY.search(head_text))
        if category and entry.source != "reviewed_head_table":
            return None
        return Bearer(
            rule="clause_head",
            po_id=entry.po_id,
            head_id=entry.head_id,
            surface=head_text,
            start=clause_start + position,
            end=clause_start + end,
            category_in_head=category,
        )

    def carry_over(
        self, record: dict, clause_start: int, start: int, member_start: int
    ) -> tuple[Bearer | None, str]:
        """Carry an explicit head across one ``;`` into a headless clause.

        ``Leaves ovate, 3 cm long; glabrous`` -- the previous clause must open with a head, and
        both the rest of that clause and the current clause up to the value must be whitelisted
        filler, so no other structure can be the implied subject.  Sentence boundaries stop it.
        """

        text = str(record.get("text", "") or "")
        if clause_start <= 0 or text[clause_start - 1] != ";":
            return None, ""
        previous, previous_start = baseline._clause_at(text, clause_start - 1)
        previous_end = previous_start + len(previous)
        if previous_end != clause_start - 1 or not previous.strip():
            return None, ""
        head = self.clause_head(record, previous, previous_start)
        if head is None or head.end is None:
            return None, ""
        surface_subject = (
            self._surface_subject_clause(text, clause_start)
            and head.po_id in SURFACE_SCOPE
            and not _HEAD_COMPLEMENT.match(text, head.end)
        )
        if not surface_subject and not self._covered(
            record, head.end, previous_end, exempt_until=previous_end
        ):
            return None, "carry_over_previous_clause_not_whitelisted"
        if not self._covered(record, clause_start, start, exempt_until=member_start):
            return None, "carry_over_clause_prefix_not_whitelisted"
        return (
            Bearer(
                rule="surface_subject_carry_over" if surface_subject else "semicolon_carry_over",
                po_id=head.po_id,
                head_id=head.head_id,
                surface=head.surface,
                start=head.start,
                end=head.end,
                category_in_head=head.category_in_head,
            ),
            "",
        )

    def _surface_subject_clause(self, text: str, clause_start: int) -> bool:
        """``...; face supérieure glabre`` / ``...; upper surface glabrous`` (E3).

        The clause opens with the evaluated surface cue, whose implicit whole is the subject of
        the previous clause: the surface noun itself names the scope, so intervening members of
        the previous clause cannot be the subject.
        """

        scope = self._scope
        if scope is None or scope.kind != "surface":
            return False
        prefix = text[clause_start : scope.start]
        if not all(word.lower() in _LEFT_CUE_PREFIX for word in _TOKEN.findall(prefix)):
            return False
        return bool(re.search(r"(?:face|surface|side)", text[scope.start : scope.end], re.I))

    def heading_bearer(self, record: dict) -> Bearer | None:
        organ = str(record.get("organ", "") or "").strip()
        if not organ:
            return None
        for entry in self.table:
            if not _family_ok(entry, record):
                continue
            if entry.pattern.fullmatch(organ):
                return Bearer(
                    rule="record_heading",
                    po_id=entry.po_id,
                    head_id=entry.head_id,
                    surface=organ,
                    start=None,
                    end=None,
                    category_in_head=bool(baseline._UNMODELLED_BEARER_CATEGORY.search(organ)),
                )
        po_id = baseline._organ_to_po(organ)
        if po_id:
            return Bearer(
                rule="record_heading",
                po_id=po_id,
                head_id="baseline_organ_heading",
                surface=organ,
                start=None,
                end=None,
                category_in_head=False,
            )
        return None

    # ------------------------------------------------------------------ filler checks
    def _word_ok(self, word: str, language: str, *, exempt: bool = False) -> str:
        """Classify a non-value word: ``filler``, ``listed``, ``heuristic`` or ``""`` (block)."""

        lower = word.lower()
        if exempt and lower in _EXEMPT_WORDS:
            return "filler"
        if lower in _SCOPING_ADVERBS:
            return ""
        if lower in _FILLER_WORDS:
            return "filler"
        if lower in _NOUN_BLACKLIST or lower in self.po_words:
            return ""
        if language == "fr":
            if lower in _FR_ADJECTIVE_WORDS:
                return "listed"
            if _FR_ADVERB.match(lower):
                return "listed"
            if _FR_ADJECTIVE.match(lower) and not lower.endswith(("ité", "ités")):
                return "heuristic"
            return ""
        if lower in _EN_ADJECTIVE_WORDS or _EN_ADVERB.match(lower):
            return "listed"
        if _EN_ADJECTIVE.match(lower):
            return "heuristic"
        return ""

    def _covered(
        self,
        record: dict,
        start: int,
        end: int,
        *,
        exempt_until: int | None = None,
    ) -> bool:
        """Return whether ``text[start:end]`` holds only value/modifier filler.

        Characters inside recognised quality cues and parsed measurements are always allowed.
        Other words must be filler, degree adverbs or adjective-like modifiers; any word that
        matches a bearer cue (explicit, contextual or unresolved) or a PO label word blocks.
        Before ``exempt_until`` (earlier comma members of the same clause) a closed list of
        locative restrictions such as ``au sommet`` or ``at base`` is tolerated because it only
        scopes that member's own values.
        """

        self.last_block = ""
        if end <= start:
            return True
        text = str(record.get("text", "") or "")
        language = str(record.get("language", "") or "")
        mask = bytearray(end - start)

        def mark(left: int, right: int) -> None:
            for index in range(max(left, start) - start, min(right, end) - start):
                mask[index] = 1

        for left, right in _value_spans(record):
            if right > start and left < end:
                mark(left, right)
        for left, right in self._scope_mask:
            if right > start and left < end:
                mark(left, right)
        blocked: list[tuple[int, int]] = []
        for pattern in self.all_bearer_patterns:
            for match in pattern.finditer(text, start, end):
                blocked.append((match.start(), match.end()))
        if exempt_until is not None and exempt_until > start:
            for match in _LOCATIVE.finditer(text, start, min(end, exempt_until)):
                mark(match.start(), match.end())
        for match in _FIGURE_REFERENCE.finditer(text, start, end):
            mark(match.start(), match.end())
        for match in _TOKEN.finditer(text, start, end):
            if any(left < match.end() and match.start() < right for left, right in blocked):
                if not all(mask[match.start() - start : match.end() - start]):
                    self.last_block = "bearer_cue:" + match.group(0).lower()
                    return False
                continue
            exempt = exempt_until is not None and match.end() <= exempt_until
            kind = self._word_ok(match.group(0), language, exempt=exempt)
            if kind == "heuristic" and language == "fr" and _member_initial(text, match.start()):
                following = re.match(r"[ \t]+([^\W\d_]+)", text[match.end() : match.end() + 40])
                if following and following.group(1).lower() not in {"ou", "et", "à", "au"}:
                    # ``épichile lisse``: a member-initial suffix-matched word directly followed
                    # by another word is as likely a new subject noun as an adjective.
                    self.last_block = "member_initial_noun_like:" + match.group(0).lower()
                    return False
            if kind:
                mark(match.start(), match.end())
        for index, flag in enumerate(mask):
            if flag:
                continue
            char = text[start + index]
            if char.isdigit() or char in _ALLOWED_PUNCT:
                continue
            token = _TOKEN.match(text, start + index)
            self.last_block = "word:" + (token.group(0).lower() if token else char)
            return False
        return True

    def _member_right_end(self, text: str, end: int, clause_end: int) -> int:
        match = _MEMBER_END.search(text, end, clause_end)
        position = match.start() if match else clause_end
        # French decimal commas (``2,5 mm``) are not member boundaries.
        while (
            match
            and text[position] == ","
            and position > 0
            and position + 1 < len(text)
            and text[position - 1].isdigit()
            and text[position + 1].isdigit()
        ):
            match = _MEMBER_END.search(text, position + 1, clause_end)
            position = match.start() if match else clause_end
        return position

    # ------------------------------------------------------------------ span evaluation
    def evaluate(self, record: dict, span: dict) -> tuple[dict | None, str, Bearer | None]:
        self._scope_mask = []
        self._scope = None
        try:
            return self._evaluate(record, span)
        finally:
            self._scope_mask = []
            self._scope = None

    def _scope_cue(
        self, text: str, start: int, end: int, member_start: int, member_end: int
    ) -> ScopeCue | None:
        """A surface or region cue adjacent to the value inside its comma member (E3)."""

        gap = re.match(r"[ \t]+", text[end:member_end])
        cue_start = end + (gap.end() if gap else 0)
        if gap:
            for side, left, right in find_surface_cues(text, cue_start, member_end):
                if left == cue_start and not text[max(0, left - 3) : left].endswith(("-", "au-")):
                    return ScopeCue("surface", side, left, right)
            region = _REGION_CUE.match(text, cue_start, member_end)
            if region:
                word = (
                    region.group("en") or region.group("fr1") or region.group("fr2")
                    or region.group("fr3")
                ).lower()
                return ScopeCue("region", _REGION_KIND[word], region.start(), region.end())
        cues = [
            row for row in find_surface_cues(text, member_start, start) if row[2] <= start
        ]
        if cues:
            side, left, right = cues[-1]
            between = text[right:start]
            before = text[member_start:left]
            if re.fullmatch(r"[ \t]+", between) and all(
                word.lower() in _LEFT_CUE_PREFIX for word in _TOKEN.findall(before)
            ):
                return ScopeCue("surface", side, left, right)
        return None

    def _evaluate(self, record: dict, span: dict) -> tuple[dict | None, str, Bearer | None]:
        text = str(record.get("text", "") or "")
        try:
            start = int(span["start"])
            end = int(span["end"])
        except (KeyError, TypeError, ValueError):
            return None, "invalid_span_offsets", None
        if not 0 <= start < end <= len(text):
            return None, "invalid_span_offsets", None
        quality = str(span.get("candidate_pato_id", "") or "")
        clause, clause_start = baseline._clause_at(text, start)
        clause_end = clause_start + len(clause)
        if end > clause_end:
            return None, "span_crosses_clause", None
        for other in record.get("unresolved_spans", []) or []:
            if other is span:
                continue
            if other.get("reason") != TARGET_REASON and _overlap(
                start, end, int(other.get("start", -1)), int(other.get("end", -1))
            ):
                return None, "overlaps_other_unresolved_reason", None
        for assertion in record.get("assertions", []) or []:
            a_start = assertion.get("source_start")
            a_end = assertion.get("source_end")
            if isinstance(a_start, int) and isinstance(a_end, int) and _overlap(
                start, end, a_start, a_end
            ):
                return None, "overlaps_existing_assertion", None

        # A non-entailing hedge (``Pod practically sessile``) or a bound cue outside the measured
        # span (``atteignant 85 cm``) would be lost from the atomic assertion.
        if _HEDGE_BEFORE_VALUE.search(text, max(0, start - 40), start):
            return None, "non_entailing_hedge_before_value", None
        if _BOUND_BEFORE_VALUE.search(text, max(0, start - 40), start):
            return None, "bound_cue_before_value", None
        if _RANGE_BEFORE_VALUE.search(text, max(0, start - 40), start):
            return None, "range_or_alternative_before_value", None
        member_end = self._member_right_end(text, end, clause_end)
        _member, member_start = baseline._comma_member_at(text, start)
        trichome = self.adjacent_trichome(record, start, end, quality, member_start, member_end)
        if trichome is not None:
            return self._build(record, span, trichome, clause, clause_start, clause_end)
        scope = self._scope_cue(text, start, end, member_start, member_end)
        if scope is not None:
            if _FREQUENCY_ALTERNATIVE_AFTER.match(text, member_end):
                return None, "scoped_value_with_hedged_alternative_after", None
            self._scope = scope
            self._scope_mask = [(scope.start, scope.end)]
        if not self._covered(record, end, member_end):
            return None, "unwhitelisted_right_context", None
        if member_end < clause_end:
            follow = text[member_end]
            if follow == "(":
                close = text.find(")", member_end)
                if close < 0 or close > clause_end or not self._covered(
                    record, member_end + 1, close
                ):
                    return None, "unwhitelisted_parenthetical_after_value", None
            elif follow == "," and _RESTRICTING_MEMBER.match(text, member_end + 1):
                return None, "restricting_member_after_value", None

        bearer = self.clause_head(record, clause, clause_start)
        carry_reason = ""
        if bearer is not None:
            assert bearer.end is not None
            if bearer.end > start:
                return None, "span_inside_bearer_head", bearer
            if not self._covered(record, bearer.end, start, exempt_until=member_start):
                return None, "unwhitelisted_head_to_span_filler", bearer
        else:
            carried, carry_reason = self.carry_over(record, clause_start, start, member_start)
            if carried is not None:
                bearer = carried
        if bearer is None:
            heading = self.heading_bearer(record)
            if heading is None:
                return None, carry_reason or "no_clause_head_or_mapped_heading", None
            if not self._covered(record, 0, start, exempt_until=member_start):
                return None, "heading_prefix_not_whitelisted", heading
            bearer = heading
        return self._build(record, span, bearer, clause, clause_start, clause_end)

    def _build(
        self,
        record: dict,
        span: dict,
        bearer: Bearer,
        clause: str,
        clause_start: int,
        clause_end: int,
    ) -> tuple[dict | None, str, Bearer | None]:
        text = str(record.get("text", "") or "")
        start = int(span["start"])
        end = int(span["end"])
        quality = str(span.get("candidate_pato_id", "") or "")
        if bearer.po_id not in self.po_ids and bearer.po_id not in self.flopo_ids:
            return None, "unknown_bearer_id", bearer
        measurement = next(
            (
                row
                for row in _measurements(record)
                if row.start == start and row.end == end and row.attribute_id == quality
            ),
            None,
        )
        if measurement is not None:
            reason = self._measurement_reason(text, start, end, bearer)
            if reason:
                return None, reason, bearer
            assertion = _measurement_assertion(record, measurement)
        else:
            cue_match = _quality_match(text, start, end, quality)
            if cue_match is None:
                return None, "span_not_a_baseline_cue", bearer
            cue, match = cue_match
            reason = self._quality_reason(text, cue, match, bearer, clause_start, clause_end)
            if reason:
                return None, reason, bearer
            assertion = _quality_assertion(record, cue, match)
        return self._finish(record, assertion, bearer, clause), "", bearer

    def adjacent_trichome(
        self,
        record: dict,
        start: int,
        end: int,
        quality: str,
        member_start: int,
        member_end: int,
    ) -> Bearer | None:
        """Attach a hair-specific quality to an adjacent hair noun in the same comma member.

        ``à poils blancs dressés``, ``hairs 0.1 mm long`` (noun first, whitelisted filler in
        between) and ``with erect hairs`` (English attributive adjective directly before the
        noun).  Pilosity values never transfer to the trichome.
        """

        if quality not in TRICHOME_QUALITIES or TRICHOME not in self.po_ids:
            return None
        text = str(record.get("text", "") or "")
        before = list(_TRICHOME_NOUN.finditer(text, member_start, start))
        if before:
            noun = before[-1]
            if self._covered(record, noun.end(), start) and self._covered(
                record, end, member_end
            ):
                return Bearer(
                    rule="adjacent_trichome",
                    po_id=TRICHOME,
                    head_id="trichome_noun_before_value",
                    surface=noun.group(0),
                    start=noun.start(),
                    end=noun.end(),
                    category_in_head=False,
                )
            return None
        if str(record.get("language", "") or "") != "en":
            return None
        after = _TRICHOME_AFTER.match(text, end, member_end)
        if after and self._covered(record, end, after.start("noun")):
            return Bearer(
                rule="adjacent_trichome",
                po_id=TRICHOME,
                head_id="trichome_noun_after_attributive_value",
                surface=after.group("noun"),
                start=after.start("noun"),
                end=after.end("noun"),
                category_in_head=False,
            )
        return None

    def _category_ok(self, text: str, position: int, bearer: Bearer) -> bool:
        if not baseline._unmodelled_bearer_category(text, position):
            return True
        if not bearer.category_in_head:
            return False
        # The head encodes the sex category (staminate/pistillate PO class).  No further
        # category word may occur in the quality's comma member beyond the head itself.
        member, member_start = baseline._comma_member_at(text, position)
        for match in baseline._UNMODELLED_BEARER_CATEGORY.finditer(member):
            absolute = member_start + match.start()
            if bearer.start is None or not bearer.start <= absolute < (bearer.end or 0):
                return False
        return True

    def _measurement_reason(self, text: str, start: int, end: int, bearer: Bearer) -> str:
        if not self._category_ok(text, start, bearer):
            return "unmodelled_bearer_category"
        if baseline._unsupported_numeric_comparator(text, start):
            return "unsupported_numeric_comparator"
        contextual = baseline._negated_or_hedged(text, start)
        if contextual:
            return contextual
        if baseline._adjacent_disjunction(text, start, end):
            return "explicit_disjunction"
        return ""

    def _quality_reason(
        self,
        text: str,
        cue: Any,
        match: re.Match[str],
        bearer: Bearer,
        clause_start: int,
        clause_end: int,
    ) -> str:
        if not self._category_ok(text, match.start(), bearer):
            return "unmodelled_bearer_category"
        # Every other cue in the clause is scored against the same recovered bearer, so the
        # baseline's disjunction/composite/transition detectors see the recovered attachment.
        matches = [
            (other_cue, other, self._scoped_bearer_id(text, other, bearer.po_id))
            for other_cue in baseline.QUALITY_PATTERNS
            for other in other_cue.pattern.finditer(text, clause_start, clause_end)
            # The baseline check tests ``other is match``; a re-found match of the evaluated
            # span itself is a different object and would count as a competing value.  Scoped
            # (E3) evaluation drops it; the unscoped v1/v2 behaviour is left unchanged.
            if not (
                self._scope is not None
                and (other.start(), other.end()) == (match.start(), match.end())
            )
        ]
        if not any(other is match for _c, other, _p in matches):
            matches.append((cue, match, bearer.po_id))
        if self._scope is not None:
            # The positional cue itself (``à la face inférieure``, ``at the apex``) is not a
            # range connector or a following value: the baseline checks see it as blank.
            blank = " " * (self._scope.end - self._scope.start)
            text = text[: self._scope.start] + blank + text[self._scope.end :]
        reason = baseline._quality_context_reason(text, cue, match, bearer.po_id, matches)
        if reason == "unmodelled_bearer_category":
            # Already decided by _category_ok for heads that encode the category.
            reason = ""
            local = baseline._negated_or_hedged(text, match.start())
            if local:
                return local
            if baseline._compound_edge(text, match):
                return "hyphenated_or_slash_compound"
            if baseline._adjacent_disjunction(text, match.start(), match.end()):
                return "explicit_disjunction"
            if baseline._adjacent_transition(text, match):
                return "unsupported_alternative_or_transition"
            if baseline._cross_comma_value_alternative(text, match.end()):
                return "explicit_disjunction"
        return reason

    def _scoped_bearer_id(self, text: str, other: re.Match[str], po_id: str) -> str:
        """Bearer identity of another clause value for the same-attribute checks.

        While a scoped value is evaluated, a value scoped to a *different* surface/region
        (``glabrous above, pubescent beneath``) is not a competing value of the same bearer.
        Unscoped values and values with the same scope still compete, so ``pubescent, glabrous
        above`` stays unresolved.
        """

        scope = self._scope
        if scope is None:
            return po_id
        member, member_start = baseline._comma_member_at(text, other.start())
        member_end = member_start + len(member)
        if member_start <= scope.start < member_end and member_start <= other.start():
            # Same comma member as the evaluated value: same scope.
            other_scope = scope
        else:
            other_scope = self._scope_cue(
                text, other.start(), other.end(), member_start, member_end
            )
        if other_scope is None or (other_scope.kind, other_scope.key) == (scope.kind, scope.key):
            return po_id
        return f"{po_id}#{other_scope.kind}:{other_scope.key}"

    def _apply_scope(
        self,
        record: dict,
        assertion: dict,
        bearer: Bearer,
        scope: ScopeCue,
        provenance: list[str],
    ) -> str:
        """Compile an adjacent surface/region cue; return a hold reason or ``""``."""

        text = str(record.get("text", "") or "")
        value = str(assertion.get("pato_id", "") or "")
        family = _value_family(value)
        if assertion.get("value_low") is not None or assertion.get("value_high") is not None:
            return "scoped_measurement"
        cue_text = text[scope.start : scope.end]
        outer = bearer.po_id
        if scope.kind == "surface":
            if family not in SURFACE_VALUE_FAMILIES | {"texture"}:
                return f"surface_scope_value_family:{family or 'other'}"
            mapped = surface_scope(outer, scope.key, scope.start, scope.end)
            if mapped is None:
                return f"surface_scope_unmapped_bearer:{outer}"
            if mapped.scope_class not in self.po_ids:
                return "surface_scope_unknown_class"
            assertion["po_id"] = mapped.scope_class
            assertion["bearer_scope"] = {
                "outer_bearer": outer,
                "scope_class": mapped.scope_class,
                "mode": mapped.mode,
                "scope_text": cue_text,
                "scope_start": scope.start,
                "scope_end": scope.end,
            }
            provenance.append(
                f"{SCOPE_PROVENANCE}:surface:{scope.key}->{mapped.side}:{outer}->{mapped.scope_class}"
            )
        else:
            if family not in {"colour", "pilosity", "texture", "shape"}:
                return f"region_scope_value_family:{family or 'other'}"
            region_class = REGION_PARTS.get(outer, {}).get(scope.key)
            if region_class is not None:
                if region_class not in self.po_ids or not po_scope_within(region_class, outer):
                    return "region_scope_unknown_class"
                assertion["po_id"] = region_class
                assertion["bearer_scope"] = {
                    "outer_bearer": outer,
                    "scope_class": region_class,
                    "mode": "substituted_bearer",
                    "scope_text": cue_text,
                    "scope_start": scope.start,
                    "scope_end": scope.end,
                }
                provenance.append(f"{SCOPE_PROVENANCE}:region:{scope.key}:{outer}->{region_class}")
            else:
                if family == "shape" or outer in _NO_BSPO_REGION or not outer.startswith("PO_"):
                    return f"region_scope_no_reviewed_part:{outer}:{scope.key}"
                filler = BSPO_REGIONS[scope.key]
                assertion["po_id"] = outer
                assertion["part_restrictions"] = [
                    {
                        "property": "BFO_0000051",
                        "filler_class": filler,
                        "qualities": [value],
                        "part_text": cue_text,
                        "part_start": scope.start,
                        "part_end": scope.end,
                    }
                ]
                if value not in HAIR_PRESENCE_VALUES:
                    assertion["pato_id"] = FAMILY_ATTRIBUTE[family]
                assertion["bearer_scope"] = {
                    "outer_bearer": outer,
                    "scope_class": filler,
                    "mode": "part_restriction",
                    "scope_text": cue_text,
                    "scope_start": scope.start,
                    "scope_end": scope.end,
                }
                provenance.append(
                    f"{SCOPE_PROVENANCE}:region:{scope.key}:{outer} has_part {filler}"
                    f" ({value}; top-level {assertion['pato_id']})"
                )
        # The retained evidence covers the positional cue.
        start = min(int(assertion["source_start"]), scope.start)
        end = max(int(assertion["source_end"]), scope.end)
        assertion["source_start"] = start
        assertion["source_end"] = end
        assertion["source_text"] = text[start:end]
        return ""

    def _finish(self, record: dict, assertion: dict, bearer: Bearer, clause: str) -> dict | None:
        text = str(record.get("text", "") or "")
        provenance = [
            f"claude_missing_bearer:{bearer.rule}",
            f"bearer_table:{bearer.head_id}",
        ]
        # Leaf-part bearers in a leaflet description are re-borne on the FLOPO leaflet part; the
        # gate below then decides whether that bearer x quality pair is admissible.
        leaflet_part = leaflet_bearer(bearer.po_id, text, int(assertion["source_start"]))
        if leaflet_part != bearer.po_id:
            provenance.append(f"leaflet_context_bearer:{bearer.po_id}->{leaflet_part}")
            bearer = replace(bearer, po_id=leaflet_part)
        scope = self._scope
        if scope is not None:
            held = self._apply_scope(record, assertion, bearer, scope, provenance)
            if held:
                assertion["_held_gate"] = {"status": "scope", "reasons": [held]}
                return assertion
        if bearer.rule in {"semicolon_carry_over", "surface_subject_carry_over"}:
            assert bearer.start is not None
            # The retained evidence must reach back over the ``;`` to the carried head.
            assertion["source_start"] = bearer.start
            assertion["source_text"] = text[bearer.start : assertion["source_end"]]
        if bearer.rule in {
            "clause_head",
            "semicolon_carry_over",
            "surface_subject_carry_over",
            "adjacent_trichome",
        }:
            assertion["raw_entity_text"] = bearer.surface
            assertion["bearer_start"] = bearer.start
            assertion["bearer_end"] = bearer.end
            provenance.append(
                f"explicit {bearer.rule.replace('_', ' ')} bearer: "
                f"{bearer.surface} [{bearer.start},{bearer.end})"
            )
        else:
            assertion["raw_entity_text"] = bearer.surface
            assertion["bearer_start"] = None
            assertion["bearer_end"] = None
            provenance.append("bearer_basis:record_organ_field_nonverbatim")
        provenance.append("filler_between_bearer_and_value:whitelisted_values_and_modifiers_only")
        if scope is None or "bearer_scope" not in assertion:
            assertion["po_id"] = bearer.po_id
        assertion["mapping_provenance"] = provenance
        assertion["extractor"] = EXTRACTOR
        assertion["normalization_status"] = "compositional"
        assertion["composition"] = {
            "status": "accept",
            "confidence": 1.0,
            "reasons": [f"deterministic_{bearer.rule}_bearer_with_whitelisted_filler"],
            "entity_label": self.po_labels.get(bearer.po_id, bearer.po_id),
            "quality_label": self.pato_labels.get(assertion["pato_id"], assertion["pato_id"]),
            "clause": clause.strip(),
        }
        for key, default in (
            ("negation_scope", ""),
            ("value_operator", "atomic"),
            ("value_terms", []),
            ("bearer_context_qualities", []),
            ("developmental_stage_contexts", []),
            ("developmental_stage_operator", "atomic"),
            ("part_restrictions", []),
            ("raw_quality_text", ""),
        ):
            assertion.setdefault(key, default)
        # Same rule as the data-model validator: an accepted atomic value must not sit in a
        # clause with an explicit alternative (``sparse or dense erect hairs``).
        clause_context = _clause_around(
            text, assertion["source_text"], assertion["source_start"], assertion["source_end"]
        )
        if _has_real_disjunction(clause_context):
            assertion["_held_gate"] = {
                "status": "guard",
                "reasons": ["atomic_clause_contains_disjunction"],
            }
            return assertion
        gate = check_assertion(
            text,
            assertion,
            self.combinations,
            self.registry,
            self.signature_registry,
            self.attribute_ids,
            taxon_provenance=record.get("taxon") if "taxon" in record else None,
            pato_catalog_ids=self.pato_ids,
            flopo_catalog_ids=self.flopo_ids,
            po_catalog_ids=self.po_ids,
        )
        admissible = gate.status == "accepted" and gate.po_pato_status == "allowed"
        if scope is not None and gate.status in {"accepted", "review"}:
            # A scoped bearer (leaf lamina abaxial epidermis x pubescent) is usually a novel
            # PO x PATO pair; it is admitted for review when novelty is the only concern.
            admissible = set(gate.reasons) <= _SCOPE_REVIEW_REASONS
        if not admissible:
            assertion["_held_gate"] = {"status": gate.status, "reasons": list(gate.reasons)}
            return assertion
        assertion["gate"] = asdict(gate)
        ensure_annotation_class_iri(assertion)
        return assertion


# ---------------------------------------------------------------------- E3 helpers
_SCOPE_REVIEW_REASONS = frozenset(
    {"po_pato_novel", "nested_po_pato_novel", "pato_attribute_trait_manual_review"}
)


def _value_family(pato_id: str) -> str:
    if pato_id in SURFACE_TEXTURE_VALUES:
        return "texture"
    return baseline.QUALITY_FAMILY.get(pato_id, "")


# ---------------------------------------------------------------------- helpers
def _labels(path: Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            labels[row.get("id", "")] = row.get("label", "")
    return labels


def _member_initial(text: str, position: int) -> bool:
    index = position - 1
    while index >= 0 and text[index] in " \t\r\n":
        index -= 1
    return index < 0 or text[index] in ",;:(["


def _family_ok(entry: HeadEntry, record: dict) -> bool:
    """Family-restricted heads need the family, or (family unknown) a heading naming them."""

    if not entry.families:
        return True
    family = str(record.get("taxon_family", "") or "").strip().casefold()
    if family:
        return family in {value.casefold() for value in entry.families}
    organ = str(record.get("organ", "") or "").strip()
    return bool(organ and entry.pattern.fullmatch(organ))


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


_RECORD_CACHE: dict[str, tuple[list, list[tuple[int, int]]]] = {}


def _cached(record: dict) -> tuple[list, list[tuple[int, int]]]:
    text = str(record.get("text", "") or "")
    key = f"{record.get('language', '')}\x00{text}"
    cached = _RECORD_CACHE.get(key)
    if cached is None:
        measurements = parse_measurements(text, str(record.get("language", "") or ""))
        spans = [
            (match.start(), match.end())
            for cue in baseline.QUALITY_PATTERNS
            for match in cue.pattern.finditer(text)
        ]
        spans.extend((row.start, row.end) for row in measurements)
        cached = (measurements, spans)
        _RECORD_CACHE.clear()
        _RECORD_CACHE[key] = cached
    return cached


def _measurements(record: dict) -> list:
    return _cached(record)[0]


def _value_spans(record: dict) -> list[tuple[int, int]]:
    return _cached(record)[1]


def _quality_match(text: str, start: int, end: int, pato_id: str):
    for cue in baseline.QUALITY_PATTERNS:
        if cue.pato_id != pato_id:
            continue
        for match in cue.pattern.finditer(text, max(0, start - 2), min(len(text), end + 2)):
            if match.start() == start and match.end() == end:
                return cue, match
    return None


def _measurement_assertion(record: dict, measurement: Any) -> dict:
    text = str(record.get("text", "") or "")
    qualifier_fields, qualifier_start, qualifier_text = baseline._modality_context(
        text, measurement.start
    )
    seasons, season_operator, season_start, season_end = baseline._season_context(
        text, measurement.start, measurement.end
    )
    source_start = min(measurement.start, qualifier_start, season_start)
    source_end = max(measurement.end, season_end)
    assertion = {
        "po_id": "",
        "pato_id": measurement.attribute_id,
        "negated": False,
        "organ": record.get("organ", ""),
        "source_text": text[source_start:source_end],
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
        **qualifier_fields,
    }
    if qualifier_text and measurement.modifier_text:
        assertion["modality_text"] = text[
            qualifier_start : measurement.start + len(measurement.modifier_text)
        ]
    return assertion


def _quality_assertion(record: dict, cue: Any, match: re.Match[str]) -> dict:
    text = str(record.get("text", "") or "")
    qualifier_fields, qualifier_start, qualifier_text = baseline._modality_context(
        text, match.start()
    )
    seasons, season_operator, season_start, season_end = baseline._season_context(
        text, match.start(), match.end()
    )
    source_start = min(match.start(), qualifier_start, season_start)
    source_end = max(match.end(), season_end)
    return {
        "po_id": "",
        "pato_id": cue.pato_id,
        "negated": False,
        "organ": record.get("organ", ""),
        "source_text": text[source_start:source_end],
        "source_start": source_start,
        "source_end": source_end,
        "modality_text": qualifier_text,
        "season_contexts": seasons,
        "season_operator": season_operator,
        **qualifier_fields,
    }


def record_key(record: dict) -> dict[str, Any]:
    return {
        "source": record.get("source", ""),
        "source_id": record.get("source_id", ""),
        "source_segment_index": record.get("source_segment_index", 0),
        "taxon": record.get("taxon", ""),
        "organ": record.get("organ", ""),
        "char_start": record.get("char_start", 0),
        "char_end": record.get("char_end", 0),
    }


def _key_tuple(key: dict[str, Any]) -> tuple:
    return tuple(
        key.get(field)
        for field in (
            "source",
            "source_id",
            "source_segment_index",
            "taxon",
            "organ",
            "char_start",
            "char_end",
        )
    )


def recover_record(record: dict, recoverer: Recoverer) -> tuple[dict | None, list[dict]]:
    """Return (delta or None, decision rows) for one segment."""

    decisions: list[dict] = []
    spans = [
        span
        for span in record.get("unresolved_spans", []) or []
        if span.get("reason") == TARGET_REASON
    ]
    if not spans:
        return None, decisions
    working = copy.deepcopy(record)
    existing_ids = {
        row.get("statement_id") for row in record.get("source_statements", []) or []
    }
    new_statements: dict[str, dict] = {}
    added: list[dict] = []
    removed: list[dict] = []
    for span in spans:
        assertion, reason, bearer = recoverer.evaluate(working, span)
        row = {
            "source": record.get("source", ""),
            "source_id": record.get("source_id", ""),
            "source_segment_index": record.get("source_segment_index", 0),
            "language": record.get("language", ""),
            "organ": record.get("organ", ""),
            "start": span.get("start"),
            "end": span.get("end"),
            "surface_form": span.get("surface_form", ""),
            "candidate_pato_id": span.get("candidate_pato_id", ""),
            "rule": bearer.rule if bearer else "",
            "head_id": bearer.head_id if bearer else "",
            "bearer_surface": bearer.surface if bearer else "",
            "po_id": bearer.po_id if bearer else "",
            "status": "retained",
            "reason": reason,
            "blocking_token": recoverer.last_block if reason.startswith(("unwhitelisted", "heading_prefix")) else "",
        }
        if assertion is not None and "_held_gate" in assertion:
            row["reason"] = "gate_" + str(assertion["_held_gate"]["status"])
            row["gate_reasons"] = ";".join(assertion["_held_gate"]["reasons"])
            assertion = None
        if assertion is None:
            decisions.append(row)
            continue
        probe = dict(working)
        probe["assertions"] = [*(working.get("assertions", []) or []), assertion]
        upgraded = ensure_source_statements(probe)
        materialized = upgraded["assertions"][-1]
        statement_id = materialized["source_statement_id"]
        statement = next(
            item
            for item in upgraded["source_statements"]
            if item.get("statement_id") == statement_id
        )
        if statement_id not in existing_ids:
            new_statements[statement_id] = statement
        working["assertions"] = [*(working.get("assertions", []) or []), materialized]
        working["source_statements"] = upgraded["source_statements"]
        added.append(materialized)
        removed.append(
            {
                "start": span.get("start"),
                "end": span.get("end"),
                "reason": TARGET_REASON,
                "surface_form": span.get("surface_form", ""),
            }
        )
        row["status"] = "recovered"
        row["reason"] = ""
        row["source_statement_id"] = statement_id
        decisions.append(row)
    if not added:
        return None, decisions
    delta = {
        "key": record_key(record),
        "add_source_statements": list(new_statements.values()),
        "add_assertions": added,
        "remove_unresolved": removed,
    }
    return delta, decisions


def iter_jsonl(path: Path) -> Iterator[dict]:
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def recover_file(
    stage_path: Path,
    out_dir: Path,
    *,
    table_path: Path = DEFAULT_TABLE,
    limit: int | None = None,
) -> dict[str, Any]:
    recoverer = Recoverer.from_config(table_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    by_language: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    by_rule: Counter[str] = Counter()
    by_bearer: Counter[str] = Counter()
    retained: Counter[str] = Counter()
    segments = 0
    with (
        (out_dir / "delta.jsonl").open("w", encoding="utf-8") as delta_handle,
        (out_dir / "decisions.jsonl").open("w", encoding="utf-8") as decision_handle,
    ):
        for record in iter_jsonl(stage_path):
            segments += 1
            if limit is not None and segments > limit:
                break
            delta, decisions = recover_record(record, recoverer)
            for row in decisions:
                decision_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                counts["target_spans"] += 1
                if row["status"] == "recovered":
                    counts["recovered_spans"] += 1
                    by_language[row["language"]] += 1
                    by_source[row["source"]] += 1
                    by_rule[row["rule"]] += 1
                    by_bearer[row["po_id"]] += 1
                else:
                    retained[row["reason"]] += 1
            if delta is not None:
                counts["delta_segments"] += 1
                counts["added_assertions"] += len(delta["add_assertions"])
                counts["added_source_statements"] += len(delta["add_source_statements"])
                delta_handle.write(json.dumps(delta, ensure_ascii=False) + "\n")
    report = {
        "stage": str(stage_path),
        "table": str(table_path),
        "segments": segments,
        "counts": dict(counts),
        "recovered_by_language": dict(by_language.most_common()),
        "recovered_by_source": dict(by_source.most_common()),
        "recovered_by_rule": dict(by_rule.most_common()),
        "recovered_by_bearer": dict(by_bearer.most_common()),
        "retained_by_reason": dict(retained.most_common()),
    }
    (out_dir / "recovery-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


# ---------------------------------------------------------------------- delta application
def apply_delta(stage_path: Path, delta_path: Path, output_path: Path) -> dict[str, int]:
    """Stream ``stage_path`` to ``output_path`` with every delta line applied exactly once."""

    if Path(stage_path).resolve() == Path(output_path).resolve():
        raise ValueError("apply output must differ from the stage input")
    deltas: dict[tuple, dict] = {}
    for delta in iter_jsonl(delta_path):
        key = _key_tuple(delta["key"])
        if key in deltas:
            raise ValueError(f"duplicate delta key: {key}")
        deltas[key] = delta
    applied = 0
    counts: Counter[str] = Counter()
    with output_path.open("w", encoding="utf-8") as handle:
        for record in iter_jsonl(stage_path):
            delta = deltas.get(_key_tuple(record_key(record)))
            if delta is not None:
                record = apply_record_delta(record, delta)
                applied += 1
                counts["assertions_added"] += len(delta["add_assertions"])
                counts["statements_added"] += len(delta["add_source_statements"])
                counts["unresolved_removed"] += len(delta["remove_unresolved"])
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    if applied != len(deltas):
        raise ValueError(f"applied {applied} of {len(deltas)} delta lines")
    counts["segments_patched"] = applied
    return dict(counts)


def apply_record_delta(record: dict, delta: dict) -> dict:
    out = copy.deepcopy(record)
    statements = list(out.get("source_statements", []) or [])
    known = {row.get("statement_id"): row for row in statements}
    for statement in delta.get("add_source_statements", []):
        previous = known.get(statement["statement_id"])
        if previous is not None and previous != statement:
            raise ValueError(f"conflicting statement {statement['statement_id']}")
        if previous is None:
            statements.append(statement)
            known[statement["statement_id"]] = statement
    for assertion in delta.get("add_assertions", []):
        if assertion.get("source_statement_id") not in known:
            raise ValueError("delta assertion references an unknown source statement")
    unresolved = list(out.get("unresolved_spans", []) or [])
    for target in delta.get("remove_unresolved", []):
        indexes = [
            index
            for index, span in enumerate(unresolved)
            if all(span.get(field) == target[field] for field in target)
        ]
        if len(indexes) != 1:
            raise ValueError(f"remove_unresolved target matched {len(indexes)} spans: {target}")
        unresolved.pop(indexes[0])
    out["source_statements"] = statements
    out["assertions"] = [*(out.get("assertions", []) or []), *delta.get("add_assertions", [])]
    out["unresolved_spans"] = unresolved
    return out


# ---------------------------------------------------------------------- review sample
def write_sample(
    decisions_path: Path,
    stage_path: Path,
    out_path: Path,
    *,
    size: int = 160,
    seed: int = 20260918,
) -> list[dict]:
    """Stratified (source x rule) seeded sample of recovered spans with a text window."""

    recovered = [
        row for row in iter_jsonl(decisions_path) if row.get("status") == "recovered"
    ]
    strata: dict[tuple[str, str], list[dict]] = {}
    for row in recovered:
        strata.setdefault((row["source"], row["rule"]), []).append(row)
    rng = random.Random(seed)
    total = len(recovered)
    chosen: list[dict] = []
    for key in sorted(strata):
        rows = strata[key]
        quota = max(3, round(size * len(rows) / max(total, 1)))
        chosen.extend(rng.sample(rows, min(quota, len(rows))))
    wanted = {
        (row["source"], row["source_id"], row["source_segment_index"]) for row in chosen
    }
    texts: dict[tuple, str] = {}
    for record in iter_jsonl(stage_path):
        key = (record.get("source"), record.get("source_id"), record.get("source_segment_index"))
        if key in wanted:
            texts[key] = str(record.get("text", ""))
    rows = []
    for row in chosen:
        text = texts[(row["source"], row["source_id"], row["source_segment_index"])]
        start, end = int(row["start"]), int(row["end"])
        window = text[max(0, start - 110) : start] + "[[" + text[start:end] + "]]" + text[
            end : end + 40
        ]
        rows.append(
            {
                "span": f"{row['source']}:{row['source_id']}:{row['source_segment_index']}:"
                f"{start}-{end}",
                "text_window": window.replace("\t", " ").replace("\n", " "),
                "assertion_summary": f"{row['bearer_surface']} -> {row['po_id']} | "
                f"{row['candidate_pato_id']} '{row['surface_form']}' ({row['rule']})",
                "verdict": "",
                "note": "",
            }
        )
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["span", "text_window", "assertion_summary", "verdict", "note"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("recover")
    run.add_argument("stage", type=Path)
    run.add_argument("--out-dir", type=Path, required=True)
    run.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    run.add_argument("--limit", type=int)
    apply = sub.add_parser("apply")
    apply.add_argument("stage", type=Path)
    apply.add_argument("delta", type=Path)
    apply.add_argument("-o", "--output", type=Path, required=True)
    sample = sub.add_parser("sample")
    sample.add_argument("decisions", type=Path)
    sample.add_argument("stage", type=Path)
    sample.add_argument("-o", "--output", type=Path, required=True)
    sample.add_argument("--size", type=int, default=160)
    sample.add_argument("--seed", type=int, default=20260918)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "recover":
        result: Any = recover_file(args.stage, args.out_dir, table_path=args.table, limit=args.limit)
    elif args.command == "apply":
        result = apply_delta(args.stage, args.delta, args.output)
    else:
        result = {"sampled": len(write_sample(
            args.decisions, args.stage, args.output, size=args.size, seed=args.seed
        ))}
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
