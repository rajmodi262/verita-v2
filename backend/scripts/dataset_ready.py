"""Is a dataset ready to serve? Used by the one-click starter (start-verita.ps1).

    cd backend && uv run python scripts/dataset_ready.py hi_small

Exit 0 when the dataset's champion artifacts exist and the configured database holds alerts for
a model trained on it; exit 1 otherwise. Prints one plain-language line either way.
"""

from __future__ import annotations

import sys

from sqlalchemy import func, select

from verita.core.config import get_settings
from verita.db.detect_models import Alert, ModelVersion
from verita.db.session import make_engine, make_session_factory, transaction


def main(dataset: str) -> int:
    settings = get_settings()
    champion = settings.data_root / "artifacts" / dataset / "detect" / "champion.txt"
    if not champion.exists():
        print(f"{dataset}: no trained model in artifacts/{dataset}")
        return 1
    factory = make_session_factory(make_engine(settings.database_url))
    with transaction(factory) as db:
        alerts = db.scalar(
            select(func.count(Alert.id))
            .join(ModelVersion, Alert.model_version_id == ModelVersion.id)
            .where(ModelVersion.dataset == dataset)
        )
    if not alerts:
        print(f"{dataset}: model found, but no alerts loaded in the database")
        return 1
    print(f"{dataset}: ready ({alerts:,} alerts)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "hi_small"))
