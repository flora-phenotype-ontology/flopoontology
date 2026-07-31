# OBO Dashboard release gate

Every push must run the same checks used by the public OBO Foundry Dashboard against
the local `ontology/flopo.owl`, together with FLOPO's live OBO registry entry.

Run the gate manually from the repository root:

```bash
python3 tools/obo_dashboard_gate.py
```

The runner pins the official OBO Dashboard container currently used by the public
Dashboard: OBO-Dashboard commit `c3601a04810d5298643bcc6468acd2a5c3d0f08e`, ROBOT
1.9.8, and container digest
`sha256:2cccfdb398af41d475ed3a5730e0a69c25a7434a0c45e8d00a44ff1aaee0a817`.
The upstream container uses ROBOT 1.9.8 for its command-line preprocessing but its
Makefile currently downloads ROBOT 1.9.5 as the Python/Java Dashboard gateway. The
gate therefore also verifies that gateway jar's SHA-256 digest
`21e96a9f6ac90dacdb6fa1303ac9b49b0d2be3594ecacf4c0e3d0e68e86def57`.
It requires all 14 implemented Dashboard checks to run, logical consistency, zero
unsatisfiable classes, RDF/XML syntax, and zero `ERROR` results. This is the official
Dashboard definition of passing; `WARN` and `INFO` are reported but do not fail the
default gate. Use `--all-pass` when a completely green report is required.

Before starting the container, the gate reads the public Dashboard index and checks
that its advertised source commit and ROBOT version still match these pins. It fails
closed if upstream changes, so new or changed Dashboard checks must be reviewed and
incorporated deliberately. The runner also fails if any of the 14 expected checks is
missing or an unreviewed check appears in its output.

The first run downloads the pinned container and RO dependency. Repeated runs reuse
`~/.cache/flopo-obo-dashboard`. The generated HTML, YAML, and ROBOT report remain in
that cache for inspection.

The tracked `.githooks/pre-push` hook archives the ontology, configuration, and gate
script from every outgoing commit and runs the check on those exact bytes before Git
transfers any objects. Multiple refs at the same commit are checked once. Enable it in
a clone with:

```bash
git config core.hooksPath .githooks
```

GitHub Actions runs the same command as a second, independent guard.

## Publishing a new version IRI

FP04 performs a live HTTP request to the dated `owl:versionIRI`. A genuinely new
version cannot pass that check until its immutable release artifact and OBO PURL route
have been published. The gate deliberately has no FP04 bypass. For the initial FLOPO
release-route bootstrap, obtain explicit curator approval for the publication order,
publish the GitHub release asset and `/releases/` PURL route, and rerun this exact gate
before transferring the branch. Subsequent release IRIs must be prepared by the same
controlled publication workflow.
