# Incident Detective

A temporal SRE investigation lab. A bounded LangGraph loop forms hypotheses, chooses typed checks
against a local Neo4j knowledge graph, evaluates the returned evidence and produces a diagnosis
package. All operational components, code and events are synthetic. The model provider is explicit:
Ollama for offline inference, or the configured OpenAI-compatible endpoint. The latter sends synthetic
evidence to that endpoint and requires internet access. There is no automatic provider fallback.

## Temporal SRE graph and question lab (ontology v2)

The approved model is `knowledge/ontology.v2.json`. It is separate from the original five-label
fixture and source-ingestion namespaces. It includes systems, components, code, commits and people,
deployments, operational changes, observations, incidents/findings, workload/cluster/storage context,
and state history. No Kubernetes cluster or real-time ingestion pipeline is required.

Populate the realistic, prepared dataset in local Neo4j:

```bash
uv run python temporal_demo.py seed
```

This idempotently imports **152 nodes and 204 relationships** in `sre-temporal-v2`, validates source
records against the approved property/endpoint definitions, and uses native UTC temporal properties.
It does not delete existing graph data. The exact fixture is `data/temporal_scenarios.json`; evidence
references resolve to JSON pointers in that file. Code and infrastructure are synthetic.

The prepared clock is **2026-10-23 10:05 Europe/Berlin (08:05 UTC)**. "Now" uses that displayed
reference time, not the host clock. "3AM today" resolves to **2026-10-23 01:00 UTC**.
Payments has recovered by the reference time; billing errors and profile instability are also modeled.
The historical Payments case includes a storage allocation change (3000 → 300 → 3000 IOPS), a later
workload cluster move, a database patch, a Payments release, an undeployed commit, exact log/error and
alert records, trace timings, and baseline/incident/recovery metrics.

Run evidence retrieval first, or invoke the hypothesis loop using the provider in `.env`:

```bash
uv run python temporal_demo.py ask "What was wrong with payments API at 3AM today?" --evidence-only
uv run python temporal_demo.py ask "What was wrong with payments API at 3AM today?" --output artifacts/payments-3am
uv run python temporal_demo.py ask "What was wrong with payments API at 3AM today?" --mode known_then --output artifacts/payments-replay
uv run python temporal_demo.py ask "Why is payments API slow now?" --output artifacts/payments-now
uv run python temporal_demo.py ask "Why does billing API throw errors?" --output artifacts/billing
uv run python temporal_demo.py ask "Why is profile service unstable?" --output artifacts/profile
```

Use `--at 2026-10-23T03:00:00+02:00` to override time explicitly. Name/alias resolution uses actual
graph entities; ambiguous or unknown targets request clarification. General natural-language time
parsing is not implemented: AM/PM times and explicit ISO overrides are supported.

Each execution uses a real LangGraph StateGraph with conditional routing. The model chooses typed
tools; fixed parameterized Cypher executes through the official local Neo4j MCP server in read-only
mode. `--transport bolt` is an explicit driver alternative. No model output becomes executable Cypher.
Knowledge-time filters distinguish historical replay from later retrospective analysis.

```text
resolve question/time → immediate topology → target observations → prior matching incidents
  → form hypotheses → choose check → execute check → assess hypotheses ─┐
                          ↑                                          │
                          └───────── continue / revise ───────────────┘
                          └───────── stop → diagnosis → validate → finalize
```

The model can call `expand_dependencies`, `inspect_observations`, `inspect_state_changes` and
`inspect_running_code`. It sees the check history and may support, refute or leave a hypothesis
unresolved, add another within the budget, select another check, or stop. The initial neighborhood
contains one application dependency hop; further discovery is selected by the model. Previous
incidents are matched by shared observation patterns and topology overlap, then ranked by overlap
and recency. Matching history suggests explanations; it does not confirm the current cause.

Hard limits: **3 hypotheses, 8 checks, 10 model calls including retries, 3 dependency hops and 180
seconds**. Each invalid decision has at most one retry. Duplicate checks cannot execute again.
Budget exhaustion returns an incomplete package with retrieved evidence. Model or tool failure
preserves that evidence and reports unavailable analysis; no successful diagnosis is manufactured.
A proposed stop immediately after discovering new resources gets at most one model review of query
coverage, within the same call/time budgets. This can select another typed check; it does not assign
diagnostic meaning to error names or automatically declare a cause.

