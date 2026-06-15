"""
Database layer for incremental Job Intelligence tracking.

Manages two tables:
- job_history: Tracks historical state of every job encountered across runs
- run_history: Tracks metadata for each pipeline run

Provides classification logic (new/updated/unchanged), content hashing,
stable identity computation, and run-level bookkeeping.
"""

import hashlib
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.path_resolution import resolve_db_path as resolve_db_path_shared


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

_JOB_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS job_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_identity TEXT NOT NULL UNIQUE,
    url TEXT,
    title TEXT,
    company TEXT,
    location TEXT,
    source TEXT,
    description TEXT,
    previous_description TEXT,
    content_hash TEXT NOT NULL,
    previous_content_hash TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_reported_at TEXT,
    last_ai_analyzed_at TEXT,
    ai_provider TEXT,
    ai_model TEXT,
    ai_prompt_version TEXT,
    analysis_status TEXT DEFAULT 'pending'
)
"""

_RUN_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_history (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    pipeline_status TEXT NOT NULL DEFAULT 'running',
    ai_status TEXT NOT NULL DEFAULT 'disabled',
    email_status TEXT NOT NULL DEFAULT 'not_requested',
    scrape_hours_old INTEGER,
    scraped_count INTEGER DEFAULT 0,
    unique_count INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    updated_count INTEGER DEFAULT 0,
    unchanged_count INTEGER DEFAULT 0,
    ai_analyzed_count INTEGER DEFAULT 0,
    report_path TEXT
)
"""

_RUN_JOB_RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_job_results (
    run_id TEXT NOT NULL,
    stable_identity TEXT NOT NULL,
    classification TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    included_in_report BOOLEAN DEFAULT 0,
    sent_to_ai BOOLEAN DEFAULT 0,
    ai_cache_hit BOOLEAN DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, stable_identity)
)
"""

_JOB_HISTORY_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_jh_content_hash ON job_history(content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_jh_last_seen ON job_history(last_seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_jh_analysis_status ON job_history(analysis_status)",
]

_RUN_HISTORY_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_rh_pipeline_status ON run_history(pipeline_status)",
    "CREATE INDEX IF NOT EXISTS idx_rh_started ON run_history(started_at)",
]

_RUN_JOB_RESULTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_rjr_run_id ON run_job_results(run_id)",
]

def bootstrap_history_schema(conn: sqlite3.Connection) -> None:
    """Create job_history, run_history, and run_job_results tables + indexes."""
    conn.execute(_JOB_HISTORY_SCHEMA)
    conn.execute(_RUN_HISTORY_SCHEMA)
    conn.execute(_RUN_JOB_RESULTS_SCHEMA)
    for idx_sql in _JOB_HISTORY_INDEXES + _RUN_HISTORY_INDEXES + _RUN_JOB_RESULTS_INDEXES:
        conn.execute(idx_sql)
    conn.commit()


# ---------------------------------------------------------------------------
# Identity & hashing helpers
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_for_hash(text: Optional[str]) -> str:
    """Lowercase, collapse whitespace, strip for consistent hashing."""
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text.lower().strip())


def compute_content_hash(
    title: str, company: str, location: str, description: str
) -> str:
    """
    SHA-256 of normalized title+company+location+description.

    Deterministic: same inputs always produce the same hash.
    """
    parts = [
        _normalize_for_hash(title),
        _normalize_for_hash(company),
        _normalize_for_hash(location),
        _normalize_for_hash(description),
    ]
    combined = "|".join(parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def compute_stable_identity(
    url: Optional[str],
    title: str,
    company: str,
    location: str,
    source: str,
) -> str:
    """
    Compute a stable identity for a job posting.

    If a normalized URL is available, use it directly.
    Otherwise, derive a composite key from title+company+location+source.
    """
    if url and url.strip():
        # Normalize: strip query params, fragments, trailing slashes
        normalized_url = url.strip().rstrip("/")
        # Remove common tracking params
        normalized_url = re.sub(r"[?#].*$", "", normalized_url)
        return normalized_url

    # Fallback: composite key
    parts = [
        _normalize_for_hash(title),
        _normalize_for_hash(company),
        _normalize_for_hash(location),
        _normalize_for_hash(source),
    ]
    combined = "|".join(parts)
    return "composite:" + hashlib.sha256(combined.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Job classification
# ---------------------------------------------------------------------------


def classify_jobs(
    conn: sqlite3.Connection,
    scraped_jobs: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Classify scraped jobs against job_history.

    Returns dict with keys: "new", "updated", "unchanged".
    Each value is a list of job dicts enriched with:
      - _stable_identity
      - _content_hash
      - _classification
      - _previous_description (for updated jobs)
    """
    result: Dict[str, List[Dict[str, Any]]] = {
        "new": [],
        "updated": [],
        "unchanged": [],
    }

    now_iso = datetime.now(timezone.utc).isoformat()

    for job in scraped_jobs:
        identity = compute_stable_identity(
            url=job.get("url"),
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            source=job.get("source", ""),
        )
        content_hash = compute_content_hash(
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            description=job.get("description", ""),
        )

        enriched = dict(job)
        enriched["_stable_identity"] = identity
        enriched["_content_hash"] = content_hash

        # Look up existing record
        row = conn.execute(
            "SELECT content_hash, description FROM job_history WHERE stable_identity = ?",
            (identity,),
        ).fetchone()

        if row is None:
            enriched["_classification"] = "new"
            enriched["_previous_description"] = None
            result["new"].append(enriched)
        elif row["content_hash"] != content_hash:
            enriched["_classification"] = "updated"
            enriched["_previous_description"] = row["description"]
            result["updated"].append(enriched)
        else:
            enriched["_classification"] = "unchanged"
            enriched["_previous_description"] = None
            result["unchanged"].append(enriched)

        # Always update last_seen_at
        _touch_last_seen(conn, identity, content_hash, enriched, now_iso)

    conn.commit()
    return result


