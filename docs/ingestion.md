# Constructing a graph from local exports

[Back to README](../README.md)

This importer reads local service manifests, deployments, incident records, structured logs and OTLP
trace exports. Adapters construct graph facts using explicit rules; no model invents graph edges.

**Current boundary:** this path writes the earlier five-label ontology in `inputs-*` namespaces.
The temporal Streamlit workspace reads `sre-temporal-v2` and does not display these imports.
The importer demonstrates continuous construction independently; it is not live ingestion for the
temporal lab. The original seeded UI is preserved at tag `dummy_data`.

```text
Append-only JSONL → strict adapter → ontology validation and canonical IDs
                                  → Neo4j facts + provenance + source cursor
                                    (one atomic transaction)
```

## Exercise continuous updates

After the README's local database setup, use a fresh output directory:

```bash
uv run python scripts/create_ingestion_example.py --output artifacts/source-demo --namespace inputs-source-demo --stage initial
uv run python ingest.py --sources artifacts/source-demo/sources.json --watch
```

Leave the watcher running. In a second terminal, append events and a later topology version:

```bash
uv run python scripts/create_ingestion_example.py --output artifacts/source-demo --stage incident
uv run python scripts/create_ingestion_example.py --output artifacts/source-demo --stage changed-topology
```

The watcher reports committed source offsets and errors. Stop with Ctrl-C; restart the same command
to resume. Omit `--watch` for one poll, which may leave additional batches to process. The initial
generator refuses to overwrite an existing source registry.

Inspect the constructed graph in [Neo4j Browser](http://localhost:7474):

```cypher
MATCH (n {demo_id: 'inputs-source-demo'})
OPTIONAL MATCH (n)-[r]->(m {demo_id: 'inputs-source-demo'})
RETURN n, r, m
LIMIT 200
```

The catalog establishes `web-api → report-store → loader`. Matched cross-service trace spans establish
`loader → source-adapter`. A later catalog closes the old declared relationship interval and points to
`backup-adapter`. Historical investigation queries can still retrieve the earlier topology.

The retained original investigator can query the constructed incident from the CLI. This command
requires the configured local Ollama model:

```bash
uv run python scripts/verify_demo.py --namespace inputs-source-demo --incident inputs-source-demo:incident:alert-export:alert-42 --output artifacts/source-investigation --offline-audit
```

## Ontology and mapping rules

[`knowledge/ontology.json`](../knowledge/ontology.json) defines allowed node properties, required
types, relationship endpoints and identity rules. [`knowledge/ontology.py`](../knowledge/ontology.py)
validates them and installs uniqueness constraints and indexes. The five operational labels are
Component, Deployment, Incident, Symptom and Finding. IngestionSource stores cursor/control metadata.

| Source | Graph meaning |
| --- | --- |
| Full service catalog | Explicit `depends_on` declarations become dependency edges |
| Deployment record | A release changed its named component |
| Error log | A symptom was observed on its named component |
| Explicit incident reference | A symptom belongs to a named incident |
| OTLP trace | Matched CLIENT→SERVER or PRODUCER→CONSUMER spans establish an observed dependency |

A dependency or recent deployment does not establish causality. New entity/relationship types require
an ontology change, mapping, tests and migration. A source checkpoint records its ontology version and
rejects an incompatible version change.

Component identity combines namespace, environment and exact service name. Event identity combines
namespace, entity type, source ID and external event ID. Catalog metadata outranks metadata inferred
from other sources. Relationships retain file/line references, source IDs, hashes, method and validity
times. Declared topology has versioned intervals; trace-derived edges expire after 15 minutes and are
aggregated by source/service pair/minute. Other component metadata is not fully bitemporal.

## Bring your own exports

Copy [`examples/sources.example.json`](../examples/sources.example.json) and update the registry's
paths, namespace, source IDs and environments. Paths resolve relative to the registry. Adapter contracts
are in [`ingestion/adapters.py`](../ingestion/adapters.py); each newline commits one complete JSON object.

These adapters expect specific structured formats, not arbitrary log text. OTLP envelopes must include
`service.name`, `resourceSpans`, `scopeSpans` and trace/span/parent IDs. Cross-export span assembly is
not implemented; an absent parent produces no inferred edge. Environments must agree with the registry.

The input contract is append-only. Graph facts and the byte cursor commit in the same transaction.
Replay uses stable IDs; conflicting payloads for immutable event IDs are rejected. Full catalogs must
arrive chronologically. Referenced incidents must exist before their logs can commit.

Bad schema, missing endpoints, stale catalogs or database errors leave the affected source cursor
unchanged while other sources continue. Register rotated/reconfigured files with a new source ID.
Fingerprints detect truncation and common replacement errors, not every possible edit to an old file.
Automatic rotation discovery, quarantine management and versioned incident updates are not implemented.

## Bounds and retention

Each poll reads at most 50 complete lines per source. A line is limited to 1 MiB and a trace export to
2,000 spans. A partial trailing line waits for its newline. The watcher resumes from persistent offsets.
Deployment and symptom retrieval uses namespace/component/time indexes; dependency retrieval is
bounded and reports truncation. These bounds are separate from the newer temporal loop's budgets.

Accepted events and catalog history remain stored. There is no automatic retention or archiver. Define
a hot evidence horizon, aggregate repeated symptoms and retain raw exports before sustained ingestion.
Preserve the records cited by confirmed findings when compacting history. A small generated benchmark
is available as `uv run python scripts/benchmark_graph.py --noise 10000`; it is not a production
capacity guarantee and does not benchmark the temporal ontology.
