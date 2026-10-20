"""``verita`` command-line interface. Pipeline stages are added here as milestones land."""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from alembic import command
from alembic.config import Config

from verita.core.config import get_settings
from verita.core.errors import AppError
from verita.db.models import Role
from verita.db.session import make_engine, make_session_factory, transaction
from verita.pipeline import run as pipeline
from verita.pipeline.config import REPO_ROOT, PipelineError, get_dataset
from verita.pipeline.datacard import write_card
from verita.pipeline.fixture import generate_fixture
from verita.services.auth import AuthService

app = typer.Typer(no_args_is_help=True, help="Verita command-line interface.")
db_app = typer.Typer(no_args_is_help=True, help="Database migrations.")
users_app = typer.Typer(no_args_is_help=True, help="User management.")
data_app = typer.Typer(
    no_args_is_help=True, help="Data pipeline (M1): verify → ingest → link → graph → split."
)
app.add_typer(db_app, name="db")
app.add_typer(users_app, name="users")
app.add_typer(data_app, name="data")
detect_app = typer.Typer(no_args_is_help=True, help="Detect (M2): features, training, evaluation.")
app.add_typer(detect_app, name="detect")
decide_app = typer.Typer(
    no_args_is_help=True, help="Decide (M4): calibration, guarantee, capacity."
)
app.add_typer(decide_app, name="decide")

BACKEND_ROOT = Path(__file__).resolve().parent.parent

DEMO_USERS: tuple[tuple[str, Role], ...] = (
    ("analyst", Role.ANALYST),
    ("analyst2", Role.ANALYST),
    ("mlro", Role.MLRO),
    ("validator", Role.VALIDATOR),
    ("reviewer", Role.REVIEWER),
)


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@db_app.command("upgrade")
def db_upgrade(revision: str = "head") -> None:
    """Apply migrations up to REVISION (default: head)."""
    command.upgrade(alembic_config(get_settings().database_url), revision)
    typer.echo(f"Database upgraded to {revision}")


@users_app.command("create")
def users_create(
    username: Annotated[str, typer.Option(prompt=True)],
    role: Annotated[Role, typer.Option(prompt=True, case_sensitive=False)],
    password: Annotated[str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)],
) -> None:
    """Create a user."""
    settings = get_settings()
    factory = make_session_factory(make_engine(settings.database_url))
    try:
        with transaction(factory) as db:
            user = AuthService(db, settings).create_user(username, password, role)
            typer.echo(f"Created {user.username} ({user.role})")
    except (AppError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@users_app.command("seed-demo")
def users_seed_demo() -> None:
    """Create the demo users. Password: VERITA_DEMO_PASSWORD, or a random one printed once."""
    settings = get_settings()
    password = os.environ.get("VERITA_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    factory = make_session_factory(make_engine(settings.database_url))
    created: list[str] = []
    with transaction(factory) as db:
        service = AuthService(db, settings)
        for username, role in DEMO_USERS:
            try:
                service.create_user(username, password, role)
                created.append(username)
            except AppError as exc:
                if exc.slug != "username-taken":
                    raise
    if not created:
        typer.echo("Demo users already exist; nothing changed.")
        return
    typer.echo(f"Created demo users: {', '.join(created)}")
    if "VERITA_DEMO_PASSWORD" not in os.environ:
        typer.echo(f"Generated password (shown once): {password}")


DatasetOpt = Annotated[str, typer.Option("--dataset", "-d", help="hi_small, li_small or fixture")]
RootOpt = Annotated[Path, typer.Option(help="Repository root (tests use a temp dir)")]


def _run_stage(stage: Callable[..., Any], dataset: str, root: Path) -> None:
    try:
        result = stage(get_dataset(dataset, root=root))
    except PipelineError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, indent=2, default=str))


@data_app.command("fixture")
def data_fixture(root: RootOpt = REPO_ROOT, seed: int = 7) -> None:
    """Generate the IBM-format fixture into data/fixture/."""
    ds = get_dataset("fixture", root=root)
    summary = generate_fixture(ds.raw_dir, seed=seed)
    typer.echo(
        f"Wrote {summary.transactions:,} transactions, {summary.patterns} patterns to {ds.raw_dir}"
    )


