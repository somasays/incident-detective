"""Check the app's temporal dataset, read-only MCP and selected structured model."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.providers import get_temporal_reasoner  # noqa: E402
from knowledge.mcp_db import Neo4jMCPDatabase  # noqa: E402
from knowledge.temporal_queries import TemporalRepository  # noqa: E402


def check_runtime(*, evidence_only=False, offline=False):
    checks = {}
    try:
        with Neo4jMCPDatabase() as db:
            names = [node["name"] for node in TemporalRepository(db).catalog()]
            if not {"payments-api", "billing-api", "profile-service"} <= set(names):
                raise ValueError("Temporal data missing. Run ./bootstrap.sh.")
            checks["neo4j"] = "temporal dataset reachable through read-only local MCP"
            checks["resources"] = names
    except Exception as exc:
        checks["neo4j_error"] = f"Temporal database check failed ({type(exc).__name__})."
    if not evidence_only:
        try:
            reasoner = get_temporal_reasoner(offline=offline)
            reasoner.check_model()
            schema = {
                "type": "object",
                "properties": {"ready": {"type": "boolean"}},
                "required": ["ready"],
                "additionalProperties": False,
            }
            raw = reasoner.generate(
                [{"role": "user", "content": 'Return {"ready":true}.'}],
                schema,
                timeout_seconds=30,
            )
            if json.loads(raw) != {"ready": True}:
                raise ValueError("Structured output check failed")
            checks["model"] = "selected provider returned valid structured output"
        except Exception as exc:
            checks["model_error"] = f"Structured model check failed ({type(exc).__name__})."
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-only", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    checks = check_runtime(evidence_only=args.evidence_only, offline=args.offline)
    print(json.dumps(checks, indent=2))
    return 1 if any(k.endswith("_error") for k in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
