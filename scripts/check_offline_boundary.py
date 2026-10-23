"""Prove macOS blocks public TCP while the three demo services remain reachable locally."""

import errno
import socket


def main():
    with socket.socket() as probe:
        probe.settimeout(2)
        result = probe.connect_ex(("1.1.1.1", 443))
        if result not in {errno.EPERM, errno.EACCES}:
            raise SystemExit(
                "Public networking was not denied by the OS. Run with "
                "sandbox-exec -f scripts/localhost-only.sb."
            )
    print("PASS: macOS denied public-network TCP access.")
    for service, port in [("Neo4j Bolt", 7687), ("Ollama", 11434), ("Streamlit", 8501)]:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            print(f"PASS: {service} is reachable on localhost:{port}.")


if __name__ == "__main__":
    main()
