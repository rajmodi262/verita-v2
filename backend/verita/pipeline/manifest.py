"""Run manifests: the lineage record every pipeline stage writes (PIVOT §5.1).

A manifest answers "exactly what produced this file?": input hashes, output hashes, the code
version, the config hash, row counts, wall time and peak memory.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess  # nosec B404
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from verita import __version__
from verita.pipeline.config import REPO_ROOT, config_hash

_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision(root: Path = REPO_ROOT) -> str:
    """Current commit, with '+dirty' if the tree has changes; 'uncommitted' before the first."""
    # Fixed argv, no shell; git on PATH is a development prerequisite.
    try:
        sha = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "HEAD"],  # noqa: S607 - git on PATH is a dev prerequisite
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(  # nosec B603 B607
            ["git", "status", "--porcelain"],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "uncommitted"
    return f"{sha}+dirty" if dirty else sha


def peak_memory_mb() -> float:
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None) or info.rss  # peak_wset is Windows-only
    return round(peak / (1024 * 1024), 1)


@dataclass
class RunManifest:
    stage: str
    dataset: str
    config: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    def add_input(self, path: Path) -> None:
        self.inputs[_rel(path)] = sha256_file(path)

    def add_output(self, path: Path) -> None:
        self.outputs[_rel(path)] = sha256_file(path)

    def to_dict(self, started: float, finished: float) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "stage": self.stage,
            "dataset": self.dataset,
            "verita_version": __version__,
            "git_revision": git_revision(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "config_hash": config_hash(self.config),
            "config": self.config,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "metrics": self.metrics,
            "started_at": datetime.fromtimestamp(started, UTC).isoformat(),
            "duration_s": round(finished - started, 3),
            "peak_memory_mb": peak_memory_mb(),
        }


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


@contextmanager
def run_manifest(
    stage: str, dataset: str, out_dir: Path, config: dict[str, Any] | None = None
) -> Iterator[RunManifest]:
    """Collect lineage during a stage; the manifest is written only if the stage succeeds."""
    manifest = RunManifest(stage=stage, dataset=dataset, config=config or {})
    started = time.time()
    yield manifest
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stage}.json"
    path.write_text(
        json.dumps(manifest.to_dict(started, time.time()), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
