#!/usr/bin/env python3
"""T2 Latency Benchmark — measure per-segment pipeline latency.

Runs against real sessions from ~/.claude/observability/sessions/.
Instruments each code path in the statusline pipeline using time.perf_counter().

Usage:
    python3 tests/t2_latency_benchmark.py

Output: JSON with per-segment timing for each session size class.
"""
from __future__ import annotations

import json
import os
import sys
import time
import hashlib
import statistics

# Add source paths
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))
sys.path.insert(0, os.path.join(REPO_ROOT, "hooks"))

# Prevent live collection
os.environ["QLINE_NO_COLLECT"] = "1"

from context_overhead import (
    _read_transcript_tail,
    _read_manifest_anchor,
    _estimate_static_overhead,
    inject_context_overhead,
)
from obs_utils import resolve_package_root, resolve_package_root_env

# ---------------------------------------------------------------------------
# Session registry — real sessions at different scales
# ---------------------------------------------------------------------------

OBS_ROOT = os.path.expanduser("~/.claude/observability")

SESSIONS = {
    "small_42": {
        "session_id": "7968468c-087d-4e5c-b8fb-640486a4c288",
        "events": 42,
        "transcript": os.path.expanduser(
            "~/.claude/projects/-Users-q/7968468c-087d-4e5c-b8fb-640486a4c288.jsonl"
        ),
    },
    "medium_335": {
        "session_id": "fce19404-6a24-4b74-bab5-a979fb73752b",
        "events": 335,
        "transcript": os.path.expanduser(
            "~/.claude/projects/-Users-q/fce19404-6a24-4b74-bab5-a979fb73752b.jsonl"
        ),
    },
    "large_842": {
        "session_id": "20053f3f-961b-4280-a1a4-77f8b14ad263",
        "events": 842,
        "transcript": os.path.expanduser(
            "~/.claude/projects/-Users-q/20053f3f-961b-4280-a1a4-77f8b14ad263.jsonl"
        ),
    },
    "xlarge_2440": {
        "session_id": "20db3daa-f160-4b2a-b47f-e2504adb8ae6",
        "events": 2440,
        "transcript": os.path.expanduser(
            "~/.claude/projects/-Users-q/20db3daa-f160-4b2a-b47f-e2504adb8ae6.jsonl"
        ),
    },
}


def time_fn(fn, *args, iterations=10, **kwargs):
    """Run fn N times, return min/median/p95/max in ms."""
    times = []
    result = None
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    times.sort()
    p95_idx = int(len(times) * 0.95)
    return {
        "min_ms": round(times[0], 3),
        "median_ms": round(statistics.median(times), 3),
        "p95_ms": round(times[p95_idx], 3),
        "max_ms": round(times[-1], 3),
        "samples": len(times),
    }, result


# ---------------------------------------------------------------------------
# Segment benchmarks
# ---------------------------------------------------------------------------

def bench_hook_events_scan(package_root):
    """Segment J-K: Full scan of hook_events.jsonl for event counts."""
    ledger = os.path.join(package_root, "metadata", "hook_events.jsonl")

    def scan():
        counts = {}
        try:
            with open(ledger) as f:
                for line in f:
                    idx = line.find('"event": "')
                    if idx >= 0:
                        start = idx + 10
                        end = line.find('"', start)
                        if end > start:
                            event = line[start:end]
                            counts[event] = counts.get(event, 0) + 1
        except Exception:
            pass
        return counts

    return time_fn(scan, iterations=20)


def bench_rereads_scan(package_root):
    """Segment J (sub): reads.jsonl reread count scan."""
    reads_path = os.path.join(package_root, "custom", "reads.jsonl")

    def scan():
        total = reread = 0
        try:
            with open(reads_path) as f:
                for line in f:
                    total += 1
                    if '"is_reread": true' in line:
                        reread += 1
        except Exception:
            pass
        return total, reread

    return time_fn(scan, iterations=20)


