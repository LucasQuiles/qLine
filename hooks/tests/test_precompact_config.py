# hooks/tests/test_precompact_config.py
"""Tests for the centralized PreCompact config surface."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestDefaults:
    def test_capsule_and_handoff_default_under_claude(self, monkeypatch):
        import precompact_config as C
        for var in ("PRECOMPACT_CAPSULE_DIR", "PRECOMPACT_HANDOFF_DIR"):
            monkeypatch.delenv(var, raising=False)
        assert C.capsule_dir().endswith("/.claude/precompact-capsules")
        assert C.handoff_dir().endswith("/.claude/precompact-handoff")

    def test_ledger_default(self, monkeypatch):
        import precompact_config as C
        monkeypatch.delenv("PRECOMPACT_LEDGER_PATH", raising=False)
        assert C.ledger_path().endswith("brick-lab/action-ledger.jsonl")

    def test_tunable_defaults(self, monkeypatch):
        import precompact_config as C
        for var in ("PRECOMPACT_PRODUCER_DEADLINE_S",
                    "PRECOMPACT_MAX_REPOS", "PRECOMPACT_MAX_FAILURES"):
            monkeypatch.delenv(var, raising=False)
        assert C.per_producer_deadline_s() == 3.0
        assert C.max_repos() == 5
        assert C.max_failures() == 10


class TestEnvOverrides:
    def test_path_override(self, monkeypatch):
        import precompact_config as C
        monkeypatch.setenv("PRECOMPACT_CAPSULE_DIR", "/tmp/caps")
        monkeypatch.setenv("PRECOMPACT_LEDGER_PATH", "/tmp/led.jsonl")
        assert C.capsule_dir() == "/tmp/caps"
        assert C.ledger_path() == "/tmp/led.jsonl"

    def test_empty_env_falls_back_to_default(self, monkeypatch):
        import precompact_config as C
        monkeypatch.setenv("PRECOMPACT_CAPSULE_DIR", "")
        assert C.capsule_dir().endswith("/.claude/precompact-capsules")

    def test_tunable_override_and_garbage_ignored(self, monkeypatch):
        import precompact_config as C
        monkeypatch.setenv("PRECOMPACT_MAX_FAILURES", "25")
        assert C.max_failures() == 25
        monkeypatch.setenv("PRECOMPACT_MAX_FAILURES", "not-an-int")
        assert C.max_failures() == 10  # garbage -> default


class TestBotpatchesSterile:
    # A portable tool must not ship a host's chat id. Default is empty
    # (forwarding disabled); a deployer opts in via the env var.
    def test_default_is_empty(self, monkeypatch):
        import precompact_config as C
        monkeypatch.delenv("PRECOMPACT_BOTPATCHES_CHAT", raising=False)
        assert C.botpatches_chat() == ""

    def test_no_hardcoded_jid_in_source(self):
        # The literal JID must not be reintroduced into any module.
        hooks_dir = os.path.join(os.path.dirname(__file__), "..")
        for fn in os.listdir(hooks_dir):
            if fn.startswith("precompact") and fn.endswith(".py"):
                with open(os.path.join(hooks_dir, fn)) as f:
                    assert "@g.us" not in f.read(), f"hardcoded JID in {fn}"

    def test_override(self, monkeypatch):
        import precompact_config as C
        monkeypatch.setenv("PRECOMPACT_BOTPATCHES_CHAT", "123@g.us")
        assert C.botpatches_chat() == "123@g.us"
