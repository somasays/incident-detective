"""Temporal model transports, evidence context and grounding validation.

The bounded hypothesis loop owns orchestration and retries. These transports only
perform structured generation; no parallel one-shot investigation path lives here.
"""

import json
import re
from time import monotonic

from agent.reasoning import AnalysisUnavailable, InvestigationAnalysis, OllamaReasoner


def validate_numerical_claims(text, cited, measurements):
    """Apply the same grounding check to compact summaries and full narratives."""

    def numeric_values(value):
        if isinstance(value, dict):
            return [n for v in value.values() for n in numeric_values(v)]
        if isinstance(value, list):
            return [n for v in value for n in numeric_values(v)]
        return [value] if type(value) in {int, float} else []

    known = json.dumps(cited) + json.dumps(measurements)
    text = re.sub(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b", lambda m: m[0].replace(",", ""), text)
    numbers = re.findall(r"(?<![\w:-])\d+(?:\.\d+)?", text)
    source_numbers = numeric_values([cited, measurements])
    for number in numbers:
        if not re.search(r"(?<![\d.])" + re.escape(number) + r"(?![\d.])", known):
            # Display rounding (19.4118x -> 19.41x) preserves the stored calculation.
            places = len(number.split(".")[1]) if "." in number else None
            if places is None or not any(round(n, places) == float(number) for n in source_numbers):
                raise ValueError(f"Narrative contains an unsupported numerical value: {number}")


def validate_temporal_analysis(raw, package):
    analysis = InvestigationAnalysis.model_validate(raw)
    if [h.rank for h in analysis.hypotheses] != list(range(1, len(analysis.hypotheses) + 1)):
        raise ValueError("Ranks must be consecutive and unique")
    eligible = {
        n["id"]
        for n in package["graph"]["nodes"]
        if n["label"]
        in {"Component", "StorageVolume", "K8sCluster", "K8sWorkload", "Change", "Deployment"}
    }
    for h in analysis.hypotheses:
        if not set(h.supporting_evidence_ids) <= package["index"].keys():
            raise ValueError("Nonexistent evidence citation")
        if h.cause_entity_id is not None and h.cause_entity_id not in eligible:
            raise ValueError("Unretrieved cause entity")
        if h.cause_entity_id is None:
            raise ValueError("A ranked hypothesis must identify a retrieved suspected entity")
        metric_ids = {
            o["id"] for o in package.get("observations", []) if o.get("kind") == "metric_window"
        }
        if metric_ids and not metric_ids.intersection(h.supporting_evidence_ids):
            raise ValueError("A hypothesis interpreting metrics must cite a metric observation")
        cited = [package["index"][eid] for eid in h.supporting_evidence_ids]
        # Code is owned through resource -> running release -> included commit/artifact.
        # Bound support traversal to ownership links; a dependency alone does not prove a cause.
        reached = {h.cause_entity_id}
        for _ in range(2):
            reached |= {
                e["target"] if e["source"] in reached else e["source"]
                for e in package["graph"].get("edges", [])
                if e["type"]
                in {
                    "OBSERVED_ON",
                    "HAS_STATE",
                    "APPLIED_TO",
                    "CHANGED",
                    "RUNNING_RELEASE",
                    "INCLUDES",
                }
                and (e["source"] in reached or e["target"] in reached)
            }
        directly_linked = bool(reached.intersection(h.supporting_evidence_ids))
        if h.cause_entity_id and h.cause_entity_id not in json.dumps(cited) and not directly_linked:
            raise ValueError("Cause must be supported by a cited record or relationship")
        validate_numerical_claims(h.title + " " + h.explanation, cited, package["measurements"])
    claims = json.dumps(raw)
    if re.search(r"\b(?:proven|definitive|confirmed current) (?:root )?cause\b", claims, re.I):
        raise ValueError("Analysis asserts a proven current cause")
    return analysis.model_dump()


def model_context(package):
    """Expose retrieved records without a second, scenario-specific property whitelist.

    The repository applies ontology and time scope. The caller enforces the input-size
    budget; an unfamiliar configuration field or error message must remain interpretable.
    """
    return {
        "request": package["request"],
        "topology": {
            "nodes": package["topology"]["nodes"],
            "relationships": package["topology"]["edges"],
        },
        "evidence_relationships": package["graph"]["edges"],
        "measurements": package["measurements"],
        "observations": package["observations"],
        "states": package["states"],
        "changes": package["changes"],
        "runningReleases": package["runningReleases"],
        "code": [n for n in package["graph"]["nodes"] if n["label"] in {"Commit", "CodeArtifact"}],
        "historicalFindings": package["historicalFindings"],
        "limitations": package["limitations"],
    }


class _BoundedMetadataClient:
    """Give each local metadata request only the time left in verification."""

    def __init__(self, settings, timeout_seconds):
        self.settings = settings
        self.deadline = monotonic() + timeout_seconds

    def _call(self, method, *args):
        from ollama import Client

        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Local model verification exceeded the investigation budget")
        client = Client(
            host=self.settings.ollama_host,
            timeout=min(self.settings.ollama_timeout_seconds, remaining),
            trust_env=False,
            follow_redirects=False,
        )
        try:
            return getattr(client, method)(*args)
        finally:
            client.close()

    def list(self):
        return self._call("list")

    def show(self, model):
        return self._call("show", model)


class TemporalReasoner(OllamaReasoner):
    def check_model_with_budget(self, timeout_seconds):
        """Verify installed local weights once per reasoner, within the remaining time."""
        if getattr(self, "_model_verified", False):
            return
        metadata = _BoundedMetadataClient(self.settings, timeout_seconds)
        OllamaReasoner(self.settings, client=metadata).check_model()
        self._model_verified = True

    def generate(self, messages, schema, timeout_seconds=None):
        from ollama import Client

        bounded_client = (
            Client(
                host=self.settings.ollama_host,
                timeout=min(self.settings.ollama_timeout_seconds, timeout_seconds),
                trust_env=False,
                follow_redirects=False,
            )
            if timeout_seconds
            else None
        )
        try:
            response = (bounded_client or self.client).chat(
                model=self.settings.ollama_model,
                messages=messages,
                format=schema,
                think=False,
                stream=False,
                keep_alive="10m",
                options={"temperature": 0, "num_predict": 1100, "num_ctx": 12288, "seed": 7},
            )
            return response.message.content
        finally:
            if bounded_client:
                bounded_client.close()


class OpenAITemporalReasoner(TemporalReasoner):
    """Same evidence, schema and validator; an explicitly configured compatible endpoint."""

    def __init__(self, settings, client=None):
        self.model_settings = settings
        self.client = client

    def check_model(self):
        self.model_settings.validate()

    def check_model_with_budget(self, timeout_seconds):
        # Provider validation is local and still checks the offline guard on every call.
        self.check_model()

    def generate(self, messages, schema, timeout_seconds=None):
        import httpx
        import openai

        settings = self.model_settings
        client = self.client or openai.OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout,
            max_retries=0,
            http_client=httpx.Client(
                trust_env=False, follow_redirects=False, timeout=settings.timeout
            ),
        )
        try:
            # GPT-5 mini's API contract differs from GPT-4o: completion tokens include
            # reasoning, and custom temperature is unsupported. No diagnostic behavior
            # depends on which provider/model is selected.
            parameters = (
                {"max_completion_tokens": 4096, "reasoning_effort": "low"}
                if settings.model == "gpt-5-mini" or settings.model.startswith("gpt-5-mini-20")
                else {"max_tokens": 1800, "temperature": 0}
            )
            response = client.chat.completions.create(
                model=settings.model,
                messages=messages,
                **parameters,
                timeout=min(settings.timeout, timeout_seconds or settings.timeout),
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "incident_diagnosis", "strict": True, "schema": schema},
                },
            )
            choice = response.choices[0]
            if choice.finish_reason != "stop" or choice.message.refusal:
                raise AnalysisUnavailable("Model declined or exceeded the bounded output length.")
            return choice.message.content or ""
        except openai.APITimeoutError:
            raise AnalysisUnavailable(
                "Model endpoint timed out. Retrieved evidence is preserved."
            ) from None
        except openai.APIConnectionError:
            raise AnalysisUnavailable("Cannot reach the configured model endpoint.") from None
        except openai.APIStatusError as exc:
            # Server error bodies can contain sensitive headers or URLs; never display them.
            body = exc.body if isinstance(exc.body, dict) else {}
            details = body.get("error", body)
            code = details.get("code") if isinstance(details, dict) else None
            hints = {
                "inactive": "Open your GraphAcademy workshop lesson or click I'm still working.",
                "access-expired": "Renew access in the workshop AI access panel.",
                "throttled": "The workshop rate limit was reached; retry after a minute.",
                "rate_limit_exceeded": "The model rate limit was reached; retry after a minute.",
                "budget-exhausted": "The workshop token budget is exhausted.",
                "model-not-allowed": "Choose a model allowed by your workshop.",
            }
            if code in hints:
                raise AnalysisUnavailable(
                    f"Model request failed (HTTP {exc.status_code}, {code}). {hints[code]}"
                ) from None
            raise AnalysisUnavailable(
                f"Model request failed (HTTP {exc.status_code}). Check the endpoint, key, "
                "model name and JSON-schema support."
            ) from None
        finally:
            if self.client is None:
                client.close()
