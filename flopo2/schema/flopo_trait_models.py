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
                    'one entity-quality observation for a taxon, grounded to PO '
                    '(entity) and PATO (quality) — optionally a TO trait and a UO '
                    'unit — with the source span for provenance. The '
                    '``annotators`` annotations make this directly usable as an '
                    'OntoGPT/SPIRES template (OAK grounds the named slots against '
                    'the listed ontologies).',
     'id': 'https://w3id.org/flopo/flopo-trait',
     'imports': ['linkml:types'],
     'license': 'https://creativecommons.org/publicdomain/zero/1.0/',
     'name': 'flopo-trait',
     'prefixes': {'BFO': {'prefix_prefix': 'BFO',
                          'prefix_reference': 'http://purl.obolibrary.org/obo/BFO_'},
                  'PATO': {'prefix_prefix': 'PATO',
                           'prefix_reference': 'http://purl.obolibrary.org/obo/PATO_'},
                  'PO': {'prefix_prefix': 'PO',
                         'prefix_reference': 'http://purl.obolibrary.org/obo/PO_'},
                  'RO': {'prefix_prefix': 'RO',
                         'prefix_reference': 'http://purl.obolibrary.org/obo/RO_'},
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

class FrequencyModifier(str, Enum):
    """
    Frequency/degree hedges common in floras ("usually pubescent", "rarely glabrous").
    """
    always = "always"
    usually = "usually"
    often = "often"
    sometimes = "sometimes"
    occasionally = "occasionally"
    rarely = "rarely"
    never = "never"



class TraitExtraction(ConfiguredBaseModel):
    """
    The set of trait assertions extracted from a single text segment (one organ block of one taxon). Carries the provenance needed to trace every assertion back to its source.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/flopo/flopo-trait', 'tree_root': True})

    taxon_name: Optional[str] = Field(default=None, description="""Verbatim taxon name string from the source treatment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitExtraction']} })
    organ_hint: Optional[str] = Field(default=None, description="""The FlorML char-class / subheading the segment came from (anatomical prior).""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitExtraction']} })
    assertions: Optional[list[TraitAssertion]] = Field(default=None, description="""The trait assertions found in this segment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitExtraction']} })


class TraitAssertion(ConfiguredBaseModel):
    """
    One grounded entity-quality observation: an anatomical entity (PO) bears a quality (PATO), optionally with a measured value/unit, modifier, or negation, justified by a source span.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/flopo/flopo-trait'})

    anatomical_entity: str = Field(default=..., description="""The plant anatomical structure the quality inheres in (Plant Ontology).""", json_schema_extra = { "linkml_meta": {'annotations': {'annotators': {'tag': 'annotators', 'value': 'sqlite:obo:po'},
                         'prompt': {'tag': 'prompt',
                                    'value': 'The plant part or anatomical structure '
                                             'described (e.g. leaf, petal, stem, '
                                             'ovary).'}},
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
    value_text: Optional[str] = Field(default=None, description="""Categorical/free-text value of the trait when not numeric (e.g. \"ovate\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    value_low: Optional[float] = Field(default=None, description="""Lower bound of a measured range (e.g. 3 in \"3-7 cm\"). Numbers only.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    value_high: Optional[float] = Field(default=None, description="""Upper bound of a measured range (e.g. 7 in \"3-7 cm\"). Numbers only.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    unit: Optional[str] = Field(default=None, description="""Measurement unit (Units of measurement ontology), e.g. cm, mm.""", json_schema_extra = { "linkml_meta": {'annotations': {'annotators': {'tag': 'annotators', 'value': 'sqlite:obo:uo'}},
         'domain_of': ['TraitAssertion']} })
    modifier: Optional[FrequencyModifier] = Field(default=None, description="""Frequency/degree hedge attached to the assertion in the text.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    negated: Optional[bool] = Field(default=False, description="""True if the text asserts the ABSENCE of the quality (e.g. \"leaves not hairy\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion'], 'ifabsent': 'boolean(false)'} })
    cardinality: Optional[str] = Field(default=None, description="""Count when the trait is a number of parts (e.g. \"stamens 6\"). Free text to allow ranges.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    source_text: str = Field(default=..., description="""The exact span of the source segment that justifies this assertion (provenance / anti-hallucination anchor). MUST be copied verbatim from the input.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })
    confidence: Optional[float] = Field(default=None, description="""Model self-reported confidence in [0,1]; refined later by self-consistency voting.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TraitAssertion']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
TraitExtraction.model_rebuild()
TraitAssertion.model_rebuild()
