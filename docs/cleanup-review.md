# Cleanup opportunities

Review date: 24 October 2026. This review identifies changes; it does not implement the refactor.
Existing uncommitted agent/UI work was preserved.

## 1. Connect ingestion to the ontology the app actually reads — P1

[`ingest.py`](../ingest.py) imports `knowledge.ontology`; [`ingestion/store.py`](../ingestion/store.py)
writes `demo_id` namespaces. [`knowledge/temporal_queries.py`](../knowledge/temporal_queries.py) reads
`datasetId=sre-temporal-v2`, with different observation, state and relationship contracts.

**Impact:** imported manifests/logs/deployments/traces cannot feed the current temporal workspace.
The two demos work independently, but the end-to-end construction story has a real integration gap.

**Change:** make the temporal ontology the canonical target, define explicit mappings and identity/time
rules for each adapter, and migrate into a fresh scoped dataset. Add a real integration test proving a
source append is retrieved by the temporal investigator. Keep legacy fixtures until this works.

## 2. Move and index the graph-browser queries — P2

[`ui/temporal_workspace.py`](../ui/temporal_workspace.py), `stored_graph_view`, embeds unlabelled Cypher
with dynamic property search and sorting. A real `EXPLAIN` of its default Component query produced:

```text
AllNodesScan → Filter → Projection → Top → Projection → ProduceResults
```

**Impact:** the 150-record display cap limits output, not the scan. More stored history or unrelated
data can increase search work. Rows after the cap have no pagination path, and relationship results
use an unordered limit.

**Change:** put explorer queries behind the repository, select labels from the ontology allowlist,
add indexes appropriate to scope/order/search, and use stable keyset pagination for nodes and edges.
Keep “All types” as an explicit bounded query strategy. Compare query plans and database work using
the same generated history before and after; the present dataset does not establish capacity.

## 3. Consolidate configuration and refresh behavior — P2

[`agent/providers.py`](../agent/providers.py), `ModelSettings.from_env`, rereads `.env` and gives it
precedence over process variables. [`config.py`](../config.py), `Settings.from_env`, reads the process
environment after a one-time `load_dotenv()`. `get_temporal_reasoner` constructs Ollama settings through
that second path. The database resource is cached without a configuration key.

**Impact:** changing providers/OpenAI settings and changing Ollama/database settings have different
refresh behavior. A shell override can also lose to `.env` for one provider but win elsewhere.

**Change:** use one typed configuration loader with documented precedence, validate the selected
provider once, and make restart/cache invalidation behavior explicit. Test configuration changes using
temporary files and environment mocks. Never include credentials in a cache key exposed to the UI.

## 4. Split the workspace and distinguish rendering errors — P2

[`ui/temporal_workspace.py`](../ui/temporal_workspace.py) combines navigation, database queries,
ontology rendering, PyVis adaptation, session state, graph execution and hypothesis activity in roughly
730 lines. Its outer exception handler reports every failure as “Local Neo4j is unavailable”.

**Impact:** a renderer or result-shape bug appears to be a database outage. UI and retrieval changes
are coupled. The new `ui/presentation.py` already starts separating pure presentation helpers.

**Change:** finish that extraction, give each workspace its own module, move queries into the
repository, and catch connection errors at the database boundary. Preserve stage/render failure
details separately, without leaking credentials. Add a regression test for a rendering failure while
Neo4j remains reachable.

## 5. Retire unreachable and overlapping investigation paths — P2

[`agent/temporal.py`](../agent/temporal.py), `build_temporal_investigator`, immediately delegates to
the hypothesis loop when a reasoner is provided. The nested one-shot `analyze_evidence` branch that
calls `reasoner.analyze_package()` is therefore unreachable. The original `agent/graph.py` pipeline,
legacy query/UI modules, and two ontology formats also remain alongside the temporal stack.
`scripts/preflight.py` still requires the original INC-104/INC-105 seed rather than checking the
temporal dataset used by the current app.

**Impact:** parallel state/result/validation contracts make it harder to identify the supported path
and easier to fix one implementation while leaving another inconsistent.

**Change:** name the evidence-only workflow explicitly, remove unreachable one-shot reasoning after
checking references, and separate legacy/demo code behind a clear compatibility boundary. Consolidate
shared result contracts and temporal predicates before deleting code still used by ingestion tests
and `verify_demo.py`. The `dummy_data` tag already preserves the original prototype.

## Suggested order

Agree the canonical ontology and adapter mapping first. Then extract the repository/UI boundaries,
fix explorer query plans and pagination, unify configuration, and retire redundant paths. Retention,
archiving and temporal performance tests should precede sustained ingestion. Avoid a broad cosmetic
rewrite while the source-to-temporal mapping is unresolved.

## Verification performed

- `uv run --offline ruff check .` — passed.
- `uv run --offline pytest -q -m 'not integration and not llm'` — 144 passed, 24 deselected.
- `RUN_NEO4J_TESTS=1 uv run --offline pytest -q -m 'not llm'` — 167 passed, 1 deselected.
- `uv run --offline python scripts/verify_temporal.py --output artifacts/readme-verification` — all
  five evidence-only cases passed through real local Neo4j MCP; JSON and HTML reports were generated.
- Live schema, constraints and indexes inspected; the explorer scan finding was confirmed with EXPLAIN.
- Current Streamlit ontology and stored graph views inspected in Chrome; a real evidence-only Profile
  investigation completed in the UI. Four fresh captures are in [the screenshot gallery](screenshots/README.md).

The model-backed test was excluded. Ollama was not running during this pass, so these results do not
claim fresh local-model inference or a complete offline UI demonstration. The MCP server logged an
optional `gds.version` capability probe failure; retrieval still completed and GDS is not required.
