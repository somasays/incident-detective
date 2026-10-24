"""The graph must choose, execute and reassess real typed checks, with bounded failure paths."""

import json
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from agent.investigation_loop import LoopLimits, build_hypothesis_loop
from knowledge.diagnostic_tools import empty_package

NOW = "2026-10-23T08:05:00Z"


def node(id, label="Component", **props):
    return {"id": id, "label": label, **props}


def edge(id, source, target, type):
    return {"id": id, "source": source, "target": target, "type": type}


def metric(id, owner, value, period="07:55", name="latency"):
    start = datetime.fromisoformat(f"2026-10-23T{period}:00+00:00")
    return node(
        id,
        "Observation",
        entityId=owner,
        kind="metric_window",
        metricName=name,
        value=value,
        unit="ms",
        aggregation="p95",
        windowStart=f"2026-10-23T{period}:00Z",
        windowEnd=(start + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        sampleCount=100,
    )


class Repository:
    def __init__(self, history=True):
        self.trace = []
        self.history = history

    def catalog(self):
        return [node("api", name="demo-api", aliases=["demo api"])]

    def topology(self, request, max_depth=1):
        return {
            "nodes": [*self.catalog(), node("auth")],
            "edges": [edge("dependency", "api", "auth", "DEPENDS_ON")],
            "paths": [["api"], ["api", "auth"]],
        }

    def observe_target(self, request, ids):
        return [
            {"observation": o, "edge": edge(o["id"] + "-edge", o["id"], "api", "OBSERVED_ON")}
            for o in [metric("prior", "api", 85, "07:20"), metric("slow", "api", 1650)]
        ]

    def find_precedents(self, request, topology, signals):
        if not self.history:
            return []
        return [
            {
                "incident": node("past", "Incident", timestamp="2026-10-22T19:00:00Z"),
                "finding": node("old-finding", "Finding", conclusion="Earlier storage contention"),
                "cause": node("volume", "StorageVolume"),
                "previousCauseId": "volume",
                "sharedPatterns": ["latency"],
                "explains": edge("ex", "old-finding", "past", "EXPLAINS"),
                "attribution": edge("attr", "old-finding", "volume", "ATTRIBUTED_TO"),
            }
        ]


class Tools:
    def __init__(self):
        self.calls = []

    def execute(self, tool, entity_ids, package, deadline, max_hops):
        self.calls.append((tool, entity_ids))
        result = empty_package(package["request"])
        if tool == "expand_dependencies":
            result["graph"] = {
                "nodes": [node("volume", "StorageVolume")],
                "edges": [edge("storage", "auth", "volume", "USES_STORAGE")],
            }
        elif tool == "inspect_observations":
            obs = metric("storage-slow", "volume", 115)
            result["observations"] = [obs]
            result["graph"] = {
                "nodes": [obs],
                "edges": [edge("observed", "storage-slow", "volume", "OBSERVED_ON")],
            }
        elif tool == "inspect_state_changes":
            change = node(
                "allocation", "Change", entityId="volume", beforeValue="3000", afterValue="300"
            )
            result["changes"] = [change]
            result["graph"] = {
                "nodes": [change],
                "edges": [edge("changed", "allocation", "volume", "APPLIED_TO")],
            }
        result["evidenceIds"] = [n["id"] for n in result["graph"]["nodes"]]
        return result


def candidate(id="H1", basis="old-finding"):
    return {
        "id": id,
        "statement": "Possible storage allocation bottleneck",
        "basis_evidence_ids": [basis],
        "expected_support": "Low allocation and high storage latency",
        "expected_refutation": "Storage latency remains at the earlier reference",
    }


def check(tool, ids, hypotheses=None):
    return {
        "tool": tool,
        "entity_ids": ids,
        "hypothesis_ids": hypotheses or ["H1"],
        "label": "Check the proposed mechanism",
        "question": "Does this evidence support the proposed mechanism?",
    }


def plan(basis="old-finding"):
    return {
        "symptom_status": "observed",
        "summary": "Latency warrants investigation.",
        "hypotheses": [candidate(basis=basis)],
        "next_check": check("expand_dependencies", ["auth"]),
    }


def evaluation(next_check, supported=False):
    return {
        "summary": "Storage allocation is a possible trigger."
        if supported
        else "Evidence remains incomplete.",
        "assessments": [
            {
                "hypothesis_id": "H1",
                "status": "supported" if supported else "unresolved",
                "finding_level": "mechanism" if supported else "propagation",
                "metric_evidence_ids": ["storage-slow"] if supported else [],
                "mechanism_evidence_ids": ["allocation"] if supported else [],
                "cause_entity_id": "volume" if supported else None,
                "summary": "Reduced allocation may explain the storage latency."
                if supported
                else "The mechanism still needs current evidence.",
                "explanation": "Storage latency was 115 ms with a reduced allocation."
                if supported
                else "More evidence is needed to test the mechanism.",
                "supporting_evidence_ids": ["storage-slow", "allocation"] if supported else [],
                "contradicting_evidence_ids": [],
                "current_evidence_ids": ["storage-slow", "allocation"] if supported else [],
                "missing_evidence": ["Independent device inspection is needed."],
                "next_verification": "Inspect the storage controller configuration history.",
            }
        ],
        "new_hypotheses": [],
        "next_check": next_check,
        "next_action_reason": "Check the mechanism."
        if next_check
        else "Mechanism has current supporting evidence.",
        "limitations": ["Synthetic evidence and limited observation windows."],
    }


class Reasoner:
    def __init__(self, responses):
        self.responses = deepcopy(responses)
        self.calls = []

    def check_model(self):
        pass

    def generate(self, messages, schema, timeout_seconds=None):
        self.calls.append(
            {"messages": deepcopy(messages), "schema": schema, "timeout": timeout_seconds}
        )
        return json.dumps(self.responses.pop(0))


def run(responses, limits=None, history=True):
    tools = Tools()
    reasoner = Reasoner(responses)
    result = build_hypothesis_loop(Repository(history), reasoner, limits, tools).invoke(
        {"question": "Why is demo API slow now?"}
    )["package"]
    return result, tools, reasoner


def successful_responses():
    return [
        plan(),
        evaluation(check("inspect_observations", ["auth", "volume"])),
        evaluation(check("inspect_state_changes", ["volume"])),
        evaluation(None, True),
    ]


def test_history_led_loop_expands_then_checks_current_metrics_and_changes():
    result, tools, model = run(successful_responses())
    assert result["status"] == "complete", result.get("error")
    assert [t for t, _ in tools.calls] == [
        "expand_dependencies",
        "inspect_observations",
        "inspect_state_changes",
    ]
    assert result["analysis"]["hypotheses"][0]["cause_entity_id"] == "volume"
    assert result["budgets"]["checksUsed"] == 3
    assert result["budgets"]["modelCallsUsed"] == len(model.calls) == 4
    assert len(result["hypothesisTests"][0]["checks"]) == 3
    assert len(result["hypothesisTests"][0]["assessments"]) == 3
    assert result["stages"][-1]["next"] == "END"
    assert sum(s["stage"] == "evaluate_hypotheses" for s in result["stages"]) == 3
    first_prompt = json.loads(model.calls[0]["messages"][1]["content"])
    assert "volume" not in first_prompt["context"]["known_resource_ids"]
    assert first_prompt["context"]["precedents"]


def test_cold_start_without_previous_incident_still_investigates():
    responses = successful_responses()
    responses[0] = plan(basis="slow")
    result, _, _ = run(responses, history=False)
    assert result["status"] == "complete", result.get("error")
    assert not result["precedents"]


def test_compact_result_cannot_introduce_an_unsupported_measurement():
    responses = successful_responses()
    responses[-1]["assessments"][0]["summary"] = "Latency reached 999999 ms."
    responses.append(deepcopy(responses[-1]))
    result, _, _ = run(responses)
    assert result["status"] == "unavailable"
    assert "unsupported numerical value" in result["error"]
    assert result["observations"]
    assert not result["analysisAvailable"]


def test_query_bookkeeping_does_not_consume_model_budget_or_discard_exported_logs():
    class VerboseQueryLog(Tools):
        def execute(self, *args):
            result = super().execute(*args)
            result["queries"] = [{"query_metadata": "x" * 70_000}]
            return result

    reasoner = Reasoner(successful_responses())
    result = build_hypothesis_loop(Repository(), reasoner, tools=VerboseQueryLog()).invoke(
        {"question": "demo API slow now"}
    )["package"]
    assert result["status"] == "complete", result.get("error")
    assert len(result["checks"][0]["queries"][0]["query_metadata"]) == 70_000
    for call in reasoner.calls:
        payload = json.loads(call["messages"][1]["content"])
        assert "query_metadata" not in json.dumps(payload)
        assert payload["context"]["observations"]


def test_check_budget_preserves_evidence_and_marks_incomplete():
    result, tools, model = run(successful_responses()[:3], LoopLimits(max_checks=2))
    assert result["status"] == "incomplete", result.get("error")
    assert len(tools.calls) == 2
    assert "storage-slow" in result["index"]
    assert result["budgets"]["modelCallsUsed"] == len(model.calls) == 3


def test_repeated_check_is_rejected_and_replanned_once():
    responses = successful_responses()
    responses.insert(1, evaluation(check("expand_dependencies", ["auth"])))
    result, tools, reasoner = run(responses)
    assert result["status"] == "complete", result.get("error")
    assert len(tools.calls) == 3
    assert len(reasoner.calls) == 5


def test_budget_during_invalid_output_retry_preserves_incomplete_evidence():
    invalid = plan()
    invalid["next_check"]["tool"] = "nonexistent_tool"
    result, tools, reasoner = run([invalid], LoopLimits(max_model_calls=1))
    assert result["status"] == "incomplete", result.get("error")
    assert not tools.calls and len(reasoner.calls) == 1
    assert result["budgets"]["modelCallsUsed"] == 1
    assert "budget" in result["stopReason"]
    assert "slow" in result["index"]


def test_invalid_tool_or_target_is_retried_once_before_execution():
    invalid = plan()
    invalid["next_check"]["entity_ids"] = ["volume"]  # Historical cause is not connected yet.
    result, tools, model = run([invalid, *successful_responses()])
    assert result["status"] == "complete", result.get("error")
    assert len(model.calls) == 5
    assert tools.calls[0] == ("expand_dependencies", ["auth"])


def test_two_invalid_plans_preserve_initial_evidence_without_fake_diagnosis():
    invalid = plan()
    invalid["next_check"]["tool"] = "delete_database"
    result, tools, model = run([invalid, invalid])
    assert result["status"] == "unavailable"
    assert not tools.calls and len(model.calls) == 2
    assert result["graph"]["nodes"] and "slow" in result["index"]
    assert not result["analysisAvailable"] and not result["analysis"]


def test_prior_finding_cannot_be_used_as_current_confirmation():
    bad = evaluation(None, True)
    bad["assessments"][0]["current_evidence_ids"] = ["old-finding"]
    bad["assessments"][0]["supporting_evidence_ids"] = ["old-finding"]
    bad["assessments"][0]["metric_evidence_ids"] = []
    bad["assessments"][0]["mechanism_evidence_ids"] = []
    result, tools, _ = run([plan(), bad, bad])
    assert result["status"] == "unavailable"
    assert "prior finding" in result["error"].lower()
    assert len(tools.calls) == 1


def test_refutation_requires_contradictory_evidence():
    bad = evaluation(None)
    bad["assessments"][0].update(status="refuted", current_evidence_ids=["slow"])
    result, _, _ = run([plan(), bad, bad])
    assert result["status"] == "unavailable"
    assert "Refutation requires" in result["error"]


def test_model_budget_stops_before_unassessable_checks():
    result, tools, model = run([plan()], LoopLimits(max_model_calls=1))
    assert result["status"] == "incomplete"
    assert not tools.calls and len(model.calls) == 1


def test_uncorroborated_symptom_does_not_reactivate_old_incident():
    result, tools, model = run(
        [
            {
                "symptom_status": "not_observed",
                "summary": "The supplied windows do not corroborate an active slowdown.",
                "hypotheses": [],
                "next_check": None,
            }
        ]
    )
    assert result["status"] == "symptom_not_observed"
    assert not tools.calls and len(model.calls) == 1
    assert result["analysis"]["hypotheses"] == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_checks": 9},
        {"max_hops": 4},
        {"max_hypotheses": 4},
        {"max_model_calls": 11},
        {"timeout_seconds": 181},
    ],
)
def test_loop_budget_cannot_be_increased_beyond_design(kwargs):
    with pytest.raises(ValueError):
        LoopLimits(**kwargs)


