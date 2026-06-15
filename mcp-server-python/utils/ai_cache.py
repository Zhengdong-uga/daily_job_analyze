"""
AI Analysis Cache for incremental Job Intelligence.

Caches per-job AI analysis results keyed by:
  (stable_identity, content_hash, provider, model, prompt_version, analysis_type)

An unchanged JD with the same provider/model/prompt will hit cache.
An updated JD (different content_hash) will miss cache automatically.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_analysis_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_identity TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    analysis_type TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(stable_identity, content_hash, provider, model, prompt_version, analysis_type)
)
"""

_CACHE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_cache_lookup ON ai_analysis_cache(stable_identity, content_hash, provider, model, prompt_version)",
]


def bootstrap_cache_schema(conn: sqlite3.Connection) -> None:
    """Create the ai_analysis_cache table if not present."""
    conn.execute(_CACHE_SCHEMA)
    for idx_sql in _CACHE_INDEXES:
        conn.execute(idx_sql)
    conn.commit()


# ---------------------------------------------------------------------------
# Cache operations
# ---------------------------------------------------------------------------


def get_cached_analysis(
    conn: sqlite3.Connection,
    stable_identity: str,
    content_hash: str,
    provider: str,
    model: str,
    prompt_version: str,
    analysis_type: str = "job_analysis",
) -> Optional[Dict[str, Any]]:
    """
    Look up a cached AI analysis result.

    Returns the parsed JSON result if found, None otherwise.
    """
    row = conn.execute(
        """
        SELECT result_json FROM ai_analysis_cache
        WHERE stable_identity = ?
          AND content_hash = ?
          AND provider = ?
          AND model = ?
          AND prompt_version = ?
          AND analysis_type = ?
        """,
        (stable_identity, content_hash, provider, model, prompt_version, analysis_type),
    ).fetchone()

    if row is None:
        return None

    try:
        return json.loads(row["result_json"])
    except (json.JSONDecodeError, TypeError):
        return None


def store_cached_analysis(
    conn: sqlite3.Connection,
    stable_identity: str,
    content_hash: str,
    provider: str,
    model: str,
    prompt_version: str,
    analysis_type: str,
    result: Dict[str, Any],
) -> None:
    """
    Store an AI analysis result in the cache.

    Uses INSERT OR REPLACE to handle updates to existing entries.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    result_json = json.dumps(result, ensure_ascii=False)

    conn.execute(
        """
        INSERT OR REPLACE INTO ai_analysis_cache (
            stable_identity, content_hash, provider, model,
            prompt_version, analysis_type, result_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            stable_identity,
            content_hash,
            provider,
            model,
            prompt_version,
            analysis_type,
            result_json,
            now_iso,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Market Summary Cache
# ---------------------------------------------------------------------------


def compute_aggregate_input_hash(
    run_metrics: Dict[str, Any],
    previous_metrics: Optional[Dict[str, Any]],
    new_analyses: list[Dict[str, Any]],
    update_analyses: list[Dict[str, Any]],
) -> str:
    """
    Generate a deterministic hash for a set of inputs to the market summary.
    """
    import hashlib
    # Extract sorting keys (using summary or joined skills to identify uniqueness)
    def _hash_analysis(a: Dict[str, Any]) -> str:
        s = a.get("summary", "") + "".join(a.get("required_skills", []))
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    # Sort hashes to ensure order independence
    new_hashes = sorted([_hash_analysis(a) for a in new_analyses])
    update_hashes = sorted([_hash_analysis(a) for a in update_analyses])

    parts = [
        json.dumps(run_metrics, sort_keys=True),
        json.dumps(previous_metrics, sort_keys=True) if previous_metrics else "None",
        "|".join(new_hashes),
        "|".join(update_hashes),
    ]
    combined = "||".join(parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def get_cached_market_summary(
    conn: sqlite3.Connection,
    aggregate_input_hash: str,
    provider: str,
    model: str,
    prompt_version: str,
) -> Optional[Dict[str, Any]]:
    """Retrieve a cached market summary using the aggregate input hash."""
    return get_cached_analysis(
        conn,
        stable_identity="market_summary",
        content_hash=aggregate_input_hash,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        analysis_type="market_summary",
    )


def store_cached_market_summary(
    conn: sqlite3.Connection,
    aggregate_input_hash: str,
    provider: str,
    model: str,
    prompt_version: str,
    result: Dict[str, Any],
) -> None:
    """Store a market summary in the cache using the aggregate input hash."""
    store_cached_analysis(
        conn,
        stable_identity="market_summary",
        content_hash=aggregate_input_hash,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        analysis_type="market_summary",
        result=result,
    )
