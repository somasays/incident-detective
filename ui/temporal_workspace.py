"""Navigation and investigation lifecycle; panels own their presentation."""

import json
import logging
import os

import streamlit as st
from neo4j.exceptions import DriverError, Neo4jError

from agent.providers import ModelSettings, get_temporal_reasoner
from agent.temporal import build_temporal_investigator
from config import Settings
from knowledge.mcp_db import Neo4jMCPDatabase as Database
from knowledge.temporal_queries import TemporalRepository
from ui.activity import STAGE_LABELS, check_timeline, hypothesis_activity, stage_detail
from ui.case_view import canvas_view, investigation_footer, panel_intro, render_case
from ui.formatting import esc
from ui.graph_workspace import ontology_view, stored_graph_view

logger = logging.getLogger(__name__)

EXAMPLES = {
    "Payments · 3 AM": "What was wrong with payments API at 3AM today?",
    "Payments · now": "Why is payments API slow now?",
    "Billing errors": "Why is our billing system throwing errors now?",
    "Profile instability": "Why is our profile service unstable now?",
}


@st.cache_resource
def temporal_database(settings):
    return Database(settings)


def investigation_view(db, settings):
    st.session_state.setdefault("sre_question", next(iter(EXAMPLES.values())))
    # Keep the draft outside widget-owned state: Streamlit removes hidden widgets
    # when moving to the ontology/graph workspace.
    if "_question_input" not in st.session_state:
        st.session_state._question_input = st.session_state.sre_question
    with st.container(key="investigation_controls"):
        with st.expander(
            "New investigation", expanded=not bool(st.session_state.get("temporal_result"))
        ):
            for col, (label, question) in zip(st.columns(4), EXAMPLES.items(), strict=True):
                if col.button(label, use_container_width=True):
                    st.session_state.sre_question = question
                    st.session_state._question_input = question
            with st.form("investigate_form", border=False):
                question_col, action = st.columns([6, 1], vertical_alignment="bottom")
                with question_col:
                    st.text_input("What are you observing?", key="_question_input", max_chars=2000)
                with action:
                    run = st.form_submit_button(
                        "Investigate →", type="primary", use_container_width=True
                    )
                with st.expander("Investigation settings"):
                    st.caption(
                        "Demo clock: 23 Oct 2026, 10:05 Europe/Berlin. All evidence is synthetic."
                    )
                    mode = st.radio(
                        "Use evidence",
                        ["retrospective", "known_then"],
                        horizontal=True,
                        format_func=lambda m: (
                            "All available history" if m == "retrospective" else "Known at the time"
                        ),
                    )
                    at = st.text_input(
                        "Override time (optional)", placeholder="2026-10-23T03:00:00+02:00"
                    )
                    evidence_only = st.checkbox(
                        "Evidence only · skip model interpretation",
                        value=os.environ.get("INCIDENT_EVIDENCE_ONLY") == "1",
                        disabled=os.environ.get("INCIDENT_EVIDENCE_ONLY") == "1",
                    )
    st.session_state.sre_question = st.session_state._question_input
    # Allocate live activity above results, but redraw the previous package before
    # starting any blocking work. It stays mounted while new checks are running.
    live = st.container()
    previous = st.session_state.get("temporal_result")
    if previous:
        if run:
            st.caption("Previous investigation · retained while the new investigation runs")
        render_package(previous)
    elif not run:
        render_case(None)
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
    left, right = st.columns([2.65, 1.1], gap="medium")
    with left:
        live_canvas = st.empty()
        live_footer = st.empty()
    with right:
        with st.container(border=True, height=725):
            live_activity = st.empty()
    last_graph = None
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
                live_package = {
                    **state.get("package", {}),
                    "request": state.get("request", {}),
                }
                if not live_package.get("graph"):
                    live_package["graph"] = state.get("topology", {})
                signature = json.dumps(live_package.get("graph", {}), sort_keys=True)
                if signature != last_graph:
                    with live_canvas.container():
                        canvas_view(live_package, running=name != "finalize")
                    last_graph = signature
                with live_footer.container():
                    investigation_footer(live_package, running=name != "finalize", state=state)
                with live_activity.container():
                    panel_intro({"request": state.get("request", {"question": state["question"]})})
                    check_timeline(state, running=name != "finalize")
                    with st.expander("Live hypotheses & check details"):
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
    render_case(package)


def temporal_workspace():
    try:
        settings = ModelSettings.from_env()
    except (ValueError, TypeError):
        settings = ModelSettings()
        st.warning("Invalid model settings in .env. Check the timeout and provider.")
    st.markdown(
        "<div class='lab-header'><div class='brand'><span class='brand-mark'>⌘</span>"
        "<strong>incident detective</strong><span class='brand-divider'></span>"
        "<span class='workspace-label'>Investigation workspace</span></div>"
        "<div class='header-status'><i class='status-dot'></i> Synthetic demo "
        "<span class='avatar'>ID</span></div></div>",
        unsafe_allow_html=True,
    )
    with st.container(key="workspace_navigation"):
        page = st.radio(
            "Workspace",
            ["Investigate", "Ontology", "Knowledge graph"],
            horizontal=True,
            label_visibility="collapsed",
            key="temporal_page",
        )
    if page == "Ontology":
        ontology_view()
        return
    try:
        db = temporal_database(Settings.from_env())
        if page == "Knowledge graph":
            stored_graph_view(db)
        else:
            investigation_view(db, settings)
    except (ConnectionError, TimeoutError, DriverError, Neo4jError) as exc:
        st.error(f"Local Neo4j is unavailable ({type(exc).__name__}).")
        st.code("./run.sh", language="bash")
    except ValueError:
        st.error("Check the database/model settings in .env and retry.")
    except Exception:
        logger.exception("Workspace rendering failed")
        st.error("The workspace could not render this result. Check the application log.")
    st.markdown(
        "<div class='lab-footer'><span>"
        "Synthetic operational evidence · Read-only investigation</span>"
        f"<span>{esc(settings.public_status())}"
        " · Neo4j · LangGraph</span></div>",
        unsafe_allow_html=True,
    )