@data_app.command("verify")
def data_verify(dataset: DatasetOpt, root: RootOpt = REPO_ROOT) -> None:
    """Check raw files exist and match configs/data_manifest.yaml."""
    _run_stage(pipeline.stage_verify, dataset, root)


@data_app.command("ingest")
def data_ingest(dataset: DatasetOpt, root: RootOpt = REPO_ROOT) -> None:
    """Validate the raw CSV against the data contract and write transactions.parquet."""
    _run_stage(pipeline.stage_ingest, dataset, root)


@data_app.command("link")
def data_link(dataset: DatasetOpt, root: RootOpt = REPO_ROOT) -> None:
    """Parse the patterns file and link each pattern row to its transaction."""
    _run_stage(pipeline.stage_link, dataset, root)


@data_app.command("graph")
def data_graph(dataset: DatasetOpt, root: RootOpt = REPO_ROOT) -> None:
    """Build accounts.parquet and account_day.parquet."""
    _run_stage(pipeline.stage_graph, dataset, root)


@data_app.command("split")
def data_split(dataset: DatasetOpt, root: RootOpt = REPO_ROOT) -> None:
    """Write count-based temporal splits (train / hpo / calib / test)."""
    _run_stage(pipeline.stage_split, dataset, root)


@data_app.command("all")
def data_all(dataset: DatasetOpt, root: RootOpt = REPO_ROOT) -> None:
    """Run every data stage in order."""
    _run_stage(pipeline.stage_all, dataset, root)


@data_app.command("card")
def data_card(
    datasets: Annotated[list[str] | None, typer.Option("--dataset", "-d")] = None,
    out: Annotated[Path | None, typer.Option(help="Output file (default: DATA_CARD.md)")] = None,
    root: RootOpt = REPO_ROOT,
) -> None:
    """Render DATA_CARD.md from the validation reports."""
    names = datasets or ["hi_small", "li_small"]
    try:
        path = write_card(names, out or root / "DATA_CARD.md", root)
    except PipelineError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Wrote {path}")


@detect_app.command("features")
def detect_features(dataset: DatasetOpt, root: RootOpt = REPO_ROOT) -> None:
    """Build as-of features for every transaction."""
    from verita.ml import stages  # noqa: PLC0415 - heavy ML imports only when needed

    _run_stage(stages.stage_features, dataset, root)


@detect_app.command("train")
def detect_train(
    dataset: DatasetOpt,
    root: RootOpt = REPO_ROOT,
    quick: Annotated[bool, typer.Option(help="Tiny settings (tests, fixture)")] = False,
) -> None:
    """Tune, train, evaluate and save the detector; writes artifacts/<dataset>/detect/."""
    from verita.ml import stages  # noqa: PLC0415

    _run_stage(lambda ds: stages.stage_detect(ds, quick=quick), dataset, root)


@detect_app.command("alerts")
def detect_alerts(dataset: DatasetOpt, root: RootOpt = REPO_ROOT) -> None:
    """Build the evidence store and load test-window alerts into the database."""
    from verita.ml import stages  # noqa: PLC0415

    settings = get_settings()
    factory = make_session_factory(make_engine(settings.database_url))

    def run(ds: Any) -> Any:
        with transaction(factory) as db:
            return stages.stage_alerts(ds, db)

    _run_stage(run, dataset, root)


@app.command("openapi")
def export_openapi(
    out: Annotated[Path, typer.Option(help="Where to write the schema")] = REPO_ROOT
    / "frontend"
    / "src"
    / "api"
    / "openapi.json",
) -> None:
    """Write the OpenAPI schema the frontend types are generated from."""
    from verita.api.app import create_app  # noqa: PLC0415
    from verita.core.config import Settings  # noqa: PLC0415

    schema = create_app(Settings(env="dev", _env_file=None)).openapi()
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    typer.echo(f"Wrote {out}")


@decide_app.command("run")
def decide_run(dataset: DatasetOpt, root: RootOpt = REPO_ROOT) -> None:
    """Calibrate, fit recall guarantees, replay coverage, forecast, drift, frontiers."""
    from verita.ml import stages  # noqa: PLC0415

    settings = get_settings()
    factory = make_session_factory(make_engine(settings.database_url))

    def run(ds: Any) -> Any:
        with transaction(factory) as db:
            return stages.stage_decide(ds, db)

    _run_stage(run, dataset, root)


