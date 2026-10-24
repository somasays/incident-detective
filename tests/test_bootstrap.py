"""Launcher behavior around offline boundaries and service startup failures."""

from argparse import Namespace
from unittest.mock import MagicMock, Mock

import pytest

import config
from agent.providers import ModelSettings
from config import Settings
from scripts import bootstrap


def options(**kwargs):
    return Namespace(
        **{"offline": True, "setup_only": True, "evidence_only": False, "port": 8501, **kwargs}
    )


def test_occupied_port_is_a_failure_before_preflight_or_startup(monkeypatch):
    monkeypatch.setattr(bootstrap, "setup_environment", Mock())
    monkeypatch.setattr(bootstrap, "port_in_use", lambda port: True)
    command = Mock()
    monkeypatch.setattr(bootstrap, "command", command)
    with pytest.raises(RuntimeError, match="Port 8501 is occupied"):
        bootstrap.bootstrap(options(setup_only=False))
    command.assert_not_called()


def test_offline_launch_rejects_remote_provider_before_starting_services(monkeypatch):
    monkeypatch.setattr(bootstrap, "setup_environment", Mock())
    monkeypatch.setattr(bootstrap.Settings, "from_env", lambda: Settings())
    monkeypatch.setattr(
        bootstrap.ModelSettings, "from_env", lambda: ModelSettings(provider="openai")
    )
    command = Mock()
    monkeypatch.setattr(bootstrap, "command", command)
    with pytest.raises(RuntimeError, match="Offline launch requires Ollama"):
        bootstrap.bootstrap(options())
    command.assert_not_called()


def test_missing_model_offline_never_triggers_download(monkeypatch):
    monkeypatch.setattr(bootstrap, "http_json", lambda url: {"models": []})
    command = Mock()
    monkeypatch.setattr(bootstrap, "command", command)
    with pytest.raises(RuntimeError, match="model is missing"):
        bootstrap.start_ollama(Settings(), offline=True)
    command.assert_not_called()


def test_command_failure_stops_setup_with_nonzero_status(monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "bootstrap", Mock(side_effect=RuntimeError("Docker is stopped")))
    assert bootstrap.main(["--setup-only"]) == 1
    assert "Docker is stopped" in capsys.readouterr().err


def test_invalid_port_never_starts_services(monkeypatch):
    command = Mock()
    monkeypatch.setattr(bootstrap, "bootstrap", command)
    with pytest.raises(SystemExit):
        bootstrap.main(["--port", "70000"])
    command.assert_not_called()


def test_dashboard_child_keeps_file_settings_refreshable_and_preserves_explicit_env(
    tmp_path, monkeypatch
):
    path = tmp_path / ".env"
    path.write_text("OPENAI_MODEL=file-model\nNEO4J_DATABASE=file-database\nLLM_PROVIDER=openai\n")
    monkeypatch.setattr(config, "ENV_FILE", path)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("NEO4J_DATABASE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    process = Mock()
    monkeypatch.setattr(bootstrap.subprocess, "run", process)
    bootstrap.command(
        ["streamlit", "run", "app.py"],
        project_environment=False,
        extra_env={"INCIDENT_OFFLINE": "1", "INCIDENT_EVIDENCE_ONLY": "1"},
    )
    environment = process.call_args.kwargs["env"]
    assert "OPENAI_MODEL" not in environment and "NEO4J_DATABASE" not in environment
    assert environment["LLM_PROVIDER"] == "ollama"
    assert environment["INCIDENT_OFFLINE"] == "1"
    assert environment["INCIDENT_EVIDENCE_ONLY"] == "1"


def test_service_commands_still_receive_project_environment(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("NEO4J_DATABASE=file-database\nOLLAMA_MODEL=file-model\n")
    monkeypatch.setattr(config, "ENV_FILE", path)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.setenv("NEO4J_DATABASE", "shell-database")
    process = Mock()
    monkeypatch.setattr(bootstrap.subprocess, "run", process)
    bootstrap.command(["docker", "compose", "up", "-d"])
    environment = process.call_args.kwargs["env"]
    assert environment["OLLAMA_MODEL"] == "file-model"
    assert environment["NEO4J_DATABASE"] == "shell-database"


def test_dashboard_launch_does_not_promote_project_environment(monkeypatch):
    monkeypatch.setattr(bootstrap, "setup_environment", Mock())
    monkeypatch.setattr(bootstrap, "port_in_use", lambda port: False)
    monkeypatch.setattr(bootstrap.Settings, "from_env", lambda: Settings())
    monkeypatch.setattr(bootstrap.ModelSettings, "from_env", lambda: ModelSettings())
    monkeypatch.setattr(bootstrap.shutil, "which", lambda executable: "/available/" + executable)
    monkeypatch.setattr(bootstrap, "Database", MagicMock())
    monkeypatch.setattr(bootstrap, "seed_temporal", lambda db: {"nodes": 1, "relationships": 1})
    monkeypatch.setattr(bootstrap, "start_ollama", Mock())
    monkeypatch.setattr(bootstrap, "check_runtime", lambda **kwargs: {})
    command = Mock()
    monkeypatch.setattr(bootstrap, "command", command)
    assert bootstrap.bootstrap(options(setup_only=False)) == 0
    assert command.call_args.kwargs["project_environment"] is False
    assert command.call_args.kwargs["extra_env"] == {"INCIDENT_OFFLINE": "1"}
