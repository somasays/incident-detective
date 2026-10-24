"""Persistent hypothesis/check activity rendered from actual graph updates."""

from textwrap import shorten

import streamlit as st

from ui.facts import render_facts
from ui.formatting import clock, esc
from ui.presentation import assessment_refs, evidence_facts, hypothesis_title, resource_name

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


def check_timeline(state, *, running=False):
    """A compact, chronological view of real checks, separate from hypothesis detail."""
    package = state.get("package", state)
    checks = state.get("check_history", package.get("checks", []))
    evaluations = state.get("evaluation_history", package.get("evaluations", []))
    if not isinstance(checks, list):
        checks = []
    st.markdown(
        "<div class='timeline-heading'><strong>Activity</strong><span>"
        + ("Following investigation" if running else f"{len(checks)} evidence checks")
        + "</span></div>",
        unsafe_allow_html=True,
    )
    entries = []
    if package.get("topology", {}).get("nodes"):
        entries.append(
            (
                "SYSTEM CONTEXT",
                "Dependency map retrieved",
                f"{len(package['topology']['nodes'])} resources connected by stored relationships.",
                "done",
            )
        )
    for number, check in enumerate(checks, 1):
        evaluation = next(
            (e for e in reversed(evaluations) if e.get("check_id") == check["id"]), {}
        )
        counts = " · ".join(
            f"{value} {kind}" for kind, value in check.get("result", {}).items() if value
        )
        entries.append(
            (
                f"CHECK {number:02d}",
                check.get("label") or TOOL_LABELS.get(check["tool"], check["tool"]),
                evaluation.get("summary")
                or counts
                or "No records returned within this query window.",
                "done",
            )
        )
    pending = state.get("pending_check") if running else None
    if pending and not any(
        c["tool"] == pending["tool"] and set(c["entity_ids"]) == set(pending["entity_ids"])
        for c in checks
    ):
        entries.append(
            (
                "NEXT CHECK",
                pending.get("label") or TOOL_LABELS[pending["tool"]],
                pending["question"],
                "pending",
            )
        )
    if not entries:
        st.caption("Start an investigation to follow each evidence check here.")
        return
    st.markdown(
        "<ol class='activity-timeline'>"
        + "".join(
            f"<li class='{status}'><span class='timeline-dot'>"
            f"{'✓' if status == 'done' else '·'}</span>"
            f"<span class='section-label'>{esc(kicker)}</span><h4>{esc(label)}</h4>"
            f"<p>{esc(shorten(detail, width=180, placeholder='…'))}</p></li>"
            for kicker, label, detail, status in entries
        )
        + "</ol>",
        unsafe_allow_html=True,
    )


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
        return f"{len(state.get('candidates', []))} hypotheses to test"
    if name in {"choose_next_check", "evaluate_hypotheses", "review_coverage"}:
        pending = state.get("pending_check")
        return (
            pending.get("label", TOOL_LABELS[pending["tool"]]) if pending else "Preparing findings"
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
    for number, hypothesis in enumerate(candidates, 1):
        assessments = [
            a
            for evaluation in evaluations
            for a in evaluation["assessments"]
            if a["hypothesis_id"] == hypothesis["id"]
        ]
        latest = assessments[-1] if assessments else {}
        with st.container(border=True):
            outcome = latest.get("status", "validating" if running else "unresolved")
            st.markdown(
                f"<div class='hypothesis-heading'><span class='hypothesis-number'>H{number}</span>"
                f"<h3>{esc(hypothesis_title(hypothesis, latest, package))}</h3>"
                f"<span class='outcome {esc(outcome)}'>{esc(outcome)}</span></div>",
                unsafe_allow_html=True,
            )
            render_facts(evidence_facts(package, assessment_refs(latest)))
            for index, check in enumerate(checks):
                if hypothesis["id"] not in check["hypothesis_ids"]:
                    continue
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
                        {},
                    )
                    if completed
                    else {}
                )
                label = check.get("label") or TOOL_LABELS.get(check["tool"], check["tool"])
                resources = ", ".join(resource_name(package, e) for e in check["entity_ids"])
                result = check.get("result", {})
                counts = (
                    " · ".join(
                        f"{value} {kind}"
                        for kind, value in result.items()
                        if value and (kind != "nodes" or check["tool"] == "expand_dependencies")
                    )
                    or "No records in this query window"
                )
                check_status = assessment.get("status", "assessing" if running else "not assessed")
                # Keep each completed check visible. Only its verbose audit details collapse.
                st.markdown(
                    f"<div class='check-row'><span class='check-number'>{index + 1:02d}</span>"
                    f"<div><strong>{esc(label)}</strong><div class='check-resources'>"
                    f"{esc(resources)}</div><div class='check-result'>{esc(counts)}</div></div>"
                    f"<span class='outcome {esc(check_status)}'>"
                    f"H{number} · {esc(check_status)}</span></div>",
                    unsafe_allow_html=True,
                )
                if assessment.get("summary"):
                    st.caption(assessment["summary"])
                else:
                    for fact in evidence_facts(package, check.get("evidence_ids", []), limit=2):
                        st.caption(f"{fact['resource']} · {fact['value']} · {fact['label']}")
                with st.expander(f"Details · {check['id']}"):
                    st.write(check["question"])
                    if assessment:
                        st.write(assessment["explanation"])
                        for gap in assessment.get("missing_evidence", []):
                            st.write("Gap: " + gap)
                    st.markdown("**Source records**")
                    st.json(
                        [
                            package.get("index", {}).get(e, {"id": e})
                            for e in check.get("evidence_ids", [])
                        ],
                        expanded=False,
                    )
            if pending and hypothesis["id"] in pending["hypothesis_ids"]:
                st.info("Next: " + pending.get("label", TOOL_LABELS[pending["tool"]]))
            with st.expander("Hypothesis details · reasoning and gaps"):
                st.caption("Internal ID: " + hypothesis["id"])
                st.write(hypothesis["statement"])
                st.write("Support: " + hypothesis["expected_support"])
                st.write("Refutation: " + hypothesis["expected_refutation"])
                if latest:
                    st.write(latest["explanation"])
                    st.caption("Finding level: " + latest["finding_level"])
                    for gap in latest.get("missing_evidence", []):
                        st.write("Gap: " + gap)


def activity_view(package):
    st.markdown("### Investigation activity")
    budgets = package.get("budgets", {})
    if budgets:
        st.caption(
            f"{budgets.get('checksUsed', 0)} / {budgets.get('maxChecks', 8)} checks · "
            f"{budgets.get('modelCallsUsed', 0)} model calls · "
            f"{package.get('status', '').replace('_', ' ')}"
        )
    hypothesis_activity(package)
    with st.expander("All stages and graph queries"):
        if package.get("stopReason"):
            st.write("Stopped: " + package["stopReason"])
        for step in package.get("stages", []):
            st.markdown(f"**{STAGE_LABELS.get(step['stage'], step['stage'])}**")
            st.caption(
                f"{step['status']} · {step['elapsedMs']} ms · "
                f"next: {STAGE_LABELS.get(step['next'], step['next'])}"
            )
        st.json(package.get("queryTrace", []))
