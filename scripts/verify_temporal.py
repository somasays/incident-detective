"""Run real temporal questions through MCP and preserve complete evidence reports."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.providers import ModelSettings, get_temporal_reasoner  # noqa: E402
from agent.temporal import build_temporal_investigator  # noqa: E402
from knowledge.db import Database  # noqa: E402
from knowledge.mcp_db import Neo4jMCPDatabase  # noqa: E402
from knowledge.temporal_queries import TemporalRepository  # noqa: E402
from scripts.verify_demo import deny_nonlocal_sockets  # noqa: E402
from ui.temporal_report import save_package  # noqa: E402

CASES = [
    ("payments-historical", "What was wrong with payments API at 3AM today?", {}),
    (
        "payments-known-then",
        "What was wrong with payments API at 3AM today?",
        {"mode": "known_then"},
    ),
    ("payments-now", "Why is payments API slow now?", {}),
    ("billing", "Why does billing API throw errors?", {}),
    ("profile", "Why is profile service unstable?", {}),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-model", action="store_true")
    parser.add_argument("--transport", choices=["mcp", "bolt"], default="mcp")
    parser.add_argument("--output", type=Path, default=Path("artifacts/temporal-verification"))
    parser.add_argument(
        "--case",
        action="append",
        choices=[c[0] for c in CASES],
        help="Run selected cases in sequence",
    )
    args = parser.parse_args()
    settings = ModelSettings.from_env()
    if not args.with_model or settings.provider == "ollama":
        deny_nonlocal_sockets()
    cases = [c for c in CASES if not args.case or c[0] in args.case]
    results = []
    with Neo4jMCPDatabase() if args.transport == "mcp" else Database() as db:
        reasoner = get_temporal_reasoner(settings) if args.with_model else None
        for case, question, options in cases:
            print(f"Starting {case}", flush=True)
            graph = build_temporal_investigator(TemporalRepository(db), reasoner)
            state = {"question": question, "options": options}
            for update in graph.stream(
                state, stream_mode="updates", config={"recursion_limit": 64}
            ):
                for stage, values in update.items():
                    state.update(values)
                    print(f"{case}: {stage}", flush=True)
            package = state["package"]
            save_package(package, args.output / case)
            analysis = package.get("analysis", {})
            results.append(
                {
                    "case": case,
                    "status": package["status"],
                    "analysisAvailable": package.get("analysisAvailable", False),
                    "summary": analysis.get("summary"),
                    "causes": [h["cause_entity_id"] for h in analysis.get("hypotheses", [])],
                    "error": package.get("error"),
                    "queries": len(package.get("queryTrace", [])),
                    "measurements": len(package.get("measurements", [])),
                }
            )
            print(json.dumps(results[-1]), flush=True)
            if package["status"] == "unavailable":
                remaining = cases[len(results) :]
                print(
                    "Stopping after unavailable analysis; remaining cases were not run.",
                    flush=True,
                )
                results.extend({"case": c[0], "status": "not_run"} for c in remaining)
                break
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "verification.json").write_text(json.dumps(results, indent=2) + "\n")
    accepted = {"complete", "symptom_not_observed"} if args.with_model else {"evidence_only"}
    return int(any(r["status"] not in accepted for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
