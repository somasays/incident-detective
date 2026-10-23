"""The SRE workspace: investigate, inspect the ontology, explore stored evidence."""

import html
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

from agent.providers import ModelSettings, get_temporal_reasoner
from agent.temporal import build_temporal_investigator
from knowledge.mcp_db import Neo4jMCPDatabase as Database
from knowledge.temporal_fixture import DATASET
from knowledge.temporal_queries import TemporalRepository, jsonable
from knowledge.temporal_seed import spec
from ui.graph_view import build_network, render_network
from ui.temporal_report import report_html

EXAMPLES = {
    "Payments · 3 AM": "What was wrong with payments API at 3AM today?",
    "Payments · now": "Why is payments API slow now?",
    "Billing errors": "Why is our billing system throwing errors now?",
    "Profile instability": "Why is our profile service unstable now?",
}
STAGE_LABELS = {
    "resolve_question": "Understand the question",
    "get_system_context": "Map the immediate system context",
    "observe_target": "Check the reported symptom",
    "find_similar_incidents": "Look for matching previous incidents",
    "form_hypotheses": "Form hypotheses and choose a check",
    "choose_next_check": "Choose the next evidence check",
    "execute_check": "Retrieve evidence for the check",
    "evaluate_hypotheses": "Assess support, contradictions and gaps",
    "review_coverage": "Review newly discovered evidence before stopping",
    "build_diagnosis": "Assemble the diagnosis",
    "reconstruct_topology": "Trace dependencies",
    "collect_temporal_evidence": "Collect evidence",
    "analyze_evidence": "Interpret evidence",
    "validate_diagnosis": "Validate the diagnosis",
    "finalize": "Deliver the evidence package",
}
TOOL_LABELS = {
    "expand_dependencies": "Explore connected resources",
    "inspect_observations": "Inspect metrics, errors and traces",
    "inspect_state_changes": "Inspect state and changes",
    "inspect_running_code": "Inspect the deployed code",
}


def esc(value):
    return html.escape(str(value))


def short(value):
    return str(value).removeprefix(DATASET + ":")


def clock(value):
    if not value:
        return "—"
    try:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            .astimezone(ZoneInfo("Europe/Berlin"))
            .strftime("%d %b · %H:%M:%S")
        )
    except ValueError:
        return str(value)


@st.cache_resource
def temporal_database():
    return Database()


def graph_html(graph, paths=None, analysis=None):
    network = build_network(
        {"graph": graph, "dependency_paths": paths or []},
        {
            "analysis_available": bool(analysis),
            "hypotheses": (analysis or {}).get("hypotheses", []),
        },
    )
    records = {n["id"]: n for n in graph["nodes"]}
    for node in network.nodes:
        record = next(n for n in records.values() if node["id"].endswith(":" + n["id"]))
        label = record.get("name") or record.get("errorType") or record.get("metricName")
        node["label"] = label or short(record["id"])
        if len(node["label"]) > 38:
            node["label"] = node["label"][:35] + "…"
        node["title"] = "<br>".join(
            esc(f"{k}: {v}")
            for k, v in record.items()
            if k in {"id", "label", "timestamp", "description", "message", "sourceRef", "kind"}
        )
        if record["label"] == "Observation":
            node["color"]["background"] = "#b66c21"
            node["color"]["border"] = "#dc9e53"
            targets = [e["target"] for e in graph["edges"] if e["source"] == record["id"]]
            for target in targets:
                other = next((n for n in network.nodes if n["id"].endswith(":" + target)), None)
                if other:
                    node["level"] = other["level"]
                    break
    return render_network(network)


def display_graph(package, *, full=False):
    graph = package.get("graph") or package.get("topology")
    if not graph or not graph.get("nodes"):
        return
    if not full:
        excluded = {"StateSnapshot", "CodeArtifact", "Commit", "Person"}
        ids = {
            n["id"]
            for n in graph["nodes"]
            if n["label"] not in excluded
            and not (n["label"] == "Observation" and n.get("kind") == "metric_window")
        }
        graph = {
            "nodes": [n for n in graph["nodes"] if n["id"] in ids],
            "edges": [e for e in graph["edges"] if e["source"] in ids and e["target"] in ids],
        }
    components.html(
        graph_html(graph, package.get("topology", {}).get("paths"), package.get("analysis")),
        height=605,
    )


