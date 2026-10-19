"""Pipeline configuration: repository paths, the dataset registry and the data contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "configs"


class PipelineError(Exception):
    """A pipeline stage cannot proceed; the message says why and what to do."""


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        msg = f"Missing config file: {path}"
        raise PipelineError(msg)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"{path} must contain a mapping"
        raise PipelineError(msg)
    return data


def config_hash(data: object) -> str:
    """Stable hash of any JSON-able config, recorded in run manifests."""
    blob = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class DataContract:
    timestamp_format: str
    currencies: frozenset[str]
    payment_formats: frozenset[str]
    typologies: frozenset[str]

    @classmethod
    def load(cls, path: Path | None = None) -> DataContract:
        raw = load_yaml(path or CONFIG_DIR / "data_contract.yaml")
        return cls(
            timestamp_format=str(raw["timestamp_format"]),
            currencies=frozenset(raw["currencies"]),
            payment_formats=frozenset(raw["payment_formats"]),
            typologies=frozenset(raw["typologies"]),
        )


@dataclass(frozen=True)
class Dataset:
    """One registered dataset and where every stage reads and writes its files."""

    name: str
    description: str
    raw_dir: Path
    transactions_file: str
    patterns_file: str
    root: Path = REPO_ROOT

    @property
    def transactions_csv(self) -> Path:
        return self.raw_dir / self.transactions_file

    @property
    def patterns_txt(self) -> Path:
        return self.raw_dir / self.patterns_file

    @cached_property
    def processed_dir(self) -> Path:
        return self.root / "data" / "processed" / self.name

    @cached_property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts" / self.name

    @property
    def transactions_parquet(self) -> Path:
        return self.processed_dir / "transactions.parquet"

    @property
    def pattern_links_parquet(self) -> Path:
        return self.processed_dir / "pattern_links.parquet"

    @property
    def accounts_parquet(self) -> Path:
        return self.processed_dir / "accounts.parquet"

    @property
    def account_day_parquet(self) -> Path:
        return self.processed_dir / "account_day.parquet"

    @property
    def features_parquet(self) -> Path:
        return self.processed_dir / "features.parquet"

    @property
    def models_dir(self) -> Path:
        return self.artifacts_dir / "models"

    @property
    def splits_json(self) -> Path:
        return self.artifacts_dir / "splits.json"

    @property
    def validation_json(self) -> Path:
        return self.artifacts_dir / "data_validation.json"

    @property
    def manifests_dir(self) -> Path:
        return self.artifacts_dir / "manifests"


def load_datasets(path: Path | None = None, root: Path = REPO_ROOT) -> dict[str, Dataset]:
    raw = load_yaml(path or CONFIG_DIR / "datasets.yaml")
    out: dict[str, Dataset] = {}
    for name, spec in raw["datasets"].items():
        out[name] = Dataset(
            name=name,
            description=str(spec["description"]),
            raw_dir=root / str(spec["raw_dir"]),
            transactions_file=str(spec["transactions"]),
            patterns_file=str(spec["patterns"]),
            root=root,
        )
    return out


def get_dataset(name: str, root: Path = REPO_ROOT) -> Dataset:
    datasets = load_datasets(root=root)
    if name not in datasets:
        known = ", ".join(sorted(datasets))
        msg = f"Unknown dataset '{name}'. Known: {known}"
        raise PipelineError(msg)
    return datasets[name]
