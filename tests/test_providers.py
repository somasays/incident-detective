"""Remote selection, structured generation, bounded retry and secret-safe errors."""

from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import openai
import pytest

from agent.providers import ModelSettings, get_temporal_reasoner
from agent.reasoning import AnalysisUnavailable
from agent.temporal import OpenAITemporalReasoner, TemporalReasoner
from knowledge.mcp_db import mcp_parameters, result_rows


def test_explicit_provider_selection_and_local_default():
    assert isinstance(get_temporal_reasoner(ModelSettings(), client=Mock()), TemporalReasoner)
    assert isinstance(
        get_temporal_reasoner(ModelSettings(provider="openai")), OpenAITemporalReasoner
    )
    with pytest.raises(AnalysisUnavailable, match="Fill"):
        ModelSettings(provider="openai").validate()
    assert "secret" not in repr(ModelSettings(api_key="secret"))


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/v1",
        "https://example.org/v1?key=secret",
        "https://user:pass@example.org/v1",
        "https://x/v1/chat/completions",
    ],
)
def test_reject_invalid_endpoint(url):
    with pytest.raises(AnalysisUnavailable):
        ModelSettings(provider="openai", base_url=url, api_key="secret").validate()


def test_openai_json_schema_and_no_implicit_fallback():
    settings = ModelSettings(
        provider="openai", base_url="https://example.org/v1", api_key="secret", model="gpt-4o"
    )
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content='{"ready":true}', refusal=None),
            )
        ]
    )
    reasoner = OpenAITemporalReasoner(settings, client)
    schema = {
        "type": "object",
        "properties": {"ready": {"type": "boolean"}},
        "required": ["ready"],
        "additionalProperties": False,
    }
    assert reasoner.generate([{"role": "user", "content": "ready?"}], schema) == '{"ready":true}'
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"]["json_schema"]["strict"]
    assert kwargs["max_tokens"] <= 2048
    client.chat.completions.create.side_effect = openai.AuthenticationError(
        "secret in error body",
        response=httpx.Response(401, request=httpx.Request("POST", settings.base_url)),
        body={"secret": "secret"},
    )
    with pytest.raises(AnalysisUnavailable, match="401") as error:
        reasoner.generate([], schema)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("model", ["gpt-5-mini", "gpt-5-mini-2025-08-07"])
def test_gpt5_mini_uses_reasoning_compatible_bounded_parameters(model):
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content='{"ready":true}', refusal=None),
            )
        ]
    )
    reasoner = OpenAITemporalReasoner(
        ModelSettings(
            provider="openai",
            base_url="https://example.org/v1",
            api_key="secret",
            model=model,
        ),
        client,
    )
    assert reasoner.generate([], {"type": "object"}) == '{"ready":true}'
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == model
    assert kwargs["max_completion_tokens"] == 4096
    assert kwargs["reasoning_effort"] == "low"
    assert "temperature" not in kwargs and "max_tokens" not in kwargs


def test_mcp_datetime_binding_is_typed_and_parameterized():
    from datetime import UTC, datetime

    query, params = mcp_parameters(
        "RETURN $at, $atom, $ids",
        {"at": datetime(2026, 10, 23, tzinfo=UTC), "atom": "literal", "ids": ["x' OR true"]},
    )
    assert query == "RETURN datetime($at), $atom, $ids"
    assert isinstance(params["at"], str)
    assert params["ids"] == ["x' OR true"]
    assert result_rows(SimpleNamespace(isError=False, structuredContent={"data": [{"ok": 1}]})) == [
        {"ok": 1}
    ]
