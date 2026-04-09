#!/usr/bin/env python3
"""qLine animation daemon — re-renders statusline on a 200ms timer.

Launched by statusline.py on first invocation. Writes rendered output
to /tmp/qline-live.txt. The statusline.py script reads this file for
fast output, only doing full computation every 30s.

The daemon exits after 5 minutes of no payload updates (session ended).
"""
import json
import os
import signal
import sys
import time

LIVE_FILE = "/tmp/qline-live.txt"
PAYLOAD_FILE = "/tmp/qline-payload.json"
PID_FILE = "/tmp/qline-daemon.pid"
RENDER_INTERVAL = 0.2  # 200ms
IDLE_TIMEOUT = 300  # 5 minutes


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def main():
    global LIVE_FILE, PID_FILE, PAYLOAD_FILE
    # PID guard — prevent multiple daemons
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            if _is_pid_alive(old_pid):
                return  # existing daemon is running
        except (ValueError, OSError):
            pass  # stale or corrupt PID file — take over

    # Daemonize
    if os.fork() != 0:
        return  # parent exits

    os.setsid()
    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # Redirect stdio
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)

    signal.signal(signal.SIGTERM, lambda *_: _cleanup_and_exit())

    src_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, src_dir)

    from statusline import (
        normalize, load_config, render, load_cache, save_cache,
        _inject_obs_counters, collect_system_data, CACHE_MAX_AGE_S, _OBS_AVAILABLE,
        _init_session_paths, _session_hash, SYSTEM_CACHE_TTL,
    )
    from context_overhead import inject_context_overhead
    if _OBS_AVAILABLE:
        from obs_utils import resolve_package_root
    else:
        resolve_package_root = None

    theme = load_config()
    last_system_collect = 0.0
    SYSTEM_COLLECT_INTERVAL = SYSTEM_CACHE_TTL  # 60s — match tiered TTL

    session_initialized = False

    while True:
        try:
            # Check if payload file was updated
            try:
                mtime = os.path.getmtime(PAYLOAD_FILE)
            except OSError:
                time.sleep(RENDER_INTERVAL)
                continue

            # Exit if idle too long
            if time.time() - mtime > IDLE_TIMEOUT:
                break

            # Re-render on each tick (animation frames change via time.time())
            with open(PAYLOAD_FILE) as f:
                payload = json.load(f)

            # Session-scope paths on first payload read
            if not session_initialized:
                sid = payload.get("session_id")
                if isinstance(sid, str) and sid:
                    _init_session_paths(sid)
                    h = _session_hash(sid)
                    LIVE_FILE = f"/tmp/qline-{h}-live.txt"
                    PAYLOAD_FILE = f"/tmp/qline-{h}-payload.json"
                    new_pid = f"/tmp/qline-{h}-daemon.pid"
                    with open(new_pid, "w") as pf:
                        pf.write(str(os.getpid()))
                    # Clean up old global PID file
                    try:
                        os.unlink(PID_FILE)
                    except OSError:
                        pass
                    PID_FILE = new_pid
                session_initialized = True

            state = normalize(payload)

            # System data collection — throttled to avoid subprocess storms
            now = time.time()
            if now - last_system_collect >= SYSTEM_COLLECT_INTERVAL:
                collect_system_data(state, theme)
                last_system_collect = now
            else:
                # Apply cached system data from main script's last run
                cache = load_cache()
                for name in ("git", "cpu", "memory", "disk", "agents", "tmux"):
                    entry = cache.get(name)
                    if isinstance(entry, dict):
                        values = entry.get("value", {})
                        if isinstance(values, dict):
                            state.update(values)

            # Obs counter injection (reads from cache, cheap)
            _inject_obs_counters(state, payload)

            # Context overhead injection
            cache_ctx = {
                "load_cache": load_cache,
                "save_cache": save_cache,
                "cache_max_age": CACHE_MAX_AGE_S,
                "obs_available": _OBS_AVAILABLE,
                "resolve_package_root": resolve_package_root,
            }
            inject_context_overhead(state, payload, theme, cache_ctx)

            output = render(state, theme)
            if output:
                tmp = LIVE_FILE + ".tmp"
                with open(tmp, "w") as f:
                    f.write(output)
                os.rename(tmp, LIVE_FILE)

        except Exception:
            pass

        time.sleep(RENDER_INTERVAL)

    _cleanup_and_exit()


def _cleanup_and_exit():
    """Clean up PID file and exit."""
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