def test_new_hypothesis_can_be_added_after_a_check():
    responses = successful_responses()
    responses[1]["new_hypotheses"] = [candidate("H2", basis="volume")]
    responses[1]["next_check"]["hypothesis_ids"].append("H2")
    for response in responses[2:]:
        alternative = deepcopy(evaluation(None)["assessments"][0])
        alternative["hypothesis_id"] = "H2"
        response["assessments"].append(alternative)
    result, _, _ = run(responses)
    assert result["status"] == "complete", result.get("error")
    assert {h["id"] for h in result["hypothesisTests"]} == {"H1", "H2"}
    assert len(result["analysis"]["hypotheses"]) == 1


def test_propagation_cannot_be_presented_as_a_root_mechanism():
    bad = evaluation(None)
    bad["assessments"][0].update(
        status="supported",
        cause_entity_id="auth",
        finding_level="propagation",
        current_evidence_ids=["slow"],
    )
    result, _, _ = run([plan(), bad, bad])
    assert result["status"] == "insufficient_evidence"
    assert not result["analysis"]["hypotheses"]
    assert result["hypothesisTests"][0]["assessments"][0]["finding_level"] == "propagation"


def test_newly_discovered_resources_receive_one_coverage_review_before_stopping():
    responses = successful_responses()
    responses.insert(1, evaluation(None))
    result, tools, reasoner = run(responses)
    assert result["status"] == "complete", result.get("error")
    assert len(tools.calls) == 3
    assert len(reasoner.calls) == 5
    assert sum(s["stage"] == "review_coverage" for s in result["stages"]) == 1
    prompt = json.loads(reasoner.calls[2]["messages"][1]["content"])
    assert prompt["newly_discovered_resource_ids"] == ["volume"]


