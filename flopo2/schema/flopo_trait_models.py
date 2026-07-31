from __future__ import annotations

import re
import sys
from datetime import (
    date,
    datetime,
    time
)
from decimal import Decimal
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Literal,
    Optional,
    Union
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer
)


metamodel_version = "1.11.0"
version = "None"


class ConfiguredBaseModel(BaseModel):
    model_config = ConfigDict(
        serialize_by_alias = True,
        validate_by_name = True,
        validate_assignment = True,
        validate_default = True,
        extra = "forbid",
        arbitrary_types_allowed = True,
        use_enum_values = True,
        strict = False,
    )





class LinkMLMeta(RootModel):
    root: dict[str, Any] = {}
    model_config = ConfigDict(frozen=True)

    def __getattr__(self, key:str):
        return getattr(self.root, key)

    def __getitem__(self, key:str):
        return self.root[key]

    def __setitem__(self, key:str, value):
        self.root[key] = value

    def __contains__(self, key:str) -> bool:
        return key in self.root


linkml_meta = LinkMLMeta({'default_prefix': 'flopo_trait',
     'default_range': 'string',
     'description': 'LinkML schema for ontology-grounded extraction of plant '
                    'phenotype assertions from flora descriptions. It is the '
                    'single contract for both extraction engines (Graph-RAG and '
                    'SPIRES+OAK), drives structured/validated LLM output, and '
                    'generates the curated-database DDL. Each TraitAssertion is '
                    'one entity-quality flora assertion for a taxon, grounded to '
                    'PO (entity) and PATO (quality) — optionally a TO trait and a '
                    'UO unit — with the source span for provenance. The '
                    '``annotators`` annotations make this directly usable as an '
                    'OntoGPT/SPIRES template (OAK grounds the named slots against '
                    'the listed ontologies).',
     'id': 'https://w3id.org/flopo/flopo-trait',
     'imports': ['linkml:types'],
     'license': 'https://creativecommons.org/publicdomain/zero/1.0/',
     'name': 'flopo-trait',
     'prefixes': {'BFO': {'prefix_prefix': 'BFO',
                          'prefix_reference': 'http://purl.obolibrary.org/obo/BFO_'},
                  'BTERM': {'prefix_prefix': 'BTERM',
                            'prefix_reference': 'https://w3id.org/flopo/botanical-term/'},
                  'ENVO': {'prefix_prefix': 'ENVO',
                           'prefix_reference': 'http://purl.obolibrary.org/obo/ENVO_'},
                  'FLOPO': {'prefix_prefix': 'FLOPO',
                            'prefix_reference': 'http://purl.obolibrary.org/obo/FLOPO_'},
                  'FLOPOAC': {'prefix_prefix': 'FLOPOAC',
                              'prefix_reference': 'https://w3id.org/flopo/annotation-class/'},
                  'FLOPOANN': {'prefix_prefix': 'FLOPOANN',
                               'prefix_reference': 'https://w3id.org/flopo/annotation/'},
                  'PATO': {'prefix_prefix': 'PATO',
                           'prefix_reference': 'http://purl.obolibrary.org/obo/PATO_'},
                  'PO': {'prefix_prefix': 'PO',
                         'prefix_reference': 'http://purl.obolibrary.org/obo/PO_'},
                  'PROV': {'prefix_prefix': 'PROV',
                           'prefix_reference': 'http://www.w3.org/ns/prov#'},
                  'RO': {'prefix_prefix': 'RO',
                         'prefix_reference': 'http://purl.obolibrary.org/obo/RO_'},
                  'SIO': {'prefix_prefix': 'SIO',
                          'prefix_reference': 'http://semanticscience.org/resource/SIO_'},
                  'TO': {'prefix_prefix': 'TO',
                         'prefix_reference': 'http://purl.obolibrary.org/obo/TO_'},
                  'UO': {'prefix_prefix': 'UO',
                         'prefix_reference': 'http://purl.obolibrary.org/obo/UO_'},
                  'flopo_trait': {'prefix_prefix': 'flopo_trait',
                                  'prefix_reference': 'https://w3id.org/flopo/flopo-trait/'},
                  'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'flopo2/schema/flopo_trait.yaml',
     'title': 'FLOPO 2.0 Trait Extraction Schema'} )

class ValueOperator(str, Enum):
    """
    Logical structure of categorical values in the source text.
    """
    atomic = "atomic"
    all_of = "all_of"
    one_of = "one_of"


class NegationScope(str, Enum):
    """
    Logical target of an explicit negative phenotype assertion.
    """
    quality = "quality"
    absence = "absence"


class DevelopmentalStageRelation(str, Enum):
    """
    Temporal relation used for PO developmental-stage class restrictions.
    """
    present_during = "present_during"


class NormalizationStatus(str, Enum):
    """
    Provenance and confidence class of an assertion's ontology normalization.
    """
    reviewed = "reviewed"
    auto = "auto"
    proposed = "proposed"
    retrieved = "retrieved"
    context_override = "context_override"
    compositional = "compositional"
    nil = "nil"


class FrequencyModifier(str, Enum):
    """
    Deprecated combined frequency, degree, and approximation vocabulary.
    """
    always = "always"
    usually = "usually"
    often = "often"
    sometimes = "sometimes"
    occasionally = "occasionally"
    rarely = "rarely"
    never = "never"
    approximately = "approximately"
    nearly = "nearly"
    almost = "almost"
    slightly = "slightly"
    very = "very"


class FrequencyQualifier(str, Enum):
    """
    Controlled frequency force; the exact source cue remains in modality_text.
    """
    universal = "universal"
    usually = "usually"
    often = "often"
    sometimes = "sometimes"
    occasionally = "occasionally"
    rarely = "rarely"
    never = "never"
    unspecified = "unspecified"


class EpistemicModality(str, Enum):
    """
    Controlled epistemic force of a flora assertion.
    """
    asserted = "asserted"
    probable = "probable"
    possible = "possible"
    uncertain = "uncertain"
    reported = "reported"


class ValueQualifier(str, Enum):
    """
    Controlled exactness or approximation of the asserted value.
    """
    exact = "exact"
    approximately = "approximately"
    nearly = "nearly"
    almost = "almost"


class DegreeQualifier(str, Enum):
    """
    Controlled degree qualifier, orthogonal to statement frequency.
    """
    unmodified = "unmodified"
    slightly = "slightly"
    moderately = "moderately"
    very = "very"
    extremely = "extremely"
    completely = "completely"


class SeasonRelation(str, Enum):
    """
    Temporal relation used in the OWL phenotype class expression.
    """
    present_during = "present_during"
    happens_during = "happens_during"


class Hemisphere(str, Enum):
    """
    Explicit spatial context for interpreting named seasons.
    """
    northern = "northern"
    southern = "southern"
    tropical = "tropical"
    equatorial = "equatorial"
    unspecified = "unspecified"



class TraitExtraction(ConfiguredBaseModel):
    """
    The set of trait assertions extracted from a single text segment (one organ block of one taxon). Carries the provenance needed to trace every assertion back to its source.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/flopo/flopo-trait', 'tree_root': True})

    annotation_extension_iri: Optional[str] = Field(default=None, description="""IRI of the annotation-extension ontology that defines the phenotype_class_iri targets used in this materialized record.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitExtraction']} })
    source_segment_index: Optional[int] = Field(default=None, description="""Zero-based document-order occurrence within one source file. This distinguishes repeated taxon/organ/text blocks whose local character offsets are otherwise identical.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitExtraction']} })
    taxon_name: Optional[str] = Field(default=None, description="""Verbatim taxon name string from the source treatment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitExtraction']} })
    organ_hint: Optional[str] = Field(default=None, description="""The FlorML char-class / subheading the segment came from (anatomical prior).""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitExtraction']} })
    source_statements: Optional[list[SourceStatement]] = Field(default=None, description="""Lossless, first-class source statements in this segment. Every assertion must identify the statement that supports it before database or OWL serialization.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitExtraction']} })
    term_mentions: Optional[list[TermMention]] = Field(default=None, description="""Botanical terminology spans detected before contextual EQ extraction.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitExtraction']} })
    unresolved_spans: Optional[list[UnresolvedTraitSpan]] = Field(default=None, description="""Source spans that contain a possible trait but cannot yet be represented as a safe atomic assertion. These remain first-class audit evidence rather than being discarded.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitExtraction']} })
    assertions: Optional[list[TraitAssertion]] = Field(default=None, description="""The trait assertions found in this segment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitExtraction']} })


class SourceStatement(ConfiguredBaseModel):
    """
    A verbatim flora statement retained as evidence. Its identifier includes document and segment identity as well as offsets and text, so identical wording in different treatments remains distinct evidence.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'class_uri': 'FLOPOANN:SourceStatement',
         'from_schema': 'https://w3id.org/flopo/flopo-trait'})

    statement_id: str = Field(default=..., description="""Stable source-scoped identifier assigned by the provenance normalizer.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement']} })
    verbatim_text: str = Field(default=..., description="""Exact source text selected by start and end.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement']} })
    start: int = Field(default=..., description="""Zero-based inclusive offset in the source segment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement',
                       'UnresolvedTraitSpan',
                       'SeasonContext',
                       'DevelopmentalStageContext',
                       'TermMention']} })
    end: int = Field(default=..., description="""Zero-based exclusive offset in the source segment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement',
                       'UnresolvedTraitSpan',
                       'SeasonContext',
                       'DevelopmentalStageContext',
                       'TermMention']} })
    document_start: Optional[int] = Field(default=None, description="""Zero-based inclusive offset in the source document, when available.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement']} })
    document_end: Optional[int] = Field(default=None, description="""Zero-based exclusive offset in the source document, when available.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement']} })
    language: Optional[str] = Field(default=None, description="""BCP 47 language code for the retained statement.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement', 'TermMention']} })
    sentence_index: Optional[int] = Field(default=None, description="""Zero-based sentence or statement occurrence within the source segment, if known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement']} })


class UnresolvedTraitSpan(ConfiguredBaseModel):
    """
    A verbatim candidate trait span withheld from assertion promotion because its negation, composition, bearer, modifier, or ontology interpretation is unresolved.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/flopo/flopo-trait'})

    start: int = Field(default=..., description="""Zero-based inclusive character offset in the source segment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement',
                       'UnresolvedTraitSpan',
                       'SeasonContext',
                       'DevelopmentalStageContext',
                       'TermMention']} })
    end: int = Field(default=..., description="""Zero-based exclusive character offset in the source segment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement',
                       'UnresolvedTraitSpan',
                       'SeasonContext',
                       'DevelopmentalStageContext',
                       'TermMention']} })
    surface_form: str = Field(default=..., description="""Exact source text selected by start and end.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedTraitSpan', 'TermMention']} })
    reason: str = Field(default=..., description="""Stable machine-readable reason the candidate was withheld.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedTraitSpan']} })
    candidate_pato_id: Optional[str] = Field(default=None, description="""PATO identifier suggested by the lexical cue, if any.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedTraitSpan']} })
    original_reason: Optional[str] = Field(default=None, description="""Stable unresolved reason retained before a context-specific recovery pass.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedTraitSpan']} })
    negation_residual_reason: Optional[str] = Field(default=None, description="""Machine-readable reason a negated candidate remains unresolved.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedTraitSpan']} })
    negation_residual_detail: Optional[str] = Field(default=None, description="""Human-readable audit detail explaining the negation residual disposition.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedTraitSpan']} })
    partial_promotion: Optional[bool] = Field(default=None, description="""True when part of this source span was promoted to one or more assertions while the retained residual still needs normalization or ontology curation.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedTraitSpan']} })
    pending_bearer: Optional[str] = Field(default=None, description="""Bearer phrase still awaiting PO or reviewed FLOPO-local anatomy grounding.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedTraitSpan']} })
    promoted_po_ids: Optional[list[str]] = Field(default=None, description="""PO identifiers already promoted from a partially resolved source span.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedTraitSpan']} })
    extractor: str = Field(default=..., description="""Extraction implementation that produced this unresolved record.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedTraitSpan', 'TraitAssertion']} })


class TraitAssertion(ConfiguredBaseModel):
    """
    One grounded entity-quality statement: an anatomical entity (PO) bears a quality (PATO), optionally with a quantitative phenotype value, bearer context quality, modality, season, or negation, justified by a retained source statement. In flora data this is normally a source-scoped universal or qualified TBox claim, not an observation or measurement event.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/flopo/flopo-trait'})

    phenotype_class_iri: Optional[str] = Field(default=None, description="""Authoritative semantic annotation target: the stable IRI of the equivalent OWL class expression in the FLOPO annotation extension. It is outside the FLOPO term namespace, is generated deterministically after extraction, and is required in materialized annotation datasets.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion'], 'slot_uri': 'FLOPOANN:phenotype_class'} })
    anatomical_entity: str = Field(default=..., description="""The plant anatomical structure the quality inheres in: normally a Plant Ontology class, or a reviewed FLOPO-local extension of the PO hierarchy when PO lacks the bearer.""", json_schema_extra = { "linkml_meta": {'annotations': {'annotators': {'tag': 'annotators', 'value': 'sqlite:obo:po'},
                         'prompt': {'tag': 'prompt',
                                    'value': 'The plant part or anatomical structure '
                                             'described (e.g. leaf, petal, stem, '
                                             'ovary). Prefer PO; use a FLOPO-local '
                                             'anatomy class only when it has an '
                                             'approved definition, asserted '
                                             'superclass, and any applicable parthood '
                                             'axiom.'}},
         'domain_of': ['TraitAssertion']} })
    quality: str = Field(default=..., description="""The phenotypic quality or attribute (PATO).""", json_schema_extra = { "linkml_meta": {'annotations': {'annotators': {'tag': 'annotators',
                                        'value': 'sqlite:obo:pato'},
                         'prompt': {'tag': 'prompt',
                                    'value': 'The quality, attribute, or state '
                                             'asserted of the anatomical structure '
                                             '(e.g. red, ovate, glabrous, length, '
                                             'pubescent).'}},
         'domain_of': ['TraitAssertion']} })
    trait: Optional[str] = Field(default=None, description="""Optional pre-composed plant trait this corresponds to (Trait Ontology).""", json_schema_extra = { "linkml_meta": {'annotations': {'annotators': {'tag': 'annotators', 'value': 'sqlite:obo:to'}},
         'domain_of': ['TraitAssertion']} })
    raw_entity_text: Optional[str] = Field(default=None, description="""Verbatim or minimally normalized entity expression emitted by the extractor.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    raw_quality_text: Optional[str] = Field(default=None, description="""Verbatim or minimally normalized quality/value expression emitted by the extractor.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    bearer_start: Optional[int] = Field(default=None, description="""Zero-based inclusive offset of the verbatim bearer mention raw_entity_text in the source segment. Provenance only: it locates the exact bearer occurrence supporting this assertion and is null when the bearer is only the record organ heading with no local mention. It is not part of any FAC / logical signature.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    bearer_end: Optional[int] = Field(default=None, description="""Zero-based exclusive offset of the verbatim bearer mention raw_entity_text in the source segment. Paired with bearer_start and never part of a FAC / logical signature.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    entity_mention_id: Optional[str] = Field(default=None, description="""Identifier of the terminology mention supporting anatomical_entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    quality_mention_ids: Optional[list[str]] = Field(default=None, description="""Identifiers of terminology mentions supporting the quality or its values.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    value_text: Optional[str] = Field(default=None, description="""Categorical/free-text value of the trait when not numeric (e.g. \"ovate\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    value_operator: Optional[ValueOperator] = Field(default=ValueOperator.atomic, description="""Derived extraction/indexing field used to construct and verify phenotype_class_iri. one_of preserves textual alternatives and must never be converted to conjunctive is_a axioms; this field is not the authoritative semantic annotation target.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion'], 'ifabsent': 'ValueOperator(atomic)'} })
    value_terms: Optional[list[str]] = Field(default=None, description="""Grounded PATO or FLOPO identifiers for atomic, conjunctive, or alternative values.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    bearer_context_qualities: Optional[list[str]] = Field(default=None, description="""Additional PATO qualities that inhere in the same anatomical bearer and form part of the OWL phenotype class description, for example young or mature. These are conjunctive bearer qualities, not developmental-stage process classes or assertion modalities.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    developmental_stage_contexts: Optional[list[DevelopmentalStageContext]] = Field(default=None, description="""PO developmental or life-cycle stages during which this phenotype is present. These contextualize the phenotype class as a whole; age or maturity qualities inhering in the anatomical bearer belong in bearer_context_qualities instead.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    developmental_stage_operator: Optional[ValueOperator] = Field(default=ValueOperator.atomic, description="""Logical relationship among multiple developmental-stage contexts. one_of is compiled as an anonymous OWL union in the FAC definition and never minted in FLOPO proper.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion'], 'ifabsent': 'ValueOperator(atomic)'} })
    value_low: Optional[float] = Field(default=None, description="""Lower bound of a quantitative phenotype range (e.g. 3 in \"3-7 cm\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    value_high: Optional[float] = Field(default=None, description="""Upper bound of a quantitative phenotype range (e.g. 7 in \"3-7 cm\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    value_low_inclusive: Optional[bool] = Field(default=True, description="""Whether value_low is an inclusive bound. True (default) renders xsd:minInclusive; False renders xsd:minExclusive for a strict lower bound. Only meaningful when value_low is set.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion'], 'ifabsent': 'True'} })
    value_high_inclusive: Optional[bool] = Field(default=True, description="""Whether value_high is an inclusive bound. True (default) renders xsd:maxInclusive; False renders xsd:maxExclusive for a strict upper bound such as the French participial \"n'atteignant pas 0,5 mm\". Only meaningful when value_high is set.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion'], 'ifabsent': 'True'} })
    unit: Optional[str] = Field(default=None, description="""Unit for the quantitative phenotype value (Units of Measurement Ontology).""", json_schema_extra = { "linkml_meta": {'annotations': {'annotators': {'tag': 'annotators', 'value': 'sqlite:obo:uo'}},
         'domain_of': ['TraitAssertion']} })
    modifier: Optional[FrequencyModifier] = Field(default=None, description="""Deprecated combined hedge field retained for wire compatibility. New data must populate the orthogonal frequency, epistemic, value, and degree qualifier fields.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    frequency_qualifier: Optional[FrequencyQualifier] = Field(default=FrequencyQualifier.unspecified, description="""Frequency force of the flora statement; unspecified preserves an absent cue.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion'], 'ifabsent': 'FrequencyQualifier(unspecified)'} })
    epistemic_modality: Optional[EpistemicModality] = Field(default=EpistemicModality.asserted, description="""Epistemic force with which the source presents the statement.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion'], 'ifabsent': 'EpistemicModality(asserted)'} })
    value_qualifier: Optional[ValueQualifier] = Field(default=ValueQualifier.exact, description="""Exactness or approximation of a categorical or numerical value.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion'], 'ifabsent': 'ValueQualifier(exact)'} })
    degree_qualifier: Optional[DegreeQualifier] = Field(default=DegreeQualifier.unmodified, description="""Degree cue kept separate from frequency and epistemic modality.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion'], 'ifabsent': 'DegreeQualifier(unmodified)'} })
    modality_text: Optional[str] = Field(default=None, description="""Exact lexical cue or phrase (for example \"usually\" or \"possibly\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    modality_start: Optional[int] = Field(default=None, description="""Zero-based inclusive offset of the verbatim modality cue modality_text in the source segment, when a cue is present. Provenance only and never part of a FAC / logical signature.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    modality_end: Optional[int] = Field(default=None, description="""Zero-based exclusive offset of the verbatim modality cue modality_text in the source segment. Paired with modality_start and never part of a FAC / logical signature.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    season_contexts: Optional[list[SeasonContext]] = Field(default=None, description="""Seasonal contexts that are part of this phenotype class description.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    season_operator: Optional[ValueOperator] = Field(default=ValueOperator.atomic, description="""Logical relationship among multiple seasonal contexts. one_of is represented as an anonymous union in the annotation-extension class definition and never minted as a FLOPO vocabulary class.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion'], 'ifabsent': 'ValueOperator(atomic)'} })
    negated: Optional[bool] = Field(default=False, description="""True if the source makes an explicitly scoped negative phenotype assertion.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion'], 'ifabsent': 'boolean(false)'} })
    negation_scope: Optional[NegationScope] = Field(default=None, description="""OWL scope of an explicit negation. quality asserts an existing bearer that does not satisfy the quality expression; absence asserts that no part satisfying the complete bearer-plus-quality expression exists. Required whenever negated is true and omitted otherwise.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    cardinality: Optional[str] = Field(default=None, description="""Count when the trait is a number of parts (e.g. \"stamens 6\"). Free text to allow ranges.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    source_text: str = Field(default=..., description="""The exact span of the source segment that justifies this assertion (provenance / anti-hallucination anchor). MUST be copied verbatim from the input.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    source_statement_id: Optional[str] = Field(default=None, description="""Identifier of the retained SourceStatement supporting this formal assertion. It is assigned deterministically before persistence when an older extractor omits it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    source_start: Optional[int] = Field(default=None, description="""Zero-based inclusive offset of source_text in its source segment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    source_end: Optional[int] = Field(default=None, description="""Zero-based exclusive offset of source_text in its source segment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    extractor: Optional[str] = Field(default=None, description="""Extraction implementation that produced the assertion (e.g. openrouter or deterministic_baseline).""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedTraitSpan', 'TraitAssertion']} })
    confidence: Optional[float] = Field(default=None, description="""Model self-reported confidence in [0,1]; refined later by self-consistency voting.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    normalization_status: Optional[NormalizationStatus] = Field(default=None, description="""How the entity/quality normalization was obtained or why it remains unresolved.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    mapping_provenance: Optional[list[str]] = Field(default=None, description="""Stable registry term identifiers or retrieval methods supporting normalization.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })


class SeasonContext(ConfiguredBaseModel):
    """
    A source-retained seasonal qualification that is compiled into the OWL phenotype class description. Named seasons may use ENVO or FLOPO annotation vocabulary terms; calendar intervals use month bounds and remain geographically scoped.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/flopo/flopo-trait'})

    season_term: Optional[str] = Field(default=None, description="""CURIE of a named season, for example ENVO:03000129 or FLOPOANN:wet_season.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeasonContext']} })
    season_text: str = Field(default=..., description="""Exact seasonal phrase copied from the source statement.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeasonContext']} })
    start: Optional[int] = Field(default=None, description="""Inclusive offset of season_text in the source segment, when available.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement',
                       'UnresolvedTraitSpan',
                       'SeasonContext',
                       'DevelopmentalStageContext',
                       'TermMention']} })
    end: Optional[int] = Field(default=None, description="""Exclusive offset of season_text in the source segment, when available.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement',
                       'UnresolvedTraitSpan',
                       'SeasonContext',
                       'DevelopmentalStageContext',
                       'TermMention']} })
    start_month: Optional[int] = Field(default=None, description="""Calendar start month in the inclusive range 1 through 12.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeasonContext']} })
    end_month: Optional[int] = Field(default=None, description="""Calendar end month in the inclusive range 1 through 12.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeasonContext']} })
    hemisphere: Optional[Hemisphere] = Field(default=None, description="""Hemisphere context if explicitly established; never inferred from a season word alone.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeasonContext']} })
    geographic_context: Optional[str] = Field(default=None, description="""Geographic entity CURIE or source-retained region label qualifying the season.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeasonContext']} })
    temporal_relation: Optional[SeasonRelation] = Field(default=SeasonRelation.present_during, description="""Relation used when compiling the seasonal class restriction.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeasonContext', 'DevelopmentalStageContext'],
         'ifabsent': 'SeasonRelation(present_during)'} })


class DevelopmentalStageContext(ConfiguredBaseModel):
    """
    A source-retained PO developmental or life-cycle stage that temporally scopes a phenotype class. It is distinct from a PATO age/maturity quality of the anatomical bearer and from a specimen-preparation state such as \"when dry\".
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/flopo/flopo-trait'})

    stage_term: str = Field(default=..., description="""PO (or reviewed FLOPO-local PO extension) class for the developmental stage.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DevelopmentalStageContext']} })
    stage_text: str = Field(default=..., description="""Exact developmental-stage phrase copied from the source statement.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DevelopmentalStageContext']} })
    start: Optional[int] = Field(default=None, description="""Inclusive offset of stage_text in the source segment, when available.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement',
                       'UnresolvedTraitSpan',
                       'SeasonContext',
                       'DevelopmentalStageContext',
                       'TermMention']} })
    end: Optional[int] = Field(default=None, description="""Exclusive offset of stage_text in the source segment, when available.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement',
                       'UnresolvedTraitSpan',
                       'SeasonContext',
                       'DevelopmentalStageContext',
                       'TermMention']} })
    temporal_relation: Optional[DevelopmentalStageRelation] = Field(default=DevelopmentalStageRelation.present_during, description="""Relation used when compiling the stage restriction on the phenotype.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeasonContext', 'DevelopmentalStageContext'],
         'ifabsent': 'DevelopmentalStageRelation(present_during)'} })


class TermMention(ConfiguredBaseModel):
    """
    A source-text span matched to prior botanical terminology before extraction.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/flopo/flopo-trait'})

    mention_id: str = Field(default=..., description="""Segment-local stable identifier used to link an assertion to this mention.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermMention']} })
    start: int = Field(default=..., description="""Zero-based inclusive character offset of the mention in the source segment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement',
                       'UnresolvedTraitSpan',
                       'SeasonContext',
                       'DevelopmentalStageContext',
                       'TermMention']} })
    end: int = Field(default=..., description="""Zero-based exclusive character offset of the mention in the source segment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement',
                       'UnresolvedTraitSpan',
                       'SeasonContext',
                       'DevelopmentalStageContext',
                       'TermMention']} })
    surface_form: str = Field(default=..., description="""Verbatim text covered by the mention span.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnresolvedTraitSpan', 'TermMention']} })
    normalized_form: str = Field(default=..., description="""Case-, accent-, and punctuation-normalized form used for lookup.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermMention']} })
    language: Optional[str] = Field(default=None, description="""BCP 47 language code inherited from the source segment or glossary.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceStatement', 'TermMention']} })
    semantic_roles: Optional[list[str]] = Field(default=None, description="""Candidate botanical roles such as entity, attribute, or value.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermMention']} })
    registry_term_ids: Optional[list[str]] = Field(default=None, description="""Stable BTERM records whose forms match this span.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermMention', 'TermCandidate']} })
    candidates: Optional[list[TermCandidate]] = Field(default=None, description="""Ranked PO, PATO, or FLOPO normalization candidates for the span.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermMention']} })
    longest_match: Optional[bool] = Field(default=None, description="""True when no longer overlapping terminology match contains this span.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermMention']} })
    overlap_group: Optional[int] = Field(default=None, description="""Segment-local number shared by overlapping mention alternatives.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermMention']} })
    match_type: Optional[str] = Field(default=None, description="""Lookup method, for example exact, inflection, or retrieved.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermMention']} })
    organ_context: Optional[str] = Field(default=None, description="""Organ heading used as a soft ranking prior for this mention.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermMention']} })
    logical_operator: Optional[ValueOperator] = Field(default=None, description="""Logical relationship among component_ids when this is a compound expression.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermMention']} })
    component_ids: Optional[list[str]] = Field(default=None, description="""PATO or FLOPO values forming a reviewed conjunction or disjunction.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermMention']} })
    attribute_id: Optional[str] = Field(default=None, description="""PATO attribute used when the mention denotes a categorical value expression.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermMention']} })


class TermCandidate(ConfiguredBaseModel):
    """
    A constrained ontology normalization candidate for a botanical source span.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/flopo/flopo-trait'})

    target_id: str = Field(default=..., description="""CURIE of the proposed PO, PATO, or FLOPO normalization target.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermCandidate']} })
    label: str = Field(default=..., description="""Preferred label of the target at registry build time.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermCandidate']} })
    namespace: str = Field(default=..., description="""Target ontology namespace, restricted operationally to PO, PATO, or FLOPO.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermCandidate']} })
    score: float = Field(default=..., description="""Reproducible hybrid retrieval score in the closed interval [0,1].""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermCandidate']} })
    mapping_relation: Optional[str] = Field(default=None, description="""SKOS or FLOPO relation asserted or proposed between source term and target.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermCandidate']} })
    review_status: Optional[str] = Field(default=None, description="""Curation state; only a human workflow may assign reviewed status.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermCandidate']} })
    registry_term_ids: Optional[list[str]] = Field(default=None, description="""Stable BTERM records supporting this candidate.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermMention', 'TermCandidate']} })
    evidence: Optional[list[str]] = Field(default=None, description="""Retrieval, synonym-scope, or curation evidence supporting the candidate.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TermCandidate']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
TraitExtraction.model_rebuild()
SourceStatement.model_rebuild()
UnresolvedTraitSpan.model_rebuild()
TraitAssertion.model_rebuild()
SeasonContext.model_rebuild()
DevelopmentalStageContext.model_rebuild()
TermMention.model_rebuild()
TermCandidate.model_rebuild()
