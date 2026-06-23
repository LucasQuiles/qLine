"""T1: characterization coverage for the two enforcement-gate hooks —
subagent-stop-gate.py (SubagentStop handoff quality) and
task-completed-gate.py (TaskCompleted evidence).

These gates had ZERO coverage despite enforcing strict/warn branching, an
exempt-list bypass, and a tri-state git probe — and they BLOCK differently:
  * subagent-stop-gate strict  -> block_stop(): prints {"decision":"block"} JSON, exit 0
  * task-completed-gate strict  -> inline print(stderr) + exit 2
Both contracts are pinned here.

Run end-to-end as subprocesses (the gate contract IS the exit code + decision
output). HOME is redirected to a tmp dir so the real fault ledger
(~/.claude/logs/lifecycle-hook-faults.jsonl) is never touched.
"""
import json
import os
import subprocess
import sys

HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..")
SUBAGENT_GATE = os.path.join(HOOKS_DIR, "subagent-stop-gate.py")
TASK_GATE = os.path.join(HOOKS_DIR, "task-completed-gate.py")


def _run(script: str, payload, tmp_home, extra_env=None):
    """Run a gate hook as a subprocess with isolated HOME. payload=None -> empty stdin."""
    env = {**os.environ, "HOME": str(tmp_home)}
    # Drop any inherited strict flags so each test controls them explicitly.
    env.pop("CLAUDE_SUBAGENT_STOP_STRICT", None)
    env.pop("CLAUDE_TASK_COMPLETED_STRICT", None)
    if extra_env:
        env.update(extra_env)
    stdin = "" if payload is None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, script],
        input=stdin, capture_output=True, text=True, timeout=10, env=env,
    )


def _git_init(path) -> str:
    path = str(path)
    subprocess.run(["git", "init", "-q", path], check=True, capture_output=True)
    return path


# --- subagent-stop-gate -----------------------------------------------------

class TestSubagentStopGate:
    def test_empty_stdin_fails_open(self, tmp_path):
        r = _run(SUBAGENT_GATE, None, tmp_path)
        assert r.returncode == 0
        assert r.stdout.strip() == ""

    def test_exempt_agent_bypasses_even_when_strict(self, tmp_path):
        """An Explore agent with an empty handoff must NOT block even in strict mode —
        the exempt-list short-circuits before the quality check."""
        r = _run(SUBAGENT_GATE, {"agent_type": "Explore", "agent_id": "a1",
                                  "last_assistant_message": ""},
                 tmp_path, {"CLAUDE_SUBAGENT_STOP_STRICT": "1"})
        assert r.returncode == 0
        assert "block" not in r.stdout

    def test_minimal_handoff_warn_mode_does_not_block(self, tmp_path):
        r = _run(SUBAGENT_GATE, {"agent_type": "general-purpose", "agent_id": "a2",
                                 "last_assistant_message": ""}, tmp_path)
        assert r.returncode == 0
        assert '"decision": "block"' not in r.stdout

    def test_minimal_handoff_strict_mode_blocks(self, tmp_path):
        r = _run(SUBAGENT_GATE, {"agent_type": "general-purpose", "agent_id": "a3",
                                 "last_assistant_message": "ok"},
                 tmp_path, {"CLAUDE_SUBAGENT_STOP_STRICT": "1"})
        assert r.returncode == 0
        out = json.loads(r.stdout)
        assert out["hookSpecificOutput"]["decision"] == "block"
        assert out["hookSpecificOutput"]["hookEventName"] == "SubagentStop"

    def test_no_outcome_signals_strict_mode_blocks(self, tmp_path):
        """A long-enough message with none of the HANDOFF_SIGNALS words still blocks."""
        msg = "x" * 80  # >= MIN_MESSAGE_LENGTH but no signal substring
        r = _run(SUBAGENT_GATE, {"agent_type": "general-purpose", "agent_id": "a4",
                                 "last_assistant_message": msg},
                 tmp_path, {"CLAUDE_SUBAGENT_STOP_STRICT": "1"})
        assert r.returncode == 0
        assert json.loads(r.stdout)["hookSpecificOutput"]["decision"] == "block"

    def test_good_handoff_passes_silently_even_when_strict(self, tmp_path):
        """A long message containing outcome signals must NOT block, proving the
        block path is content-driven, not unconditional."""
        msg = "Implemented the retry path and fixed the failing auth test in login.py"
        r = _run(SUBAGENT_GATE, {"agent_type": "general-purpose", "agent_id": "a5",
                                 "last_assistant_message": msg},
                 tmp_path, {"CLAUDE_SUBAGENT_STOP_STRICT": "1"})
        assert r.returncode == 0
        assert "block" not in r.stdout


# --- task-completed-gate ----------------------------------------------------

class TestTaskCompletedGate:
    def test_empty_stdin_fails_open(self, tmp_path):
        r = _run(TASK_GATE, None, tmp_path)
        assert r.returncode == 0

    def test_exempt_subject_bypasses(self, tmp_path):
        r = _run(TASK_GATE, {"task_id": "1", "task_subject": "research the API",
                             "task_description": "", "cwd": str(tmp_path)}, tmp_path)
        assert r.returncode == 0
        assert r.stderr.strip() == ""

    def test_code_task_clean_repo_strict_exits_2(self, tmp_path):
        """code keyword + clean git + strict -> blocks completion with exit 2."""
        repo = _git_init(tmp_path / "repo")  # fresh init = no changes = clean
        r = _run(TASK_GATE, {"task_id": "2", "task_subject": "implement login",
                             "task_description": "", "cwd": repo},
                 tmp_path, {"CLAUDE_TASK_COMPLETED_STRICT": "1"})
        assert r.returncode == 2
        assert "task-completed-gate" in r.stderr

    def test_code_task_clean_repo_warn_mode_exits_0_with_warning(self, tmp_path):
        repo = _git_init(tmp_path / "repo")
        r = _run(TASK_GATE, {"task_id": "3", "task_subject": "implement login",
                             "task_description": "", "cwd": repo}, tmp_path)
        assert r.returncode == 0
        assert "Warning:" in r.stderr

    def test_dirty_repo_is_evidence_no_warning(self, tmp_path):
        """Uncommitted changes count as evidence -> no warning even for a code task."""
        repo = _git_init(tmp_path / "repo")
        with open(os.path.join(repo, "touched.txt"), "w") as f:
            f.write("work")
        r = _run(TASK_GATE, {"task_id": "4", "task_subject": "implement login",
                             "task_description": "", "cwd": repo},
                 tmp_path, {"CLAUDE_TASK_COMPLETED_STRICT": "1"})
        assert r.returncode == 0
        assert "completed without detected file changes" not in r.stderr

    def test_non_git_cwd_unknown_probe_fails_open(self, tmp_path):
        """git probe 'unknown' (cwd not a repo) -> safety bias, exit 0 even in strict."""
        non_repo = tmp_path / "plain"
        non_repo.mkdir()
        r = _run(TASK_GATE, {"task_id": "5", "task_subject": "implement login",
                             "task_description": "", "cwd": str(non_repo)},
                 tmp_path, {"CLAUDE_TASK_COMPLETED_STRICT": "1"})
        assert r.returncode == 0