@app.command("bench")
def bench(dataset: DatasetOpt, root: RootOpt = REPO_ROOT) -> None:
    """Latency of subgraph extraction and exact plans; writes artifacts/<dataset>/bench.json."""
    from verita.ml.bench import run_bench  # noqa: PLC0415

    factory = make_session_factory(make_engine(get_settings().database_url))

    def run(ds: Any) -> Any:
        with transaction(factory) as db:
            return run_bench(ds, db)

    _run_stage(run, dataset, root)


defend_app = typer.Typer(help="Defend: case files, verifier evaluation, job worker.")
app.add_typer(defend_app, name="defend")


@defend_app.command("eval")
def defend_eval(
    dataset: DatasetOpt,
    root: RootOpt = REPO_ROOT,
    cases: int = 300,
    seed: int = 0,
    llm_cases: int = 30,
    llm: Annotated[
        bool, typer.Option(help="Also send evidence to the configured LLM providers")
    ] = False,
) -> None:
    """Fault-injection evaluation of the verifier; writes artifacts/<dataset>/defend/."""
    from verita.defend.evaluation import run_eval  # noqa: PLC0415
    from verita.defend.narrative import providers_from_settings  # noqa: PLC0415

    settings = get_settings()
    factory = make_session_factory(make_engine(settings.database_url))

    def run(ds: Any) -> Any:
        with transaction(factory) as db:
            providers = providers_from_settings(settings) if llm else []
            result = run_eval(ds, db, cases, seed, providers, llm_cases)
        for f in result["faults"].values():
            f.pop("misses")
        result.pop("clean_failures")
        return result

    _run_stage(run, dataset, root)


@app.command("worker")
def worker(once: bool = False, poll_seconds: float = 1.0) -> None:
    """Run queued jobs (narrative drafts) until stopped; --once runs at most one."""
    import time  # noqa: PLC0415

    from verita.services import cases, jobs  # noqa: PLC0415

    settings = get_settings()
    cases.configure(settings)
    factory = make_session_factory(make_engine(settings.database_url))
    while True:
        job = jobs.run(factory)
        if job is not None:
            typer.echo(f"job {job.id} {job.kind}: {job.status}")
        if once:
            return
        if job is None:
            time.sleep(poll_seconds)


report_app = typer.Typer(help="Generated reports: metrics.json, README block, cards, honesty scan.")
app.add_typer(report_app, name="report")


@report_app.command("build")
def report_build(root: RootOpt = REPO_ROOT) -> None:
    """Collect artifacts into reports/metrics.json and regenerate every derived document."""
    from verita.reports import docs, metrics  # noqa: PLC0415

    path = metrics.write(metrics.build(root), root / "reports" / "metrics.json")
    m = json.loads(path.read_text(encoding="utf-8"))  # render exactly what `check` will read
    for target, text in docs.rendered(m, root).items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        typer.echo(f"Wrote {target}")
    typer.echo(f"Wrote {path} ({len(m['headline'])} headline figures)")


@report_app.command("check")
def report_check(root: RootOpt = REPO_ROOT) -> None:
    """Fail if a committed document differs from what the committed metrics.json renders."""
    from verita.reports import docs  # noqa: PLC0415

    m = json.loads((root / "reports" / "metrics.json").read_text(encoding="utf-8"))
    stale = [
        str(t.relative_to(root))
        for t, text in docs.rendered(m, root).items()
        if not t.exists() or t.read_text(encoding="utf-8") != text
    ]
    if stale:
        typer.echo("Out of date (run `verita report build`): " + ", ".join(stale), err=True)
        raise typer.Exit(1)
    typer.echo("Generated documents match reports/metrics.json")


@report_app.command("scan")
def report_scan(root: RootOpt = REPO_ROOT) -> None:
    """Fail on hand-typed metrics in public docs and UI code."""
    from verita.reports.honesty import scan  # noqa: PLC0415

    findings = scan(root)
    for f in findings:
        typer.echo(str(f), err=True)
    if findings:
        typer.echo(f"{len(findings)} hand-typed metric(s) found", err=True)
        raise typer.Exit(1)
    typer.echo("No hand-typed metrics")


if __name__ == "__main__":  # pragma: no cover - `python -m verita.cli`
    app()
