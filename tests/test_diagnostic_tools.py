"""Real temporal tools: narrow context, time-safe memory, incremental graph expansion."""

import os
from time import monotonic

import pytest

from knowledge.diagnostic_tools import (
    DiagnosticTools,
    empty_package,
    merge_evidence,
    runtime_depths,
)
from knowledge.mcp_db import Neo4jMCPDatabase
from knowledge.temporal_fixture import PREFIX
from knowledge.temporal_queries import TemporalRepository, resolve_request

LIVE = pytest.mark.skipif(os.getenv("RUN_NEO4J_TESTS") != "1", reason="Requires local Neo4j MCP")


@pytest.fixture(scope="module")
def mcp_repository():
    with Neo4jMCPDatabase() as database:
        yield TemporalRepository(database)


def context(repository, question="payments API at 3AM today", mode="known_then"):
    request = resolve_request(question, repository.catalog(), mode=mode)
    topology = repository.topology(request, max_depth=1)
    package = merge_evidence(empty_package(request), {"graph": topology})
    package["topology"] = topology
    return package


def expand(tools, package, ids):
    addition = tools.execute("expand_dependencies", ids, package, monotonic() + 180)
    assert "error" not in addition
    merged = merge_evidence(package, addition)
    graph = merged["graph"]
    runtime_ids = {
        n["id"]
        for n in graph["nodes"]
        if n["label"] in {"System", "Component", "K8sCluster", "K8sWorkload", "StorageVolume"}
    }
    merged["topology"] = {
        "nodes": [n for n in graph["nodes"] if n["id"] in runtime_ids],
        "edges": [
            e for e in graph["edges"] if e["source"] in runtime_ids and e["target"] in runtime_ids
        ],
        "paths": [],
    }
    return merged


@LIVE
@pytest.mark.integration
def test_context_and_history_do_not_preload_the_answer(mcp_repository):
    repository = mcp_repository
    package = context(repository)
    ids = {n["id"] for n in package["topology"]["nodes"]}
    assert PREFIX + "auth-service" in ids
    assert PREFIX + "auth-db" not in ids
    assert PREFIX + "auth-volume" not in ids
    signals = repository.observe_target(package["request"])
    assert all(row["observation"]["entityId"] == PREFIX + "payments-api" for row in signals)
    memories = repository.find_precedents(package["request"], package["topology"], signals)
    assert {m["incident"]["id"] for m in memories} == {PREFIX + "INC-184", PREFIX + "INC-187"}
    assert all(m["finding"]["id"] != PREFIX + "finding-201" for m in memories)
    assert all(row["tool"] != "state_history" for row in repository.trace)


@LIVE
@pytest.mark.integration
def test_selected_tools_incrementally_reach_storage_and_keep_replay_cutoff(mcp_repository):
    tools = DiagnosticTools(mcp_repository)
    package = context(mcp_repository)
    with pytest.raises(ValueError, match="currently connected"):
        tools.execute("inspect_state_changes", [PREFIX + "auth-volume"], package, monotonic() + 180)
    package = expand(tools, package, [PREFIX + "auth-service"])
    package = expand(tools, package, [PREFIX + "auth-db"])
    assert runtime_depths(package["topology"], package["request"])[PREFIX + "auth-db"] == 2
    for name in ["inspect_observations", "inspect_state_changes"]:
        addition = tools.execute(
            name, [PREFIX + "auth-db", PREFIX + "auth-volume"], package, monotonic() + 180
        )
        assert "error" not in addition
        package = merge_evidence(package, addition)
    assert PREFIX + "storage-17" in package["index"]
    assert PREFIX + "storage-18" not in package["index"]
    assert PREFIX + "late-storage-alert" not in package["index"]
    assert PREFIX + "notification-noise" not in package["index"]
    assert any(
        m["entityId"] == PREFIX + "auth-db" and m["incident"] == 78
        for m in package["measurements"]
        if m["metric"] == "db.io_wait"
    )
    assert all("recovery" not in m for m in package["measurements"])
    assert any(s.get("provisionedIops") == 300 for s in package["states"])
    assert all(q["transport"] == "neo4j-mcp/stdio" for q in mcp_repository.trace)


@LIVE
@pytest.mark.integration
def test_code_tool_retrieves_only_code_in_running_deployment(mcp_repository):
    tools = DiagnosticTools(mcp_repository)
    package = context(mcp_repository)
    addition = tools.execute(
        "inspect_running_code", [PREFIX + "payments-api"], package, monotonic() + 180
    )
    assert "error" not in addition
    ids = {n["id"] for n in addition["graph"]["nodes"]}
    assert PREFIX + "payments-r18-code" in ids
    assert PREFIX + "payments-unreleased" not in ids
    assert not addition["observations"] and not addition["states"]


@LIVE
@pytest.mark.integration
def test_depth_budget_blocks_further_application_hops(mcp_repository):
    tools = DiagnosticTools(mcp_repository)
    package = context(mcp_repository)
    addition = tools.execute(
        "expand_dependencies", [PREFIX + "auth-service"], package, monotonic() + 180, max_hops=1
    )
    assert PREFIX + "auth-db" not in {n["id"] for n in addition["graph"]["nodes"]}
    assert any("capped at 1" in n for n in addition["limitations"])