def _touch_last_seen(
    conn: sqlite3.Connection,
    identity: str,
    content_hash: str,
    job: Dict[str, Any],
    now_iso: str,
) -> None:
    """Insert or update job_history with current encounter."""
    existing = conn.execute(
        "SELECT id FROM job_history WHERE stable_identity = ?", (identity,)
    ).fetchone()

    if existing is None:
        # New record
        conn.execute(
            """
            INSERT INTO job_history (
                stable_identity, url, title, company, location, source,
                description, content_hash,
                first_seen_at, last_seen_at, analysis_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                identity,
                job.get("url", ""),
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("source", ""),
                job.get("description", ""),
                content_hash,
                now_iso,
                now_iso,
            ),
        )
    else:
        # Existing record — update
        old_row = conn.execute(
            "SELECT content_hash, description FROM job_history WHERE stable_identity = ?",
            (identity,),
        ).fetchone()

        if old_row["content_hash"] != content_hash:
            # Content changed — store previous state
            conn.execute(
                """
                UPDATE job_history
                SET title = ?, company = ?, location = ?, source = ?,
                    description = ?, previous_description = ?,
                    content_hash = ?, previous_content_hash = ?,
                    last_seen_at = ?, analysis_status = 'pending'
                WHERE stable_identity = ?
                """,
                (
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    job.get("source", ""),
                    job.get("description", ""),
                    old_row["description"],
                    content_hash,
                    old_row["content_hash"],
                    now_iso,
                    identity,
                ),
            )
        else:
            # Same content — just touch last_seen_at
            conn.execute(
                "UPDATE job_history SET last_seen_at = ? WHERE stable_identity = ?",
                (now_iso, identity),
            )


def update_analysis_status(
    conn: sqlite3.Connection,
    identity: str,
    status: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    prompt_version: Optional[str] = None,
) -> None:
    """Update AI analysis metadata for a job_history record."""
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE job_history
        SET analysis_status = ?,
            last_ai_analyzed_at = ?,
            ai_provider = COALESCE(?, ai_provider),
            ai_model = COALESCE(?, ai_model),
            ai_prompt_version = COALESCE(?, ai_prompt_version)
        WHERE stable_identity = ?
        """,
        (status, now_iso, provider, model, prompt_version, identity),
    )


