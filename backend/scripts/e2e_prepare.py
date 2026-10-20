"""Prepare a deterministic stack for the browser end-to-end tests.

    cd backend && uv run python scripts/e2e_prepare.py

Builds the generated fixture dataset end to end (pipeline → quick detector → alerts → Decide) into
an isolated SQLite database and signing key under ``backend/.e2e/`` and seeds the demo users with
the password in ``VERITA_DEMO_PASSWORD`` (default: the e2e-only value below). Nothing touches
the development database, the real datasets or ``keys/``.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 - fixed commands
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
E2E = BACKEND / ".e2e"
DEFAULT_PASSWORD = "e2e-only-password-0001"  # noqa: S105 - test-only value, never a real secret


def env() -> dict[str, str]:
    return {
        **os.environ,
        "VERITA_DATABASE_URL": f"sqlite+pysqlite:///{(E2E / 'e2e.sqlite').as_posix()}",
        "VERITA_DATASET": "fixture",
        "VERITA_SIGNING_KEY_PATH": str(E2E / "signing.pem"),
        "VERITA_PUBLIC_KEY_PATH": str(E2E / "pub.pem"),
        "VERITA_LLM_PROVIDERS": "[]",
        "VERITA_DEMO_PASSWORD": os.environ.get("VERITA_DEMO_PASSWORD", DEFAULT_PASSWORD),
        "PYTHONIOENCODING": "utf-8",
    }


STEPS = [
    ["data", "fixture"],
    ["data", "all", "--dataset", "fixture"],
    ["detect", "features", "--dataset", "fixture"],
    ["detect", "train", "--dataset", "fixture", "--quick"],
    ["db", "upgrade"],
    ["detect", "alerts", "--dataset", "fixture"],
    ["decide", "run", "--dataset", "fixture"],
    ["users", "seed-demo"],
]


def main() -> int:
    shutil.rmtree(E2E, ignore_errors=True)
    E2E.mkdir(parents=True)
    for step in STEPS:
        print("verita", " ".join(step), flush=True)
        result = subprocess.run(  # noqa: S603 - fixed argument list
            [sys.executable, "-m", "verita.cli", *step],
            cwd=BACKEND,
            env=env(),
            stdout=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            print(f"step failed: verita {' '.join(step)}", file=sys.stderr)
            return result.returncode
    print(f"e2e stack ready in {E2E}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
