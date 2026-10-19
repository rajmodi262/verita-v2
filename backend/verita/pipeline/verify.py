"""`verita data verify`: confirm the raw files are exactly the ones the manifest names (M1.03)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from verita.pipeline.config import CONFIG_DIR, Dataset, PipelineError, load_yaml
from verita.pipeline.manifest import sha256_file


@dataclass(frozen=True)
class FileCheck:
    name: str
    path: str
    present: bool
    expected_sha256: str | None
    actual_sha256: str | None

    @property
    def ok(self) -> bool:
        if not self.present:
            return False
        return self.expected_sha256 is None or self.expected_sha256 == self.actual_sha256

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ok": self.ok}


def expected_hashes(manifest_path: Path | None = None) -> dict[str, str | None]:
    manifest = load_yaml(manifest_path or CONFIG_DIR / "data_manifest.yaml")
    return {str(f["name"]): f.get("sha256") for f in manifest.get("files", [])}


def verify_raw(dataset: Dataset, manifest_path: Path | None = None) -> list[FileCheck]:
    """Check presence and SHA-256 of a dataset's raw files. Raises if any check fails.

    Files without a recorded hash (e.g. the generated fixture) are checked for presence only.
    """
    expected = expected_hashes(manifest_path)
    checks: list[FileCheck] = []
    for path in (dataset.transactions_csv, dataset.patterns_txt):
        present = path.is_file()
        checks.append(
            FileCheck(
                name=path.name,
                path=str(path),
                present=present,
                expected_sha256=expected.get(path.name),
                actual_sha256=sha256_file(path) if present else None,
            )
        )
    failed = [c for c in checks if not c.ok]
    if failed:
        lines = []
        for c in failed:
            if not c.present:
                lines.append(f"  missing: {c.path}")
            else:
                lines.append(
                    f"  hash mismatch: {c.name} (expected {c.expected_sha256}, "
                    f"got {c.actual_sha256})"
                )
        msg = "Raw data verification failed:\n" + "\n".join(lines)
        raise PipelineError(msg)
    return checks
