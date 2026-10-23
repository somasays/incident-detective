"""Populate the approved temporal KG and ask real graph-grounded diagnostic questions."""

import argparse
import json
from pathlib import Path

from agent.providers import get_temporal_reasoner
from agent.temporal import build_temporal_investigator
from knowledge.db import Database
from knowledge.mcp_db import Neo4jMCPDatabase
from knowledge.temporal_fixture import DATA_AS_OF, DATASET, FIXTURE, build_fixture
from knowledge.temporal_queries import TemporalRepository
from knowledge.temporal_seed import seed_temporal, validate_fixture
from ui.temporal_report import save_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    ask = sub.add_parser("ask")
    ask.add_argument("question")
    ask.add_argument("--at", help="ISO time, optionally without offset in --timezone")
    ask.add_argument("--timezone", default="Europe/Berlin")
    ask.add_argument("--mode", choices=["retrospective", "known_then"], default="retrospective")
    ask.add_argument("--known-at")
    ask.add_argument("--evidence-only", action="store_true")
    ask.add_argument("--transport", choices=["mcp", "bolt"], default="mcp")
    ask.add_argument("--output", type=Path, default=Path("artifacts/temporal-investigation"))
    args = parser.parse_args()
    connection = (
        Database if args.command == "seed" or args.transport == "bolt" else Neo4jMCPDatabase
    )
    with connection() as db:
        if hasattr(db, "wait_ready"):
            db.wait_ready(attempts=3, delay=1)
        if args.command == "seed":
            fixture = validate_fixture(build_fixture())
            FIXTURE.write_text(json.dumps(fixture, indent=2) + "\n")
            print(json.dumps(seed_temporal(db, fixture), indent=2))
            print(f"Synthetic dataset {DATASET}; reference time {DATA_AS_OF}.")
            return 0
        repository = TemporalRepository(db)
        graph = build_temporal_investigator(
            repository, None if args.evidence_only else get_temporal_reasoner()
        )
        initial = {
            "question": args.question,
            "options": {
                "at": args.at,
                "mode": args.mode,
                "known_at": args.known_at,
                "timezone": args.timezone,
            },
        }
        state = dict(initial)
        for update in graph.stream(initial, stream_mode="updates", config={"recursion_limit": 64}):
            for name, values in update.items():
                state.update(values)
                print(name, flush=True)
        package = state["package"]
        path = save_package(package, args.output)
        print(
            json.dumps(
                {
                    "request": package.get("request"),
                    "status": package["status"],
                    "analysis": package.get("analysis"),
                    "error": package.get("error"),
                    "report": str(path),
                },
                indent=2,
            )
        )
        return 1 if package["status"] == "unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