def ontology_view():
    ontology = spec()
    st.subheader("The model behind the investigation")
    st.caption("Stable identities connect to dated observations, state versions and changes.")
    left, right = st.columns([3, 2], gap="large")
    with right:
        choices = {n["label"]: key for key, n in ontology["nodes"].items()}
        label = st.selectbox("Inspect an entity type", sorted(choices), key="ontology_type")
        key = choices[label]
        definition = ontology["nodes"][key]
        st.text(definition.get("description", ""))
        st.dataframe(
            [
                {"Property": name, "Type": p["type"], "Required": bool(p.get("must_exist"))}
                for name, p in definition["properties"].items()
            ],
            hide_index=True,
            use_container_width=True,
        )
        with st.expander("Full definition"):
            st.json(definition)
    with left:
        network = Network(height="590px", width="100%", directed=True, bgcolor="#0B1423")
        relationships = [
            r
            for r in ontology["relationships"].values()
            if key in {r["from"]["node"], r["to"]["node"]}
        ]
        node_keys = {key} | {r[end]["node"] for r in relationships for end in ("from", "to")}
        for node_key in sorted(node_keys):
            n = ontology["nodes"][node_key]
            network.add_node(
                node_key,
                label=n["label"],
                shape="box",
                margin=12,
                color="#0d9488" if node_key == key else "#24446a",
                font={"color": "#e5e7eb", "face": "system-ui"},
            )
        seen = set()
        for r in relationships:
            edge = (r["from"]["node"], r["to"]["node"], r["type"])
            if edge not in seen:
                network.add_edge(
                    edge[0],
                    edge[1],
                    label=edge[2],
                    arrows="to",
                    color="#537397",
                    font={"size": 10, "color": "#abbdd0", "strokeWidth": 0},
                )
                seen.add(edge)
        network.set_options(
            json.dumps(
                {
                    "layout": {"randomSeed": 7},
                    "physics": {"enabled": True, "stabilization": {"iterations": 150}},
                    "interaction": {"hover": True},
                }
            )
        )
        components.html(render_network(network), height=605)
        st.caption(
            f"Ontology {ontology['version']} · {len(ontology['nodes'])} entity types · "
            "Showing relationships for the selected type."
        )
    st.info(
        "Two clocks: validFrom/validTo describe when a fact held; recordedAt/supersededAt "
        "describe when that version was known. Historical queries use both."
    )
    st.download_button(
        "Download ontology", json.dumps(ontology, indent=2), "ontology.json", "application/json"
    )


def stored_graph_view(repo):
    st.subheader("Explore the stored knowledge graph")
    search_col, filter_col = st.columns([3, 2])
    with search_col:
        search = st.text_input("Search records", placeholder="payments, IOPS, timeout, schema…")[
            :200
        ]
    with filter_col:
        labels = ["All types", *sorted(repo.nodes)]
        label = st.selectbox("Entity type", labels, index=labels.index("Component"))
    db = repo.database
    rows = db.read(
        "CYPHER 25 MATCH (n {datasetId:$dataset}) "
        "WHERE ($label = '' OR $label IN labels(n)) AND ($search = '' OR "
        "any(k IN keys(n) WHERE toLower(toString(n[k])) CONTAINS $search)) "
        "RETURN n{.*,label:head(labels(n))} AS node ORDER BY n.id LIMIT 151",
        dataset=DATASET,
        label="" if label == "All types" else label,
        search=search.lower(),
    )
    nodes = [jsonable(row["node"]) for row in rows[:150]]
    ids = [n["id"] for n in nodes]
    if not ids:
        st.info("No matching records. Try another entity type or search term.")
        return
    edges = [
        jsonable(r["edge"])
        for r in db.read(
            "CYPHER 25 MATCH (a {datasetId:$dataset})-[r]->(b {datasetId:$dataset}) "
            "WHERE a.id IN $ids AND b.id IN $ids "
            "RETURN r{.*,source:a.id,target:b.id,type:type(r)} AS edge LIMIT 401",
            dataset=DATASET,
            ids=ids,
        )
    ]
    st.caption(
        f"{len(nodes)} matching records · {min(len(edges), 400)} stored relationships · "
        "All retained history. Edges connect matching records only."
    )
    if len(rows) > 150 or len(edges) > 400:
        st.info("Display limit reached. Narrow the search to inspect more records.")
    left, right = st.columns([3, 2], gap="large")
    with left:
        components.html(graph_html({"nodes": nodes, "edges": edges[:400]}), height=605)
    with right:
        selected = st.selectbox("Inspect a record", ids, format_func=short)
        st.json(next(n for n in nodes if n["id"] == selected), expanded=True)


