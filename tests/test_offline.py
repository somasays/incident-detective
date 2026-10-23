import importlib
import os

import pytest

import config


def test_inherited_remote_tracing_disabled(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_OTEL_ENABLED", "true")
    importlib.reload(config)
    assert all(
        os.environ[key] == "false"
        for key in [
            "LANGSMITH_TRACING",
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_TRACING",
            "LANGSMITH_OTEL_ENABLED",
        ]
    )


def test_loopback_only_config_without_network():
    for host in ["localhost", "127.0.0.1", "[::1]"]:
        assert config.Settings(ollama_host=f"http://{host}:11434")
    with pytest.raises(ValueError):
        config.Settings(ollama_host="http://127.0.0.1.evil.test:11434")
