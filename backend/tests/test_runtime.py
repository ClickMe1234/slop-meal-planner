from __future__ import annotations

from types import SimpleNamespace

from app import runtime


def test_worker_role_does_not_run_migrations(monkeypatch):
    environment = {
        "MEAL_PLANNER_DATABASE_URL": "postgresql+psycopg://u:p@db/app",
        "CELERY_BROKER_URL": "redis://redis:6379/0",
        "CELERY_RESULT_BACKEND": "redis://redis:6379/1",
        "MEAL_PLANNER_SECRET_KEY": "a" * 32,
        "MEAL_PLANNER_SETUP_TOKEN": "b" * 32,
    }
    monkeypatch.setattr(runtime, "configure_environment", lambda **_: environment)
    monkeypatch.setattr(runtime, "run_migrations", lambda *_: (_ for _ in ()).throw(AssertionError("migrated")))
    calls: list[list[str]] = []

    def fake_run(command, **_):
        calls.append(command)
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    assert runtime.main(["worker"]) == 7
    assert calls[0][:4] == ["celery", "-A", "app.worker.celery_app", "worker"]


def test_stop_children_terminates_and_reaps_every_child():
    class FakeChild:
        def __init__(self):
            self.returncode = None
            self.terminated = False
            self.killed = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self):
            return self.returncode

    first, second = FakeChild(), FakeChild()
    runtime.stop_children({"web": first, "worker": second}, grace_seconds=0)

    assert first.terminated and second.terminated
    assert first.returncode == 0 and second.returncode == 0

