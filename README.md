# Incident Detective

A fully local incident investigation dashboard. LangGraph retrieves dependency paths, changes,
symptoms and confirmed historical findings from Neo4j, then asks a local Ollama model for bounded,
evidence-grounded hypotheses. Streamlit presents the evidence graph, ranked explanations, missing
evidence and the next verification action. All operational components and events are synthetic.

## Local setup — macOS Apple Silicon

Prerequisites: Docker with a running local engine, Ollama, and uv. Python 3.11–3.13 is supported.
Initial package, Docker image and model downloads require internet access. Subsequent runtime uses
localhost only.

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
  localhost-only profile: **75 passed, no skips**. This includes real Cypher, Streamlit/PyVis checks
  and a real local-model investigation after removing the connector deployment.
- `uv run ruff check .`: passed.
- Both real investigations completed through LangGraph and produced validated hypotheses. Both
  were also exercised in Chrome; the interactive graph, evidence, historical memory and node
  inspection rendered. Selecting or inspecting cached results did not repeat inference.
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