def bench_manifest_read(package_root):
    """Segment I: manifest.json read + parse."""
    manifest = os.path.join(package_root, "manifest.json")

    def read():
        try:
            with open(manifest) as f:
                return json.load(f)
        except Exception:
            return {}

    return time_fn(read, iterations=20)


def bench_manifest_anchor(package_root):
    """Segment I (sub): Read cache_anchor from manifest."""
    return time_fn(_read_manifest_anchor, package_root, iterations=20)


def bench_transcript_tail(transcript_path, window=5):
    """Segment H: Transcript tail read."""
    if not os.path.isfile(transcript_path):
        return {"error": "transcript not found"}, None
    return time_fn(_read_transcript_tail, transcript_path, window_size=window, iterations=10)


def bench_cache_io():
    """Segment L: Cache read + write roundtrip."""
    cache_path = "/tmp/qline-bench-cache.json"

    def read_cache():
        try:
            with open(cache_path) as f:
                return json.load(f)
        except Exception:
            return {}

    def write_cache(data):
        import tempfile
        try:
            fd = tempfile.NamedTemporaryFile(
                mode="w", dir="/tmp", prefix="qline-bench-", suffix=".tmp", delete=False
            )
            json.dump(data, fd)
            fd.flush()
            os.fsync(fd.fileno())
            fd.close()
            os.rename(fd.name, cache_path)
        except Exception:
            pass

    # Seed a realistic cache
    sample = {
        "version": 1,
        "modules": {
            "git_branch": "main",
            "git_sha": "abc123",
            "cpu_percent": 45,
            "_obs": {
                "test-session": {
                    "event_counts": {"file.read": 10, "bash.executed": 5},
                    "last_count_ts": time.time(),
                }
            },
        },
    }
    with open(cache_path, "w") as f:
        json.dump(sample, f)

    read_timing, _ = time_fn(read_cache, iterations=20)
    write_timing, _ = time_fn(write_cache, sample, iterations=20)

    # Cleanup
    try:
        os.unlink(cache_path)
    except OSError:
        pass

    return {"read": read_timing, "write": write_timing}


def bench_static_overhead_estimate():
    """Segment G (Phase 1): Static overhead estimation."""
    return time_fn(_estimate_static_overhead, iterations=20)


def bench_obs_health_read(package_root):
    """Read overall health from manifest."""
    manifest = os.path.join(package_root, "manifest.json")

    def read():
        try:
            with open(manifest) as f:
                m = json.load(f)
            return m.get("health", {}).get("overall", "unknown")
        except Exception:
            return "unknown"

    return time_fn(read, iterations=20)


def bench_resolve_package_root(session_id):
    """Segment: resolve_package_root via runtime map."""
    # Clear the cache to measure cold path
    from obs_utils import _package_root_cache
    _package_root_cache.clear()

    def resolve_cold():
        _package_root_cache.clear()
        return resolve_package_root(session_id)

    cold_timing, _ = time_fn(resolve_cold, iterations=20)

    # Now measure warm path (cached)
    resolve_package_root(session_id)  # warm the cache
    warm_timing, pkg = time_fn(resolve_package_root, session_id, iterations=20)

    return {"cold": cold_timing, "warm": warm_timing}, pkg


def bench_seq_counter(package_root):
    """Measure seq counter read time (read-only, no increment)."""
    seq_path = os.path.join(package_root, "metadata", ".seq_counter")

    def read_seq():
        try:
            with open(seq_path) as f:
                return int(f.read().strip() or "0")
        except Exception:
            return 0

    return time_fn(read_seq, iterations=20)


# ---------------------------------------------------------------------------
# Full pipeline simulation
# ---------------------------------------------------------------------------

