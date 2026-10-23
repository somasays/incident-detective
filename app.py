"""Incident Detective — local Streamlit dashboard. Run: uv run streamlit run app.py"""

import html
import json
from urllib.parse import quote

import streamlit as st
import streamlit.components.v1 as components

from agent.graph import build_investigator
from agent.reasoning import OllamaReasoner
from config import DEMO_ID, Settings
from knowledge.db import Database
from knowledge.memory import confirm_finding
from knowledge.ontology import VERSION
from knowledge.queries import KnowledgeRepository
from ui.graph_view import render_evidence_graph
from ui.styles import CSS, LOGO, header
from ui.views import knowledge_graph_view, ontology_view

st.set_page_config(
    page_title="Incident Detective",
    page_icon="data:image/svg+xml," + quote(LOGO),
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(CSS, unsafe_allow_html=True)
st.markdown(header(), unsafe_allow_html=True)
view = st.radio(
    "WORKSPACE VIEW",
    ["Investigation", "Ontology", "Knowledge Graph"],
    horizontal=True,
    key="workspace_view",
)
if view == "Ontology":
    ontology_view()
    st.stop()


def esc(value):
    return html.escape(str(value))


@st.cache_resource
def resources():
    settings = Settings.from_env()
    database = Database(settings)
    return database, KnowledgeRepository(database), OllamaReasoner(settings)


def panel_heading(title, tag=""):
    st.markdown(
        f"<div class='panel-heading'>{esc(title)}<span class='tag'>{esc(tag)}</span></div>",
        unsafe_allow_html=True,
    )


def signal(time, title, detail):
    st.markdown(
        f"<div class='signal-row'><div class='signal-time'>{esc(time)}</div><div>"
        f"<div class='signal-title'>{esc(title)}</div>"
        f"<div class='signal-detail'>{esc(detail)}</div></div></div>",
        unsafe_allow_html=True,
    )


def plain_paragraph(value):
    # Model/user text must never turn into remote Markdown image or HTML requests.
    st.markdown(f"<p>{esc(value)}</p>", unsafe_allow_html=True)


def render_analysis(result):
    if not result.get("analysis_available"):
        st.warning(result.get("summary", "Run an investigation to rank hypotheses."))
        if result.get("validation_error"):
            with st.expander("Local analysis diagnostics"):
                st.text(result["validation_error"])
        if result.get("evidence"):
            st.caption(
                "Evidence retrieval completed. Restore Ollama and investigate again for analysis."
            )
        return
    if not result["hypotheses"]:
        st.info("No sufficiently supported root-cause hypothesis was returned.")
        plain_paragraph(result["summary"])
        for limitation in result["limitations"]:
            plain_paragraph(limitation)
        return
    leading = result["hypotheses"][0]
    st.markdown(
        "<div class='hypothesis'><div class='eyebrow'>01 / LEADING HYPOTHESIS</div>"
        f"<h2>{esc(leading['title'])}</h2><p>{esc(leading['explanation'])}</p></div>",
        unsafe_allow_html=True,
    )
    st.caption("Working hypothesis · requires verification")
    st.markdown("<div class='eyebrow'>SUPPORTING EVIDENCE</div>", unsafe_allow_html=True)
    evidence = result["evidence"]

    def citation_order(eid):
        item = evidence["index"][eid]
        historical = eid.startswith("FINDING:") or (
            eid.startswith("INCIDENT:") and item.get("id") != evidence["incident"]["id"]
        )
        return (
            2 if historical else 0 if item.get("timestamp") else 1,
            item.get("timestamp", ""),
            eid,
        )

    for eid in sorted(set(leading["supporting_evidence_ids"]), key=citation_order):
        item = evidence["index"][eid]
        time = item.get("timestamp", "")
        title = item.get("type", item.get("id", "Dependency path"))
        detail = item.get("message", item.get("description", item.get("conclusion", "")))
        if eid.startswith("PATH:"):
            detail = " → ".join(item["path"])
        if eid.startswith("INCIDENT:"):
            detail = item.get("summary", "Historical symptom match")
        historical = eid.startswith("FINDING:") or (
            eid.startswith("INCIDENT:") and item.get("id") != evidence["incident"]["id"]
        )
        if historical and time:
            detail = time[:10] + " · " + detail
        signal("PAST" if historical else time[11:16] if time else "GRAPH", title, detail)
    st.markdown(
        "<div class='verification'><div class='eyebrow'>NEXT VERIFICATION</div>"
        f"<p>{esc(leading['next_check'])}</p></div>",
        unsafe_allow_html=True,
    )
    with st.expander("Missing or contradictory evidence", expanded=True):
        for item in leading["contradicting_or_missing_evidence"]:
            plain_paragraph("• " + item)
    if len(result["hypotheses"]) > 1:
        with st.expander("Alternative hypotheses"):
            for h in result["hypotheses"][1:]:
                plain_paragraph(f"{h['rank']}. {h['title']}")
                plain_paragraph(h["explanation"])
                plain_paragraph(
                    "Missing / contradictory: " + "; ".join(h["contradicting_or_missing_evidence"])
                )
                plain_paragraph("Next check: " + h["next_check"])
    with st.expander("Evidence IDs & analysis limitations"):
        plain_paragraph(result["summary"])
        for h in result["hypotheses"]:
            st.markdown(f"**Rank {h['rank']} citations**")
            st.code("\n".join(h["supporting_evidence_ids"]), language=None)
        for limitation in result["limitations"]:
            plain_paragraph(limitation)


database = repository = reasoner = None
connection_error = None
incidents = []
try:
    database, repository, reasoner = resources()
    namespaces = repository.list_namespaces()
    previous_namespace = st.session_state.get("selected_graph_namespace", DEMO_ID)
    namespace = st.selectbox(
        "GRAPH DATA",
        namespaces,
        index=namespaces.index(previous_namespace) if previous_namespace in namespaces else 0,
        format_func=lambda value: (
            "Manual fixture baseline · dummy_data"
            if value == DEMO_ID
            else f"Constructed from local sources · {value}"
        ),
    )
    st.session_state.selected_graph_namespace = namespace
    if namespace != DEMO_ID:
        repository = KnowledgeRepository(database, namespace)
    with st.expander("Graph construction · ontology & sources"):
        st.caption(f"Ontology {VERSION} · knowledge/ontology.json")
        if namespace == DEMO_ID:
            st.caption("This baseline was seeded from manually authored nodes and relationships.")
        else:
            st.dataframe(repository.ingestion_status(), hide_index=True, use_container_width=True)
            st.caption(
                "Cursors show successful commits. The ingest CLI reports blocked sources "
                "and errors. "
                "Refresh this page after new source records are ingested."
            )
    incidents = repository.list_incidents() if view == "Investigation" else []
    if view == "Investigation" and not incidents:
        connection_error = "No open incidents in this graph dataset. Import incident records first."
except Exception as exc:
    connection_error = f"Local Neo4j is unavailable ({type(exc).__name__})."

if view == "Knowledge Graph":
    if connection_error:
        st.warning(connection_error)
        st.code("docker compose up -d\nuv run python seed.py", language="bash")
    else:
        try:
            knowledge_graph_view(repository)
        except Exception as exc:
            st.error(f"Graph retrieval unavailable ({type(exc).__name__}).")
            st.caption("Check the local Neo4j connection and refresh this view.")
    st.stop()

controls, runtime = st.columns([3, 2], gap="large")
with controls:
    st.markdown("<div class='eyebrow'>INVESTIGATION WORKSPACE</div>", unsafe_allow_html=True)
    picker, trigger = st.columns([3, 1.15], vertical_alignment="bottom")
    with picker:
        selected = st.selectbox(
            "SELECT INCIDENT",
            options=[i["id"] for i in incidents],
            format_func=lambda id: next(
                f"{i['id']} — {i['summary']}" for i in incidents if i["id"] == id
            ),
            placeholder="Seed local Neo4j to load incidents",
            disabled=not incidents,
        )
    with trigger:
        investigate = st.button(
            "Investigate →", type="primary", use_container_width=True, disabled=not incidents
        )
with runtime:
    st.markdown("<div class='eyebrow'>LOCAL INVESTIGATION ENGINE</div>", unsafe_allow_html=True)
    st.markdown("**LangGraph**  ·  Neo4j  ·  Ollama")
    st.caption("Synthetic infrastructure · 3 dependency hops · 30-minute evidence window")

if connection_error:
    st.warning(connection_error)
    with st.expander("Start the local demo", expanded=True):
        st.code(
            "uv run python scripts/setup_env.py\ndocker compose up -d\n"
            "ollama pull qwen2.5:14b-instruct\nuv run python seed.py\n"
            "uv run python scripts/preflight.py",
            language="bash",
        )
        st.caption(
            "After starting local services, refresh this page. No production systems are connected."
        )

if investigate:
    initial = {"incident_id": selected, "stages": [], "analysis_available": False}
    result = dict(initial)
    try:
        with st.status("Investigating local graph evidence…", expanded=True) as progress:
            investigator = build_investigator(repository, reasoner)
            for update in investigator.stream(
                initial, config={"recursion_limit": 12}, stream_mode="updates"
            ):
                for name, values in update.items():
                    result.update(values)
                    st.write("✓ " + name.replace("_", " ").capitalize())
            progress.update(
                label="Investigation complete"
                if result.get("analysis_available")
                else "Investigation finished with a limitation",
                state="complete",
                expanded=False,
            )
    except Exception as exc:
        result.update(
            status="workflow_failed",
            analysis_available=False,
            hypotheses=[],
            summary=f"Investigation interrupted ({type(exc).__name__}). Please retry.",
        )
    st.session_state.setdefault("investigations", {})[selected] = result

result = st.session_state.get("investigations", {}).get(selected)
evidence = result.get("evidence") if result else None
incident = next((i for i in incidents if i["id"] == selected), None)

if incident:
    st.divider()
    metrics = st.columns(4)
    metrics[0].metric("Affected service", incident["affected_name"])
    metrics[1].metric("Incident recorded · UTC", incident["timestamp"][11:16])
    metrics[2].metric("Severity", incident["severity"])
    metrics[3].metric(
        "Retrieved signals",
        str(len(evidence["observed_symptoms"]) + len(evidence["recent_deployments"]))
        if evidence
        else "—",
    )

left, right = st.columns([3, 2], gap="large")
with left:
    with st.container(border=True):
        panel_heading("EVIDENCE GRAPH", "SCOPED TO INCIDENT")
        st.markdown(
            "<div class='legend'><span><i style='background:#2563EB'></i>Service</span>"
            "<span><i style='background:#0D9488'></i>Pipeline</span>"
            "<span><i style='background:#B83C49'></i>Deployment</span>"
            "<span><i style='background:#E59A38'></i>Symptom</span>"
            "<span><i style='background:#7861AA'></i>Memory</span></div>",
            unsafe_allow_html=True,
        )
        if evidence:
            components.html(render_evidence_graph(evidence, result), height=600, scrolling=False)
            st.caption(
                "Arrows show stored relationship direction. "
                "Dashed dependencies were observed in traces. "
                "Red outline marks the leading suspected entity."
            )
            with st.expander("Inspect a graph node"):
                node_id = st.selectbox(
                    "Retrieved node", [n["id"] for n in evidence["graph"]["nodes"]]
                )
                node = next(n for n in evidence["graph"]["nodes"] if n["id"] == node_id)
                st.json({k: v for k, v in node.items() if k != "demo_id"}, expanded=True)
        else:
            st.markdown(
                "<div class='empty-graph'>"
                + LOGO
                + "<h2>Follow the evidence.</h2><p>Select an incident and investigate to trace "
                "dependencies, connect recent changes, and retrieve confirmed incident memory.</p>"
                "<div class='workflow'><span>DEPENDENCIES</span><span>CHANGES</span>"
                "<span>SYMPTOMS</span><span>MEMORY</span></div></div>",
                unsafe_allow_html=True,
            )
with right:
    panel_heading("INVESTIGATION RESULT", "LOCAL REASONING")
    if evidence and not evidence["recent_deployments"]:
        st.caption("No relevant deployment in the 30-minute evidence window.")
    if result:
        render_analysis(result)
    else:
        st.markdown("### An explanation, with a trail.")
        st.write(
            "Ranked hypotheses connect each suspected cause to retrieved graph evidence, "
            "historical context, and a concrete verification action."
        )
        st.info("Choose **Investigate** to begin. Model inference runs only when you request it.")
        st.caption(
            "All components and events in this demo are synthetic. "
            "Nothing is connected to production."
        )

st.divider()
panel_heading("HISTORICAL INCIDENT MEMORY", "CONFIRMED KNOWLEDGE")
if evidence and evidence["similar_incidents"]:
    memory_columns = st.columns(min(len(evidence["similar_incidents"]), 2))
    for index, memory in enumerate(evidence["similar_incidents"]):
        with memory_columns[index % len(memory_columns)]:
            findings = memory["confirmed_findings"]
            conclusions = (
                " · ".join(f["conclusion"] for f in findings) or "No confirmed finding recorded."
            )
            causes = sorted({c["id"] for f in findings for c in f["causes"]})
            st.markdown(
                f"<div class='memory-card'><span class='memory-id'>{esc(memory['id'])}</span>"
                "<span class='tag' style='float:right'>"
                f"{len(memory['shared_symptoms'])} SHARED SIGNALS</span>"
                f"<p>{esc(conclusions)}</p><div class='memory-meta'>"
                f"{esc(' · '.join(memory['shared_symptoms']))}<br>"
                f"Attributed to: {esc(', '.join(causes) or 'Unrecorded')}<br>"
                f"{esc(memory['timestamp'])} · Historical context, not current proof"
                "</div></div>",
                unsafe_allow_html=True,
            )
elif evidence:
    st.caption(
        "No prior incident with shared symptom types was found before this incident's timestamp."
    )
else:
    st.caption(
        "Relevant past incidents and their confirmed findings appear after evidence retrieval."
    )

if evidence and database:
    st.divider()
    with st.expander("Confirm a verified finding · save to graph memory"):
        st.caption(
            "Save only after independently checking the cause. "
            "This is an explicit human confirmation."
        )
        with st.form(f"confirmation-{selected}"):
            cause = st.selectbox("Verified root-cause entity", evidence["eligible_cause_ids"])
            conclusion = st.text_area(
                "Verified conclusion",
                max_chars=2000,
                placeholder="Describe what you verified and why it explains this incident.",
            )
            confirmed = st.checkbox(
                "I verified this finding and want to store it as confirmed knowledge."
            )
            save = st.form_submit_button("Confirm finding", type="primary")
        if save:
            try:
                id = confirm_finding(
                    database, selected, cause, conclusion, evidence, user_confirmed=confirmed
                )
                st.success(
                    f"Saved {id} to local Neo4j. Repeating the same confirmation is idempotent."
                )
            except Exception as exc:
                st.error(str(exc))
    st.download_button(
        "Download investigation JSON",
        json.dumps(result, indent=2),
        file_name=f"{selected}-investigation.json",
        mime="application/json",
    )
if result and result.get("stages"):
    st.caption("LangGraph execution: " + " → ".join(result["stages"]))
st.markdown(
    "<div class='footer-note'>INCIDENT DETECTIVE / LOCAL DEMO &nbsp; · &nbsp; "
    "Graph evidence first. Hypotheses require verification. &nbsp; · &nbsp; "
    "No cloud models · No production connectivity</div>",
    unsafe_allow_html=True,
)
