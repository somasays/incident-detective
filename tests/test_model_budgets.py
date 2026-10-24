"""Metadata and generation share the wall-clock budget without a hidden 60-second cap."""

from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from pydantic import BaseModel

import agent.investigation_loop as loop
import agent.temporal_reasoning as reasoning
from config import Settings
from knowledge.diagnostic_tools import empty_package


class Answer(BaseModel):
    ready: bool


def decision_state(deadline=100):
    return {"deadline": deadline, "model_calls": 0, "package": empty_package({})}


def test_generation_uses_time_remaining_after_legacy_metadata_check(monkeypatch):
    clock = [0]
    monkeypatch.setattr(loop, "monotonic", lambda: clock[0])

    class ScriptedReasoner:
        def check_model(self):
            clock[0] += 20

        def generate(self, messages, schema, timeout_seconds):
            assert timeout_seconds == 79
            return '{"ready":true}'

    result, calls, error = loop.structured_decision(
        ScriptedReasoner(), Answer, {}, decision_state(), loop.LoopLimits(), lambda _: None
    )
    assert result == {"ready": True}
    assert calls == 1 and error is None


def test_verification_receives_budget_and_retries_use_remaining_time(monkeypatch):
    clock = [0]
    monkeypatch.setattr(loop, "monotonic", lambda: clock[0])
    supplied = []

    class ScriptedReasoner:
        def check_model_with_budget(self, timeout_seconds):
            supplied.append(("metadata", timeout_seconds))
            clock[0] += 10

        def generate(self, messages, schema, timeout_seconds):
            supplied.append(("generation", timeout_seconds))
            clock[0] += 20
            return "invalid" if len(supplied) == 2 else '{"ready":true}'

    result, calls, error = loop.structured_decision(
        ScriptedReasoner(), Answer, {}, decision_state(), loop.LoopLimits(), lambda _: None
    )
    assert supplied == [
        ("metadata", 99), ("generation", 89), ("metadata", 69), ("generation", 59)
    ]
    assert result == {"ready": True}
    assert calls == 2 and error is None


def test_expired_metadata_budget_never_starts_generation(monkeypatch):
    clock = [0]
    monkeypatch.setattr(loop, "monotonic", lambda: clock[0])
    reasoner = Mock(spec=["check_model", "generate"])
    reasoner.check_model.side_effect = lambda: clock.__setitem__(0, 100)
    with pytest.raises(loop.DecisionBudgetExhausted) as failure:
        loop.structured_decision(
            reasoner, Answer, {}, decision_state(), loop.LoopLimits(), lambda _: None
        )
    assert failure.value.calls == 1
    reasoner.generate.assert_not_called()


def test_local_metadata_checks_recompute_time_and_cache_only_success(monkeypatch):
    clock = [0]
    monkeypatch.setattr(reasoning, "monotonic", lambda: clock[0])
    listing, details = Mock(), Mock()

    def list_models():
        clock[0] += 20
        return SimpleNamespace(models=[SimpleNamespace(model="local:14b")])

    listing.list.side_effect = list_models
    details.show.return_value.model_dump.return_value = {
        "modelfile": "FROM /weights/sha256-" + "a" * 64,
        "details": {"parameter_size": "14B"},
    }
    factory = Mock(side_effect=[listing, details])
    monkeypatch.setattr("ollama.Client", factory)
    reasoner = reasoning.TemporalReasoner(Settings(ollama_model="local:14b"), client=Mock())
    reasoner.check_model_with_budget(timeout_seconds=60)
    assert [call.kwargs["timeout"] for call in factory.call_args_list] == [60, 40]
    listing.close.assert_called_once()
    details.close.assert_called_once()
    reasoner.check_model_with_budget(timeout_seconds=5)
    assert factory.call_count == 2


def test_failed_local_model_verification_is_not_cached(monkeypatch):
    client = Mock()
    client.list.return_value = SimpleNamespace(models=[])
    factory = Mock(return_value=client)
    monkeypatch.setattr("ollama.Client", factory)
    reasoner = reasoning.TemporalReasoner(Settings(), client=Mock())
    for _ in range(2):
        with pytest.raises(reasoning.AnalysisUnavailable, match="not installed"):
            reasoner.check_model_with_budget(timeout_seconds=5)
    assert factory.call_count == 2


