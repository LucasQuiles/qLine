"""Register qLine observability hooks in Claude Code settings.json."""
import json
import sys

if len(sys.argv) < 3:
    print("Usage: register_obs_hooks.py <settings.json> <hooks_dir>", file=sys.stderr)
    sys.exit(1)

settings_path = sys.argv[1]
hooks_dir = sys.argv[2]

with open(settings_path) as f:
    settings = json.load(f)

hooks = settings.setdefault("hooks", {})

# (event, matcher, hook_filename, timeout_ms)
OBS_HOOKS = [
    ("SessionStart", ".*", "obs-session-start.py", 5000),
    ("PreToolUse", "Read", "obs-pretool-read.py", 5000),
    ("PostToolUse", "Write", "obs-posttool-write.py", 5000),
    ("PostToolUse", "Bash", "obs-posttool-bash.py", 5000),
    ("PostToolUse", "Edit|MultiEdit", "obs-posttool-edit.py", 5000),
    ("UserPromptSubmit", ".*", "obs-prompt-submit.py", 5000),
    ("Stop", ".*", "obs-stop-cache.py", 2000),
    ("PreCompact", ".*", "obs-precompact.py", 5000),
    ("SubagentStop", ".*", "obs-subagent-stop.py", 5000),
    ("SessionEnd", ".*", "obs-session-end.py", 5000),
    ("TaskCompleted", ".*", "obs-task-completed.py", 5000),
]

registered = 0
for event, matcher, filename, timeout in OBS_HOOKS:
    command = f"{hooks_dir}/{filename}"
    event_hooks = hooks.setdefault(event, [])

    # Check if already registered
    already = any(
        any(h.get("command") == command for h in entry.get("hooks", []))
        for entry in event_hooks
    )
    if not already:
        event_hooks.append({
            "matcher": matcher,
            "hooks": [{"type": "command", "command": command, "timeout": timeout}]
        })
        registered += 1

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)

print(f"  Registered {registered} obs hooks ({len(OBS_HOOKS) - registered} already present)")
