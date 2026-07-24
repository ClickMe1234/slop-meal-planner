"""Supervised production runtime used by the Docker image."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping, MutableMapping
from threading import Event

from .deployment import DeploymentConfigError, configure_environment, configured_redis_urls


BACKEND_ROOT = Path(__file__).resolve().parents[1]
LOCK_ID = 0x4D45414C504C414E  # "MEALPLAN"
DEPENDENCY_TIMEOUT_SECONDS = 120
GRACEFUL_SHUTDOWN_SECONDS = 30


def _postgres_driver_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _dependency_error(dependency: str) -> RuntimeError:
    return RuntimeError(f"{dependency} is unavailable")


def wait_for_dependencies(environment: Mapping[str, str] | None = None) -> None:
    """Wait for PostgreSQL and every configured Redis endpoint."""

    import psycopg
    import redis

    source = environment or os.environ
    database_url = _postgres_driver_url(source["MEAL_PLANNER_DATABASE_URL"])
    redis_urls = configured_redis_urls(source)
    deadline = time.monotonic() + DEPENDENCY_TIMEOUT_SECONDS
    delay = 1.0
    last_dependency = "PostgreSQL"

    while True:
        try:
            with psycopg.connect(database_url, connect_timeout=3) as connection:
                connection.execute("SELECT 1")
        except Exception:
            last_dependency = "PostgreSQL"
        else:
            try:
                for url in redis_urls:
                    client = redis.Redis.from_url(
                        url,
                        socket_connect_timeout=3,
                        socket_timeout=3,
                        retry_on_timeout=False,
                    )
                    try:
                        client.ping()
                    finally:
                        client.close()
            except Exception:
                last_dependency = "Redis"
            else:
                print("Dependencies are ready", flush=True)
                return

        if time.monotonic() >= deadline:
            raise _dependency_error(last_dependency)
        time.sleep(min(delay, max(0.1, deadline - time.monotonic())))
        delay = min(delay * 1.7, 8.0)


def run_migrations(environment: Mapping[str, str] | None = None) -> None:
    """Run migrations and normalisation jobs exactly once under an advisory lock."""

    import psycopg

    source = environment or os.environ
    database_url = _postgres_driver_url(source["MEAL_PLANNER_DATABASE_URL"])
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            for command in (
                ["alembic", "-c", "alembic.ini", "upgrade", "head"],
                [sys.executable, "-m", "scripts.reparse_ingredients"],
                [sys.executable, "-m", "scripts.normalise_quantities"],
            ):
                subprocess.run(
                    command,
                    check=True,
                    cwd=BACKEND_ROOT,
                    env=dict(source),
                    capture_output=True,
                    text=True,
                )
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


def _children_alive(children: Mapping[str, subprocess.Popen]) -> Iterable[tuple[str, subprocess.Popen]]:
    return ((name, child) for name, child in children.items() if child.poll() is None)


def stop_children(children: Mapping[str, subprocess.Popen], *, grace_seconds: int = GRACEFUL_SHUTDOWN_SECONDS) -> None:
    """Terminate and reap every child, escalating after the grace period."""

    for name, child in _children_alive(children):
        print(f"Stopping {name}", flush=True)
        child.terminate()
    deadline = time.monotonic() + grace_seconds
    while any(child.poll() is None for child in children.values()) and time.monotonic() < deadline:
        time.sleep(0.1)
    for name, child in _children_alive(children):
        print(f"Force-stopping {name}", flush=True)
        child.kill()
    for child in children.values():
        child.wait()


def supervise(environment: Mapping[str, str] | None = None) -> int:
    """Run web, worker, and beat as one restartable application unit."""

    source = dict(environment or os.environ)
    children: dict[str, subprocess.Popen] = {}
    interrupted = Event()

    def request_shutdown(signum: int, _frame: object) -> None:
        print(f"Received {signal.Signals(signum).name}; stopping application", flush=True)
        interrupted.set()

    previous_handlers = {
        signal.SIGTERM: signal.signal(signal.SIGTERM, request_shutdown),
        signal.SIGINT: signal.signal(signal.SIGINT, request_shutdown),
    }
    commands = {
        "web": ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"],
        "worker": ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel", source.get("LOG_LEVEL", "INFO")],
        "scheduler": [
            "celery",
            "-A",
            "app.worker.celery_app",
            "beat",
            "--loglevel",
            source.get("LOG_LEVEL", "INFO"),
            "--schedule",
            source.get("CELERY_BEAT_SCHEDULE", "/data/celerybeat-schedule"),
        ],
    }
    try:
        for name, command in commands.items():
            print(f"Starting {name}", flush=True)
            children[name] = subprocess.Popen(command, cwd=BACKEND_ROOT, env=source)

        while True:
            if interrupted.is_set():
                stop_children(children)
                return 0
            for name, child in children.items():
                returncode = child.poll()
                if returncode is not None:
                    print(f"{name} exited unexpectedly with code {returncode}", flush=True)
                    stop_children(children)
                    return 1
            time.sleep(0.2)
    finally:
        if any(child.poll() is None for child in children.values()):
            stop_children(children)
        signal.signal(signal.SIGTERM, previous_handlers[signal.SIGTERM])
        signal.signal(signal.SIGINT, previous_handlers[signal.SIGINT])


def _run_script(script: str, arguments: list[str], environment: MutableMapping[str, str]) -> int:
    command = ["sh", script, *arguments]
    return subprocess.run(command, cwd=BACKEND_ROOT, env=dict(environment), check=False).returncode


def main(arguments: list[str] | None = None) -> int:
    arguments = list(arguments if arguments is not None else sys.argv[1:])
    role = arguments.pop(0) if arguments else "all"
    application_roles = {"all", "web", "worker", "scheduler", "migrate"}
    try:
        environment = configure_environment(require_application=role in application_roles)
        if role in {"all", "migrate"}:
            wait_for_dependencies(environment)
        if role in {"all", "migrate"} or (
            role == "web" and environment.get("RUN_MIGRATIONS", "true") == "true"
        ):
            run_migrations(environment)
        if role == "all":
            return supervise(environment)
        if role == "web":
            return subprocess.run(
                ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", *arguments],
                cwd=BACKEND_ROOT,
                env=dict(environment),
                check=False,
            ).returncode
        if role == "worker":
            return subprocess.run(
                ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel", environment.get("LOG_LEVEL", "INFO"), *arguments],
                cwd=BACKEND_ROOT,
                env=dict(environment),
                check=False,
            ).returncode
        if role == "scheduler":
            return subprocess.run(
                [
                    "celery", "-A", "app.worker.celery_app", "beat",
                    "--loglevel", environment.get("LOG_LEVEL", "INFO"),
                    "--schedule", environment.get("CELERY_BEAT_SCHEDULE", "/data/celerybeat-schedule"),
                    *arguments,
                ],
                cwd=BACKEND_ROOT,
                env=dict(environment),
                check=False,
            ).returncode
        if role == "migrate":
            return 0
        if role == "backup":
            return _run_script("/opt/meal-planner/backup.sh", arguments, environment)
        if role == "restore":
            return _run_script("/opt/meal-planner/restore.sh", arguments, environment)
        print("Unknown role: expected all, web, worker, scheduler, migrate, backup, or restore", file=sys.stderr)
        return 64
    except DeploymentConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 64
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 75
    except Exception as exc:
        print(f"{role} failed: {type(exc).__name__}", file=sys.stderr)
        return 1