def bench_full_pipeline(session_id, transcript_path, package_root, theme):
    """Simulate the full statusline pipeline (minus stdin read and render).

    Measures: resolve_package_root + _inject_obs_counters path + inject_context_overhead.
    """
    from obs_utils import _package_root_cache

    # Build a realistic payload
    payload = {
        "session_id": session_id,
        "model": {"display_name": "Opus 4.6 (1M context)"},
        "version": "2.1.92",
        "cost": {"total_cost_usd": 1.23, "total_duration_ms": 45000},
        "context_window": {
            "used_percentage": 35.0,
            "context_window_size": 1000000,
            "used": 350000,
            "total": 1000000,
            "total_input_tokens": 280000,
            "total_output_tokens": 70000,
        },
    }

    cache_ctx = {
        "load_cache": lambda: {},
        "save_cache": lambda c: None,
        "cache_max_age": 60.0,
        "obs_available": True,
        "resolve_package_root": resolve_package_root_env,
    }

    def run_obs_counters():
        """Simulate _inject_obs_counters logic (inline since it's in statusline.py)."""
        state = {"transcript_path": transcript_path}
        _package_root_cache.clear()
        pkg = resolve_package_root(session_id)
        if pkg is None:
            return state

        # Event count scan
        ledger = os.path.join(pkg, "metadata", "hook_events.jsonl")
        counts = {}
        try:
            with open(ledger) as f:
                for line in f:
                    idx = line.find('"event": "')
                    if idx >= 0:
                        start = idx + 10
                        end = line.find('"', start)
                        if end > start:
                            event = line[start:end]
                            counts[event] = counts.get(event, 0) + 1
        except Exception:
            pass

        # Rereads
        reads_path = os.path.join(pkg, "custom", "reads.jsonl")
        total = reread = 0
        try:
            with open(reads_path) as f:
                for line in f:
                    total += 1
                    if '"is_reread": true' in line:
                        reread += 1
        except Exception:
            pass

        # Health
        manifest = os.path.join(pkg, "manifest.json")
        try:
            with open(manifest) as f:
                m = json.load(f)
            health = m.get("health", {}).get("overall", "unknown")
        except Exception:
            health = "unknown"

        state["obs_reads"] = total
        state["obs_reread_count"] = reread
        state["obs_writes"] = counts.get("file.write.diff", 0)
        state["obs_bash"] = counts.get("bash.executed", 0)
        state["obs_failures"] = counts.get("tool.failed", 0)
        return state

    def run_overhead():
        state = {"transcript_path": transcript_path}
        inject_context_overhead(state, payload, theme, cache_ctx)
        return state

    obs_timing, _ = time_fn(run_obs_counters, iterations=5)
    overhead_timing, _ = time_fn(run_overhead, iterations=5)

    return {"obs_counters": obs_timing, "overhead_injection": overhead_timing}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    results = {}

    # Cache I/O (session-independent)
    print("Benchmarking cache I/O...", file=sys.stderr)
    results["cache_io"] = bench_cache_io()

    # Static overhead estimate (session-independent)
    print("Benchmarking static overhead estimate...", file=sys.stderr)
    timing, est = bench_static_overhead_estimate()
    results["static_overhead_estimate"] = {"timing": timing, "value": est}

    theme = {
        "context_bar": {
            "overhead_source": "auto",
            "cache_warn_rate": 0.8,
            "cache_critical_rate": 0.3,
        },
    }

    for label, info in SESSIONS.items():
        sid = info["session_id"]
        tp = info["transcript"]
        events = info["events"]

        print(f"\nBenchmarking session {label} ({events} events)...", file=sys.stderr)
        session_results = {"events": events}

        # Resolve package root
        resolve_timing, pkg = bench_resolve_package_root(sid)
        session_results["resolve_package_root"] = resolve_timing

        if pkg is None:
            print(f"  SKIP: package_root not found for {sid}", file=sys.stderr)
            results[label] = session_results
            continue

        # File sizes
        ledger_path = os.path.join(pkg, "metadata", "hook_events.jsonl")
        reads_path = os.path.join(pkg, "custom", "reads.jsonl")
        manifest_path = os.path.join(pkg, "manifest.json")
        session_results["file_sizes"] = {
            "hook_events_bytes": os.path.getsize(ledger_path) if os.path.isfile(ledger_path) else 0,
            "reads_bytes": os.path.getsize(reads_path) if os.path.isfile(reads_path) else 0,
            "manifest_bytes": os.path.getsize(manifest_path) if os.path.isfile(manifest_path) else 0,
            "transcript_bytes": os.path.getsize(tp) if os.path.isfile(tp) else 0,
        }

        # Segment benchmarks
        timing, _ = bench_hook_events_scan(pkg)
        session_results["hook_events_scan"] = timing

        timing, _ = bench_rereads_scan(pkg)
        session_results["rereads_scan"] = timing

        timing, _ = bench_manifest_read(pkg)
        session_results["manifest_read"] = timing

        timing, _ = bench_manifest_anchor(pkg)
        session_results["manifest_anchor"] = timing

        timing, _ = bench_transcript_tail(tp, window=5)
        session_results["transcript_tail_w5"] = timing

        timing, _ = bench_transcript_tail(tp, window=8)
        session_results["transcript_tail_w8"] = timing

        timing, _ = bench_obs_health_read(pkg)
        session_results["obs_health_read"] = timing

        timing, _ = bench_seq_counter(pkg)
        session_results["seq_counter_read"] = timing

        # Full pipeline simulation
        pipeline = bench_full_pipeline(sid, tp, pkg, theme)
        session_results["full_pipeline"] = pipeline

        results[label] = session_results

    # Print results
    print("\n" + "=" * 70, file=sys.stderr)
    print("T2 LATENCY BENCHMARK RESULTS", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    print(json.dumps(results, indent=2))

    # Print summary table to stderr
    print("\n--- SUMMARY TABLE ---", file=sys.stderr)
    print(f"{'Segment':<30} {'Small(42)':<14} {'Med(335)':<14} {'Large(842)':<14} {'XL(2440)':<14}", file=sys.stderr)
    print("-" * 86, file=sys.stderr)

    segments = [
        ("hook_events_scan", "J-K: Event scan"),
        ("rereads_scan", "J: Rereads scan"),
        ("manifest_read", "I: Manifest read"),
        ("manifest_anchor", "I: Manifest anchor"),
        ("transcript_tail_w5", "H: Transcript tail(w5)"),
        ("transcript_tail_w8", "H: Transcript tail(w8)"),
        ("obs_health_read", "Health read"),
        ("seq_counter_read", "Seq counter read"),
    ]

    for key, label in segments:
        vals = []
        for skey in ["small_42", "medium_335", "large_842", "xlarge_2440"]:
            s = results.get(skey, {})
            v = s.get(key, {})
            if isinstance(v, dict) and "median_ms" in v:
                vals.append(f"{v['median_ms']:.2f}ms")
            else:
                vals.append("N/A")
        print(f"{label:<30} {vals[0]:<14} {vals[1]:<14} {vals[2]:<14} {vals[3]:<14}", file=sys.stderr)

    # Pipeline segments
    print("\n--- PIPELINE SEGMENTS ---", file=sys.stderr)
    for skey in ["small_42", "medium_335", "large_842", "xlarge_2440"]:
        s = results.get(skey, {})
        p = s.get("full_pipeline", {})
        obs = p.get("obs_counters", {})
        ovh = p.get("overhead_injection", {})
        print(f"{skey}: obs_counters={obs.get('median_ms','N/A')}ms, overhead={ovh.get('median_ms','N/A')}ms", file=sys.stderr)

    # Cache I/O
    ci = results.get("cache_io", {})
    print(f"\nCache read: {ci.get('read',{}).get('median_ms','N/A')}ms", file=sys.stderr)
    print(f"Cache write: {ci.get('write',{}).get('median_ms','N/A')}ms", file=sys.stderr)

    # Resolve timing
    print("\n--- RESOLVE PACKAGE ROOT ---", file=sys.stderr)
    for skey in ["small_42", "medium_335", "large_842", "xlarge_2440"]:
        s = results.get(skey, {})
        r = s.get("resolve_package_root", {})
        cold = r.get("cold", {})
        warm = r.get("warm", {})
        print(f"{skey}: cold={cold.get('median_ms','N/A')}ms, warm={warm.get('median_ms','N/A')}ms", file=sys.stderr)


if __name__ == "__main__":
    main()
