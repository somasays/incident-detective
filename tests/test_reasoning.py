import copy
import json
from types import SimpleNamespace

import pytest
from ollama import Client

from agent.reasoning import AnalysisUnavailable, OllamaReasoner, validate_analysis
from config import Settings


def test_valid_analysis(valid_analysis, evidence):
    assert validate_analysis(valid_analysis, evidence).hypotheses[0].cause_entity_id == "deploy-014"


def test_namespaced_evidence_ids_are_validated_as_complete_ids(valid_analysis, evidence):
    replacements = {
        key: key.split(":", 1)[0] + ":inputs-test:source:" + key.split(":", 1)[1]
        for key in evidence["index"]
        if not key.startswith("PATH:")
    }
    evidence["index"] = {
        replacements.get(key, key): value for key, value in evidence["index"].items()
    }
    hypothesis = valid_analysis["hypotheses"][0]
    hypothesis["supporting_evidence_ids"] = [
        replacements.get(key, key) for key in hypothesis["supporting_evidence_ids"]
    ]
    assert validate_analysis(valid_analysis, evidence).hypotheses


def test_oversized_evidence_falls_back_before_model_inference(evidence):
    evidence["observed_symptoms"][0]["message"] = "x" * 40_000
    with pytest.raises(AnalysisUnavailable, match="input budget"):
        OllamaReasoner(client=object()).analyze(evidence)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda a: a["hypotheses"][0].update(supporting_evidence_ids=["DEPLOY:deploy-999"]),
        lambda a: a["hypotheses"][0].update(cause_entity_id="imaginary-service"),
        lambda a: a["hypotheses"].append(copy.deepcopy(a["hypotheses"][0])),
        lambda a: a.update(hypotheses=a["hypotheses"] * 4),
        lambda a: a["hypotheses"][0].update(rank=2),
        lambda a: a["hypotheses"][0].update(explanation="deploy-999 happened first."),
        lambda a: a["hypotheses"][0].update(explanation="The error occurred at 10:30."),
        lambda a: a["hypotheses"][0].update(explanation="An event at 2026-10-21T10:30:00Z."),
        lambda a: a["hypotheses"][0].update(explanation="This is the confirmed root cause."),
        lambda a: a["hypotheses"][0].update(explanation="It definitely caused the incident."),
        lambda a: a["hypotheses"][0].update(explanation="INC-999 proves this."),
        lambda a: a["hypotheses"][0].update(explanation="SYMPTOM:imaginary-error was observed."),
        lambda a: a["hypotheses"][0].update(cause_entity_id="deploy-009"),
        lambda a: a["hypotheses"][0].update(cause_entity_id="orders-api"),
        lambda a: a.update(unexpected_field=True),
        lambda a: a["hypotheses"][0].update(supporting_evidence_ids=[]),
        lambda a: a.update(summary=None),
    ],
)
def test_grounding_rejections(valid_analysis, evidence, mutation):
    mutation(valid_analysis)
    with pytest.raises(ValueError):
        validate_analysis(valid_analysis, evidence)


