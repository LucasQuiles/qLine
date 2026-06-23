# hooks/recapture_producer.py
"""V6A recapture staleness scan. Emits paths + verdicts only — never bodies.

Mirrors the producer pattern: pure functions, fail-open at the adapter layer.

C1 fix: "1" and "0" are NOT in the bool-coercion sets. freshness_window_days
is parsed as int explicitly (via int(str(...))) BEFORE bool coercion, so a
doc with freshness_window_days: 1 is treated as window=1 day (an integer),
not coerced to True and then broken by int(str(True)) raising.
"""
from __future__ import annotations

import glob as _glob
import os
import re
import time as _time
from datetime import datetime

# C1 fix: exclude "1" and "0" — numeric strings are NOT boolean YAML values.
# YAML boolean: true/false/yes/no/on/off only.
_BOOL_TRUE = {"true", "yes", "on"}
_BOOL_FALSE = {"false", "no", "off"}

_FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

_REQUIRED_FIELDS = (
    "freshness_window_days", "recapture_owner",
    "recapture_trigger_files", "stale_action",
)


def parse_front_matter(path: str) -> dict | None:
    """Return the parsed leading YAML front-matter as a dict, or None if the
    file has no leading `---` block. Minimal scalar parser (no PyYAML dep).

    C1 fix: freshness_window_days is stored as its raw string value so the
    caller (classify) can int()-parse it independently of bool coercion.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(8192)
    except OSError:
        return None
    m = _FM_RE.match(head)
    if not m:
        return None
    fm: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        low = val.lower()
        # C1: only coerce recognized YAML bool tokens. Numeric strings pass
        # through as-is so freshness_window_days: 1 stays "1", not True.
        if low in _BOOL_TRUE:
            fm[key] = True
        elif low in _BOOL_FALSE:
            fm[key] = False
        else:
            fm[key] = val
    return fm


def missing_fields(fm: dict) -> list[str]:
    return [f for f in _REQUIRED_FIELDS if not fm.get(f)]


def _eod_epoch(date_str: str) -> float | None:
    """End-of-day local epoch for a YYYY-MM-DD string. None if unparseable."""
    try:
        d = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
    except (ValueError, AttributeError):
        return None
    eod = d.replace(hour=23, minute=59, second=59)
    return eod.timestamp()


def classify(path: str, fm: dict, *, now_epoch: float) -> dict | None:
    """Return a stale verdict dict or None (fresh). Conformant docs only.

    C1 fix: freshness_window_days is parsed via int(str(...)) directly, which
    correctly handles "1" -> 1, "0" -> 0. No bool coercion intermediary.

    C2 fix: (a) malformed/absent `updated` falls back to os.path.getmtime;
    (b) empty glob expansion is NOT a breach (spec 2.3); literal missing path
    IS a breach (trigger_missing).
    """
    updated_raw = fm.get("updated", "")
    updated_epoch = _eod_epoch(str(updated_raw))
    if updated_epoch is None:
        # C2a: fallback to filesystem mtime when updated is absent/unparseable
        try:
            updated_epoch = os.path.getmtime(path)
        except OSError:
            updated_epoch = now_epoch

    action = str(fm.get("stale_action", "warn"))

    # C1 fix: parse freshness_window_days as int directly from the stored value
    try:
        window = int(str(fm.get("freshness_window_days", "0")))
    except (ValueError, TypeError):
        window = 0

    # age rule
    if window > 0 and (now_epoch - updated_epoch) > window * 86400:
        return {"path": path, "owner": str(fm.get("recapture_owner", "")),
                "reason": "age", "stale_action": action}

    # trigger rules
    for entry in str(fm.get("recapture_trigger_files", "")).split(","):
        entry = entry.strip()
        if not entry:
            continue
        expanded = _glob.glob(os.path.expanduser(entry))
        if not expanded:
            # C2b: empty-glob expansion (wildcard that matched nothing) is NOT
            # a breach. A literal path that is missing IS trigger_missing.
            if not any(ch in entry for ch in "*?["):
                return {"path": path,
                        "owner": str(fm.get("recapture_owner", "")),
                        "reason": "trigger_missing", "stale_action": action}
            continue
        for hit in expanded:
            try:
                if os.path.getmtime(hit) > updated_epoch:
                    return {"path": path,
                            "owner": str(fm.get("recapture_owner", "")),
                            "reason": "trigger_mtime", "stale_action": action}
            except OSError:
                continue
    return None


def _iter_recapture_docs(roots: list[str]):
    """Yield candidate .md paths under roots. Seam — monkeypatched in tests.
    Excludes transcript/observability noise (spec 2.5)."""
    skip = ("/.claude/projects", "/.claude/observability", "/node_modules/")
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            if any(s in dirpath for s in skip):
                continue
            for fn in files:
                if fn.endswith(".md"):
                    yield os.path.join(dirpath, fn)


def scan(roots: list[str], *, now_epoch: float | None = None) -> dict | None:
    """Scan roots for requires_recapture docs; return section dict or None."""
    now_epoch = now_epoch if now_epoch is not None else _time.time()
    stale: list[dict] = []
    missing: list[dict] = []
    for path in _iter_recapture_docs(roots):
        try:
            fm = parse_front_matter(path)
        except Exception:
            continue  # fail-open per doc
        if not fm or fm.get("requires_recapture") is not True:
            continue
        mf = missing_fields(fm)
        if mf:
            missing.append({"path": path, "missing": mf})
            continue
        try:
            verdict = classify(path, fm, now_epoch=now_epoch)
        except Exception:
            continue  # fail-open per doc
        if verdict:
            stale.append(verdict)
    if not stale and not missing:
        return None
    return {"stale": stale, "missing_fields": missing}