@pytest.mark.parametrize("remaining, expected", [(179, 90), (17, 17)])
def test_local_generation_respects_configured_and_remaining_time(monkeypatch, remaining, expected):
    client = Mock()
    client.chat.return_value = SimpleNamespace(message=SimpleNamespace(content='{"ready":true}'))
    factory = Mock(return_value=client)
    monkeypatch.setattr("ollama.Client", factory)
    reasoner = reasoning.TemporalReasoner(Settings(ollama_timeout_seconds=90), client=Mock())
    assert reasoner.generate([], {}, timeout_seconds=remaining) == '{"ready":true}'
    assert factory.call_args.kwargs["timeout"] == expected
    client.close.assert_called_once()


def test_expired_local_metadata_verification_stops_before_another_request(monkeypatch):
    clock = [0]
    monkeypatch.setattr(reasoning, "monotonic", lambda: clock[0])
    client = Mock()

    def list_models():
        clock[0] = 6
        return SimpleNamespace(models=[SimpleNamespace(model="local:14b")])

    client.list.side_effect = list_models
    factory = Mock(return_value=client)
    monkeypatch.setattr("ollama.Client", factory)
    reasoner = reasoning.TemporalReasoner(Settings(ollama_model="local:14b"), client=Mock())
    with pytest.raises(TimeoutError, match="verification exceeded"):
        reasoner.check_model_with_budget(timeout_seconds=5)
    assert factory.call_count == 1
    client.show.assert_not_called()


@pytest.mark.parametrize("elapsed", [99, 100])
@pytest.mark.parametrize("attempt", [1, 2])
def test_deadline_limited_transport_timeout_routes_as_budget_exhaustion(
    monkeypatch, elapsed, attempt
):
    clock = [0]
    monkeypatch.setattr(loop, "monotonic", lambda: clock[0])
    reasoner = Mock(spec=["check_model", "generate"])

    def timeout(*args, **kwargs):
        if reasoner.generate.call_count < attempt:
            return "invalid"
        clock[0] = elapsed
        raise httpx.ReadTimeout("timed out")

    reasoner.generate.side_effect = timeout
    with pytest.raises(loop.DecisionBudgetExhausted) as failure:
        loop.structured_decision(
            reasoner, Answer, {}, decision_state(), loop.LoopLimits(), lambda _: None
        )
    assert failure.value.calls == attempt


def test_per_call_timeout_with_overall_budget_remaining_stays_unavailable(monkeypatch):
    clock = [0]
    monkeypatch.setattr(loop, "monotonic", lambda: clock[0])
    reasoner = Mock(spec=["check_model", "generate"])

    def timeout(*args, **kwargs):
        clock[0] = 60
        raise httpx.ReadTimeout("timed out")

    reasoner.generate.side_effect = timeout
    result, calls, error = loop.structured_decision(
        reasoner, Answer, {}, decision_state(), loop.LoopLimits(), lambda _: None
    )
    assert result is None and calls == 1
    assert error == "Model unavailable (ReadTimeout): timed out"


def test_deadline_timeout_preserves_previous_graph_assessments(monkeypatch):
    from tests.test_investigation_loop import (
        Reasoner,
        Repository,
        Tools,
        successful_responses,
    )

    clock = [0]
    monkeypatch.setattr(loop, "monotonic", lambda: clock[0])

    class TimeoutReasoner(Reasoner):
        def generate(self, messages, schema, timeout_seconds=None):
            if len(self.calls) == 2:
                self.calls.append({"timeout": timeout_seconds})
                clock[0] = 180
                raise httpx.ReadTimeout("timed out")
            return super().generate(messages, schema, timeout_seconds)

    reasoner = TimeoutReasoner(successful_responses())
    result = loop.build_hypothesis_loop(Repository(), reasoner, tools=Tools()).invoke(
        {"question": "Why is demo API slow now?"}
    )["package"]
    assert result["status"] == "incomplete"
    assert result["analysisAvailable"]
    assert result["error"] is None
    assert result["graph"]["nodes"]
    assert len(result["hypothesisTests"][0]["assessments"]) == 1
    assert result["budgets"]["modelCallsUsed"] == 3
    assert "budget" in result["stopReason"]