def diagnosis_view(package):
    analysis = package.get("analysis", {})
    if package.get("status") == "incomplete":
        st.warning("Investigation stopped within its limits. Findings below remain incomplete.")
    if not package.get("analysisAvailable"):
        st.info(
            package.get("error") or "Evidence retrieved. Model interpretation was not requested."
        )
        return
    st.text(analysis.get("summary", ""))
    for hypothesis in analysis.get("hypotheses", []):
        st.markdown(
            "<div class='diagnosis-card'><span class='section-label'>"
            + ("LEADING HYPOTHESIS" if hypothesis["rank"] == 1 else "ALTERNATIVE HYPOTHESIS")
            + f"</span><h3>{esc(hypothesis['title'])}</h3>"
            + f"<p>{esc(hypothesis['explanation'])}</p></div>",
            unsafe_allow_html=True,
        )
        st.markdown("**Next verification**")
        st.text(hypothesis["next_check"])
        with st.expander("Supporting evidence and gaps"):
            for eid in hypothesis["supporting_evidence_ids"]:
                st.json(package.get("index", {}).get(eid, {"id": eid}), expanded=False)
            for gap in hypothesis["contradicting_or_missing_evidence"]:
                st.text(gap)
    if not analysis.get("hypotheses"):
        st.caption("No supported root-cause hypothesis in the retrieved evidence.")
    for limitation in analysis.get("limitations", []):
        st.caption(limitation)


def measured_evidence(package):
    tabs = st.tabs(["Measurements", "Changes & code", "Errors & traces", "History"])
    with tabs[0]:
        st.caption("Prior window is a reference comparison, not a learned normal range or SLO.")
        rows = [
            {
                "Resource": short(m["entityId"]),
                "Metric": m["metric"],
                "Statistic": m["aggregation"],
                "Unit": m["unit"],
                "Prior": m.get("baseline"),
                "At incident": m.get("incident"),
                "After": m.get("recovery"),
            }
            for m in package.get("measurements", [])
        ]
        st.dataframe(rows, hide_index=True, use_container_width=True)
        with st.expander("Exact windows, sample counts and evidence IDs"):
            st.json(package.get("measurements", []))
    with tabs[1]:
        changes = package.get("changes", [])
        if changes:
            st.dataframe(
                [
                    {
                        "Time · Berlin": clock(c.get("timestamp")),
                        "Resource": short(c.get("entityId", c["id"])),
                        "Kind": c.get("kind", c["label"]),
                        "Before": c.get("beforeValue", "—"),
                        "After": c.get("afterValue", "—"),
                        "Description": c.get("description", ""),
                    }
                    for c in changes
                ],
                hide_index=True,
            )
        else:
            st.caption("No change retrieved in this time window.")
        for record in package.get("graph", {}).get("nodes", []):
            if record["label"] in {"CodeArtifact", "Commit", "Deployment"}:
                with st.expander(short(record["id"])):
                    st.json(record)
    with tabs[2]:
        records = [o for o in package.get("observations", []) if o.get("kind") != "metric_window"]
        if not records:
            st.caption("No error, alert or trace sample retrieved in this time window.")
        for o in records:
            with st.expander(f"{clock(o.get('timestamp'))} · {o.get('errorType', o['kind'])}"):
                st.text(o.get("message", ""))
                st.json(o)
    with tabs[3]:
        for memory in package.get("historicalFindings", []):
            st.text(memory["finding"]["conclusion"])
            st.caption(
                "Confirmed in a later postmortem · " + clock(memory["finding"].get("confirmedAt"))
            )
        with st.expander("State versions valid in the investigation window"):
            st.json(package.get("states", []))
        if not package.get("historicalFindings"):
            st.caption("No confirmed finding available within this knowledge cutoff.")


