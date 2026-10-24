"""Diagnosis and measured evidence panels; no queries or model calls."""

import streamlit as st

from ui.facts import render_facts
from ui.formatting import clock, esc, short
from ui.presentation import evidence_facts, hypothesis_title


def diagnosis_view(package, *, show_facts=True):
    analysis = package.get("analysis", {})
    if package.get("status") == "incomplete":
        st.warning("Investigation stopped within its limits. Findings below remain incomplete.")
    if not package.get("analysisAvailable"):
        st.info(
            package.get("error") or "Evidence retrieved. Model interpretation was not requested."
        )
        return
    for hypothesis in analysis.get("hypotheses", []):
        assessment = next(
            (
                h["assessments"][-1]
                for h in package.get("hypothesisTests", [])
                if h.get("assessments")
                and h["assessments"][-1].get("cause_entity_id") == hypothesis.get("cause_entity_id")
                and h["assessments"][-1].get("status") == "supported"
            ),
            {},
        )
        summary = assessment.get("summary", "")
        if not summary and len(hypothesis["explanation"]) <= 220:
            summary = hypothesis["explanation"]
        st.markdown(
            "<div class='diagnosis-card'><span class='section-label'>"
            + ("LEADING HYPOTHESIS" if hypothesis["rank"] == 1 else "ALTERNATIVE HYPOTHESIS")
            + f"</span><h3>{esc(hypothesis_title(hypothesis, assessment, package))}</h3>"
            + (f"<p>{esc(summary)}</p>" if summary else "")
            + "<span class='muted'>Evidence supports a hypothesis · "
            + "cause remains provisional</span>"
            + "</div>",
            unsafe_allow_html=True,
        )
        if show_facts:
            render_facts(evidence_facts(package, hypothesis["supporting_evidence_ids"]))
        st.markdown("**Next verification**")
        if len(hypothesis["next_check"]) <= 180:
            st.write(hypothesis["next_check"])
        else:
            st.caption("See the verification request in Details.")
        with st.expander("Details · reasoning, gaps and sources"):
            st.write(hypothesis["explanation"])
            st.markdown("**Verification request**")
            st.write(hypothesis["next_check"])
            st.markdown("**Missing or contradictory evidence**")
            for gap in hypothesis["contradicting_or_missing_evidence"]:
                st.write(gap)
            st.markdown("**Source records**")
            for eid in hypothesis["supporting_evidence_ids"]:
                st.json(package.get("index", {}).get(eid, {"id": eid}), expanded=False)
    if not analysis.get("hypotheses"):
        st.caption("No supported root-cause hypothesis in the retrieved evidence.")
        st.write(analysis.get("summary", ""))
    with st.expander("Investigation summary and limitations"):
        st.write(analysis.get("summary", ""))
        for limitation in analysis.get("limitations", []):
            st.write(limitation)


def measured_evidence(package, *, compact=False):
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
        if compact:
            refs = [
                m["evidenceIds"]["incident"]
                for m in package.get("measurements", [])
                if m.get("evidenceIds", {}).get("incident")
            ]
            render_facts(evidence_facts(package, refs, limit=len(rows)))
            with st.expander("Full measurements table"):
                st.dataframe(rows, hide_index=True, use_container_width=True)
        else:
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
