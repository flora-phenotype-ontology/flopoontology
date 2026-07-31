"""Pinned PO/PATO/FLOPO target catalog used by botanical term alignment."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from flopo2.terminology.normalize import fold


_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_OWL = "http://www.w3.org/2002/07/owl#"
_OBO = "http://purl.obolibrary.org/obo/"
_OBO_IN_OWL = "http://www.geneontology.org/formats/oboInOwl#"


def canonical_curie(value: str) -> str:
    value = (value or "").strip()
    if re.match(r"^(?:PO|PATO|FLOPO):\d+$", value):
        return value.replace(":", "_", 1)
    return value


@dataclass
class OntologyTerm:
    curie: str
    label: str
    namespace: str
    synonyms: tuple[str, ...] = ()
    synonym_scopes: tuple[tuple[str, str], ...] = ()
    definition: str = ""
    parents: tuple[str, ...] = ()
    signature: str = ""
    deprecated: bool = False
    source: str = ""

    @property
    def forms(self) -> tuple[str, ...]:
        return (self.label, *self.synonyms)


@dataclass
class OntologyCatalog:
    terms: dict[str, OntologyTerm]
    form_to_ids: dict[str, set[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.form_to_ids:
            return
        for term in self.terms.values():
            if term.deprecated:
                continue
            for form in term.forms:
                normalized = fold(form)
                if normalized:
                    self.form_to_ids.setdefault(normalized, set()).add(term.curie)

    def namespaces_for_role(self, role: str) -> set[str]:
        if role == "entity":
            return {"PO"}
        if role == "quality":
            return {"PATO"}
        if role in {"value", "phenotype"}:
            return {"PATO", "FLOPO"}
        return {"PO", "PATO"}

    def exact(self, surface: str, role: str = "ambiguous") -> list[OntologyTerm]:
        allowed = self.namespaces_for_role(role)
        return [
            self.terms[curie]
            for curie in sorted(self.form_to_ids.get(fold(surface), ()))
            if self.terms[curie].namespace in allowed and not self.terms[curie].deprecated
        ]

    def relation_for_surface(self, term: OntologyTerm, surface: str) -> str:
        normalized = fold(surface)
        if fold(term.label) == normalized:
            return "skos:exactMatch"
        scopes = {fold(label): scope for label, scope in term.synonym_scopes}
        scope = scopes.get(normalized, "EXACT")
        return {
            "EXACT": "skos:exactMatch",
            "RELATED": "skos:relatedMatch",
            # OBO scope is relative to the class; SSSOM/SKOS predicate is subject -> class.
            "BROAD": "skos:narrowMatch",
            "NARROW": "skos:broadMatch",
        }.get(scope, "skos:relatedMatch")


def _quoted_value(line: str) -> str:
    match = re.search(r'"((?:\\.|[^"\\])*)"', line)
    if not match:
        return ""
    return match.group(1).replace('\\"', '"').replace("\\n", " ")


def _clean_obo_synonym(value: str) -> str:
    """Remove PO-style editorial scope notes embedded in synonym literals.

    Current PO serializations contain forms such as ``capitulum (exact)`` and
    ``capitula (exact, plural)`` while also carrying the formal OBO synonym
    scope after the quoted literal.  The parenthetical text is curation
    metadata, not part of the botanical surface form.
    """
    return re.sub(
        r"\s+\((?=[^)]*\b(?:exact|broad|narrow|related)\b)[^)]*\)$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()


def load_obo_metadata(path: Path) -> dict[str, dict]:
    """Read only the small subset of OBO metadata needed for retrieval."""
    out: dict[str, dict] = {}
    stanza: dict | None = None

    def finish() -> None:
        nonlocal stanza
        if stanza and stanza.get("id"):
            out[canonical_curie(stanza["id"])] = stanza
        stanza = None

    with Path(path).open(encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line == "[Term]":
                finish()
                stanza = {
                    "synonyms": [],
                    "synonym_scopes": [],
                    "parents": [],
                    "subsets": [],
                    "deprecated": False,
                }
                continue
            if line.startswith("["):
                finish()
                continue
            if stanza is None:
                continue
            if line.startswith("id: "):
                stanza["id"] = line[4:].strip()
            elif line.startswith("name: "):
                stanza["label"] = line[6:].strip()
            elif line.startswith("namespace: "):
                stanza["namespace"] = line[11:].strip()
            elif line.startswith("subset: "):
                stanza["subsets"].append(line[8:].strip())
            elif line.startswith("def: "):
                stanza["definition"] = _quoted_value(line)
            elif line.startswith("synonym: "):
                language_match = re.search(
                    r'"\s+(?:EXACT|BROAD|NARROW|RELATED)\s+'
                    r"([A-Za-z][A-Za-z_-]*)\s+\[",
                    line,
                )
                if language_match and language_match.group(1).casefold() not in {
                    "en",
                    "english",
                }:
                    continue
                synonym = _clean_obo_synonym(_quoted_value(line))
                if synonym:
                    stanza["synonyms"].append(synonym)
                    scope_match = re.search(r'"\s+(EXACT|BROAD|NARROW|RELATED)\b', line)
                    stanza["synonym_scopes"].append(
                        (synonym, scope_match.group(1) if scope_match else "RELATED")
                    )
            elif line.startswith("is_a: "):
                stanza["parents"].append(canonical_curie(line[6:].split()[0]))
            elif line == "is_obsolete: true":
                stanza["deprecated"] = True
        finish()
    return out


def _load_lexicon(path: Path, namespace: str, obo: dict[str, dict]) -> dict[str, OntologyTerm]:
    terms: dict[str, OntologyTerm] = {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            curie = canonical_curie(row["id"])
            metadata = obo.get(curie, {})
            synonyms: list[str] = []
            for value in (row.get("synonyms") or "").split("|"):
                if value and value not in synonyms:
                    synonyms.append(value)
            for value in metadata.get("synonyms", []):
                if value and value not in synonyms:
                    synonyms.append(value)
            terms[curie] = OntologyTerm(
                curie=curie,
                label=row["label"],
                namespace=namespace,
                synonyms=tuple(synonyms),
                synonym_scopes=tuple(metadata.get("synonym_scopes", ())),
                definition=metadata.get("definition", ""),
                parents=tuple(metadata.get("parents", ())),
                deprecated=bool(metadata.get("deprecated", False)),
                source=path.as_posix(),
            )
    return terms


def _load_obo_terms(path: Path, namespace: str) -> dict[str, OntologyTerm]:
    """Load every term from an OBO file, including scoped synonym metadata.

    The checked-in TSV lexicons are useful runtime indexes, but they can lag their
    upstream ontologies.  Evidence audits therefore need a catalog made directly
    from the pinned ontology artifacts rather than from those derived TSVs. Obsolete
    terms remain in ``terms`` so mappings to them can be diagnosed, but the catalog
    excludes them from its lexical index.
    """
    terms: dict[str, OntologyTerm] = {}
    for curie, metadata in load_obo_metadata(path).items():
        if not curie.startswith(f"{namespace}_"):
            continue
        label = metadata.get("label", "").strip()
        if not label:
            continue
        terms[curie] = OntologyTerm(
            curie=curie,
            label=label,
            namespace=namespace,
            synonyms=tuple(metadata.get("synonyms", ())),
            synonym_scopes=tuple(metadata.get("synonym_scopes", ())),
            definition=metadata.get("definition", ""),
            parents=tuple(metadata.get("parents", ())),
            deprecated=bool(metadata.get("deprecated", False)),
            source=Path(path).as_posix(),
        )
    return terms


def _load_flopo_owl_metadata(path: Path) -> dict[str, dict]:
    """Stream released FLOPO labels, definitions, hierarchy, and scoped synonyms.

    RDF/XML permits a named OWL class to be serialized either as an ``owl:Class``
    element or as an ``rdf:Description`` carrying ``rdf:type owl:Class``.  FLOPO's
    release contains both forms, so restricting the stream to the former silently
    drops valid normalization targets.  An untyped ``rdf:Description`` is only an
    annotation subject and must not by itself promote a registry reservation to a
    released class.
    """
    metadata: dict[str, dict] = {}
    if not Path(path).exists():
        return metadata
    synonym_properties = {
        "hasExactSynonym": "EXACT",
        "hasBroadSynonym": "BROAD",
        "hasNarrowSynonym": "NARROW",
        "hasRelatedSynonym": "RELATED",
    }
    context = etree.iterparse(
        str(path),
        events=("end",),
        tag=(f"{{{_OWL}}}Class", f"{{{_RDF}}}Description"),
        recover=True,
        huge_tree=True,
    )
    for _event, element in context:
        is_explicit_class = element.tag == f"{{{_OWL}}}Class"
        is_typed_class = any(
            type_element.get(f"{{{_RDF}}}resource", "") == f"{_OWL}Class"
            for type_element in element.findall(f"{{{_RDF}}}type")
        )
        if not (is_explicit_class or is_typed_class):
            element.clear(keep_tail=True)
            continue
        iri = element.get(f"{{{_RDF}}}about", "")
        curie = iri.rsplit("/", 1)[-1]
        if not re.fullmatch(r"FLOPO_\d{7}", curie):
            element.clear(keep_tail=True)
            continue
        label = element.findtext(f"{{{_RDFS}}}label", default="").strip()
        definition = element.findtext(f"{{{_OBO}}}IAO_0000115", default="").strip()
        deprecated = (
            element.findtext(f"{{{_OWL}}}deprecated", default="").strip().casefold() == "true"
        )
        synonyms: list[str] = []
        synonym_scopes: list[tuple[str, str]] = []
        for property_name, scope in synonym_properties.items():
            for synonym_element in element.findall(f"{{{_OBO_IN_OWL}}}{property_name}"):
                synonym = "".join(synonym_element.itertext()).strip()
                if synonym and synonym not in synonyms:
                    synonyms.append(synonym)
                    synonym_scopes.append((synonym, scope))
        parents = []
        for parent_element in element.findall(f"{{{_RDFS}}}subClassOf"):
            parent_iri = parent_element.get(f"{{{_RDF}}}resource", "")
            parent = canonical_curie(parent_iri.rsplit("/", 1)[-1])
            if re.fullmatch(r"(?:PO|PATO|FLOPO)_\d{7}", parent):
                parents.append(parent)
        metadata[curie] = {
            "label": label,
            "definition": definition,
            "synonyms": tuple(synonyms),
            "synonym_scopes": tuple(synonym_scopes),
            "parents": tuple(parents),
            "deprecated": deprecated,
        }
        element.clear(keep_tail=True)
        parent_element = element.getparent()
        if parent_element is not None:
            while element.getprevious() is not None:
                del parent_element[0]
    del context
    return metadata


def _load_flopo_registry(
    path: Path | None, owl_path: Path | None = None
) -> dict[str, OntologyTerm]:
    terms: dict[str, OntologyTerm] = {}
    owl_is_authoritative = bool(owl_path and Path(owl_path).is_file())
    owl_metadata = _load_flopo_owl_metadata(owl_path) if owl_is_authoritative else {}
    if path is not None and Path(path).is_file():
        with Path(path).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                iri = row.get("flopo_iri", "")
                curie = iri.rsplit("/", 1)[-1] if "/" in iri else canonical_curie(iri)
                if not curie.startswith("FLOPO_"):
                    continue
                # A registry row can reserve or describe an identifier without declaring an OWL
                # class. When the release OWL is available, only its explicit or rdf:type-based
                # class declarations are valid targets; annotation-only descriptions are excluded.
                if owl_is_authoritative and curie not in owl_metadata:
                    continue
                metadata = owl_metadata.pop(curie, {})
                terms[curie] = OntologyTerm(
                    curie=curie,
                    label=metadata.get("label") or row.get("label", "") or curie,
                    namespace="FLOPO",
                    synonyms=tuple(metadata.get("synonyms", ())),
                    synonym_scopes=tuple(metadata.get("synonym_scopes", ())),
                    definition=metadata.get("definition", ""),
                    parents=tuple(metadata.get("parents", ())),
                    signature=row.get("signature", ""),
                    deprecated=(
                        row.get("deprecated", "") in {"1", "true", "True"}
                        or bool(metadata.get("deprecated", False))
                    ),
                    source=(owl_path or path).as_posix(),
                )
    for curie, metadata in owl_metadata.items():
        if not metadata.get("label"):
            continue
        terms[curie] = OntologyTerm(
            curie=curie,
            label=metadata["label"],
            namespace="FLOPO",
            synonyms=tuple(metadata.get("synonyms", ())),
            synonym_scopes=tuple(metadata.get("synonym_scopes", ())),
            definition=metadata.get("definition", ""),
            parents=tuple(metadata.get("parents", ())),
            deprecated=bool(metadata.get("deprecated", False)),
            source=(owl_path or path).as_posix(),
        )
    return terms


def load_catalog_from_ontology_files(
    po_obo: Path,
    pato_obo: Path,
    flopo_owl: Path,
    flopo_registry: Path | None = None,
) -> OntologyCatalog:
    """Build an audit catalog from pinned PO/PATO and the released FLOPO OWL.

    Unlike :func:`load_catalog`, this deliberately bypasses the derived PO/PATO
    lexicon TSVs so a stale local index cannot make an extant upstream class look
    like an ontology gap.
    """
    terms = _load_obo_terms(po_obo, "PO")
    terms.update(_load_obo_terms(pato_obo, "PATO"))
    terms.update(_load_flopo_registry(flopo_registry, flopo_owl))
    return OntologyCatalog(terms)


def load_catalog(
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
    flopo_registry: Path = Path("config/flopo_id_registry.tsv"),
    po_obo: Path = Path("ont/plant_ontology.obo"),
    pato_obo: Path = Path("ont/quality.obo"),
    flopo_owl: Path = Path("ontology/flopo.owl"),
) -> OntologyCatalog:
    po_metadata = load_obo_metadata(po_obo) if Path(po_obo).exists() else {}
    pato_metadata = load_obo_metadata(pato_obo) if Path(pato_obo).exists() else {}
    terms = _load_lexicon(po_lexicon, "PO", po_metadata)
    terms.update(_load_lexicon(pato_lexicon, "PATO", pato_metadata))
    terms.update(_load_flopo_registry(flopo_registry, flopo_owl))
    return OntologyCatalog(terms)
