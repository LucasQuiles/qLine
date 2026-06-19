# hooks/tests/test_precompact_orchestrator.py
"""Integration tests for the PreCompact orchestrator hook."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..")
ORCH = os.path.join(HOOKS_DIR, "precompact-orchestrator.py")


def _run(payload: dict, env_extra: dict, tmp_path):
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)            # isolate capsule/handoff/task dirs
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, ORCH],
        input=json.dumps(payload), capture_output=True, text=True,
        env=env, timeout=30,
    )


class TestEnvGate:
    def test_disabled_emits_nothing(self, tmp_path):
        proc = _run({"session_id": "s"}, {}, tmp_path)  # flag unset
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_enabled_runs(self, tmp_path):
        proc = _run({"session_id": "s"}, {"PRECOMPACT_ORCHESTRATOR_ENABLED": "1"}, tmp_path)
        assert proc.returncode == 0


class TestGoldenParity:
    def test_reproduces_open_tasks_and_plan(self, tmp_path):
        sid = "golden-sess"
        task_dir = tmp_path / ".claude" / "tasks" / sid
        task_dir.mkdir(parents=True)
        (task_dir / "t1.json").write_text(json.dumps(
            {"id": "10", "subject": "wire tests", "status": "pending"}))
        plan_dir = tmp_path / ".claude" / "plans"
        plan_dir.mkdir(parents=True)
        (plan_dir / "2026-06-19-precompact-orchestrator.md").write_text("# plan")

        proc = _run({"session_id": sid}, {"PRECOMPACT_ORCHESTRATOR_ENABLED": "1"}, tmp_path)
        out = json.loads(proc.stdout)
        msg = out["systemMessage"]
        assert "Open tasks (1):" in msg
        assert "[pending] #10: wire tests" in msg
        assert "Active plan: 2026-06-19-precompact-orchestrator.md" in msg
        from precompact_capsule import read_capsule
        cap = read_capsule(sid, base_dir=str(tmp_path / ".claude" / "precompact-capsules"))
        assert cap["open_tasks"].startswith("Open tasks")
        assert "preserve" in cap["_producers_ok"]


class TestEmptySession:
    def test_empty_session_emits_no_systemmessage(self, tmp_path):
        proc = _run({"session_id": "empty-sess"},
                    {"PRECOMPACT_ORCHESTRATOR_ENABLED": "1"}, tmp_path)
        assert proc.returncode == 0
        if proc.stdout.strip():
            out = json.loads(proc.stdout)
            assert "systemMessage" not in out


class TestProducerFailure:
    def test_failing_producer_recorded_capsule_still_ships(self, tmp_path, monkeypatch):
        import importlib
        orch = importlib.import_module("precompact_orchestrator_lib")
        results, failed = orch.run_producers(
            {"session_id": "s"},
            producers=["preserve", "boom"],
            runner=lambda name, inp, deadline_s: (_ for _ in ()).throw(TimeoutError())
                if name == "boom" else None,
        )
        assert "boom" in failed


class TestConcurrentBudget:
    def test_producers_run_concurrently_not_serially(self):
        # 5 producers each "taking" 0.3s must finish well under the serial
        # sum (1.5s); concurrency bounds wall-clock to ~one producer.
        import time
        import importlib
        orch = importlib.import_module("precompact_orchestrator_lib")

        def slow_runner(name, inp, deadline_s):
            time.sleep(0.3)
            return None

        t0 = time.monotonic()
        results, failed = orch.run_producers(
            {"session_id": "s"},
            producers=["preserve", "git", "failures", "stats", "handoff"],
            runner=slow_runner,
        )
        elapsed = time.monotonic() - t0
        assert elapsed < 1.0, f"serial-looking: {elapsed:.2f}s for 5x0.3s"
        assert failed == []
        assert set(results) == {"preserve", "git", "failures", "stats", "handoff"}
