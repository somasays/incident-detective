"""Configuration refresh and override behavior must match across all local services/providers."""

import pytest

import config
from agent.providers import ModelSettings, get_temporal_reasoner
from agent.reasoning import AnalysisUnavailable


def test_file_edits_are_fresh_and_shell_overrides_win(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", path)
    keys = ["OLLAMA_MODEL", "NEO4J_DATABASE", "LLM_PROVIDER", "OPENAI_MODEL"]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    path.write_text("OLLAMA_MODEL=first\nNEO4J_DATABASE=one\nLLM_PROVIDER=ollama\n")
    assert config.Settings.from_env().ollama_model == "first"
    assert config.Settings.from_env().neo4j_database == "one"
    path.write_text("OLLAMA_MODEL=second\nNEO4J_DATABASE=two\nLLM_PROVIDER=openai\n")
    assert config.Settings.from_env().ollama_model == "second"
    assert config.Settings.from_env().neo4j_database == "two"
    assert ModelSettings.from_env().provider == "openai"
    monkeypatch.setenv("OLLAMA_MODEL", "shell-model")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert config.Settings.from_env().ollama_model == "shell-model"
    assert ModelSettings.from_env().provider == "ollama"


def test_invalid_provider_and_secrets_are_not_exposed():
    with pytest.raises(AnalysisUnavailable, match="LLM_PROVIDER"):
        ModelSettings(provider="unknown").validate()
    assert "private-password" not in repr(config.Settings(neo4j_password="private-password"))
    assert "private-key" not in repr(ModelSettings(api_key="private-key"))


def test_offline_flag_blocks_later_remote_provider_selection(monkeypatch):
    monkeypatch.setenv("INCIDENT_OFFLINE", "1")
    with pytest.raises(AnalysisUnavailable, match="remote providers are disabled"):
        get_temporal_reasoner(ModelSettings(provider="openai"))
