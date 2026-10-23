"""Explicit model selection. Credentials stay on the Streamlit server."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

from agent.reasoning import AnalysisUnavailable


@dataclass(frozen=True)
class ModelSettings:
    provider: str = "ollama"
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    model: str = "gpt-5-mini"
    timeout: float = 90

    @classmethod
    def from_env(cls):
        # Read fresh on each investigation, so saving .env does not require a restart.
        values = {**os.environ, **dotenv_values(Path(__file__).resolve().parents[1] / ".env")}
        return cls(
            provider=(values.get("LLM_PROVIDER") or "ollama").strip().lower(),
            base_url=(values.get("OPENAI_BASE_URL") or "").strip().rstrip("/"),
            api_key=(values.get("OPENAI_API_KEY") or "").strip(),
            model=(values.get("OPENAI_MODEL") or "gpt-5-mini").strip(),
            timeout=float(values.get("OPENAI_TIMEOUT_SECONDS") or "90"),
        )

    def validate(self):
        if self.provider not in {"openai", "ollama"}:
            raise AnalysisUnavailable("Set LLM_PROVIDER to openai or ollama in .env.")
        if self.provider == "ollama":
            return
        missing = [
            key
            for key, value in [("OPENAI_BASE_URL", self.base_url), ("OPENAI_API_KEY", self.api_key)]
            if not value
        ]
        if missing:
            raise AnalysisUnavailable("Fill " + " and ".join(missing) + " in .env, then retry.")
        url = urlparse(self.base_url)
        local = url.hostname in {"127.0.0.1", "localhost", "::1"}
        if (
            not url.hostname
            or url.scheme not in ({"http", "https"} if local else {"https"})
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path.endswith(("/chat/completions", "/responses"))
        ):
            raise AnalysisUnavailable(
                "OPENAI_BASE_URL must be an HTTPS API base URL (usually ending /v1), "
                "without credentials, query parameters or /chat/completions."
            )
        if not self.model or not 1 <= self.timeout <= 180:
            raise AnalysisUnavailable("Set OPENAI_MODEL and a timeout between 1 and 180 seconds.")

    def public_status(self):
        if self.provider == "ollama":
            return "Ollama · local model"
        if self.provider != "openai":
            return "Model configuration needed"
        return f"{self.model} · " + (
            "endpoint configured" if self.base_url and self.api_key else "setup needed in .env"
        )


def get_temporal_reasoner(settings=None, client=None):
    from agent.temporal import OpenAITemporalReasoner, TemporalReasoner

    settings = settings or ModelSettings.from_env()
    if settings.provider == "ollama":
        return TemporalReasoner(client=client)
    return OpenAITemporalReasoner(settings, client=client)