def stage_detail(name, state):
    if state.get("error"):
        return state["error"]
    if name == "resolve_question":
        r = state["request"]
        return f"{r['rootName']} · {clock(r['effectiveAt'])} Berlin · {r['mode']}"
    if name in {"reconstruct_topology", "get_system_context"}:
        t = state["topology"]
        return f"{len(t['nodes'])} resources · {len(t['edges'])} stored relationships"
    if name in {"collect_temporal_evidence", "observe_target", "execute_check"}:
        p = state["package"]
        return (
            f"{len(p.get('measurements', []))} metric comparisons · "
            f"{len(p.get('changes', []))} changes · {len(p.get('observations', []))} observations"
        )
    if name == "analyze_evidence":
        return f"{len(state.get('analysis', {}).get('hypotheses', []))} candidate hypotheses"
    if name == "find_similar_incidents":
        return (
            f"{len(state.get('precedents', []))} matching prior findings · "
            "current evidence still required"
        )
    if name == "form_hypotheses":
        return state.get("latest_summary", "")
    if name in {"choose_next_check", "evaluate_hypotheses", "review_coverage"}:
        return state.get("stop_reason") or state.get(
            "decision_reason", "Choose a useful evidence check"
        )
    if name == "validate_diagnosis":
        return "Checked retrieved citations, cause entities, numerical values and rank order"
    return "Evidence package ready"


def hypothesis_activity(state, *, running=False):
    """Render executed checks and model assessments, never invented progress or hidden reasoning."""
    candidates = state.get("candidates", state.get("hypothesisTests", []))
    checks = state.get("check_history", state.get("checks", []))
    evaluations = state.get("evaluation_history", state.get("evaluations", []))
    package = state.get("package", state)
    pending = state.get("pending_check") if running else None
    if pending and any(
        c["tool"] == pending["tool"] and set(c["entity_ids"]) == set(pending["entity_ids"])
        for c in checks
    ):
        pending = None
    if not candidates:
        if running:
            st.info("Checking the symptom and previous incidents before forming hypotheses…")
        return
    for hypothesis in candidates:
        assessments = [
            a
            for evaluation in evaluations
            for a in evaluation["assessments"]
            if a["hypothesis_id"] == hypothesis["id"]
        ]
        latest = assessments[-1] if assessments else {}
        with st.container(border=True):
            st.markdown(f"**{hypothesis['id']} · {hypothesis['statement']}**")
            outcome = latest.get("status", "validating" if running else "unresolved")
            st.caption(outcome.upper() + (" · " + latest["finding_level"] if latest else ""))
            with st.expander("What would support or refute this hypothesis?"):
                st.write("Support: " + hypothesis["expected_support"])
                st.write("Refutation: " + hypothesis["expected_refutation"])
            for index, check in enumerate(checks):
                if hypothesis["id"] not in check["hypothesis_ids"]:
                    continue
                with st.expander(f"{check['id']} · {check['question']}", expanded=True):
                    st.caption(
                        TOOL_LABELS.get(check["tool"], check["tool"])
                        + " · "
                        + ", ".join(short(e) for e in check["entity_ids"])
                    )
                    result = check.get("result", {})
                    st.write(
                        "Retrieved: "
                        + (
                            " · ".join(f"{value} {kind}" for kind, value in result.items() if value)
                            or "No records for these selected resources in the query window."
                        )
                    )
                    check_evaluations = [e for e in evaluations if e.get("check_id") == check["id"]]
                    completed = (
                        check_evaluations[-1]
                        if check_evaluations
                        else (
                            evaluations[index]
                            if index < len(evaluations) and not evaluations[index].get("check_id")
                            else None
                        )
                    )
                    assessment = (
                        next(
                            (
                                a
                                for a in completed["assessments"]
                                if a["hypothesis_id"] == hypothesis["id"]
                            ),
                            None,
                        )
                        if completed
                        else None
                    )
                    if assessment:
                        st.write(assessment["explanation"])
                        for gap in assessment.get("missing_evidence", []):
                            st.caption("Gap: " + gap)
                    elif running:
                        st.caption("Evidence retrieved · assessment in progress")
                    else:
                        st.caption("Evidence retained; this check has no completed assessment.")
                    with st.expander(f"Source records · {len(check.get('evidence_ids', []))}"):
                        st.json(
                            [
                                package.get("index", {}).get(e, {"id": e})
                                for e in check.get("evidence_ids", [])
                            ],
                            expanded=False,
                        )
            if pending and hypothesis["id"] in pending["hypothesis_ids"]:
                st.info("Next check: " + pending["question"])
            if latest:
                st.caption("Assessment: " + latest["explanation"])


