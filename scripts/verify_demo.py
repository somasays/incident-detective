"""Run real Neo4j + LangGraph + Ollama, save evidence/HTML, optionally deny nonlocal sockets."""

import argparse
import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.graph import build_investigator  # noqa: E402
from agent.reasoning import OllamaReasoner  # noqa: E402
from knowledge.db import Database  # noqa: E402
from knowledge.queries import KnowledgeRepository  # noqa: E402
from ui.graph_view import render_evidence_graph  # noqa: E402


def deny_nonlocal_sockets():
    """A process-local audit, not a claim that the Mac's internet was disabled."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo
    allowed = {"localhost", "127.0.0.1", "::1"}

    def check(address):
        if isinstance(address, tuple) and address[0] not in allowed:
            raise RuntimeError(f"Offline audit blocked a nonlocal connection: {address[0]}")

    def connect(sock, address):
        check(address)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        check(address)
        return original_connect_ex(sock, address)

    def getaddrinfo(host, *args, **kwargs):
        if host not in allowed and host not in {b"localhost", b"127.0.0.1", b"::1"}:
            raise RuntimeError(f"Offline audit blocked nonlocal DNS: {host}")
        return original_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-audit", action="store_true")
    parser.add_argument("--incident", choices=["INC-104", "INC-105"], action="append")
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    if args.offline_audit:
        deny_nonlocal_sockets()
    args.output.mkdir(parents=True, exist_ok=True)
    failures = []
    with Database() as db:
        db.wait_ready(attempts=3, delay=1)
        graph = build_investigator(KnowledgeRepository(db), OllamaReasoner())
        for incident_id in args.incident or ["INC-104", "INC-105"]:
            result = {"incident_id": incident_id}
            for update in graph.stream(
                result, config={"recursion_limit": 12}, stream_mode="updates"
            ):
                for name, values in update.items():
                    result.update(values)
                    print(f"{incident_id}: {name}", flush=True)
            (args.output / f"{incident_id}.json").write_text(json.dumps(result, indent=2))
            if evidence := result.get("evidence"):
                (args.output / f"{incident_id}.html").write_text(
                    render_evidence_graph(evidence, result)
                )
            if not result.get("analysis_available") or not result.get("hypotheses"):
                failures.append(incident_id)
                print(
                    result.get("validation_error")
                    or result.get("retrieval_error")
                    or "No supported hypothesis returned.",
                    flush=True,
                )
            else:
                print(
                    json.dumps(
                        {"incident": incident_id, "leading_hypothesis": result["hypotheses"][0]},
                        indent=2,
                    ),
                    flush=True,
                )
    if failures:
        print("Failed to obtain validated local analysis: " + ", ".join(failures))
        return 1
    print("Both requested investigations completed with validated local model analysis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