class FakeOllama:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def list(self):
        return SimpleNamespace(models=[SimpleNamespace(model="qwen2.5:14b-instruct")])

    def show(self, name):
        return SimpleNamespace(
            model_dump=lambda: {
                "details": {"parameter_size": "4B"},
                "modelfile": "FROM /local/models/blobs/sha256-" + "a" * 64,
            }
        )

    def chat(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(message=SimpleNamespace(content=response))


def test_structured_output_retry_once(valid_analysis, evidence):
    client = FakeOllama(["invalid", json.dumps(valid_analysis)])
    reasoner = OllamaReasoner(Settings(), client)
    output = reasoner.analyze(evidence)
    assert output["hypotheses"][0]["rank"] == 1
    assert len(client.calls) == 2
    assert client.calls[0]["format"]["type"] == "object"
    assert client.calls[0]["options"]["temperature"] == 0
    assert client.calls[0]["options"]["num_predict"] <= 2000
    assert client.calls[0]["think"] is False
    assert len(client.calls[1]["messages"]) == 3


def test_invalid_output_never_manufactures_success(evidence):
    client = FakeOllama(["{}", "{}"])
    with pytest.raises(AnalysisUnavailable, match="after two attempts"):
        OllamaReasoner(Settings(), client).analyze(evidence)
    assert len(client.calls) == 2


def test_timeout_does_not_retry(evidence):
    client = FakeOllama([TimeoutError("timeout")])
    with pytest.raises(AnalysisUnavailable, match="Evidence is preserved"):
        OllamaReasoner(Settings(), client).analyze(evidence)
    assert len(client.calls) == 1


def test_missing_model_never_calls_chat(evidence):
    client = FakeOllama([])
    client.list = lambda: SimpleNamespace(models=[])
    with pytest.raises(AnalysisUnavailable, match="not installed"):
        OllamaReasoner(Settings(), client).analyze(evidence)
    assert not client.calls


@pytest.mark.parametrize(
    "kwargs",
    [
        {"neo4j_uri": "bolt://example.com:7687"},
        {"neo4j_uri": "neo4j://localhost:7687"},
        {"ollama_host": "https://api.example.com"},
        {"ollama_host": "http://user:password@localhost:11434"},
        {"ollama_host": "http://localhost:11434/redirect"},
        {"ollama_model": "large:cloud"},
        {"ollama_timeout_seconds": 999},
    ],
)
def test_nonlocal_configuration_rejected(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)


def test_preflight_short_structured_response():
    client = FakeOllama(['{"ready":true}'])
    assert OllamaReasoner(Settings(), client).preflight()["structured_output"]


def test_remote_backed_model_rejected(evidence):
    client = FakeOllama([])
    client.show = lambda _: SimpleNamespace(
        model_dump=lambda: {
            "remote_model": "model",
            "remote_host": "https://ollama.com",
            "details": {"parameter_size": "4B"},
        }
    )
    with pytest.raises(AnalysisUnavailable, match="Remote-backed"):
        OllamaReasoner(Settings(), client).analyze(evidence)


def test_cause_must_be_supported_by_its_citations(valid_analysis, evidence):
    valid_analysis["hypotheses"][0].update(
        cause_entity_id="analytics-api", supporting_evidence_ids=["DEPLOY:deploy-014"]
    )
    with pytest.raises(ValueError, match="no support"):
        validate_analysis(valid_analysis, evidence)


def test_known_deployment_claim_requires_its_citation(valid_analysis, evidence):
    valid_analysis["hypotheses"][0].update(
        cause_entity_id="ingestion-pipeline", supporting_evidence_ids=["SYMPTOM:schema-error-104"]
    )
    with pytest.raises(ValueError, match="without citing"):
        validate_analysis(valid_analysis, evidence)


def test_short_timestamp_and_explicit_uncertainty_allowed(valid_analysis, evidence):
    valid_analysis["summary"] = "No confirmed root cause is available. Deployment at 10:38 UTC."
    valid_analysis["limitations"] = ["This is not a proven cause."]
    assert validate_analysis(valid_analysis, evidence)


def test_unverified_weights_rejected(evidence):
    client = FakeOllama([])
    client.show = lambda _: SimpleNamespace(
        model_dump=lambda: {
            "details": {"parameter_size": "4B"},
            "modelfile": "FROM remote-model:cloud",
        }
    )
    with pytest.raises(AnalysisUnavailable, match="local model weights"):
        OllamaReasoner(Settings(), client).analyze(evidence)


def test_official_ollama_sdk_request_contract(evidence, valid_analysis):
    import httpx

    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.host == "localhost"
        if request.url.path == "/api/tags":
            body = {"models": [{"model": "qwen2.5:14b-instruct"}]}
        elif request.url.path == "/api/show":
            body = {
                "details": {"parameter_size": "4B"},
                "model_info": {"general.architecture": "qwen3"},
                "modelfile": "FROM /local/models/blobs/sha256-" + "a" * 64,
            }
        else:
            assert request.url.path == "/api/chat"
            payload = json.loads(request.content)
            assert payload["stream"] is False
            assert payload["think"] is False
            hypothesis_schema = payload["format"]["$defs"]["Hypothesis"]["properties"]
            assert hypothesis_schema["supporting_evidence_ids"]["items"]["enum"] == sorted(
                evidence["index"]
            )
            assert payload["options"]["num_predict"] == 1800
            body = {
                "model": "qwen2.5:14b-instruct",
                "message": {"role": "assistant", "content": json.dumps(valid_analysis)},
                "done": True,
            }
        return httpx.Response(200, json=body)

    with Client(
        host="http://localhost:11434",
        transport=httpx.MockTransport(respond),
        trust_env=False,
        follow_redirects=False,
        timeout=1,
    ) as client:
        assert OllamaReasoner(Settings(), client).analyze(evidence) == valid_analysis
    assert [r.url.path for r in requests] == ["/api/tags", "/api/show", "/api/chat"]


def test_official_sdk_remote_metadata_cannot_masquerade_as_local_weights(evidence):
    import httpx

    def respond(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"model": "qwen2.5:14b-instruct"}]})
        assert request.url.path == "/api/show"  # Chat must never be invoked.
        return httpx.Response(
            200,
            json={
                "details": {"parameter_size": "4B"},
                "model_info": {},
                "modelfile": "FROM remote-server-model",
                "remote_host": "https://remote.example",
                "remote_model": "model",
            },
        )

    with Client(
        host="http://localhost:11434",
        transport=httpx.MockTransport(respond),
        trust_env=False,
        timeout=1,
    ) as client:
        with pytest.raises(AnalysisUnavailable, match="local model weights|Remote-backed"):
            OllamaReasoner(Settings(), client).analyze(evidence)
