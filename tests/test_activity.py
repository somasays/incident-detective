"""Regression coverage for persistent live activity and retained diagnosis packages."""

from unittest.mock import patch

import pytest

from tests.test_app import DummyDatabase, app_test
from tests.test_investigation_loop import run, successful_responses
from ui.presentation import evidence_facts, hypothesis_title


@pytest.fixture(autouse=True)
def clear_cache():
    import streamlit as st

    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def test_completed_checks_and_source_records_stay_in_the_activity_tree():
    package, _, _ = run(successful_responses())
    with patch("ui.temporal_workspace.Database", DummyDatabase):
        app = app_test()
        app.session_state["temporal_result"] = package
        app.run()
        assert not app.exception
        assert any("Possible storage allocation bottleneck" in m.value for m in app.markdown)
        assert any("class='outcome supported'" in m.value for m in app.markdown)
        assert any("3 / 8 checks" in c.value for c in app.caption)
        assert any("check-3" in e.label for e in app.expander)
        assert any("Source records" in m.value for m in app.markdown)
        app.run()
        assert not app.exception
        assert app.session_state["temporal_result"]["investigationId"] == package["investigationId"]


def test_previous_package_renders_before_the_new_investigation_starts():
    from ui.temporal_workspace import render_package

    previous, _, _ = run(successful_responses())
    updated = {**previous, "investigationId": "next-investigation"}
    events = []

    def render(package):
        events.append(("render", package["investigationId"]))
        render_package(package)

    def stream(*args):
        events.append(("stream", None))
        assert events[-2] == ("render", previous["investigationId"])
        return updated

    with (
        patch("ui.temporal_workspace.Database", DummyDatabase),
        patch("ui.temporal_workspace.render_package", side_effect=render),
        patch("ui.temporal_workspace.stream_investigation", side_effect=stream) as model_run,
    ):
        app = app_test()
        app.session_state["temporal_result"] = previous
        app.run()
        events.clear()
        next(b for b in app.button if b.label == "Investigate →").click().run()
        assert not app.exception
        assert events == [
            ("render", previous["investigationId"]),
            ("stream", None),
            ("render", "next-investigation"),
        ]
        assert model_run.call_count == 1
        app.run()
        assert model_run.call_count == 1


def test_old_verbose_packages_keep_full_details_without_paragraph_sized_headers():
    package, _, _ = run(successful_responses())
    verbose = "An extremely long hypothesis with detailed chronology and citations. " * 3
    question = "Inspect counters, queue lengths and timing windows for every resource. " * 4
    hypothesis = package["hypothesisTests"][0]
    hypothesis["statement"] = verbose
    for check in package["checks"]:
        check.pop("label")
        check["question"] = question
    for evaluation in package["evaluations"]:
        for assessment in evaluation["assessments"]:
            assessment.pop("summary")
    assert hypothesis_title(hypothesis, hypothesis["assessments"][-1], package) == (
        "Suspected cause · volume"
    )
    with patch("ui.temporal_workspace.Database", DummyDatabase):
        app = app_test()
        app.session_state["temporal_result"] = package
        app.run()
        assert not app.exception
        assert all(question not in expander.label for expander in app.expander)
        assert any(question.strip() in m.value for m in app.markdown)
        assert any(verbose.strip() in m.value for m in app.markdown)
        assert any("3,000 → 300" in m.value for m in app.markdown)
        assert all(
            not e.proto.expanded for e in app.expander if e.label.startswith("Details · check")
        )


def test_fact_cards_use_cited_records_and_retrieved_prior_values_only():
    package, _, _ = run(successful_responses())
    facts = evidence_facts(package, ["allocation", "slow"])
    assert [(f["value"], f["context"]) for f in facts] == [
        ("3,000 → 300", "Recorded change"),
        ("85 → 1,650 ms", "Prior → incident"),
    ]
    assert facts[1]["evidence_ids"] == ["prior", "slow"]
    assert evidence_facts(package, ["unretrieved-record"]) == []
    package["index"].pop("prior")
    assert evidence_facts(package, ["slow"])[0]["value"] == "1,650 ms"