def test_final_package_keeps_citations_across_measurement_and_mechanism_roles():
    class MoreTelemetry(Tools):
        def execute(self, tool, *args):
            result = super().execute(tool, *args)
            if tool == "inspect_observations":
                for index in range(13):
                    observation = node(
                        f"log-{index}", "Observation", entityId="volume", kind="error"
                    )
                    result["observations"].append(observation)
                    result["graph"]["nodes"].append(observation)
                    result["graph"]["edges"].append(
                        edge(f"owner-{index}", observation["id"], "volume", "OBSERVED_ON")
                    )
            return result

    responses = successful_responses()
    assessment = responses[-1]["assessments"][0]
    assessment["supporting_evidence_ids"] = [f"log-{i}" for i in range(12)]
    assessment["current_evidence_ids"] = ["log-12", "storage-slow", "allocation"]
    result = build_hypothesis_loop(Repository(), Reasoner(responses), tools=MoreTelemetry()).invoke(
        {"question": "demo API slow now"}
    )["package"]
    assert result["status"] == "complete", result.get("error")
    citations = result["analysis"]["hypotheses"][0]["supporting_evidence_ids"]
    assert all(f"log-{i}" in citations for i in range(13))
    assert {"storage-slow", "allocation"} <= set(citations)


def test_mechanism_assessment_requires_explicit_current_citations():
    bad = evaluation(None)
    bad["assessments"][0].update(
        status="supported",
        cause_entity_id="auth",
        finding_level="mechanism",
        current_evidence_ids=["slow"],
        metric_evidence_ids=["slow"],
    )
    result, _, _ = run([plan(), bad, bad])
    assert result["status"] == "unavailable"
    assert "requires citations" in result["error"]


