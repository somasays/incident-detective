"""Fresh configuration with shell overrides and tracing disabled before LangGraph imports."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

DEMO_ID = "incident-detective-v1"
ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
# Deliberately override inherited tracing configuration for this offline application.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGCHAIN_TRACING"] = "false"
os.environ["LANGSMITH_OTEL_ENABLED"] = "false"
os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"


def load_environment():
    """Reread the project file without polluting os.environ; explicit shell values win."""
    return {**{k: v for k, v in dotenv_values(ENV_FILE).items() if v is not None}, **os.environ}


def require_loopback(value: str, schemes: set[str]) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme not in schemes
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Only localhost endpoints without credentials or paths are allowed.")
    return value


@dataclass(frozen=True)
class Settings:
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = field(default="", repr=False)
    neo4j_database: str = "neo4j"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:14b-instruct"
    ollama_timeout_seconds: float = 90

    def __post_init__(self):
        require_loopback(self.neo4j_uri, {"bolt"})
        require_loopback(self.ollama_host, {"http"})
        if not 1 <= self.ollama_timeout_seconds <= 180:
            raise ValueError("OLLAMA_TIMEOUT_SECONDS must be between 1 and 180.")
        if "cloud" in self.ollama_model.lower() or "/" in self.ollama_model:
            raise ValueError("Use a locally downloaded Ollama library model, not a cloud model.")

    @classmethod
    def from_env(cls):
        values = load_environment()
        return cls(
            neo4j_uri=values.get("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_username=values.get("NEO4J_USERNAME", "neo4j"),
            neo4j_password=values.get("NEO4J_PASSWORD", ""),
            neo4j_database=values.get("NEO4J_DATABASE", "neo4j"),
            ollama_host=values.get("OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=values.get("OLLAMA_MODEL", "qwen2.5:14b-instruct"),
            ollama_timeout_seconds=float(values.get("OLLAMA_TIMEOUT_SECONDS", "90")),
        )
