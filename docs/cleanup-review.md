# Cleanup review

Review and implementation: **24 October 2026**. An independent reviewer inspected the existing code,
implemented a scoped reasoning/measurement extraction, and reviewed the integrated changes. Existing
agent policy and presentation work was preserved.

## Implemented

| Finding | Change |
| --- | --- |
| Unreachable one-shot temporal reasoning | Removed the dead branch and `analyze_package`; `agent/temporal.py` is a small public facade over the explicit evidence-only StateGraph and bounded hypothesis loop. |
| Duplicate metric calculations | `knowledge/measurements.py` now supplies both retrieval paths, with deterministic grouping, window selection and zero-baseline handling. |
| Monolithic Streamlit workspace | Extracted activity, diagnosis, graph workspaces and pure formatting helpers. Removed unused `ui/views.py` and `ui/styles.py`. |
| Browser queries embedded in UI and scanning all nodes | Moved reads into `knowledge/explorer.py`, added ontology-allowlisted labels, composite scope/ID indexes, and keyset pagination for records and relationships. |
| Inconsistent configuration precedence | One fresh loader reads `.env`, with shell overrides taking precedence. Database resources are keyed by settings, secret values are hidden from representations, and offline mode remains enforced across rerenders. |
| Rendering bugs reported as database outages | Connection/configuration/render failures now have distinct UI paths and a regression test. |
| Stale preflight requiring original incident IDs | Preflight checks the current temporal dataset through real read-only MCP and requests a short structured response from the selected model. |
| Model calls not sharing the full remaining deadline | Metadata verification, generation and retries now respect the investigation deadline. Budget exhaustion preserves previous assessments in an incomplete package. |
| Long manual setup sequence | `bootstrap.sh` prepares and launches; `run.sh` uses installed artifacts and enforces local inference. Setup handles readiness, idempotent seeding, missing models and occupied ports. |
| Dark UI and incomplete screenshot presentation | Dashboard, graphs and standalone reports use a light theme. The README embeds five current app captures. |

The live default Component-browser query used `NodeIndexSeek` after this change. Its predecessor
used `AllNodesScan`. This validates the access path on the prepared graph, not capacity at production
scale. Search still filters properties within the selected scope.

## Verification

- Full suite with real Neo4j and Ollama enabled: **199 passed**, including local structured inference,
  grounding, ablation, MCP retrieval, temporal queries, graph pagination and launcher regressions.
- Ruff and `git diff --check`: passed.
- Final five-case evidence-only verifier: passed real MCP retrieval and generated JSON/HTML reports
  under `artifacts/cleanup-final-evidence`.
- `LLM_PROVIDER=ollama ./run.sh --setup-only`: passed real Docker readiness, idempotent seed,
  temporal catalog retrieval through MCP and a short structured local-model response.
- `./run.sh`: launched the light dashboard at `http://localhost:8501` using installed artifacts.
- Explicit GPT-5 mini bootstrap: MCP and structured model preflight passed; dashboard launched at
  `http://localhost:8502`. The actual model-backed outcomes are recorded below.

### GPT-5 mini end-to-end results

All five prepared questions were exercised against the configured GPT-5 mini endpoint using real
Neo4j/MCP retrieval. **The model-backed verifier did not pass.** Acceptance was left unchanged.

| Run | Outcome |
| --- | --- |
| Historical Payments | Incomplete at the investigation budget; no supported initiating cause. |
| Payments known at the time | Endpoint timeout in the earlier run, preserving evidence. Deadline routing was subsequently corrected and covered by regression tests; this case was not rerun against the final correction. |
| Payments now | Incomplete at the budget; no supported root-cause mechanism. |
| Billing | Incomplete; a worker-related hypothesis was retained but the initiating mechanism remained unresolved. |
| Profile, CLI | Analysis unavailable after the model repeated an already executed check despite the bounded correction retry. |
| Profile, Streamlit | Incomplete with a provisional cache-client-limit hypothesis, real measurements, four checks and a next verification action. |

The Streamlit result was downloaded through both UI controls. Its JSON citations and cause entity
were checked against the retrieved evidence. The standalone HTML export contains inline graph
assets and no external asset URLs. [Screenshots](screenshots/README.md) show this actual run, including
the incomplete status; no successful diagnosis was substituted. Local reports are retained under
`artifacts/cleanup-gpt5-validation`, `artifacts/cleanup-gpt5-final` and `artifacts/cleanup-gpt5-ui`.

The test suite does not establish that every model investigation reaches a correct diagnosis.
The optional MCP `gds.version` capability probe logs an error because GDS is absent; retrieval works
and the application does not require GDS.

## Remaining work

1. **Source-to-temporal mapping:** `ingest.py` and the local manifest/log/deployment/trace adapters
   write the original `demo_id` ontology; the current workspace reads `datasetId=sre-temporal-v2`.
   Define explicit identity, observation and temporal mappings, then verify a source append through
   the temporal investigator. The current prepared temporal dataset is not a live ingestion pipeline.
2. **Diagnostic quality and latency:** deeper model runs can exhaust the 180-second budget before
   finding an initiating change. Structured, grounded output can still be incomplete. Preserve these
   limits while evaluating prompts, tool choices and local model performance on independent cases.
3. **Sustained growth:** retention, archival, indexed text search and long-duration ingestion/query
   benchmarks remain unimplemented. Pagination bounds results, not the entire database's growth.
4. **Legacy boundary:** original agent/query/memory modules still have active CLI and test callers.
   They were retained; deleting them before a deliberate migration would break supported commands.

No cloud fallback, additional database or production system integration was introduced. GPT-5 mini
runs were explicitly requested; the local launch path continues to use Ollama.

## Workspace presentation follow-up

The reference-inspired layout remains in Streamlit: an off-white evidence canvas, forest/sage accents,
a scrollable Investigation/Report/Evidence panel and finding cards below the graph. The Report tab
keeps verification and downloads beside the map; the Evidence tab presents measurements as readable
cards with full tables and exact source windows available below. The standalone HTML shares the theme
and explicitly retains investigation status.

Browser checks verified a fresh evidence-only Profile run against real Neo4j/MCP, full/focused graph
switching, navigation with the prior GPT result preserved, and the updated HTML download. The current
non-LLM suite passed **198 tests** with one model-backed test deselected. This UI follow-up does not
change or resolve the model-backed diagnostic limitations documented above.
