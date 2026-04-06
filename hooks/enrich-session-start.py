#!/usr/bin/env python3
"""SessionStart enrichment hook: injects past session context from Pinecone.

Queries Pinecone for relevant past session digests and decisions based on the
current working directory, then injects a context summary so the agent starts
with institutional knowledge of what's been done before.

Requires PINECONE_API_KEY in environment (use with-pinecone-env wrapper).
"""
import json
import os
import sqlite3
import ssl
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_utils import read_hook_input, run_fail_open, allow_with_context

_HOOK_NAME = "enrich-session-start"
_EVENT_NAME = "SessionStart"

# Pinecone configuration
_EMBED_URL = "https://api.pinecone.io/embed"
_EMBED_MODEL = "llama-text-embed-v2"
_INDEX_NAME = "claude"
_INDEX_HOST_FALLBACK = "https://claude-b865wv1.svc.aped-4627-b74a.pinecone.io"
_DIGESTS_NAMESPACE = "brick-digests"
_DECISIONS_NAMESPACE = "brick-decisions"
_TOP_K = 5
_TOTAL_TIMEOUT_S = 10
_OPS_DB_PATH = os.path.expanduser("~/.local/share/brick-lab/brick-ops.db")


def _make_ssl_context() -> ssl.SSLContext:
    """Create a permissive SSL context (same pattern as other hooks)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _get_api_key() -> str | None:
    """Get Pinecone API key from environment."""
    return os.environ.get("PINECONE_API_KEY")


def _resolve_index_host(api_key: str, ssl_ctx: ssl.SSLContext) -> str:
    """Resolve the Pinecone index host, falling back to hardcoded value."""
    try:
        req = urllib.request.Request(
            f"https://api.pinecone.io/indexes/{_INDEX_NAME}",
            headers={"Api-Key": api_key, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=3) as resp:
            data = json.loads(resp.read())
            host = data.get("host", "")
            if host:
                return f"https://{host}" if not host.startswith("https://") else host
    except Exception:
        pass
    return _INDEX_HOST_FALLBACK


def build_query_text(cwd: str) -> str:
    """Build a semantic query from the working directory path.

    Extracts meaningful path components to create a query that will match
    relevant past sessions working in similar areas.
    """
    if not cwd:
        return ""

    # Extract the meaningful part of the path
    home = os.path.expanduser("~")
    rel = cwd.replace(home, "~") if cwd.startswith(home) else cwd

    # Extract project-level components
    parts = [p for p in rel.split("/") if p and p != "~"]
    if not parts:
        return ""

    # Build a natural language query
    project_hint = " ".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    return f"work in {rel} project {project_hint}"


def _embed_query(
    query_text: str, api_key: str, ssl_ctx: ssl.SSLContext
) -> list[float] | None:
    """Embed query text using Pinecone's embedding API."""
    payload = json.dumps({
        "model": _EMBED_MODEL,
        "parameters": {"input_type": "query"},
        "inputs": [{"text": query_text}],
    }).encode()

    req = urllib.request.Request(
        _EMBED_URL,
        data=payload,
        headers={
            "Api-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, context=ssl_ctx, timeout=5) as resp:
        data = json.loads(resp.read())
        embeddings = data.get("data", [])
        if embeddings and "values" in embeddings[0]:
            return embeddings[0]["values"]
    return None


def _query_namespace(
    index_host: str,
    namespace: str,
    vector: list[float],
    api_key: str,
    ssl_ctx: ssl.SSLContext,
    top_k: int = _TOP_K,
) -> list[dict]:
    """Query a Pinecone namespace and return matches with metadata."""
    payload = json.dumps({
        "namespace": namespace,
        "vector": vector,
        "topK": top_k,
        "includeMetadata": True,
    }).encode()

    req = urllib.request.Request(
        f"{index_host}/query",
        data=payload,
        headers={
            "Api-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, context=ssl_ctx, timeout=5) as resp:
        data = json.loads(resp.read())
        return data.get("matches", [])


def format_digest_match(match: dict) -> str:
    """Format a single digest match as a summary line."""
    meta = match.get("metadata", {})
    date = meta.get("date", meta.get("timestamp", "unknown"))
    goal = meta.get("goal", meta.get("summary", meta.get("text", "unknown")))
    outcome = meta.get("outcome", meta.get("status", ""))

    # Truncate long goals
    if len(goal) > 120:
        goal = goal[:117] + "..."

    line = f"- {date}: {goal}"
    if outcome:
        line += f" -- {outcome}"
    return line


def _load_decision_outcomes(db_path: str = _OPS_DB_PATH) -> dict[str, str]:
    """Load decision outcomes from the ops DB, keyed by topic.

    Returns empty dict if DB is missing or query fails (fail-open).
    """
    if not os.path.exists(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path, timeout=2)
        conn.execute("PRAGMA journal_mode=WAL")
        rows = conn.execute(
            "SELECT topic, outcome FROM decisions WHERE outcome != 'untested'"
        ).fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    except Exception:
        return {}


def format_decision_match(
    match: dict, outcomes: dict[str, str] | None = None
) -> str:
    """Format a single decision match as a summary line."""
    meta = match.get("metadata", {})
    topic = meta.get("topic", meta.get("subject", meta.get("text", "unknown")))
    decision = meta.get("decision", meta.get("summary", ""))
    confidence = meta.get("confidence", "")

    if len(topic) > 80:
        topic = topic[:77] + "..."

    line = f"- {topic}"
    if decision:
        line += f": {decision}"
    if confidence:
        line += f" ({confidence})"

    # Append outcome from ops DB if available
    if outcomes:
        # Try exact match first, then match against truncated topic
        outcome = outcomes.get(topic) or outcomes.get(topic.rstrip("..."))
        if not outcome:
            # Fuzzy: check if any DB topic starts with the (possibly truncated) display topic
            raw_topic = meta.get("topic", meta.get("subject", meta.get("text", "")))
            outcome = outcomes.get(raw_topic)
        if outcome:
            line += f" \u2192 OUTCOME: {outcome}"
    return line


def format_context(
    digests: list[dict], decisions: list[dict]
) -> tuple[str, int, int]:
    """Format Pinecone results as additionalContext text.

    Returns (context_text, decisions_with_outcomes, decisions_without_outcomes).
    Returns ("", 0, 0) if no results worth injecting.
    """
    parts: list[str] = []

    # Filter by minimum relevance score
    relevant_digests = [m for m in digests if m.get("score", 0) > 0.3]
    relevant_decisions = [m for m in decisions if m.get("score", 0) > 0.3]

    with_outcomes = 0
    without_outcomes = 0

    if not relevant_digests and not relevant_decisions:
        return "", 0, 0

    parts.append("[Brick session context]")

    if relevant_digests:
        parts.append("Recent sessions in this area:")
        for m in relevant_digests:
            parts.append(format_digest_match(m))

    if relevant_decisions:
        if relevant_digests:
            parts.append("")
        # Load outcomes from ops DB (fail-open)
        outcomes = _load_decision_outcomes()
        parts.append("Key decisions:")
        for m in relevant_decisions:
            line = format_decision_match(m, outcomes)
            parts.append(line)
            if "\u2192 OUTCOME:" in line:
                with_outcomes += 1
            else:
                without_outcomes += 1

    # Check for unresolved items in digests
    unresolved = []
    for m in relevant_digests:
        meta = m.get("metadata", {})
        items = meta.get("unresolved", [])
        if isinstance(items, str):
            items = [items]
        unresolved.extend(items)

    if unresolved:
        parts.append("")
        parts.append("Unresolved from previous sessions:")
        for item in unresolved[:5]:
            parts.append(f"- {item}")

    return "\n".join(parts), with_outcomes, without_outcomes


def main() -> None:
    t0 = time.time()

    input_data = read_hook_input(timeout_seconds=2)
    if not input_data:
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    cwd = input_data.get("cwd", "") or os.getcwd()

    # Skip on compact events — no need to inject session history during compaction
    source = input_data.get("source", "")
    if source == "compact":
        sys.exit(0)

    # Build query
    query_text = build_query_text(cwd)
    if not query_text:
        sys.exit(0)

    # API key
    api_key = _get_api_key()
    if not api_key:
        sys.exit(0)

    # Circuit breaker
    try:
        from brick_circuit import CircuitBreaker
        cb = CircuitBreaker()
        if not cb.allow_request():
            sys.exit(0)
    except Exception:
        pass  # If circuit breaker unavailable, proceed anyway

    ssl_ctx = _make_ssl_context()

    # Resolve index host
    index_host = _resolve_index_host(api_key, ssl_ctx)

    # Embed the query
    vector = _embed_query(query_text, api_key, ssl_ctx)
    if not vector:
        sys.exit(0)

    # Query both namespaces (sequential to stay within timeout)
    digests: list[dict] = []
    decisions: list[dict] = []

    elapsed = time.time() - t0
    if elapsed < _TOTAL_TIMEOUT_S:
        try:
            digests = _query_namespace(
                index_host, _DIGESTS_NAMESPACE, vector, api_key, ssl_ctx
            )
        except Exception:
            pass

    elapsed = time.time() - t0
    if elapsed < _TOTAL_TIMEOUT_S:
        try:
            decisions = _query_namespace(
                index_host, _DECISIONS_NAMESPACE, vector, api_key, ssl_ctx
            )
        except Exception:
            pass

    # Format results
    context, decisions_with_outcomes, decisions_without_outcomes = format_context(
        digests, decisions
    )

    # Compute hit/miss instrumentation
    relevant_digests = [m for m in digests if m.get("score", 0) > 0.3]
    relevant_decisions = [m for m in decisions if m.get("score", 0) > 0.3]
    digests_found = len(relevant_digests)
    decisions_found = len(relevant_decisions)
    all_scores = [m.get("score", 0) for m in digests + decisions]
    top_relevance_score = max(all_scores) if all_scores else 0.0
    hit = (digests_found + decisions_found) > 0

    # Log metrics (best-effort) — log both hits and misses
    latency_ms = int((time.time() - t0) * 1000)
    try:
        from brick_metrics import log_enrichment
        log_enrichment(
            hook=_HOOK_NAME,
            session_id=session_id,
            tool_name="SessionStart",
            action="enriched" if hit else "miss",
            latency_ms=latency_ms,
            findings_preview=context[:200] if context else "",
            decisions_with_outcomes=decisions_with_outcomes,
            decisions_without_outcomes=decisions_without_outcomes,
            digests_found=digests_found,
            decisions_found=decisions_found,
            relevance_score=top_relevance_score,
        )
    except Exception:
        pass

    if not context:
        sys.exit(0)

    # Record circuit breaker success
    try:
        cb.record_success()
    except Exception:
        pass

    allow_with_context(context, event=_EVENT_NAME)


if __name__ == "__main__":
    run_fail_open(main, _HOOK_NAME, _EVENT_NAME)
