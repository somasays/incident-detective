"""Canvas-led investigation workspace and its adjacent activity/report panel."""

import json

import streamlit as st

from ui.activity import TOOL_LABELS, activity_view, check_timeline
from ui.diagnosis import diagnosis_view, measured_evidence
from ui.facts import render_facts
from ui.formatting import clock, esc, short
from ui.graph_workspace import display_graph
from ui.presentation import evidence_facts
from ui.temporal_report import report_html

STATUS_LABELS = {
    "complete": "Investigation complete",
    "incomplete": "Incomplete · evidence preserved",
    "symptom_not_observed": "Symptom not corroborated",
    "insufficient_evidence": "Further evidence needed",
    "evidence_only": "Evidence ready · interpretation skipped",
    "unavailable": "Analysis unavailable · evidence preserved",
}


def canvas_view(package, *, running=False, full=False):
    request = package.get("request", {})
    graph = package.get("graph", {})
    mode = (
        "Following investigation"
        if running
        else "Retrieved graph"
        if graph.get("nodes")
        else "Waiting for evidence"
    )
    st.markdown(
        "<div class='canvas-heading'><span><i class='status-dot'></i> Evidence map</span>"
        f"<span>{esc(request.get('rootName', 'No investigation selected'))}</span>"
        "<span class='canvas-tag'>" + mode + "</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    if graph.get("nodes"):
        display_graph(package, full=full)
    else:
        st.markdown(
            "<div class='canvas-empty'><div class='empty-mark'>⌘</div>"
            "<span class='section-label'>YOUR EVIDENCE WORKSPACE</span>"
            "<h2>See how the system connects.</h2>"
            "<p>Choose a question above. Dependencies, changes and observations "
            "will appear here as the investigation retrieves them.</p>"
            "<div class='empty-legend'><span>Services</span><span>Changes</span>"
            "<span>Observations</span></div></div>",
            unsafe_allow_html=True,
        )


def investigation_footer(package, *, running=False, state=None):
    checks = state.get("check_history", []) if state else package.get("checks", [])
    count = len(checks) if isinstance(checks, list) else checks
    nodes = len(package.get("graph", {}).get("nodes", []))
    status = package.get("status", "")
    label = (
        "Investigation in progress"
        if running
        else STATUS_LABELS.get(status, "Ready to investigate")
    )
    detail = (
        "Each check adds inspectable evidence" if not nodes else f"{nodes} records · {count} checks"
    )
    if running and state and state.get("pending_check"):
        pending = state["pending_check"]
        detail = pending.get("label") or TOOL_LABELS[pending["tool"]]
    st.markdown(
        "<div class='canvas-footer'><span class='run-symbol'>"
        + ("◌" if running else "Ⅱ" if status == "incomplete" else "✓" if nodes else "○")
        + f"</span><div><strong>{esc(label)}</strong><span>{esc(detail)}</span></div>"
        + "<div class='evidence-scale'>"
        + "".join(
            f"<i class='{'filled' if position < min(count, 8) else ''}'></i>"
            for position in range(8)
        )
        + f"</div><span class='run-count'>{count:02d} checks</span></div>",
        unsafe_allow_html=True,
    )


def panel_intro(package):
    request = package.get("request", {})
    question = request.get("question", "Choose a prepared question or describe a symptom.")
    st.markdown(
        "<div class='assistant-intro'><span class='section-label'>INCIDENT DETECTIVE</span>"
        "<h2>Follow the evidence.<br>See every step.</h2>"
        "<p>From the first symptom to a finding you can inspect.</p></div>"
        "<div class='question-card'><span class='section-label'>INVESTIGATION QUESTION</span>"
        f"<p>{esc(question)}</p>"
        "<span><i class='status-dot'></i> Synthetic evidence · read-only investigation</span>"
        "</div>",
        unsafe_allow_html=True,
    )


def evidence_strip(package):
    hypotheses = package.get("analysis", {}).get("hypotheses", [])
    refs = (
        hypotheses[0].get("supporting_evidence_ids", [])
        if hypotheses
        else list(package.get("index", {}))
    )
    facts = evidence_facts(package, refs)
    st.markdown(
        "<div class='findings-heading'><strong>Findings & evidence</strong>"
        f"<span>{len(package.get('observations', []))} observations · "
        f"{len(package.get('changes', []))} changes</span></div>",
        unsafe_allow_html=True,
    )
    if facts:
        render_facts(facts)
    else:
        st.caption("Retrieved measurements and changes will appear here. No findings are assumed.")


def report_view(package):
    st.markdown("<span class='section-label'>INVESTIGATION REPORT</span>", unsafe_allow_html=True)
    diagnosis_view(package, show_facts=False)
    with st.expander("Export the complete diagnosis package", expanded=True):
        left, right = st.columns(2)
        left.download_button(
            "Download JSON",
            json.dumps(package, indent=2),
            "investigation.json",
            "application/json",
            use_container_width=True,
        )
        right.download_button(
            "Download HTML report",
            report_html(package),
            "report.html",
            "text/html",
            use_container_width=True,
        )
        st.caption("The complete report includes sources, checks and coverage limitations.")


def render_case(package):
    package = package or {}
    request = package.get("request", {})
    status = STATUS_LABELS.get(package.get("status"), "Ready to investigate")
    st.markdown(
        "<div class='case-heading'><div><span>INVESTIGATIONS / TEMPORAL LAB</span>"
        f"<h1>{esc(request.get('rootName', 'Operational investigation'))}</h1></div>"
        f"<span class='case-mode'>{esc(status)}</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    if request:
        st.caption(
            f"Incident time: {clock(request['effectiveAt'])} Berlin · "
            f"Knowledge cutoff: {clock(request['knowledgeAsOf'])} Berlin"
        )
    left, right = st.columns([2.65, 1.1], gap="medium")
    with left:
        with st.container(border=True, key="evidence_canvas"):
            canvas_view(package, full=st.session_state.get("full_evidence_graph", False))
            investigation_footer(package)
        evidence_strip(package)
        if package:
            with st.expander("Graph display & record inspector"):
                st.checkbox(
                    "Show measurements, code and state records in graph", key="full_evidence_graph"
                )
                records = package.get("index", {})
                if records:
                    selected = st.selectbox(
                        "Inspect a source record", list(records), format_func=short
                    )
                    st.json(records[selected], expanded=False)
    with right:
        with st.container(border=True, height=725, key="investigation_panel"):
            investigation, report, evidence = st.tabs(["Investigation", "Report", "Evidence"])
            with investigation:
                panel_intro(package)
                check_timeline(package)
                if package:
                    with st.expander("Hypotheses & check details"):
                        activity_view(package)
            with report:
                if package:
                    report_view(package)
                else:
                    st.caption(
                        "Your diagnosis and downloadable report will appear after investigation."
                    )
            with evidence:
                if package:
                    measured_evidence(package, compact=True)
                else:
                    st.caption("Source records will appear as the graph is explored.")