def update_last_reported(
    conn: sqlite3.Connection, identities: List[str]
) -> None:
    """Mark jobs as reported in the current run."""
    now_iso = datetime.now(timezone.utc).isoformat()
    for identity in identities:
        conn.execute(
            "UPDATE job_history SET last_reported_at = ? WHERE stable_identity = ?",
            (now_iso, identity),
        )


def get_previous_description(
    conn: sqlite3.Connection, identity: str
) -> Optional[str]:
    """Retrieve the previous description for a job (before content update)."""
    row = conn.execute(
        "SELECT previous_description FROM job_history WHERE stable_identity = ?",
        (identity,),
    ).fetchone()
    return row["previous_description"] if row else None


def persist_run_job_results(
    conn: sqlite3.Connection,
    run_id: str,
    classified_jobs: Dict[str, List[Dict[str, Any]]],
) -> None:
    """Persist the exact classification for this run to run_job_results."""
    now_iso = datetime.now(timezone.utc).isoformat()
    rows = []
    for cls, jobs in classified_jobs.items():
        for job in jobs:
            rows.append((
                run_id,
                job["_stable_identity"],
                cls,
                job["_content_hash"],
                0,  # included_in_report
                0,  # sent_to_ai
                0,  # ai_cache_hit
                now_iso
            ))
    
    if rows:
        conn.executemany(
            """
            INSERT INTO run_job_results (
                run_id, stable_identity, classification, content_hash,
                included_in_report, sent_to_ai, ai_cache_hit, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows
        )
        conn.commit()


def update_run_job_ai_status(
    conn: sqlite3.Connection, run_id: str, identity: str, sent_to_ai: bool, ai_cache_hit: bool
) -> None:
    """Update AI cache and execution status in run_job_results."""
    conn.execute(
        """
        UPDATE run_job_results 
        SET sent_to_ai = ?, ai_cache_hit = ?
        WHERE run_id = ? AND stable_identity = ?
        """,
        (sent_to_ai, ai_cache_hit, run_id, identity)
    )
    conn.commit()


def update_run_job_report_status(
    conn: sqlite3.Connection, run_id: str, identities: List[str]
) -> None:
    """Mark jobs as included in the report for a specific run."""
    if not identities:
        return
    placeholders = ",".join(["?"] * len(identities))
    conn.execute(
        f"""
        UPDATE run_job_results 
        SET included_in_report = 1
        WHERE run_id = ? AND stable_identity IN ({placeholders})
        """,
        [run_id] + identities
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Run tracking
# ---------------------------------------------------------------------------


def start_run(conn: sqlite3.Connection, hours_old: int) -> str:
    """Create a new run_history record and return the run_id."""
    run_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO run_history (run_id, started_at, pipeline_status, ai_status, email_status, scrape_hours_old)
        VALUES (?, ?, 'running', 'disabled', 'not_requested', ?)
        """,
        (run_id, now_iso, hours_old),
    )
    conn.commit()
    return run_id


