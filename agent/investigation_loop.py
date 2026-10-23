"""A bounded, history-led hypothesis-testing StateGraph over typed Neo4j tools."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, perf_counter
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from knowledge.diagnostic_tools import (
    TOOL_DESCRIPTIONS,
    BudgetExhausted,
    DiagnosticTools,
    empty_package,
    merge_evidence,
    owned_evidence_ids,
)
from knowledge.temporal_queries import READ_DEADLINE, resolve_request


@dataclass(frozen=True)
class LoopLimits:
    max_hypotheses: int = 3
    max_checks: int = 8
    max_model_calls: int = 10
    max_hops: int = 3
    timeout_seconds: float = 180

    def __post_init__(self):
        if not (
            1 <= self.max_hypotheses <= 3
            and 1 <= self.max_checks <= 8
            and 1 <= self.max_model_calls <= 10
            and 0 <= self.max_hops <= 3
            and 1 <= self.timeout_seconds <= 180
        ):
            raise ValueError("Loop limits may reduce, but never exceed, the prototype budgets")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Candidate(StrictModel):
    id: str = Field(min_length=1, max_length=20)
    statement: str = Field(
        min_length=1,
        max_length=150,
        description="A short readable title, ideally under 12 words. "
        "Put details in expected_support.",
    )
    basis_evidence_ids: list[str] = Field(min_length=1, max_length=8)
    expected_support: str = Field(min_length=1, max_length=500)
    expected_refutation: str = Field(min_length=1, max_length=500)


class Check(StrictModel):
    tool: Literal[
        "expand_dependencies",
        "inspect_observations",
        "inspect_state_changes",
        "inspect_running_code",
    ]
    entity_ids: list[str] = Field(min_length=1, max_length=3)
    hypothesis_ids: list[str] = Field(min_length=1, max_length=3)
    question: str = Field(min_length=1, max_length=500)


class Plan(StrictModel):
    symptom_status: Literal["observed", "not_observed", "insufficient_data"]
    summary: str = Field(min_length=1, max_length=1000)
    hypotheses: list[Candidate] = Field(max_length=3)
    next_check: Check | None


class Assessment(StrictModel):
    hypothesis_id: str
    status: Literal["supported", "refuted", "unresolved"]
    finding_level: Literal["symptom", "propagation", "mechanism"] = Field(
        description="Symptom: reported effect. Propagation: where the effect came from, but its "
        "trigger is unresolved. Mechanism: evidence explains why the initiating resource degraded."
    )
    cause_entity_id: str | None
    explanation: str = Field(min_length=1, max_length=1500)
    supporting_evidence_ids: list[str] = Field(max_length=12)
    contradicting_evidence_ids: list[str] = Field(max_length=8)
    current_evidence_ids: list[str] = Field(max_length=8)
    metric_evidence_ids: list[str] = Field(max_length=6)
    mechanism_evidence_ids: list[str] = Field(max_length=6)
    missing_evidence: list[str] = Field(max_length=6)
    next_verification: str = Field(min_length=1, max_length=500)


class Evaluation(StrictModel):
    summary: str = Field(min_length=1, max_length=1000)
    assessments: list[Assessment] = Field(min_length=1, max_length=3)
    new_hypotheses: list[Candidate] = Field(max_length=3)
    next_check: Check | None
    next_action_reason: str = Field(min_length=1, max_length=600)
    limitations: list[str] = Field(min_length=1, max_length=6)


class LoopState(TypedDict, total=False):
    question: str
    options: dict
    request: dict
    package: dict
    topology: dict
    signals: list[dict]
    precedents: list[dict]
    plan: dict
    candidates: list[dict]
    assessments: list[dict]
    pending_check: dict | None
    last_check: dict
    check_history: list[dict]
    evaluation_history: list[dict]
    stages: list[dict]
    model_calls: int
    checks: int
    deadline: float
    stop_reason: str
    error: str
    status: str
    analysis: dict
    latest_summary: str
    decision_reason: str
    assessment_limitations: list[str]
    coverage_review_done: bool


def check_signature(check):
    return json.dumps([check["tool"], sorted(set(check["entity_ids"]))], separators=(",", ":"))


class DecisionBudgetExhausted(BudgetExhausted):
    def __init__(self, message, calls):
        super().__init__(message)
        self.calls = calls


def validate_check(check, candidates, package):
    if check is None:
        return
    ids = [h["id"] for h in candidates]
    if not set(check["hypothesis_ids"]) <= set(ids):
        raise ValueError("Check names an unknown hypothesis")
    known = {n["id"] for n in package["topology"]["nodes"]}
    if not set(check["entity_ids"]) <= known:
        raise ValueError(
            "Check targets an undiscovered resource; expand a connected dependency first"
        )
    if len(set(check["entity_ids"])) != len(check["entity_ids"]):
        raise ValueError("Check repeats resource IDs")


def validate_candidates(candidates, package, maximum):
    if len(candidates) > maximum or len({h["id"] for h in candidates}) != len(candidates):
        raise ValueError("Hypothesis IDs must be unique and within the hypothesis budget")
    for hypothesis in candidates:
        if not set(hypothesis["basis_evidence_ids"]) <= package["index"].keys():
            raise ValueError("Hypothesis basis contains an unretrieved evidence ID")


def compact_context(package):
    from agent.temporal import model_context

    context = model_context(package)
    context["precedents"] = package.get("precedents", [])
    context["known_resource_ids"] = [n["id"] for n in package["topology"]["nodes"]]
    return context


def decision_history(state):
    """Keep operational evidence intact; deduplicate prior model/transport bookkeeping.

    Query logs remain in the full package. The model already sees the selected IDs,
    tool contracts, result counts and actual source records, so repeating query
    parameters and multiple overlapping citation arrays wastes its input budget.
    """
    checks = [
        {k: v for k, v in check.items() if k not in {"queries", "coverage"}}
        for check in state["check_history"]
    ]
    assessments = [
        {
            **{
                k: a[k]
                for k in [
                    "hypothesis_id",
                    "status",
                    "finding_level",
                    "cause_entity_id",
                    "explanation",
                    "missing_evidence",
                ]
            },
            "evidence_ids": sorted(
                {
                    eid
                    for field in [
                        "supporting_evidence_ids",
                        "contradicting_evidence_ids",
                        "current_evidence_ids",
                        "metric_evidence_ids",
                        "mechanism_evidence_ids",
                    ]
                    for eid in a[field]
                }
            ),
        }
        for a in state["assessments"]
    ]
    return {"checks_performed": checks, "previous_assessments": assessments}


POLICY = (Path(__file__).with_name("skills") / "temporal-diagnosis" / "SKILL.md").read_text()


def structured_decision(reasoner, model, payload, state, limits, validator):
    """One invalid-output retry, counted against the shared call and wall-clock budgets."""
    schema = model.model_json_schema()
    resource_ids = [n["id"] for n in state["package"]["topology"]["nodes"]]
    evidence_ids = sorted(state["package"]["index"])
    defs = schema.get("$defs", {})
    if "Check" in defs:
        defs["Check"]["properties"]["entity_ids"]["items"] = {
            "type": "string",
            "enum": resource_ids,
        }
    if "Candidate" in defs:
        defs["Candidate"]["properties"]["basis_evidence_ids"]["items"] = {
            "type": "string",
            "enum": evidence_ids,
        }
    if "Assessment" in defs:
        hypothesis_ids = [h["id"] for h in state.get("candidates", [])]
        defs["Assessment"]["properties"]["hypothesis_id"] = {
            "type": "string",
            "enum": hypothesis_ids,
        }
        schema["properties"]["assessments"]["minItems"] = len(hypothesis_ids)
        schema["properties"]["assessments"]["maxItems"] = len(hypothesis_ids)
        schema["properties"]["new_hypotheses"]["maxItems"] = limits.max_hypotheses - len(
            hypothesis_ids
        )
        for key in [
            "supporting_evidence_ids",
            "contradicting_evidence_ids",
            "current_evidence_ids",
        ]:
            defs["Assessment"]["properties"][key]["items"] = {
                "type": "string",
                "enum": evidence_ids,
            }
        current = current_evidence_ids(state["package"])
        if current:
            defs["Assessment"]["properties"]["current_evidence_ids"]["items"] = {
                "type": "string",
                "enum": sorted(current),
            }
        else:
            defs["Assessment"]["properties"]["current_evidence_ids"]["maxItems"] = 0
        defs["Assessment"]["properties"]["cause_entity_id"] = {
            "anyOf": [{"type": "string", "enum": resource_ids}, {"type": "null"}]
        }
        metrics = [
            o["id"] for o in state["package"]["observations"] if o.get("kind") == "metric_window"
        ]
        for key, ids in [
            ("metric_evidence_ids", metrics),
            ("mechanism_evidence_ids", current),
        ]:
            if ids:
                defs["Assessment"]["properties"][key]["items"] = {
                    "type": "string",
                    "enum": sorted(ids),
                }
            else:
                defs["Assessment"]["properties"][key]["maxItems"] = 0
    content = json.dumps(payload, separators=(",", ":"))
    if len(content.encode()) > 60_000:
        raise BudgetExhausted("Model context exceeds the 60 KB input budget")
    messages = [{"role": "system", "content": POLICY}, {"role": "user", "content": content}]
    calls = 0
    error = "Invalid structured decision"
    for _ in range(2):
        remaining = state["deadline"] - monotonic()
        if state.get("model_calls", 0) + calls >= limits.max_model_calls or remaining < 2:
            raise DecisionBudgetExhausted("Model-call or investigation-time budget reached", calls)
        calls += 1
        try:
            reasoner.check_model()
            raw = reasoner.generate(messages, schema, timeout_seconds=min(60, remaining - 1))
            decision = model.model_validate_json(raw).model_dump()
            validator(decision)
            return decision, calls, None
        except (ValueError, TypeError) as exc:
            error = str(exc)[:500]
            if "raw" in locals():
                messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": "Decision rejected: "
                    + error
                    + ". Correct the decision using only supplied evidence and tools.",
                }
            )
        except Exception as exc:
            return None, calls, f"Model unavailable ({type(exc).__name__}): {str(exc)[:300]}"
    return None, calls, error


def current_evidence_ids(package):
    """Scope citations by retrieval provenance, never by diagnostic meaning or error names.

    The model assigns evidence roles. This function cannot determine whether a record
    explains a cause: it only excludes prior-incident context from current evidence.
    """
    records = {
        r["id"]
        for key in ["observations", "states", "changes", "runningReleases"]
        for r in package[key]
    }
    records |= {
        e["target"]
        for e in package["graph"]["edges"]
        if e["type"] == "INCLUDES" and e["source"] in records
    }
    return records


def build_hypothesis_loop(repository, reasoner, limits=None, tools=None):
    limits = limits or LoopLimits()
    tools = tools or DiagnosticTools(repository)

    def resolve(state):
        request = resolve_request(
            state["question"], repository.catalog(), **state.get("options", {})
        )
        return {
            "request": request,
            "package": empty_package(request),
            "checks": 0,
            "model_calls": 0,
            "check_history": [],
            "candidates": [],
            "assessments": [],
            "evaluation_history": [],
            "coverage_review_done": False,
        }

    def context(state):
        topology = repository.topology(state["request"], max_depth=min(1, limits.max_hops))
        package = merge_evidence(state["package"], {"graph": topology})
        package["topology"] = topology
        return {"package": package, "topology": topology}

    def observe(state):
        ids = [state["request"]["rootId"]]
        if state["request"]["rootLabel"] == "System":
            ids.extend(
                e["source"]
                for e in state["topology"]["edges"]
                if e["type"] == "PART_OF" and e["target"] == state["request"]["rootId"]
            )
        rows = repository.observe_target(state["request"], ids)
        observations = [r["observation"] for r in rows]
        addition = {
            "observations": observations,
            "graph": {"nodes": observations, "edges": [r["edge"] for r in rows]},
        }
        return {"signals": rows, "package": merge_evidence(state["package"], addition)}

    def history(state):
        matches = repository.find_precedents(state["request"], state["topology"], state["signals"])
        nodes, edges = [], []
        for match in matches:
            nodes.extend([match["incident"], match["finding"], match["cause"]])
            edges.extend([match["explains"], match["attribution"]])
        package = merge_evidence(state["package"], {"graph": {"nodes": nodes, "edges": edges}})
        package["precedents"] = matches
        package["historicalFindings"] = [
            {"incident": m["incident"], "finding": m["finding"]} for m in matches
        ]
        return {"precedents": matches, "package": package}

    def propose(state):
        def validate(plan):
            validate_candidates(plan["hypotheses"], state["package"], limits.max_hypotheses)
            validate_check(plan["next_check"], plan["hypotheses"], state["package"])
            if plan["hypotheses"] and plan["next_check"] is None:
                raise ValueError("Provisional hypotheses require a current evidence check")
            if not plan["hypotheses"] and plan["next_check"] is not None:
                raise ValueError("A check must test an actual hypothesis")
            if plan["symptom_status"] == "observed" and not plan["hypotheses"]:
                raise ValueError("An observed symptom needs a provisional hypothesis and a check")
            if plan["symptom_status"] == "not_observed" and not state["signals"]:
                raise ValueError("Missing observations mean insufficient_data, not healthy state")

        plan, calls, error = structured_decision(
            reasoner,
            Plan,
            {
                "task": "Form provisional hypotheses and choose the first discriminating check.",
                "context": compact_context(state["package"]),
                "tools": TOOL_DESCRIPTIONS,
            },
            state,
            limits,
            validate,
        )
        if error:
            return {"error": error, "model_calls": state["model_calls"] + calls}
        return {
            "plan": plan,
            "candidates": plan["hypotheses"],
            "pending_check": plan["next_check"],
            "latest_summary": plan["summary"],
            "model_calls": state["model_calls"] + calls,
        }

    def select(state):
        check = state.get("pending_check")
        if check is None:
            return {"stop_reason": state.get("decision_reason", "No further check requested")}
        reason = None
        if state["checks"] >= limits.max_checks:
            reason = (
                "Eight-check budget reached" if limits.max_checks == 8 else "Check budget reached"
            )
        elif state["model_calls"] >= limits.max_model_calls:
            reason = "Model-call budget reached"
        elif monotonic() + 25 > state["deadline"]:
            reason = "Investigation deadline reached"
        elif check_signature(check) in {check_signature(c) for c in state["check_history"]}:
            reason = "Repeated evidence check rejected; existing results are preserved"
        return {"stop_reason": reason} if reason else {"stop_reason": ""}

    def execute(state):
        check = state["pending_check"]
        addition = tools.execute(
            check["tool"], check["entity_ids"], state["package"], state["deadline"], limits.max_hops
        )
        package = merge_evidence(state["package"], addition)
        if check["tool"] == "expand_dependencies":
            topology = deepcopy(package["topology"])
            for kind in ["nodes", "edges"]:
                entries = {n["id"]: n for n in topology[kind]}
                entries.update({n["id"]: n for n in addition["graph"][kind]})
                topology[kind] = list(entries.values())
            package["topology"] = topology
        record = {
            **check,
            "id": f"check-{state['checks'] + 1}",
            "evidence_ids": addition.get("evidenceIds", []),
            "result": {
                "observations": len(addition["observations"]),
                "states": len(addition["states"]),
                "changes": len(addition["changes"]),
                "releases": len(addition["runningReleases"]),
                "nodes": len(addition["graph"]["nodes"]),
            },
            "queries": addition.get("queries", []),
            "coverage": addition.get("coverage", {}),
            "new_resource_ids": [
                n["id"]
                for n in addition["graph"]["nodes"]
                if n["id"] not in {known["id"] for known in state["package"]["topology"]["nodes"]}
            ]
            if check["tool"] == "expand_dependencies"
            else [],
        }
        return {
            "package": package,
            "topology": package["topology"],
            "last_check": record,
            "check_history": [*state["check_history"], record],
            "checks": state["checks"] + 1,
            **({"error": addition["error"]} if addition.get("error") else {}),
            **({"stop_reason": addition["stopReason"]} if addition.get("stopReason") else {}),
        }

    def assess(state, *, review=False):
        def validate(decision):
            candidates = [*state["candidates"], *decision["new_hypotheses"]]
            validate_candidates(candidates, state["package"], limits.max_hypotheses)
            ids = {h["id"] for h in state["candidates"]}
            assessments = decision["assessments"]
            if {a["hypothesis_id"] for a in assessments} != ids or len(assessments) != len(ids):
                raise ValueError("Assess each existing ID exactly once: " + ", ".join(sorted(ids)))
            new_ids = {h["id"] for h in decision["new_hypotheses"]}
            if new_ids and (
                decision["next_check"] is None
                or not new_ids <= set(decision["next_check"]["hypothesis_ids"])
            ):
                raise ValueError("New hypotheses must be assigned to the next evidence check")
            current = current_evidence_ids(state["package"])
            runtime = {n["id"] for n in state["package"]["topology"]["nodes"]}
            for assessment in assessments:
                refs = [
                    *assessment["supporting_evidence_ids"],
                    *assessment["contradicting_evidence_ids"],
                    *assessment["current_evidence_ids"],
                    *assessment["metric_evidence_ids"],
                    *assessment["mechanism_evidence_ids"],
                ]
                if not set(refs) <= state["package"]["index"].keys():
                    raise ValueError("Assessment cites unretrieved evidence")
                if not set(assessment["current_evidence_ids"]) <= current:
                    raise ValueError("A prior finding is not current confirming evidence")
                metrics = {
                    o["id"]
                    for o in state["package"]["observations"]
                    if o.get("kind") == "metric_window"
                }
                if not set(assessment["metric_evidence_ids"]) <= metrics:
                    raise ValueError("Metric citations must refer to actual metric observations")
                if not set(assessment["mechanism_evidence_ids"]) <= current:
                    raise ValueError("Mechanism citations must be retrieved current evidence")
                if assessment["status"] in {"supported", "refuted"}:
                    if not assessment["current_evidence_ids"]:
                        raise ValueError("Support/refutation requires current evidence IDs")
                if (
                    assessment["status"] == "refuted"
                    and not assessment["contradicting_evidence_ids"]
                ):
                    raise ValueError("Refutation requires contradictory evidence, not missing data")
                if (
                    assessment["status"] == "supported"
                    and assessment["cause_entity_id"] not in runtime
                ):
                    raise ValueError("Supported cause must be a discovered runtime resource")
                if (
                    assessment["status"] == "supported"
                    and assessment["finding_level"] == "mechanism"
                ):
                    if not assessment["mechanism_evidence_ids"]:
                        raise ValueError(
                            "A mechanism assessment requires citations to current evidence"
                        )
                    if metrics and not assessment["metric_evidence_ids"]:
                        raise ValueError(
                            "A mechanism hypothesis must cite its actual metric observations"
                        )
                    if not set(assessment["mechanism_evidence_ids"]) & owned_evidence_ids(
                        state["package"], assessment["cause_entity_id"]
                    ):
                        raise ValueError(
                            "Mechanism evidence must belong to its cause entity. "
                            "Choose the resource linked to the cited records."
                        )
                if assessment["status"] == "supported" and assessment[
                    "next_verification"
                ].strip().lower() in {"n/a", "none", "na"}:
                    raise ValueError("Provide a concrete independent verification, not N/A")
            validate_check(decision["next_check"], candidates, state["package"])
            if decision["next_check"] and check_signature(decision["next_check"]) in {
                check_signature(c) for c in state["check_history"]
            }:
                raise ValueError(
                    "This check already ran; use its returned evidence. Choose a different "
                    "check, or stop with the supported findings and unresolved gaps."
                )

        decision, calls, error = structured_decision(
            reasoner,
            Evaluation,
            {
                "task": (
                    "Review the proposed stopping decision. The last check discovered new "
                    "resources but did not inspect their observations, configuration or code. "
                    "Earlier empty queries for another owner say nothing about these resources. "
                    "Decide whether they could resolve the underlying trigger. Choose a typed "
                    "check if useful, or explain why stopping is justified. An upstream slowdown "
                    "with an unresolved trigger is propagation, not a complete root mechanism."
                )
                if review
                else (
                    "Evaluate the check result, update hypotheses, then choose a new check "
                    "or stop. Do not present an intermediate symptom as a verified trigger."
                ),
                "context": compact_context(state["package"]),
                "hypotheses": state["candidates"],
                **decision_history(state),
                "newly_discovered_resource_ids": state.get("last_check", {}).get(
                    "new_resource_ids", []
                ),
                "remaining_checks": limits.max_checks - state["checks"],
                "unchecked_resource_ids_by_tool": {
                    tool: sorted(
                        {n["id"] for n in state["package"]["topology"]["nodes"]}
                        - {
                            e
                            for c in state["check_history"]
                            if c["tool"] == tool
                            for e in c["entity_ids"]
                        }
                    )
                    for tool in TOOL_DESCRIPTIONS
                },
                "tools": TOOL_DESCRIPTIONS,
            },
            state,
            limits,
            validate,
        )
        if error:
            return {"error": error, "model_calls": state["model_calls"] + calls}
        return {
            "candidates": [*state["candidates"], *decision["new_hypotheses"]],
            "assessments": decision["assessments"],
            "pending_check": decision["next_check"],
            "latest_summary": decision["summary"],
            "decision_reason": decision["next_action_reason"],
            "assessment_limitations": decision["limitations"],
            "model_calls": state["model_calls"] + calls,
            "evaluation_history": [
                *state["evaluation_history"],
                {**decision, "check_id": state["last_check"]["id"]},
            ],
        }

    def review_coverage(state):
        return {**assess(state, review=True), "coverage_review_done": True, "stop_reason": ""}

    def diagnosis(state):
        candidates = {h["id"]: h for h in state["candidates"]}
        supported = [
            a
            for a in state["assessments"]
            if a["status"] == "supported" and a["finding_level"] == "mechanism"
        ]
        analysis = {
            "summary": state.get("latest_summary", "No diagnostic conclusion available."),
            "hypotheses": [],
            "limitations": [
                *state["package"]["limitations"],
                *state.get("assessment_limitations", []),
            ],
        }
        for assessment in supported:
            refs = list(
                dict.fromkeys(
                    [
                        *assessment["supporting_evidence_ids"],
                        *assessment["current_evidence_ids"],
                        *assessment["metric_evidence_ids"],
                        *assessment["mechanism_evidence_ids"],
                    ]
                )
            )
            analysis["hypotheses"].append(
                {
                    "rank": len(analysis["hypotheses"]) + 1,
                    "title": candidates[assessment["hypothesis_id"]]["statement"],
                    "explanation": assessment["explanation"],
                    "cause_entity_id": assessment["cause_entity_id"],
                    "supporting_evidence_ids": refs,
                    "contradicting_or_missing_evidence": assessment["missing_evidence"]
                    or ["The inferred mechanism still requires independent verification."],
                    "next_check": assessment["next_verification"],
                }
            )
        reason = state.get("stop_reason", "")
        budget = any(word in reason.lower() for word in ["budget", "deadline", "repeated"])
        status = "incomplete" if budget else "complete" if supported else "insufficient_evidence"
        if (
            not state["candidates"]
            and state.get("plan", {}).get("symptom_status") == "not_observed"
        ):
            status = "symptom_not_observed"
        elif not supported:
            analysis["summary"] = (
                "This investigation did not establish a supported root-cause mechanism. "
                "The hypothesis assessments retain contributing symptoms, contradictions and gaps."
            )
        if reason:
            analysis["limitations"].insert(0, reason)
        analysis["limitations"] = list(dict.fromkeys(analysis["limitations"]))[:6]
        return {"analysis": analysis, "status": status}

    def validate(state):
        from agent.temporal import validate_temporal_analysis

        return {"analysis": validate_temporal_analysis(state["analysis"], state["package"])}

    def finish(state):
        package = deepcopy(state.get("package", empty_package(state.get("request", {}))))
        failed = bool(state.get("error"))
        package.update(
            analysis={} if failed else state.get("analysis", {}),
            analysisAvailable=not failed and bool(state.get("analysis")),
            status="unavailable" if failed else state.get("status", "insufficient_evidence"),
            error=state.get("error"),
            stopReason=state.get("stop_reason"),
            hypothesisTests=[
                {
                    **h,
                    "checks": [
                        c for c in state.get("check_history", []) if h["id"] in c["hypothesis_ids"]
                    ],
                    "assessments": [
                        a
                        for e in state.get("evaluation_history", [])
                        for a in e["assessments"]
                        if a["hypothesis_id"] == h["id"]
                    ],
                }
                for h in state.get("candidates", [])
            ],
            checks=state.get("check_history", []),
            evaluations=state.get("evaluation_history", []),
            budgets={
                "checksUsed": state.get("checks", 0),
                "maxChecks": limits.max_checks,
                "modelCallsUsed": state.get("model_calls", 0),
                "maxModelCalls": limits.max_model_calls,
                "maxDependencyHops": limits.max_hops,
                "timeoutSeconds": limits.timeout_seconds,
            },
            queryTrace=deepcopy(repository.trace),
            stages=state.get("stages", []),
        )
        package["investigationId"] = hashlib.sha256(
            json.dumps(package, sort_keys=True).encode()
        ).hexdigest()[:16]
        return {"package": package}

    functions = {
        "resolve_question": resolve,
        "get_system_context": context,
        "observe_target": observe,
        "find_similar_incidents": history,
        "form_hypotheses": propose,
        "choose_next_check": select,
        "execute_check": execute,
        "evaluate_hypotheses": assess,
        "review_coverage": review_coverage,
        "build_diagnosis": diagnosis,
        "validate_diagnosis": validate,
        "finalize": finish,
    }
    linear = {
        "resolve_question": "get_system_context",
        "get_system_context": "observe_target",
        "observe_target": "find_similar_incidents",
        "find_similar_incidents": "form_hypotheses",
        "form_hypotheses": "choose_next_check",
        "choose_next_check": "execute_check",
        "execute_check": "evaluate_hypotheses",
        "evaluate_hypotheses": "choose_next_check",
        "review_coverage": "choose_next_check",
        "build_diagnosis": "validate_diagnosis",
        "validate_diagnosis": "finalize",
    }

    def route(name, state):
        if state.get("error"):
            return "finalize"
        if (
            name == "choose_next_check"
            and not state.get("pending_check")
            and state.get("last_check", {}).get("new_resource_ids")
            and not state.get("coverage_review_done")
            and state["checks"] < limits.max_checks
            and state["model_calls"] < limits.max_model_calls
            and monotonic() + 25 < state["deadline"]
        ):
            return "review_coverage"
        if state.get("stop_reason") and name not in {"build_diagnosis", "validate_diagnosis"}:
            return "build_diagnosis"
        if name == "choose_next_check" and (
            state.get("stop_reason") or not state.get("pending_check")
        ):
            return "build_diagnosis"
        if name == "execute_check" and state.get("stop_reason"):
            return "build_diagnosis"
        return linear[name]

    builder = StateGraph(LoopState)
    for name, function in functions.items():

        def instrument(state, name=name, function=function):
            started = perf_counter()
            deadline = (
                monotonic() + limits.timeout_seconds
                if name == "resolve_question"
                else state["deadline"]
            )
            token = READ_DEADLINE.set(deadline)
            try:
                update = function(state)
            except (BudgetExhausted, TimeoutError) as exc:
                update = {"stop_reason": str(exc)}
                if isinstance(exc, DecisionBudgetExhausted):
                    update["model_calls"] = state.get("model_calls", 0) + exc.calls
            except Exception as exc:
                update = {"error": f"{type(exc).__name__}: {str(exc)[:600]}"}
            finally:
                READ_DEADLINE.reset(token)
            merged = {**state, **update}
            next_name = "END" if name == "finalize" else route(name, merged)
            event = {
                "stage": name,
                "purpose": name.replace("_", " "),
                "status": "failed"
                if update.get("error")
                else "stopped"
                if update.get("stop_reason")
                else "complete",
                "elapsedMs": round((perf_counter() - started) * 1000),
                "next": next_name,
            }
            if name == "execute_check" and update.get("last_check"):
                event.update(
                    hypothesisIds=update["last_check"]["hypothesis_ids"],
                    check=deepcopy(update["last_check"]),
                )
            if name in {"evaluate_hypotheses", "review_coverage"} and update.get("assessments"):
                event.update(assessments=update["assessments"], reason=update["decision_reason"])
            stages = [*state.get("stages", []), event]
            if name == "finalize" and "package" in update:
                update["package"]["stages"] = stages
            return {**update, "deadline": deadline, "stages": stages}

        builder.add_node(name, instrument)
    builder.add_edge(START, "resolve_question")
    for name in linear:
        targets = {linear[name], "finalize"}
        if name == "choose_next_check":
            targets.add("review_coverage")
        if name not in {"build_diagnosis", "validate_diagnosis"}:
            targets.add("build_diagnosis")
        builder.add_conditional_edges(
            name, lambda s, name=name: route(name, s), {n: n for n in targets}
        )
    builder.add_edge("finalize", END)
    return builder.compile().with_config({"recursion_limit": 64})