def activity_view(package):
    st.markdown("### Investigation activity")
    budgets = package.get("budgets", {})
    if budgets:
        st.caption(
            f"{budgets.get('checksUsed', 0)} / {budgets.get('maxChecks', 8)} checks · "
            f"{budgets.get('modelCallsUsed', 0)} model calls · "
            f"{package.get('status', '').replace('_', ' ')}"
        )
    if package.get("stopReason"):
        st.caption("Stopped: " + package["stopReason"])
    hypothesis_activity(package)
    with st.expander("All stages and graph queries"):
        for step in package.get("stages", []):
            st.markdown(f"**{STAGE_LABELS.get(step['stage'], step['stage'])}**")
            st.caption(
                f"{step['status']} · {step['elapsedMs']} ms · "
                f"next: {STAGE_LABELS.get(step['next'], step['next'])}"
            )
        st.json(package.get("queryTrace", []))


def investigation_view(db, settings):
    st.markdown(
        "<div class='lab-meta'>Prepared data: 23 Oct 2026, 10:05 Europe/Berlin · "
        "“Now” and “today” use this demo clock.</div>",
        unsafe_allow_html=True,
    )
    st.session_state.setdefault("sre_question", next(iter(EXAMPLES.values())))
    for col, (label, question) in zip(st.columns(4), EXAMPLES.items(), strict=True):
        if col.button(label, use_container_width=True):
            st.session_state.sre_question = question
    with st.form("investigate_form"):
        st.text_area("What are you observing?", key="sre_question", height=85, max_chars=2000)
        with st.expander("Investigation settings"):
            mode = st.radio(
                "Use evidence",
                ["retrospective", "known_then"],
                horizontal=True,
                format_func=lambda m: (
                    "All available history" if m == "retrospective" else "Known at the time"
                ),
            )
            at = st.text_input("Override time (optional)", placeholder="2026-10-23T03:00:00+02:00")
            evidence_only = st.checkbox("Evidence only · skip model interpretation")
        run = st.form_submit_button("Investigate →", type="primary")
    # Allocate live activity above results, but redraw the previous package before
    # starting any blocking work. It stays mounted while new checks are running.
    live = st.container()
    previous = st.session_state.get("temporal_result")
    if previous:
        if run:
            st.caption("Previous investigation · retained while the new investigation runs")
        render_package(previous)
    elif not run:
        st.markdown(
            "<div class='lab-empty'><h3>From a symptom to an evidence trail.</h3>"
            "<p>Ask about Payments, Billing or Profiles. Watch each hypothesis get tested, "
            "then inspect the diagnosis and its evidence graph.</p>"
            "<p>Symptom → hypotheses → checks & results → diagnosis</p></div>",
            unsafe_allow_html=True,
        )
    if run:
        state = {
            "question": st.session_state.sre_question,
            "options": {"at": at or None, "mode": mode},
        }
        with live:
            package = stream_investigation(db, settings, state, evidence_only)
        st.session_state.temporal_result = package
        # Render the new result once on a fresh pass, without duplicating widgets
        # or invoking the model again. Previous output stayed visible until here.
        st.rerun()


