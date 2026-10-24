"""Start local services, seed the temporal graph, preflight and launch the dashboard."""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.providers import ModelSettings  # noqa: E402
from config import ROOT, Settings, load_environment  # noqa: E402
from knowledge.db import Database  # noqa: E402
from knowledge.temporal_seed import seed_temporal  # noqa: E402
from scripts.preflight import check_runtime  # noqa: E402
from scripts.setup_env import main as setup_environment  # noqa: E402


def command(args, *, timeout=180, extra_env=None, project_environment=True):
    # Credentials are passed through the process environment, never command arguments or logs.
    # Dashboard settings must remain in .env: copying them into os.environ would
    # turn them into permanent overrides and prevent configuration refresh on rerun.
    environment = load_environment() if project_environment else dict(os.environ)
    subprocess.run(
        args, cwd=ROOT, env={**environment, **(extra_env or {})}, check=True, timeout=timeout
    )


def http_json(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=3) as response:
        return json.loads(response.read())


def start_ollama(settings, *, offline):
    url = settings.ollama_host.rstrip("/") + "/api/tags"
    try:
        models = http_json(url)
    except (OSError, urllib.error.URLError):
        runtime = ROOT / "artifacts" / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        with (runtime / "ollama.log").open("ab") as log:
            process = subprocess.Popen(
                ["ollama", "serve"],
                cwd=ROOT,
                env={
                    **load_environment(),
                    "OLLAMA_HOST": settings.ollama_host,
                    "OLLAMA_NO_CLOUD": "1",
                },
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        (runtime / "ollama.pid").write_text(str(process.pid))
        for _ in range(30):
            if process.poll() is not None:
                raise RuntimeError(
                    "Ollama did not start. See artifacts/runtime/ollama.log."
                ) from None
            try:
                models = http_json(url)
                break
            except (OSError, urllib.error.URLError):
                time.sleep(1)
        else:
            raise RuntimeError("Ollama readiness timed out. See artifacts/runtime/ollama.log.")
    installed = {m.get("name", m.get("model")) for m in models.get("models", [])}
    if (
        settings.ollama_model not in installed
        and settings.ollama_model + ":latest" not in installed
    ):
        if offline:
            raise RuntimeError("The configured model is missing. Run ./bootstrap.sh while online.")
        print("Downloading the configured local model…", flush=True)
        command(["ollama", "pull", settings.ollama_model], timeout=1800)


def port_in_use(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def bootstrap(args):
    os.chdir(ROOT)
    setup_environment()
    if not args.setup_only and port_in_use(args.port):
        raise RuntimeError(
            f"Port {args.port} is occupied. Stop that dashboard or choose --port 8502."
        )
    settings, model = Settings.from_env(), ModelSettings.from_env()
    if args.offline and not args.evidence_only and model.provider != "ollama":
        raise RuntimeError("Offline launch requires Ollama. Use LLM_PROVIDER=ollama ./run.sh.")
    if not args.evidence_only:
        model.validate()
    required = ["docker"] + (
        ["ollama"] if model.provider == "ollama" and not args.evidence_only else []
    )
    for executable in required:
        if not shutil.which(executable):
            raise RuntimeError(f"Install {executable} first; see the README prerequisites.")
    print("Starting Neo4j Community…", flush=True)
    docker = ["docker", "compose", "up", "-d"]
    if args.offline:
        docker += ["--pull", "never"]
    command(docker)
    with Database(settings) as db:
        db.wait_ready()
        result = seed_temporal(db)
    print(
        f"Graph ready: {result['nodes']} nodes, {result['relationships']} relationships.",
        flush=True,
    )
    if model.provider == "ollama" and not args.evidence_only:
        print("Checking local Ollama and installed weights…", flush=True)
        start_ollama(settings, offline=args.offline)
    print("Verifying the temporal dataset, read-only MCP and structured model output…", flush=True)
    checks = check_runtime(evidence_only=args.evidence_only, offline=args.offline)
    print(json.dumps(checks, indent=2), flush=True)
    if any(key.endswith("_error") for key in checks):
        raise RuntimeError("Preflight failed; fix the reported service and rerun this script.")
    if args.setup_only:
        print("Setup complete. Run ./run.sh to open the dashboard.", flush=True)
        return 0
    url = f"http://localhost:{args.port}"
    print(f"Incident Detective: {url} · Ctrl-C stops the dashboard.", flush=True)
    app_env = {"INCIDENT_OFFLINE": "1"} if args.offline else {}
    if args.evidence_only:
        app_env["INCIDENT_EVIDENCE_ONLY"] = "1"
    command(
        [
            "uv",
            "run",
            "--locked",
            "--offline",
            "streamlit",
            "run",
            "app.py",
            "--server.port",
            str(args.port),
        ],
        timeout=None,
        extra_env=app_env,
        project_environment=False,
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Never download an image or model")
    parser.add_argument("--setup-only", action="store_true", help="Prepare services without the UI")
    parser.add_argument(
        "--evidence-only", action="store_true", help="Skip model setup and inference"
    )
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        return bootstrap(args)
    except KeyboardInterrupt:
        print("Dashboard stopped. Neo4j data and local model weights are preserved.")
        return 130
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        # External command output already identifies the failed step; never dump settings or keys.
        print(
            f"Setup failed ({type(exc).__name__}). "
            + (str(exc) if isinstance(exc, RuntimeError) else "Check the preceding step and .env."),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
