"""Build a self-contained, deployable release of the Saudi Flora Trait Atlas.

    python -m tools.atlas_release [--stamp 20261023-1200]

Writes ``local-corpora/saudi-flora/releases/<stamp>/`` with

- ``rdf/<name>.nq``: every graph of ``manifest.json`` plus ``ontology/flopo-inferred.owl``, as
  N-Quads in its named graph. Blank-node labels are prefixed per input file, so labels that two
  files happen to share stay distinct in the index;
- ``web/``: the browser (``web/saudi/``) and ``summary.json``;
- ``release.json``: git commit, triple count and SHA-256 per graph, which the checks compare
  against the loaded endpoint.

The QLever index is built from ``rdf/`` by ``tools/deploy_atlas.sh``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pyoxigraph as ox

from flopo2.saudi.server import DATA, WEB, _inputs

RELEASES = DATA / "releases"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def export_graph(source: Path, graph: str, target: Path, tag: str) -> int:
    """Write ``source`` into ``graph`` as N-Quads; returns the number of triples."""

    fmt = ox.RdfFormat.RDF_XML if source.suffix == ".owl" else ox.RdfFormat.from_extension(source.suffix.lstrip("."))
    name = ox.NamedNode(graph)
    count = 0

    def term(t):
        return ox.BlankNode(f"{tag}{t.value}") if isinstance(t, ox.BlankNode) else t

    def quads():
        nonlocal count
        for q in ox.parse(path=str(source), format=fmt, lenient=True):
            count += 1
            yield ox.Quad(term(q.subject), q.predicate, term(q.object), name)

    ox.serialize(quads(), output=str(target), format=ox.RdfFormat.N_QUADS)
    return count


def build(stamp: str, out: Path = RELEASES, data: Path = DATA, web: Path = WEB) -> Path:
    release = out / stamp
    if release.exists():
        raise SystemExit(f"{release} exists; choose another stamp")
    (release / "rdf").mkdir(parents=True)
    graphs = []
    for i, (graph, source) in enumerate(_inputs(data, with_flopo=True)):
        started = time.time()
        target = release / "rdf" / f"{i:02d}-{graph.rstrip('/').rsplit('/graph/', 1)[-1].replace('/', '-')}.nq"
        triples = export_graph(source, graph, target, tag=f"g{i}x")
        graphs.append({"graph": graph, "source": str(source), "file": f"rdf/{target.name}", "triples": triples,
                       "sha256": _sha256(target)})
        print(f"{graph}: {triples} triples ({time.time() - started:.1f}s)", file=sys.stderr)
    shutil.copytree(web, release / "web")
    shutil.copy2(data / "summary.json", release / "web" / "summary.json")
    meta = {
        "stamp": stamp,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": _git("rev-parse", "HEAD"),
        "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "triples": sum(g["triples"] for g in graphs),
        "graphs": graphs,
    }
    for target in (release / "release.json", release / "web" / "release.json"):
        target.write_text(json.dumps(meta, indent=1) + "\n")
    return release


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d-%H%M"))
    parser.add_argument("--out", type=Path, default=RELEASES)
    args = parser.parse_args(argv)
    print(build(args.stamp, args.out))


if __name__ == "__main__":
    main()
