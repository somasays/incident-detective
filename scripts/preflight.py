"""Check actual local database, installed model, and short structured inference."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.reasoning import OllamaReasoner  # noqa: E402
from knowledge.db import Database  # noqa: E402
from knowledge.queries import KnowledgeRepository  # noqa: E402


def main():
    checks = {}
    try:
        with Database() as db:
            db.wait_ready(attempts=3, delay=1)
            repo = KnowledgeRepository(db)
            checks["neo4j"] = "reachable on localhost"
            checks["incidents"] = [i["id"] for i in repo.list_incidents()]
            if not {"INC-104", "INC-105"} <= set(checks["incidents"]):
                raise ValueError("Seed the demo first: uv run python seed.py")
    except Exception as exc:
        checks["neo4j_error"] = str(exc)
    try:
        checks["ollama"] = OllamaReasoner().preflight()
    except Exception as exc:
        checks["ollama_error"] = str(exc)
    print(json.dumps(checks, indent=2))
    return 1 if any(k.endswith("_error") for k in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