Diagnostic policy is in [`agent/skills/temporal-diagnosis/SKILL.md`](agent/skills/temporal-diagnosis/SKILL.md).
The model interprets record contents and relationships. There is no error-name allowlist that decides
which events establish a mechanism. Retrieved observation and configuration properties reach the
model without a scenario-specific field filter. Deterministic validation checks schema, citations,
time-scoped provenance, metric references and evidence ownership; **it cannot prove causal correctness**.

Current live checks with GPT-5 mini identified the prepared Profile cache-limit fault and Billing
adapter schema change. The deeper Payments case still sometimes stops at upstream propagation
instead of establishing the storage-allocation trigger. That case remains a diagnostic-quality gap;
a structurally valid `complete` result is not sufficient evidence that its root cause is correct.

Every output directory contains `investigation.json` and a self-contained `report.html`, including
measured values, exact windows/sample counts, deterministic differences/ratios, source messages,
trace samples, state history, changes, code/release provenance, an interactive graph and query/stage
records. It also retains `hypothesisTests`, executed checks, assessment history, next-action reasons,
budget usage and stop reasons for the deferred hypothesis-tree UI. The baseline is explicitly a
**configured prior-window reference**, not a learned normal
range, SLO, or separate baseline profile. Measurement records are stored as `Observation` nodes.

Streamlit opens **Temporal SRE lab**. It includes question-driven diagnosis, ontology v2
inspection and searchable stored graph history. Results remain in session state on reruns; another
model call requires the Investigate button. The earlier prototype is retained in source and at
`dummy_data`; only the temporal lab is exposed in the current app. Live activity displays each
hypothesis, its selected checks, returned records, assessments and the next action. The completed
tree remains available alongside the diagnosis and evidence graph without another model request.
Live checks render outside the collapsible status header. Completed check results remain expanded,
and the previous diagnosis package stays mounted until the next investigation finishes.

To use the official OpenAI endpoint, edit the existing ignored `.env` locally:

```dotenv
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5-mini
OPENAI_API_KEY=<your OpenAI API key>
LANGSMITH_TRACING=false
```