def test_model_schema_separates_previous_findings_from_current_evidence():
    _, _, reasoner = run(successful_responses())
    properties = reasoner.calls[1]["schema"]["$defs"]["Assessment"]["properties"]
    assert "old-finding" not in properties["current_evidence_ids"]["items"]["enum"]
    assert "old-finding" in properties["supporting_evidence_ids"]["items"]["enum"]
    assert "old-finding" not in properties["mechanism_evidence_ids"]["items"]["enum"]
    assert "slow" in properties["mechanism_evidence_ids"]["items"]["enum"]


@pytest.mark.parametrize("error_type", ["MAX_CLIENTS_REACHED", "VENDOR_X_EVENT_72", "unfamiliar"])
def test_error_names_do_not_control_evidence_roles_or_the_diagnosis(error_type):
    class TelemetryTools(Tools):
        def execute(self, tool, *args):
            result = super().execute(tool, *args)
            if tool == "inspect_observations":
                observation = node(
                    "diagnostic-log",
                    "Observation",
                    entityId="volume",
                    kind="error",
                    errorType=error_type,
                    message="Controller reports allocation contention.",
                )
                result["observations"].append(observation)
                result["graph"]["nodes"].append(observation)
                result["graph"]["edges"].append(
                    edge("log-owner", "diagnostic-log", "volume", "OBSERVED_ON")
                )
            return result

    for supported in [False, True]:
        last = evaluation(None, supported)
        if supported:
            assessment = last["assessments"][0]
            for field in [
                "supporting_evidence_ids",
                "current_evidence_ids",
                "mechanism_evidence_ids",
            ]:
                assessment[field] = ["diagnostic-log", "storage-slow"]
            assessment["explanation"] = (
                "Storage latency was 115 ms; the controller reports contention."
            )
        reasoner = Reasoner(
            [
                plan(),
                evaluation(check("inspect_observations", ["volume"])),
                last,
            ]
        )
        result = build_hypothesis_loop(Repository(), reasoner, tools=TelemetryTools()).invoke(
            {"question": "Why is demo API slow now?"}
        )["package"]
        assert result["status"] == ("complete" if supported else "insufficient_evidence"), (
            result.get("error")
        )
        props = reasoner.calls[-1]["schema"]["$defs"]["Assessment"]["properties"]
        assert "diagnostic-log" in props["mechanism_evidence_ids"]["items"]["enum"]
        assert bool(result["analysis"]["hypotheses"]) == supported


def test_partial_tool_failure_keeps_records_already_returned():
    class PartialTools(Tools):
        def execute(self, *args):
            result = super().execute(*args)
            result["error"] = "Network failed after returning the dependency relationship"
            return result

    tools = PartialTools()
    result = build_hypothesis_loop(Repository(), Reasoner([plan()]), tools=tools).invoke(
        {"question": "demo API slow now"}
    )["package"]
    assert result["status"] == "unavailable"
    assert "storage" in result["index"]
    assert result["checks"]
    assert not result["analysisAvailable"]


def test_deadline_prevents_another_tool_call(monkeypatch):
    import agent.investigation_loop as loop

    time = [100.0]
    monkeypatch.setattr(loop, "monotonic", lambda: time[0])

    class SlowReasoner(Reasoner):
        def generate(self, *args, **kwargs):
            response = super().generate(*args, **kwargs)
            time[0] += 30
            return response

    tools = Tools()
    result = build_hypothesis_loop(
        Repository(), SlowReasoner([plan()]), LoopLimits(timeout_seconds=30), tools
    ).invoke({"question": "demo API slow now"})["package"]
    assert result["status"] == "incomplete"
    assert not tools.calls
    assert "deadline" in result["stopReason"]
    assert "slow" in result["index"]