def complete_run(
    conn: sqlite3.Connection,
    run_id: str,
    stats: Dict[str, Any],
) -> None:
    """Mark a run as completed with final statistics."""
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE run_history
        SET completed_at = ?, pipeline_status = 'completed',
            scraped_count = ?, unique_count = ?,
            new_count = ?, updated_count = ?, unchanged_count = ?,
            ai_analyzed_count = ?, report_path = ?
        WHERE run_id = ?
        """,
        (
            now_iso,
            stats.get("scraped_count", 0),
            stats.get("unique_count", 0),
            stats.get("new_count", 0),
            stats.get("updated_count", 0),
            stats.get("unchanged_count", 0),
            stats.get("ai_analyzed_count", 0),
            stats.get("report_path", ""),
            run_id,
        ),
    )
    conn.commit()


def fail_run(conn: sqlite3.Connection, run_id: str) -> None:
    """Mark a run as failed."""
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE run_history SET completed_at = ?, pipeline_status = 'failed' WHERE run_id = ?",
        (now_iso, run_id),
    )
    conn.commit()


def update_run_ai_status(conn: sqlite3.Connection, run_id: str, status: str) -> None:
    """Update ai_status (disabled, completed, partial, fallback, failed)."""
    conn.execute(
        "UPDATE run_history SET ai_status = ? WHERE run_id = ?",
        (status, run_id),
    )
    conn.commit()


def update_run_email_status(conn: sqlite3.Connection, run_id: str, status: str) -> None:
    """Update email_status (not_requested, sent, failed)."""
    conn.execute(
        "UPDATE run_history SET email_status = ? WHERE run_id = ?",
        (status, run_id),
    )
    conn.commit()


def get_previous_successful_run(
    conn: sqlite3.Connection,
) -> Optional[Dict[str, Any]]:
    """
    Retrieve the most recent successfully completed run.

    This is the comparison baseline — NOT midnight, NOT a calendar day.
    """
    row = conn.execute(
        """
        SELECT run_id, started_at, completed_at, pipeline_status as status,
               scrape_hours_old, scraped_count, unique_count,
               new_count, updated_count, unchanged_count,
               ai_analyzed_count, report_path
        FROM run_history
        WHERE pipeline_status = 'completed'
        ORDER BY completed_at DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def get_run_metrics(
    conn: sqlite3.Connection, run_id: str
) -> Optional[Dict[str, Any]]:
    """Retrieve metrics for a specific run."""
    row = conn.execute(
        "SELECT * FROM run_history WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def get_jobs_for_run(
    conn: sqlite3.Connection, run_id: str
) -> List[Dict[str, Any]]:
    """Retrieve all jobs evaluated in a specific run with their descriptions."""
    rows = conn.execute(
        """
        SELECT jh.stable_identity as _stable_identity,
               jh.title, jh.company, jh.location, jh.source, jh.description,
               rjr.classification as _classification,
               rjr.content_hash as _content_hash
        FROM run_job_results rjr
        JOIN job_history jh ON jh.stable_identity = rjr.stable_identity
        WHERE rjr.run_id = ?
        """,
        (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Backfill migration
# ---------------------------------------------------------------------------


def backfill_from_jobs_table(conn: sqlite3.Connection) -> int:
    """
    One-time migration: populate job_history from existing jobs table rows.

    Each existing job is inserted as a baseline record (not permanently
    classified unchanged). It will be evaluated in the next run.

    Returns the number of rows backfilled.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    rows = conn.execute(
        """
        SELECT url, title, company, location, source, description, created_at
        FROM jobs
        """
    ).fetchall()

    backfilled = 0
    for row in rows:
        identity = compute_stable_identity(
            url=row["url"],
            title=row["title"] or "",
            company=row["company"] or "",
            location=row["location"] or "",
            source=row["source"] or "",
        )
        content_hash = compute_content_hash(
            title=row["title"] or "",
            company=row["company"] or "",
            location=row["location"] or "",
            description=row["description"] or "",
        )

        # Skip if already exists (idempotent)
        existing = conn.execute(
            "SELECT id FROM job_history WHERE stable_identity = ?", (identity,)
        ).fetchone()
        if existing:
            continue

        first_seen = row["created_at"] or now_iso

        conn.execute(
            """
            INSERT INTO job_history (
                stable_identity, url, title, company, location, source,
                description, content_hash,
                first_seen_at, last_seen_at, analysis_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                identity,
                row["url"],
                row["title"] or "",
                row["company"] or "",
                row["location"] or "",
                row["source"] or "",
                row["description"] or "",
                content_hash,
                first_seen,
                now_iso,
            ),
        )
        backfilled += 1

    conn.commit()
    return backfilled


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


def get_history_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Open a read-write connection to the jobs database and bootstrap
    the history schema.

    Returns a connection with row_factory = sqlite3.Row.
    """
    resolved = resolve_db_path_shared(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    bootstrap_history_schema(conn)
    return conn
