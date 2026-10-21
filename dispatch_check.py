"""Start the GitHub refuge check. The Windows scheduled task runs this."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = "Marc-Phenix/tmb-refuge-check"
WORKFLOW = "tmb_refuge_alert.yml"
LOG_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "tmb-refuge-alert.log"


def git_token() -> str:
    completed = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=Path(__file__).resolve().parent,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git credential fill failed ({completed.returncode})")
    for line in completed.stdout.splitlines():
        if line.startswith("password="):
            token = line.split("=", 1)[1]
            if token:
                return token
    raise RuntimeError("No GitHub credential is stored for this repo.")


def dispatch() -> int:
    token = git_token()
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches",
        data=json.dumps({"ref": "main", "inputs": {"send_test": False}}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "tmb-refuge-check",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.status


def log(message: str) -> None:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def main() -> None:
    try:
        status = dispatch()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:180]
        log(f"failed {exc.code} {detail}")
        print(f"Alert start failed: {exc.code}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        log(f"failed {exc}")
        print(f"Alert start failed: {exc}", file=sys.stderr)
        sys.exit(1)
    log(f"started {status}")
    print(f"Started the refuge check ({status}).")


if __name__ == "__main__":
    main()
