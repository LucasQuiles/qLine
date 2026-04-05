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


def main():
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

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    src_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, src_dir)

    from statusline import normalize, load_config, render_context_bar, render, _alert_state
    from context_overhead import inject_context_overhead

    theme = load_config()
    last_mtime = 0

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

            state = normalize(payload)

            # Lightweight overhead injection (reads from cache, not transcript)
            cache_path = "/tmp/qline-cache.json"
            def load_cache():
                try:
                    with open(cache_path) as f:
                        return json.load(f)
                except Exception:
                    return {}

            def save_cache(c):
                try:
                    with open(cache_path, "w") as f:
                        json.dump(c, f)
                except Exception:
                    pass

            cache_ctx = {
                "load_cache": load_cache,
                "save_cache": save_cache,
                "cache_max_age": 300,
                "obs_available": False,
                "resolve_package_root": None,
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

    # Cleanup
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass


if __name__ == "__main__":
    main()
