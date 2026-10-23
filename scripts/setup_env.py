"""Create a private local .env once without overwriting existing settings."""

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / ".env"
    text = (ROOT / ".env.example").read_text().replace("change-me", secrets.token_urlsafe(24))
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(".env already exists; kept existing configuration.")
        return
    with os.fdopen(fd, "w") as output:
        output.write(text)
    print("Created private .env with a generated local Neo4j password. No credentials printed.")


if __name__ == "__main__":
    main()