GPT-5 mini uses `max_completion_tokens=4096`, `reasoning_effort=low`, and no custom temperature,
with the same bounded loop and JSON schema. See the [Chat Completions API parameters](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
The workshop URL `https://graphacademy.neo4j.com/api/llm/v1` can also be configured, using a model
allowed by that workshop; it rejected GPT-5 mini during verification. An `inactive` response from
that proxy requires reactivating the lesson. Keys remain server-side and are never written into
reports. For fully offline inference use
`LLM_PROVIDER=ollama` and an already downloaded `OLLAMA_MODEL`; install dependencies and the Docker
image beforehand. MCP telemetry and LangSmith tracing are disabled. Compose copies bundled APOC from
the Neo4j image locally, with no plugin download on startup.

```bash
uv run streamlit run app.py
RUN_NEO4J_TESTS=1 uv run pytest -q tests/test_temporal.py
uv run pytest -q -m 'not integration and not llm'
RUN_NEO4J_TESTS=1 uv run pytest -q tests/test_diagnostic_tools.py tests/test_temporal.py
uv run python scripts/verify_temporal.py --with-model --output artifacts/loop-validation
```

The temporal tests exercise historical versus current state/placement, late-arriving evidence,
known-then replay, numeric/error grounding, actual running code versus undeployed commits, idempotent
seeding and a dependency-edge ablation rolled back in its transaction. Retrieval/output caps and
timeouts bound this prototype; production ingestion, retention and capacity testing remain deferred.

## Initial local setup and earlier prototype

Prerequisites: Docker with a running local engine, Ollama, and uv. Python 3.11–3.13 is supported.
Initial package, Docker image and model downloads require internet access. Subsequent runtime uses
localhost only.

The manually seeded prototype is preserved at Git tag **`dummy_data`** (`4606d5a`). The current
implementation also constructs a separate graph incrementally from local source exports. The
source example remains synthetic; no real monitoring platform or production environment is connected.

Run these commands from this repository:

```bash
python3 scripts/setup_env.py
uv sync
docker compose up -d
ollama list
ollama pull qwen2.5:14b-instruct
uv run python seed.py
uv run python scripts/preflight.py
uv run pytest -q
uv run ruff check .
uv run streamlit run app.py
```

If Ollama is not running, start the macOS Ollama application or run
`OLLAMA_NO_CLOUD=1 ollama serve` in another terminal.
The seed script waits for Neo4j with bounded retries. `preflight.py` checks the actual database, both
incidents, the configured installed model, and a short JSON-schema response. It never downloads a
model automatically.

- Dashboard: <http://localhost:8501>
- Neo4j Browser: <http://localhost:7474>
- Neo4j Bolt: `bolt://localhost:7687`
- Ollama: <http://localhost:11434>

`scripts/setup_env.py` creates `.env` with a generated password and mode 0600. It preserves an existing
file. The Compose service and Python driver read the same password. Do not commit `.env`.
Use the password from your private `.env` when logging into Neo4j Browser as `neo4j`.

The image is pinned to **Neo4j Community 2026.10.0**, the version used in the
[official Docker installation documentation](https://neo4j.com/docs/operations-manual/current/docker/introduction/).
Ports bind only to loopback. Compose uses its own named volumes and does not alter other containers.
If either port is already occupied, stop the conflicting service or explicitly adjust both Compose
and `.env`; the application never connects to a cloud database.

## Investigate

The dashboard has three workspace views:

- **Ontology:** a schema diagram generated from `knowledge/ontology.json`, entity/property inspection,
  permitted relationship directions, source construction rules, and the downloadable contract.
  This view works without Neo4j or Ollama.
- **Knowledge Graph:** stored instances queried directly from the selected Neo4j namespace, independent
  of investigation results. Filter entity/relationship types, inspect node and relationship provenance,
  focus a neighborhood, and download the displayed subgraph. It does not call Ollama.
- **Investigation:** the bounded LangGraph workflow, hypotheses, evidence, memory, and confirmation.

In **Knowledge Graph**, the default is all recorded dependency history. Choose an incident under
**Dependency time** to filter dependency validity intervals at that incident's timestamp. Other stored
events and the latest component metadata remain visible. Pagination uses stable entity IDs, with
50–200 nodes per page and at most 400 relationships. Only connections between displayed nodes are
shown; the view explicitly reports when a display budget is reached. Refresh after ingestion commits.

1. Select **INC-104 — Analytics API failure**, then click **Investigate**.
2. Follow the dependency path from Analytics API through Analytics Store and Ingestion Pipeline to
   Event Connector. A deployment changes the connector at 10:38 UTC; a schema mismatch appears at
   10:41; API errors follow at 10:42. INC-092 supplies a confirmed historical mapping regression.
3. Inspect the leading hypothesis, its cited evidence and missing information. Compare the connector
   mapping before and after the deployment to verify the proposed mechanism. Chronology is not proof.
4. Select **INC-105 — Orders API timeout**. No deployment is found in its dependency graph in the
   preceding 30 minutes. Pool exhaustion at 14:12 and request timeouts at 14:15, together with INC-071,
   support investigating application connection-pool limits, active connections and pending acquisitions.
5. Hover, pan and zoom the graph. **Inspect a graph node** exposes complete retrieved properties.
   Download the investigation JSON for a reproducible record.

The expected scenario explanations are a demo guide, not hardcoded agent responses. Model output
depends on the retrieved evidence. Removing the connector deployment removes it from eligible causes,
citations and highlights. The model may return up to three hypotheses without numeric confidence scores.

The app runs inference only when **Investigate** is clicked. Node inspection, downloads and form edits
reuse the result in Streamlit session state. Results are kept separately for each selected incident.

## Construct the graph from source records

The ingestion path accepts service manifests, release records, incident records, structured logs,
and OTLP/JSON trace exports. It derives graph mutations from source facts. It does not accept
prewritten graph edges or ask an LLM to invent relationships.

```text
Local append-only JSONL exports
    → strict source adapter
    → versioned ontology validation + canonical identity
    → transactional Neo4j facts, provenance and source cursor
    → bounded, time-aware investigation queries
```

Exercise construction and continuous updates in three terminals:

```bash
# Create raw source exports and their source registry (run once in a fresh output directory).
uv run python scripts/create_ingestion_example.py --stage initial

# Start continuous ingestion; leave this terminal running. Ctrl-C stops it safely.
uv run python ingest.py --sources artifacts/input-lab/sources.json --watch
```

```bash
# In a second terminal, append a release, an incident and application errors.
uv run python scripts/create_ingestion_example.py --stage incident

# In a third terminal, run the dashboard.
uv run streamlit run app.py
```

Refresh the dashboard, choose **Constructed from local sources · inputs-lab** in **GRAPH DATA**, and
investigate `alert-42`. The `web-api → report-store → loader` path comes from the catalog. The
`loader → source-adapter` edge comes from matching trace/span parent IDs across services; the manifest
does not declare it. Hover over an edge or inspect a node to see provenance. Expand **Graph
construction · ontology & sources** to see the committed source offsets.

Append a topology change while the worker is running:

```bash
uv run python scripts/create_ingestion_example.py --stage changed-topology
```

Refresh the dashboard. `alert-43` at 11:02 follows the newly declared `backup-adapter` dependency.
Re-investigating `alert-42` at 10:42 still follows the previous topology. Catalog updates close old
relationship intervals; trace observations expire after 15 minutes. Intervals are `[start, end)`.
This is dependency/event-time history; component descriptions retain the latest authoritative metadata,
not a complete bitemporal history of every property.

For a one-batch import, omit `--watch`. A poll reads at most 50 complete lines per source and reports
remaining bytes. The watcher processes subsequent batches. Each line is limited to 1 MiB; each trace
export to 2,000 spans. A partial final line waits for its terminating newline.

To verify real local reasoning on the constructed graph:

```bash
uv run python scripts/verify_demo.py --namespace inputs-lab \
  --incident inputs-lab:incident:alert-export:alert-42 \
  --output artifacts/constructed --offline-audit
```

### Ontology and construction rules

**`knowledge/ontology.json` is the versioned ontology.** It defines the five operational entity types,
required/allowed property names and types, permitted relationship endpoints, identity policy and
construction semantics. `knowledge/ontology.py` enforces it and installs Neo4j uniqueness constraints
and time-window indexes. `ingestion/adapters.py` defines the strict input contracts and their mappings.
`IngestionSource` is an additional control-plane label for atomic ingestion checkpoints; it is never
included in evidence or sent to the model.

| Input | What establishes a relationship | What it does not establish |
|---|---|---|
| Full service catalog snapshot | Explicit `depends_on` declaration | Actual traffic or causality |
| OTLP trace export | Cross-service CLIENT→SERVER or PRODUCER→CONSUMER parent/child span IDs in one trace | Unobserved dependencies or incident causes |
| Deployment record | A release changed its named service | That release caused an error |
| Structured error log | An error was observed on its named service | A dependency based on similar text |
| Explicit incident reference in a log | The symptom belongs to a named incident | Automatic correlation from timing alone |
| Human confirmation | A reviewed finding explains an incident | Permission for the model to confirm itself |

These are human-defined domain rules. A new relationship type requires an ontology/code change,
tests and migration; an LLM cannot silently extend the ontology. Source checkpoints retain the ontology
version and refuse subsequent commits under a different version until explicitly migrated.

Components use `(graph namespace, environment, service name)` as their canonical identity. Events use
`(graph namespace, entity type, source ID, external event ID)`. Exact service naming is required across
sources: aliases are not guessed. Authoritative catalog metadata outranks inferred component metadata
from logs/traces; same-priority metadata uses the most recent observation. Relationships retain source
ID, file/line reference, payload hash, construction method and applicable validity times. Nodes also
retain first ingestion time. Trace samples are aggregated per source/service-pair/minute, preserving
first and last validity bounds and bounded provenance samples.

### Source contracts and replay

Copy `examples/sources.example.json` and supply your own local exports. Paths are relative to the
registry file. Each input line is a JSON object; these first adapters intentionally support explicit
formats rather than attempting to interpret arbitrary text. Common examples:

```json
{"observed_at":"2026-10-23T10:00:00Z","services":[{"name":"api","type":"service","description":"Request handler","depends_on":["store"]},{"name":"store","type":"storage","description":"Storage","depends_on":[]}]}
```

```json
{"id":"release-1","service":"api","timestamp":"2026-10-23T10:38:00Z","version":"1.2.0","description":"Changed connection pool configuration"}
```

```json
{"id":"alert-1","service":"api","timestamp":"2026-10-23T10:42:00Z","summary":"Requests time out","severity":"SEV-1","status":"open"}
```

```json
{"id":"log-1","service":"api","timestamp":"2026-10-23T10:41:00Z","severity":"ERROR","error_type":"REQUEST_TIMEOUT","message":"Connection acquisition timed out","incident_id":"alert-1","incident_source":"alert-export"}
```

The OTLP adapter reads one JSON `ExportTraceServiceRequest` envelope per line, with `resourceSpans`,
`resource.attributes` including `service.name`, and `scopeSpans[].spans`. It supports numeric or enum
span kinds, `traceId`, `spanId`, `parentSpanId` and `startTimeUnixNano`. The registry supplies the
environment; a resource `deployment.environment.name`, when present, must agree. Missing parents
produce a warning and no inferred edge. Joining spans across separate exports is not implemented;
configure an exporter to emit complete traces or add a bounded span assembler before this adapter.
The mapping follows [OpenTelemetry parent/child span semantics](https://opentelemetry.io/docs/specs/otel/trace/api/).

The input contract is **append-only**. Newlines delimit committed source records. Graph changes and
the byte cursor commit in one Neo4j transaction. Crash recovery resumes at that cursor; duplicate
events use stable IDs and cannot create duplicate facts. Conflicting payloads for the same event ID
are rejected. These initial event adapters are immutable records; mutable incident lifecycle updates
need a versioned update adapter. Full catalog snapshots must arrive chronologically.

Bad schema, unresolved endpoints, stale catalogs or transaction failures block that source without
advancing its cursor; other sources continue. Import referenced incident sources before their logs,
or let the watcher retry once those incidents arrive. The CLI reports blocked-source errors; the UI
shows last successful commits, not an assurance that a source is healthy. Prefix/tail fingerprints
detect truncation and common replacement errors, not arbitrary edits anywhere in a large file.
Preserve rotated files and register a new path/source ID. Automatic rotation discovery, correction
workflows and quarantine/replay administration are not implemented. Source configuration changes also
require a new source ID. Rebuild from retained exports into a new `inputs-*` namespace when testing a
new mapping, rather than altering the baseline graph.

### Growth and processing cost

Graph size, query work, visual graph size and model context are different budgets:

- The worker processes bounded batches with persistent offsets; it does not reread the entire history.
- Component identity indexes provide starting points. Composite `(namespace, component, timestamp)`
  indexes filter deployments and symptoms using numeric UTC timestamps. A separate symptom-type/time
  index supports memory matching. Live tests use `PROFILE` to check index usage.
- Dependency retrieval uses bounded breadth-first expansion: depth 3, at most 16 dependencies per
  component and 64 components total. It retains one discovered path per component, avoiding enumeration
  of every possible path. Truncation is explicitly reported in the evidence and model limitations.
- Each investigation returns at most 50 recent deployments and 100 recent symptoms. Historical matching
  examines at most 8 current symptom types and 100 candidates per type before ranking 5 incidents.
  Caps trade recall for predictable output size; truncated searches cannot establish absence.
- Model requests have a 32 KB serialized evidence/schema guard, plus the existing bounded generation
  and timeouts. Oversized evidence preserves the graph/UI and reports analysis unavailable. This byte
  guard is not an exact token count or a guarantee that every model will fit the same context.
- Depth and row caps do not make database work constant: Neo4j may still scan/sort many relationships
  at a high-degree node. The induced evidence graph can also grow dense. Query timeouts and the model
  guard fail safely; further graph pagination/aggregation remains necessary for very dense incidents.

Neo4j documents both [composite index planning](https://neo4j.com/docs/cypher-manual/current/indexes/performance-indexes/using-indexes/)
and the risk of [path-count growth in variable-length traversals](https://neo4j.com/docs/cypher-manual/current/patterns/variable-length-paths/).

Measure actual retrieval with disposable generated data:

```bash
uv run python scripts/benchmark_graph.py --noise 10000
```

The final executed warm local run measured approximately 39 ms before and 38 ms after adding 10,000 old
symptoms on the affected service; both returned the same four relevant components and no out-of-window
symptoms. The variation is measurement/cache noise, not evidence that larger graphs are faster.
A separate 100-dependency root returned 19 bounded components and explicitly reported truncation.
This small generated benchmark does not establish production capacity or ingestion throughput.

**Storage still grows without a retention policy.** INFO/DEBUG logs are excluded and trace relationships
are bucketed, but accepted error events and catalog history are retained. There is no automatic deletion
or archiver yet. Before sustained high-volume operation, define a hot evidence horizon, aggregate
repeated symptoms into time buckets, archive raw exports on local disk, and pin confirmed findings and
their supporting deployments/incidents. Compaction must retain evidence references and explicitly mark
historical coverage gaps. Query limits protect investigations; they do not replace storage lifecycle
management. No million-node or long-duration ingestion claim has been verified.

## Confirmed memory

After independently verifying a cause, expand **Confirm a verified finding**, select an eligible current
component or recent deployment, enter the verified conclusion, check the confirmation box and save.
The app transactionally creates `Finding → EXPLAINS → Incident` and
`Finding → ATTRIBUTED_TO → Component/Deployment`. Repeating the same incident, entity and normalized
conclusion returns the same finding. A model never confirms its own hypothesis.

Historical memory ranks incidents by shared symptom-type count, then recency and ID. It excludes
future incidents and findings created after the investigated incident. Consequently, a confirmation
saved today will inform an incident with a later timestamp; it will not retroactively change a historical
investigation. Historical findings provide context rather than proof of a current cause.

## Architecture and bounds

```text
Streamlit → compiled LangGraph StateGraph
             load_incident
             → traverse_dependencies
             → collect_evidence
             → analyze_evidence (official Ollama Python client)
             → validate_hypotheses
             → conditional finalize / fallback → END

           Neo4j Community ← fixed, parameterized Cypher
           Ollama host     ← JSON schema, temperature 0, fixed sampling seed
```

- Seven actual LangGraph nodes; no cycles, model tool loop, generated Cypher or backend API server.
- Controlled retrieval-error exits prevent incomplete state reaching normal analysis nodes.
- Dependency traversal includes the affected service and follows `DEPENDS_ON` to depth 3.
- Changes and symptoms are limited to the 30 minutes up to the incident timestamp.
- Stable evidence IDs identify incidents, paths, deployments, symptoms and historical findings.
- Validation rejects invalid schemas, invented citations or causes, ungrounded deployment/incident IDs
  and timestamps, invalid ranks, more than three hypotheses and explicit assertions of a confirmed cause.
  These checks constrain output; they do not prove that a model's causal interpretation is correct.
- The reasoning request uses the Pydantic JSON schema with enums for retrieved causes/citations,
  1,800 generated tokens, a fixed seed and low temperature. Invalid output gets one retry; connection
  failures/timeouts fall back immediately. `OLLAMA_TIMEOUT_SECONDS` defaults to 90, capped at 180.
- If Ollama fails, retrieved evidence, graph and memory remain available, with no fabricated hypotheses.
- Neo4j is the sole persistent application database; LangGraph state describes one execution.
- The PyVis model uses only retrieved nodes and relationships. Inline bundled vis-network assets,
  disabled physics, explicit hierarchy levels and semantic arrow direction keep the graph stable offline.
- Components such as Analytics Store and Orders Database are metadata, not running infrastructure.

## Configuration

See [.env.example](.env.example). `NEO4J_URI` accepts only a loopback Bolt address;
`OLLAMA_HOST` accepts only a loopback HTTP address. Remote endpoints, redirects, inherited HTTP proxies,
cloud-tagged models and remote-backed model metadata are rejected. Do not run Ollama in a mode that
proxies model requests to a remote service. For defense in depth, start a dedicated Ollama process
with `OLLAMA_NO_CLOUD=1`.

`LANGSMITH_TRACING=false` is enforced at import time along with legacy tracing flags. No LangSmith
key is required. The LangGraph dependency tree includes LangSmith libraries, but tracing is disabled.
Streamlit usage statistics and Neo4j driver telemetry/usage reports are disabled.
Neo4j Fleet Manager and discovery broadcasts are also disabled.

To use a different downloaded model, set `OLLAMA_MODEL` in `.env`, run `ollama list`, then rerun
`scripts/preflight.py` and `scripts/verify_demo.py`. There is no automatic remote or larger-model fallback.
The selected default is **qwen2.5:14b-instruct**, a quantized model of approximately 9 GB that was
verified on the 24 GB Mac. The initial `qwen3:4b` model produced valid JSON but weaker causal explanations
and verification steps. It remains a smaller optional model; rerun the demo checks if you select it.
Ranked hypotheses must select a retrieved cause entity; the model can return no hypotheses when
evidence is too weak. It never needs to declare a cause confirmed in order to identify a suspect.

## Tests and real integration verification

```bash
uv run pytest -q
uv run ruff check .

# Actual Cypher tests; creates and removes only isolated test namespaces.
RUN_NEO4J_TESTS=1 uv run pytest -q -m 'integration and not llm'

# Full suite, including a real local-model investigation with the deployment removed.
RUN_NEO4J_TESTS=1 RUN_OLLAMA_TESTS=1 uv run pytest -q

# Actual Neo4j + LangGraph + Ollama, saved evidence JSON and standalone graph HTML.
uv run python scripts/verify_demo.py --offline-audit
```

Unit tests cover fixture integrity, independent fixture traversal, parameterized query dispatch,
evidence normalization, real LangGraph routing with mock dependencies, grounding, structured retries,
Ollama failure, graph construction, HTML escaping, confirmation validation and Streamlit reruns.
Neo4j integration tests execute the actual Cypher, idempotent seeding, time/noise filters, historical
memory, transactional confirmation, namespace isolation and deployment ablation. They are opt-in and
are not counted as verified unless explicitly executed successfully.

`verify_demo.py` calls the real local model. It exits nonzero if validated analysis is unavailable.
It saves `artifacts/INC-104.json`, `artifacts/INC-104.html` and the corresponding INC-105 files.
Artifacts and credentials are ignored by Git. No exact model wording is required by unit tests.

### Executed verification — 23 October 2026

The following checks passed on this 24 GB Apple Silicon Mac:

- `uv sync` generated the committed lockfile; `uv sync --locked --offline` also passed.
- `docker compose up -d` started Neo4j Community 2026.10.0. Seeding created 37 nodes and
  49 relationships, and live tests verified repeatable seeding and isolated confirmation writes.
- `scripts/preflight.py` reached Neo4j and Ollama, found both demo incidents, and obtained a real
  structured response from `qwen2.5:14b-instruct`.
- `RUN_NEO4J_TESTS=1 RUN_OLLAMA_TESTS=1 uv run --offline pytest -q`, launched under the
  localhost-only profile: **101 passed, no skips**. This includes real Cypher, Streamlit/PyVis checks,
  source construction, cursor atomicity, historical topology, and a real local-model investigation
  after removing the connector deployment, plus confirmation in the constructed graph's namespace.
- `uv run ruff check .`: passed.
- The subsequent ontology/graph workspace change passed **107 tests with the model test deselected**
  (`RUN_NEO4J_TESTS=1 uv run --offline pytest -q -m 'not llm'`). Chrome verified both diagrams, the
  source-derived four-component graph before any incident existed, provenance inspection, and dataset
  preservation across navigation. These read-only views do not invoke the model.
- Both real investigations completed through LangGraph and produced validated hypotheses. Both
  were also exercised in Chrome; the interactive graph, evidence, historical memory and node
  inspection rendered. Selecting or inspecting cached results did not repeat inference.
- A separate investigation of the graph built by `ingest.py` completed with real local Ollama
  analysis, both via CLI and in Chrome. Appending a catalog snapshot while the watcher was running
  updated the graph without reseeding. A concurrent verification run once exceeded the model timeout;
  sequential verification passed, and the timeout correctly preserved evidence without analysis.
- A deliberately unavailable model produced the expected evidence-preserving fallback, without
  hypotheses or suspected-cause highlights.
- Ollama and Streamlit ran under the macOS localhost-only profile. The network boundary check
  confirmed public TCP was denied while local services remained reachable, and both investigations
  passed `verify_demo.py --offline-audit`. The Mac's Wi-Fi was not physically disabled.

## Offline readiness

Before disconnecting, install everything and verify the artifacts exist locally:

```bash
uv sync --locked
docker image inspect neo4j:2026.10.0
ollama list
uv run python scripts/preflight.py
```

Disable Wi-Fi and unplug other internet connections on the Mac, keeping loopback available. Then run:

```bash
docker compose up -d --pull never
uv sync --locked --offline
uv run --offline python seed.py
uv run --offline python scripts/verify_demo.py --offline-audit
uv run --offline streamlit run app.py
```

In a browser, open the dashboard and investigate both incidents. Verify that the graph renders,
hypotheses and memory appear, and node inspection works. In browser developer tools, confirm that all
requests are to localhost. The graph iframe has a CSP forbidding network connections and uses inline
assets; it does not load fonts, CSS, JavaScript or icons from a CDN.

For a repeatable macOS check without changing the Mac's Wi-Fi, this repository also includes an
OS-enforced localhost-only profile. After downloading the model, launch Ollama and Streamlit in
separate terminals with this profile (stop any existing instance on those ports first):

```bash
OLLAMA_NO_CLOUD=1 sandbox-exec -f scripts/localhost-only.sb ollama serve
sandbox-exec -f scripts/localhost-only.sb uv run --offline streamlit run app.py
```

Then verify the network boundary and run both real investigations:

```bash
sandbox-exec -f scripts/localhost-only.sb uv run --offline python scripts/check_offline_boundary.py
sandbox-exec -f scripts/localhost-only.sb uv run --offline python scripts/verify_demo.py --offline-audit
```

The boundary check requires macOS to reject a public TCP connection while allowing all three local
services. The profile applies only to the launched process and its children. Neo4j exposes only
loopback ports, with usage reporting and Fleet Manager disabled. The browser uses localhost assets
and an inline graph with a restrictive CSP.
`--offline-audit` additionally denies nonlocal DNS/socket calls within Python. These checks demonstrate
operation with application internet access blocked; they do not claim that the Mac's Wi-Fi was turned off.

## Seed safety and reset

```bash
uv run python seed.py                # MERGE; repeat safely, preserve confirmations
uv run python seed.py --reset-demo   # explicit reset of incident-detective-v1 only
docker compose stop                 # preserve data volumes
```

Every seeded node carries `demo_id=incident-detective-v1`. All retrieval and memory queries are scoped.
The seed transaction refuses ID collisions with non-demo data and refuses reset if demo nodes have
relationships to another namespace. It never executes an unscoped delete. Do not remove Docker volumes
if you want to keep confirmed findings. Constraints enforce unique IDs per label.

## 90-second demo

- **0–15s:** “We have errors, deployments and dependencies, but root-cause evidence is scattered.”
- **15–40s:** Investigate INC-104; trace the API-to-connector dependency path and relevant deployment.
- **40–60s:** Show 10:38 deployment, 10:41 schema error, 10:42 API failure and INC-092 memory. Explain
  that the graph supports a hypothesis that still needs a mapping comparison.
- **60–75s:** Investigate INC-105; show pool exhaustion, historical context and no relevant deployment.
- **75–90s:** “Confirmed investigations make future investigations smarter.” Demonstrate explicit
  confirmation after describing the independent verification.

## Construction-first demo walkthrough

If the services are already running, open <http://localhost:8501>. Otherwise run these from the
repository root (start the Ollama app or `OLLAMA_NO_CLOUD=1 ollama serve` if needed):

```bash
docker compose up -d --pull never
uv sync --locked --offline
uv run python seed.py
uv run python scripts/preflight.py
uv run streamlit run app.py
```

For a fresh source-construction walkthrough, use a new output directory and namespace. The initial
stage refuses to overwrite an existing example. If it already exists, continue with the watcher:

```bash
# Second terminal: generate initial manifest/trace exports and watch them.
uv run python scripts/create_ingestion_example.py --output artifacts/live-demo \
  --namespace inputs-live-demo --stage initial
uv run python ingest.py --sources artifacts/live-demo/sources.json --watch
```

1. Open **Ontology**. Show the five operational types, seven relationship types, required properties,
   and the rules that permit each assertion. Select `Component`, then `Finding` in the type inspector.
2. Open **Knowledge Graph**, choose **Constructed from local sources · inputs-live-demo**, and click
   **Refresh graph**. Initially there are four components and three dependency relationships. Show
   `loader → source-adapter`: this dashed edge was derived from linked trace spans rather than a
   manifest declaration. Inspect its source reference in **Relationship properties**.
3. In a third terminal, append an incident and its supporting source records:

   ```bash
   uv run python scripts/create_ingestion_example.py --output artifacts/live-demo --stage incident
   ```

4. Wait for the watcher to report committed records, then **Refresh graph**. The graph grows from four
   to eight nodes: show the new deployment, incident and two symptoms. Inspect a node's source file,
   line and payload hash.
5. Open **Investigation**, select `alert-42`, and click **Investigate**. The local model interprets
   facts that were constructed by the pipeline. Its result remains a hypothesis requiring verification.
6. Append a topology change while the watcher continues running:

   ```bash
   uv run python scripts/create_ingestion_example.py --output artifacts/live-demo --stage changed-topology
   ```

7. Return to **Knowledge Graph**, click **Refresh graph**, and choose `alert-42 · 10:42 UTC`, then
   `alert-43 · 11:02 UTC` under **Dependency time**. The old incident retains the trace-observed source
   adapter; the later incident follows the declared backup adapter. Use the `Component` entity filter
   to make the topology change especially easy to see.

All example inputs are synthetic. This walkthrough demonstrates parsing, ontology enforcement,
identity resolution, incremental ingestion, provenance and time-aware retrieval. It does not claim
that a production environment has been discovered automatically.

## Hypothesis validation tree

The SRE sees each provisional hypothesis with its own validation branch:

```text
Hypothesis: <possible cause and mechanism>
  Validating
    Step 1: <specific evidence check>
      Result: <observed values, evidence references, implication>
    Step n: <next check>
      Result: <what was learned>
  Outcome: supported / refuted / unresolved
```

Agent events should retain the hypothesis ID, check, result, evidence IDs and next action.
The Streamlit activity view renders this tree from actual LangGraph updates and retains it after
completion. Source records and executed queries remain inspectable.