def stream_investigation(db, settings, state, evidence_only):
    # The status header owns no evidence content. Collapsing it cannot hide the
    # hypothesis tree, progress or previous diagnosis package.
    status = st.status("Understanding the question…", expanded=False)
    progress = st.empty()
    live_hypotheses = st.empty()
    try:
        workflow = build_temporal_investigator(
            TemporalRepository(db),
            None if evidence_only else get_temporal_reasoner(settings),
        )
        for update in workflow.stream(state, stream_mode="updates", config={"recursion_limit": 64}):
            for name, values in update.items():
                state.update(values)
                step = values.get("stages", [{}])[-1]
                if name in STAGE_LABELS:
                    progress.caption(
                        f"{len(state.get('stages', []))} stages · "
                        f"{state.get('checks', 0)} checks · "
                        f"{state.get('model_calls', 0)} model calls · " + stage_detail(name, state)
                    )
                    status.update(label=STAGE_LABELS.get(step.get("next"), "Packaging evidence…"))
                with live_hypotheses.container():
                    hypothesis_activity(state, running=name != "finalize")
        package = state["package"]
    except Exception as exc:
        package = {
            **state.get("package", {}),
            "status": "unavailable",
            "analysisAvailable": False,
            "error": f"Investigation interrupted ({type(exc).__name__}). Retry.",
        }
    status.update(
        label={
            "complete": "Investigation complete",
            "incomplete": "Investigation stopped · evidence preserved",
            "symptom_not_observed": "Reported symptom not corroborated",
            "insufficient_evidence": "No root cause established",
            "evidence_only": "Evidence package ready",
        }.get(package.get("status"), "Analysis unavailable · evidence preserved"),
        state="error" if package.get("status") == "unavailable" else "complete",
    )
    return package


def render_package(package):
    request = package.get("request", {})
    st.caption("Investigated: " + request.get("question", st.session_state.sre_question))
    with st.expander("Agent activity · hypotheses, checks and results", expanded=True):
        activity_view(package)
    if request:
        st.caption(
            f"Incident time: {clock(request['effectiveAt'])} Berlin · "
            f"Knowledge cutoff: {clock(request['knowledgeAsOf'])} Berlin"
        )
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("### Evidence graph")
        full = st.checkbox("Show measurements, code and state records in graph")
        display_graph(package, full=full)
        st.caption("Stored edge directions · zoom, pan and hover · red outline = suspected entity")
    with right:
        st.markdown("### Diagnosis")
        diagnosis_view(package)
    st.markdown("### Evidence")
    measured_evidence(package)
    with st.expander("Export the complete diagnosis package"):
        st.download_button(
            "Download JSON", json.dumps(package, indent=2), "investigation.json", "application/json"
        )
        st.download_button("Download HTML report", report_html(package), "report.html", "text/html")
        for limitation in package.get("limitations", []):
            st.text(limitation)


def temporal_workspace():
    try:
        settings = ModelSettings.from_env()
    except (ValueError, TypeError):
        settings = ModelSettings()
        st.warning("Invalid model settings in .env. Check the timeout and provider.")
    st.markdown(
        "<div class='lab-header'><div><div class='lab-kicker'>INCIDENT DETECTIVE</div>"
        "<h1>Temporal SRE lab</h1><p>Investigate the system as it was. Follow the evidence.</p>"
        "</div><span class='lab-badge'>SYNTHETIC DATA</span></div>",
        unsafe_allow_html=True,
    )
    page = st.radio(
        "Workspace",
        ["Investigate", "Ontology", "Knowledge graph"],
        horizontal=True,
        label_visibility="collapsed",
        key="temporal_page",
    )
    st.caption(settings.public_status() + " · Local Neo4j MCP · LangGraph")
    if page == "Ontology":
        ontology_view()
        return
    try:
        db = temporal_database()
        if page == "Knowledge graph":
            stored_graph_view(TemporalRepository(db))
        else:
            investigation_view(db, settings)
    except Exception as exc:
        st.error(f"Local Neo4j is unavailable ({type(exc).__name__}).")
        st.code("docker compose up -d\nuv run python temporal_demo.py seed", language="bash")
    st.markdown(
        "<div class='lab-footer'>Synthetic operational evidence · Read-only investigation · "
        "Hypotheses require verification</div>",
        unsafe_allow_html=True,
    )
