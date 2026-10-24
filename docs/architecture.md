# Architecture and configuration

[Back to README](../README.md)

## Runtime

```text
Streamlit → LangGraph StateGraph → typed diagnostic tools
                    │                       │
                    ▼                       ▼
             Ollama on localhost    read-only Neo4j MCP process
                                            │
                                            ▼
                                    Neo4j Community in Docker
```

Streamlit invokes the compiled graph directly; there is no backend API server. MCP runs as a local
stdio subprocess and executes fixed Cypher templates. CLI investigations can select the direct Bolt
driver with `--transport bolt`. Seeding and source ingestion use the driver for transactional writes.

`LLM_PROVIDER=ollama` uses the official Ollama Python client and a downloaded model. The optional
`openai` provider uses the configured OpenAI-compatible endpoint; this mode may require internet and
sends retrieved evidence to that endpoint. Neither provider automatically falls back to the other.

## Ontology and construction

Two implementations currently coexist:

| | Temporal investigation lab | Local-export importer / original demo |
| --- | --- | --- |
| Ontology | `knowledge/ontology.v2.json` | `knowledge/ontology.json` |
| Scope | `datasetId=sre-temporal-v2` | `demo_id=inputs-*` or `incident-detective-v1` |
| Population | `temporal_demo.py seed` | `ingest.py` or `seed.py` |
| Time representation | Native UTC datetime properties | UTC strings and indexed millisecond timestamps |
| Current Streamlit app | Reads this graph | Not exposed by the current workspace |

The temporal ontology describes 14 labels: System, Component, K8sWorkload, K8sCluster, StorageVolume,
StateSnapshot, Observation, Change, Deployment, CodeArtifact, Commit, Person, Incident and Finding.
The **Ontology** view reads the same specification used by fixture validation. Application validation
checks declared properties, types, required fields and relationship endpoints. Neo4j Community
provides ID uniqueness constraints; it does not enforce the whole ontology.

The temporal fixture generator is `knowledge/temporal_fixture.py`. Seeding validates its records,
regenerates `data/temporal_scenarios.json`, and imports 152 nodes and 204 relationships into a dedicated
dataset. Records include source references and hashes. Repeating an unchanged seed is safe; conflicting
immutable records are rejected. Seeding does not delete unrelated data.

The temporal lab is a prepared dataset, not a live ingestion pipeline. Connecting the existing source
adapters to this ontology requires an explicit mapping/migration. See [construction](ingestion.md).

## Two clocks

`validFrom` / `validTo` describe when a relationship or state held. `recordedAt` / `supersededAt`
describe when that version was available to the investigator. Intervals are half-open: `[start, end)`.

- **Retrospective:** reconstruct incident-time state using knowledge available at the demo reference time.
- **Known at the time:** exclude records unavailable at the incident-time knowledge cutoff.

The reference clock is `2026-10-23T08:05:00Z`. It is deliberately fixed, so the same questions keep
their meaning after the real calendar advances. State, placement, observations, changes and release
provenance are filtered by the resolved request; historical confirmations are context, not proof.

## Investigation lifecycle

```text
resolve question → immediate topology → target observations → matching history
    → form hypotheses → choose check → execute check → assess
                            ↑                          │
                            └──── continue/revise ─────┘
                            └──── stop → diagnosis → validate → finalize
```

The model chooses among `expand_dependencies`, `inspect_observations`, `inspect_state_changes` and
`inspect_running_code`. Checks target discovered resource IDs. Further dependencies must be discovered
before their records can be inspected. Repeated identical checks are blocked.

Budgets limit hypotheses to 3, checks to 8, model calls including retries to 10, dependency hops to 3,
and investigation time to 180 seconds. Individual requests also have timeouts. The model payload has
a 60 KB guard; the investigation evidence graph is capped at 150 nodes and 300 edges. Limits may
reduce recall. A truncated query cannot establish that no matching evidence exists.

Structured validation checks schema, citations, cause entities, evidence ownership and numerical claims.
It cannot prove causality. A model may stop at a propagation path without finding the initiating change;
the deeper Payments case remains a diagnostic-quality challenge. The prior measurement window is a
configured reference, not a learned normal range or an SLO.

Results retain source records, measurements, hypothesis/check histories, assessments, budgets and
query/stage records. Neo4j stores graph facts and historical findings; per-run LangGraph state is not
persisted in a second database. The current temporal workspace is read-only and has no finding
confirmation form. The original prototype's confirmation implementation remains in source.

## Configuration

Use [`.env.example`](../.env.example) as the configuration reference. Keep credentials in the ignored
`.env`; `scripts/setup_env.py` creates it once with a generated database password and restrictive mode.

| Settings | Purpose |
| --- | --- |
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | Local database connection |
| `LLM_PROVIDER` | Explicit `ollama` or `openai` selection |
| `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_SECONDS` | Downloaded local model and request timeout |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS` | Optional compatible endpoint |

Database and Ollama endpoints are restricted to loopback. OpenAI endpoint validation permits remote
HTTPS URLs. LangSmith and legacy tracing flags are forcibly disabled. Driver/MCP telemetry,
Streamlit statistics and Neo4j usage reporting are disabled. Compose copies bundled APOC locally;
startup does not download a plugin. GDS is not required.

Restart Streamlit after changing database or Ollama settings. Provider settings have a separate refresh
path today; configuration consolidation is recorded in the [cleanup review](cleanup-review.md).

## Offline operation

Use the README's offline commands after installing all artifacts. `uv --offline` prevents dependency
downloads; it does not itself prevent application networking. The temporal verifier denies nonlocal
Python socket connections when using Ollama or evidence-only mode.

On macOS, the included localhost-only profile can also constrain launched processes and their children.
Run these in separate terminals, with no existing instance using the same port:

```bash
OLLAMA_NO_CLOUD=1 sandbox-exec -f scripts/localhost-only.sb ollama serve
sandbox-exec -f scripts/localhost-only.sb uv run --offline streamlit run app.py
sandbox-exec -f scripts/localhost-only.sb uv run --offline python scripts/verify_temporal.py --with-model
```

Neo4j runs separately in Docker. Its exposed ports bind to loopback. PyVis JavaScript and styles are
inline; the graph iframe has a restrictive content security policy and no CDN dependency. Browser
inspection should confirm requests remain local. Socket guards and process isolation do not constitute
a claim that the whole Mac's internet connection has been physically disabled.

## Growth

Bounded retrieval, query timeouts and model limits protect individual investigations, not total storage
or constant query latency. The temporal graph explorer currently scans the graph before applying its
display cap. There is no retention worker or long-duration ingestion benchmark for the temporal graph.
Before continuous operation, add scoped/indexed queries, keyset pagination, event aggregation,
retention/archiving and tests that preserve evidence needed by confirmed historical findings.
