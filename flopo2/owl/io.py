"""Read and write OWL Functional Syntax alongside rdflib's RDF syntaxes.

rdflib does not implement OWL Functional Syntax. FLOPO uses ROBOT/OWLAPI as the
lossless bridge: writers serialize a temporary N-Triples graph and render it as
``.ofn``; readers convert ``.ofn`` to RDF/XML before loading it into rdflib.
RDF-backed formats continue to use rdflib directly and therefore do not require
Java or ROBOT.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from rdflib import OWL, RDF, Graph, URIRef


FUNCTIONAL_FORMATS = frozenset({"ofn", "functional", "functional-syntax"})


def _normalized_format(value: str | None) -> str:
    return (value or "").strip().lower().replace("_", "-")


def is_functional_syntax(path: Path, owl_format: str | None = None) -> bool:
    """Return whether an explicit format or filename denotes OWL Functional Syntax."""

    normalized = _normalized_format(owl_format)
    if normalized:
        return normalized in FUNCTIONAL_FORMATS
    return Path(path).suffix.lower() == ".ofn"


def _robot_command() -> list[str]:
    configured = os.environ.get("FLOPO_ROBOT", "").strip()
    if configured:
        return [configured]

    root = Path(__file__).resolve().parents[2]
    wrapper = root / "bin" / "robot"
    if wrapper.is_file() and os.access(wrapper, os.X_OK):
        return [str(wrapper)]

    installed = shutil.which("robot")
    if installed:
        return [installed]

    jar = root / "tools" / "robot.jar"
    java = shutil.which("java")
    if jar.is_file() and java:
        return [java, "-jar", str(jar)]
    raise RuntimeError(
        "OWL Functional Syntax requires ROBOT/OWLAPI; set FLOPO_ROBOT or install "
        "bin/robot (tools/robot.jar)"
    )


def _convert(input_path: Path, output_path: Path, output_format: str) -> None:
    command = [
        *_robot_command(),
        "convert",
        "--input",
        str(input_path),
        "--format",
        output_format,
        "--output",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"ROBOT OWL conversion failed ({completed.returncode}): {detail}")


def _inject_functional_imports(path: Path, imports: list[str]) -> None:
    """Restore import declarations without asking OWLAPI to dereference them while writing."""

    if not imports:
        return
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^Ontology\([^\n]*\n", text, re.MULTILINE)
    if not match:
        raise RuntimeError("OWLAPI Functional Syntax output lacks an Ontology declaration")
    declarations = "".join(f"Import(<{iri}>)\n" for iri in imports)
    text = text[: match.end()] + declarations + text[match.end() :]
    path.write_text(text, encoding="utf-8")


def _without_functional_imports(path: Path, output: Path) -> list[str]:
    """Copy Functional Syntax while extracting project-generated absolute-IRI imports."""

    imports: list[str] = []
    kept: list[str] = []
    pattern = re.compile(r"^\s*Import\(<([^>]+)>\)\s*$")
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        match = pattern.match(line.rstrip("\r\n"))
        if match:
            imports.append(match.group(1))
        else:
            kept.append(line)
    output.write_text("".join(kept), encoding="utf-8")
    return imports


def serialize_ontology(graph: Graph, output_path: Path, owl_format: str = "turtle") -> None:
    """Serialize an rdflib graph, using OWLAPI when Functional Syntax is requested."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not is_functional_syntax(output_path, owl_format):
        graph.serialize(output_path.as_posix(), format=owl_format)
        return

    with tempfile.TemporaryDirectory(prefix="flopo-owl-write-") as directory:
        intermediate = Path(directory) / "ontology.nt"
        imports = sorted(
            str(value)
            for ontology in graph.subjects(RDF.type, OWL.Ontology)
            for value in graph.objects(ontology, OWL.imports)
            if isinstance(value, URIRef)
        )
        # ROBOT/OWLAPI eagerly loads imports during conversion.  Conversion does not require the
        # imported closure, so omit the triples temporarily and restore them as native Functional
        # Syntax declarations.  This makes source-module serialization deterministic offline.
        local_graph = Graph()
        for triple in graph:
            if triple[1] != OWL.imports:
                local_graph.add(triple)
        local_graph.serialize(intermediate.as_posix(), format="nt", encoding="utf-8")
        _convert(intermediate, output_path, "ofn")
        _inject_functional_imports(output_path, imports)


def parse_ontology(path: Path, owl_format: str | None = None) -> Graph:
    """Load RDF OWL or ``.ofn`` into an rdflib graph without losing OWL axioms."""

    path = Path(path)
    if not is_functional_syntax(path, owl_format):
        graph = Graph()
        graph.parse(path.as_posix(), format=owl_format)
        return graph

    with tempfile.TemporaryDirectory(prefix="flopo-owl-read-") as directory:
        local_input = Path(directory) / "ontology-local.ofn"
        intermediate = Path(directory) / "ontology.owl"
        imports = _without_functional_imports(path, local_input)
        _convert(local_input, intermediate, "owl")
        graph = Graph()
        graph.parse(intermediate.as_posix(), format="xml")
        ontology = next(graph.subjects(RDF.type, OWL.Ontology), None)
        if ontology is not None:
            for imported_iri in imports:
                graph.add((ontology, OWL.imports, URIRef(imported_iri)))
        return graph
