"""
Tests for the incremental Job Intelligence system.

Covers:
- Job classification (new, updated, unchanged)
- Content hashing and stable identity
- Run history tracking
- AI cache behavior
- AI provider mocking (Gemini, OpenAI)
- AI fallback to rules
- Report generation focus
- Email behavior
- Backfill migration

No real API calls are made.
"""

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure mcp-server-python is on sys.path
import sys

_repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_repo_root / "mcp-server-python"))

from db.job_history_db import (
    backfill_from_jobs_table,
    bootstrap_history_schema,
    classify_jobs,
    complete_run,
    compute_content_hash,
    compute_stable_identity,
    fail_run,
    get_previous_successful_run,
    start_run,
    update_analysis_status,
    update_last_reported,
)
from utils.ai_cache import (
    bootstrap_cache_schema,
    get_cached_analysis,
    store_cached_analysis,
)
from utils.ai_provider import (
    GeminiProvider,
    NoOpProvider,
    OpenAIProvider,
    _parse_json_response,
    create_provider,
)
from utils.email_sender import (
    build_incremental_email_subject,
    build_zero_new_email_body,
)
from utils.jd_preprocessor import preprocess_for_ai, strip_boilerplate
from utils.report_generator import generate_incremental_report


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mem_db():
    """In-memory SQLite database with history schema bootstrapped."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    bootstrap_history_schema(conn)
    bootstrap_cache_schema(conn)
    return conn


@pytest.fixture
def mem_db_with_jobs_table(mem_db):
    """In-memory DB with both the legacy jobs table and history tables."""
    mem_db.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            title TEXT,
            company TEXT,
            location TEXT,
            source TEXT,
            description TEXT,
            status TEXT DEFAULT 'new',
            created_at TEXT NOT NULL
        )
    """)
    mem_db.commit()
    return mem_db


def _make_job(
    title="Software Engineer",
    company="Acme Corp",
    location="New York, NY",
    source="linkedin",
    url="https://linkedin.com/jobs/view/123",
    description="Build amazing software with React and TypeScript.",
):
    return {
        "title": title,
        "company": company,
        "location": location,
        "source": source,
        "url": url,
        "description": description,
        "match_state": "matched",
        "matched_target_role": "Software Engineer",
        "_stable_identity": title
    }


# ---------------------------------------------------------------------------
# Content Hash Tests
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_deterministic(self):
        """Same inputs always produce the same hash."""
        h1 = compute_content_hash("Engineer", "Acme", "NYC", "Build stuff")
        h2 = compute_content_hash("Engineer", "Acme", "NYC", "Build stuff")
        assert h1 == h2

    def test_different_description_different_hash(self):
        """Different description → different hash."""
        h1 = compute_content_hash("Engineer", "Acme", "NYC", "Build stuff")
        h2 = compute_content_hash("Engineer", "Acme", "NYC", "Build different stuff")
        assert h1 != h2

    def test_normalized_whitespace(self):
        """Extra whitespace is normalized before hashing."""
        h1 = compute_content_hash("  Engineer  ", "Acme", "NYC", "Build   stuff")
        h2 = compute_content_hash("Engineer", "Acme", "NYC", "Build stuff")
        assert h1 == h2

    def test_case_insensitive(self):
        """Hashing is case-insensitive."""
        h1 = compute_content_hash("ENGINEER", "ACME", "NYC", "BUILD STUFF")
        h2 = compute_content_hash("engineer", "acme", "nyc", "build stuff")
        assert h1 == h2


# ---------------------------------------------------------------------------
# Stable Identity Tests
# ---------------------------------------------------------------------------


class TestStableIdentity:
    def test_url_preferred(self):
        """URL is used as identity when available."""
        identity = compute_stable_identity(
            url="https://linkedin.com/jobs/view/123",
            title="Engineer", company="Acme", location="NYC", source="linkedin"
        )
        assert identity == "https://linkedin.com/jobs/view/123"

    def test_url_normalized(self):
        """URL trailing slashes and query params are stripped."""
        i1 = compute_stable_identity(
            url="https://example.com/job/1?utm=foo",
            title="", company="", location="", source=""
        )
        i2 = compute_stable_identity(
            url="https://example.com/job/1",
            title="", company="", location="", source=""
        )
        assert i1 == i2

    def test_fallback_composite(self):
        """Composite key used when URL is unavailable."""
        identity = compute_stable_identity(
            url="", title="Engineer", company="Acme", location="NYC", source="linkedin"
        )
        assert identity.startswith("composite:")

    def test_fallback_deterministic(self):
        """Composite key is deterministic."""
        i1 = compute_stable_identity(
            url="", title="Engineer", company="Acme", location="NYC", source="linkedin"
        )
        i2 = compute_stable_identity(
            url="", title="Engineer", company="Acme", location="NYC", source="linkedin"
        )
        assert i1 == i2


# ---------------------------------------------------------------------------
# Classification Tests
# ---------------------------------------------------------------------------


class TestClassification:
    def test_new_job(self, mem_db):
        """First-time job is classified as new."""
        job = _make_job()
        result = classify_jobs(mem_db, [job])
        assert len(result["new"]) == 1
        assert result["new"][0]["_classification"] == "new"
        assert len(result["updated"]) == 0
        assert len(result["unchanged"]) == 0

    def test_unchanged_job(self, mem_db):
        """Identical historical job is classified as unchanged."""
        job = _make_job()
        classify_jobs(mem_db, [job])  # First encounter

        result = classify_jobs(mem_db, [job])  # Second encounter
        assert len(result["unchanged"]) == 1
        assert result["unchanged"][0]["_classification"] == "unchanged"
        assert len(result["new"]) == 0

    def test_updated_job(self, mem_db):
        """Job with changed description is classified as updated."""
        job = _make_job(description="Original description")
        classify_jobs(mem_db, [job])  # First encounter

        updated_job = _make_job(description="Completely new description with different requirements")
        result = classify_jobs(mem_db, [updated_job])  # Second encounter
        assert len(result["updated"]) == 1
        assert result["updated"][0]["_classification"] == "updated"
        assert result["updated"][0]["_previous_description"] == "Original description"

    def test_last_seen_at_updates(self, mem_db):
        """last_seen_at is updated every encounter."""
        job = _make_job()
        classify_jobs(mem_db, [job])

        first_seen = mem_db.execute(
            "SELECT last_seen_at FROM job_history WHERE url = ?", (job["url"],)
        ).fetchone()["last_seen_at"]

        # Classify again
        import time
        time.sleep(0.01)  # Tiny delay to ensure timestamp changes
        classify_jobs(mem_db, [job])

        second_seen = mem_db.execute(
            "SELECT last_seen_at FROM job_history WHERE url = ?", (job["url"],)
        ).fetchone()["last_seen_at"]

        assert second_seen >= first_seen

    def test_multiple_jobs_mixed(self, mem_db):
        """Multiple jobs with mixed classifications in one batch."""
        existing_job = _make_job(url="https://example.com/1", description="old desc")
        classify_jobs(mem_db, [existing_job])

        batch = [
            _make_job(url="https://example.com/1", description="old desc"),  # unchanged
            _make_job(url="https://example.com/1b", description="new desc",
                      title="Changed Job"),  # wait — different URL → new
            _make_job(url="https://example.com/2", description="brand new job"),  # new
        ]
        # Need to fix: url /1 is unchanged, /1b and /2 are new
        result = classify_jobs(mem_db, batch)
        assert len(result["unchanged"]) == 1
        assert len(result["new"]) == 2


# ---------------------------------------------------------------------------
# Run History Tests
# ---------------------------------------------------------------------------


class TestRunHistory:
    def test_start_and_complete(self, mem_db):
        """Run lifecycle: start → complete."""
        run_id = start_run(mem_db, hours_old=24)
        assert run_id

        complete_run(mem_db, run_id, {
            "scraped_count": 100,
            "unique_count": 80,
            "new_count": 20,
            "updated_count": 5,
            "unchanged_count": 55,
            "ai_analyzed_count": 15,
            "report_path": "/tmp/report.md",
        })

        row = mem_db.execute(
            "SELECT * FROM run_history WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert row["pipeline_status"] == "completed"
        assert row["new_count"] == 20

    def test_previous_successful_run_baseline(self, mem_db):
        """Previous successful run is the comparison baseline."""
        # No runs yet
        assert get_previous_successful_run(mem_db) is None

        # Complete a run
        run_id = start_run(mem_db, 24)
        complete_run(mem_db, run_id, {"new_count": 10})

        prev = get_previous_successful_run(mem_db)
        assert prev is not None
        assert prev["run_id"] == run_id
        assert prev["new_count"] == 10

    def test_failed_run_not_baseline(self, mem_db):
        """Failed runs should not be used as baseline."""
        run_id = start_run(mem_db, 24)
        fail_run(mem_db, run_id)

        assert get_previous_successful_run(mem_db) is None

    def test_most_recent_successful(self, mem_db):
        """Most recent successful run is selected as baseline."""
        r1 = start_run(mem_db, 24)
        complete_run(mem_db, r1, {"new_count": 5})

        r2 = start_run(mem_db, 48)
        complete_run(mem_db, r2, {"new_count": 15})

        prev = get_previous_successful_run(mem_db)
        assert prev["run_id"] == r2


# ---------------------------------------------------------------------------
# AI Cache Tests
# ---------------------------------------------------------------------------


class TestAICache:
    def test_cache_miss(self, mem_db):
        """Cache returns None for unknown entries."""
        result = get_cached_analysis(
            mem_db, "identity", "hash", "gemini", "gemini-2.5-flash", "v1.0"
        )
        assert result is None

    def test_cache_hit(self, mem_db):
        """Stored result is retrievable."""
        data = {"summary": "A great job", "required_skills": ["Python"]}
        store_cached_analysis(
            mem_db, "identity1", "hash1", "gemini", "gemini-2.5-flash",
            "v1.0", "job_analysis", data
        )
        result = get_cached_analysis(
            mem_db, "identity1", "hash1", "gemini", "gemini-2.5-flash",
            "v1.0", "job_analysis"
        )
        assert result == data

    def test_updated_jd_cache_miss(self, mem_db):
        """Different content_hash → cache miss (new analysis needed)."""
        data = {"summary": "Old analysis"}
        store_cached_analysis(
            mem_db, "identity1", "old_hash", "gemini", "gemini-2.5-flash",
            "v1.0", "job_analysis", data
        )
        result = get_cached_analysis(
            mem_db, "identity1", "new_hash", "gemini", "gemini-2.5-flash",
            "v1.0", "job_analysis"
        )
        assert result is None

    def test_different_provider_cache_miss(self, mem_db):
        """Different provider → separate cache entry."""
        data = {"summary": "Gemini analysis"}
        store_cached_analysis(
            mem_db, "identity1", "hash1", "gemini", "gemini-2.5-flash",
            "v1.0", "job_analysis", data
        )
        result = get_cached_analysis(
            mem_db, "identity1", "hash1", "openai", "gpt-4o-mini",
            "v1.0", "job_analysis"
        )
        assert result is None


# ---------------------------------------------------------------------------
# AI Provider Tests (Mocked)
# ---------------------------------------------------------------------------


class TestGeminiProviderMocked:
    @patch("utils.ai_provider.GeminiProvider._get_client")
    @patch("utils.ai_provider.GeminiProvider._call_model")
    def test_analyze_job(self, mock_call, mock_get_client):
        """Gemini provider returns parsed JSON from mocked _call_model."""
        mock_call.return_value = json.dumps({
            "summary": "Test summary",
            "required_skills": ["Python", "React"],
        })
        provider = GeminiProvider(api_key="test-key")

        result = provider.analyze_job(_make_job())
        assert result["summary"] == "Test summary"
        assert "Python" in result["required_skills"]


class TestOpenAIProviderMocked:
    @patch("utils.ai_provider.OpenAIProvider._get_client")
    @patch("utils.ai_provider.OpenAIProvider._call_model")
    def test_analyze_job(self, mock_call, mock_get_client):
        """OpenAI provider returns parsed JSON from mocked _call_model."""
        mock_call.return_value = json.dumps({
            "summary": "OpenAI test summary",
            "role_cluster": "Frontend Engineering",
        })
        provider = OpenAIProvider(api_key="test-key")

        result = provider.analyze_job(_make_job())
        assert result["summary"] == "OpenAI test summary"


class TestNoOpProvider:
    def test_returns_empty(self):
        """NoOp provider returns empty dicts."""
        provider = NoOpProvider()
        assert provider.analyze_job(_make_job()) == {}
        assert provider.analyze_job_update("old", "new") == {}
        assert provider.generate_market_summary({}, None, []) == {}


class TestAIFailureFallback:
    @patch("utils.ai_provider.GeminiProvider._get_client")
    def test_ai_failure_returns_empty(self, mock_get_client):
        """AI failure returns empty dict (rule-based fallback can be used)."""
        provider = GeminiProvider(api_key="test-key")
        # Simulate a provider that raises on _call_model
        provider._call_model = MagicMock(side_effect=Exception("API error"))
        result = provider.analyze_job(_make_job())
        assert result == {}


# ---------------------------------------------------------------------------
# JSON Parsing Tests
# ---------------------------------------------------------------------------


class TestJSONParsing:
    def test_clean_json(self):
        assert _parse_json_response('{"key": "value"}') == {"key": "value"}

    def test_json_with_fences(self):
        assert _parse_json_response('```json\n{"key": "value"}\n```') == {"key": "value"}

    def test_empty_response(self):
        assert _parse_json_response("") == {}

    def test_invalid_json(self):
        assert _parse_json_response("not json at all") == {}


# ---------------------------------------------------------------------------
# Report Tests
# ---------------------------------------------------------------------------


class TestIncrementalReport:
    def _make_config(self):
        from utils.watch_config import JobWatchConfig
        return JobWatchConfig(
            target_roles=["Software Engineer"],
            locations=["New York, NY"],
        )

    def test_report_focuses_on_new_updated(self):
        """Report detailed sections focus on new and updated jobs."""
        classified = {
            "new": [_make_job(title="New Job", url="https://example.com/new")],
            "updated": [_make_job(title="Updated Job", url="https://example.com/updated")],
            "unchanged": [_make_job(title="Old Job", url="https://example.com/old")],
        }
        config = self._make_config()
        config.analysis_scope.include_all_current_jobs = False
        report = generate_incremental_report(
            classified, {"scrape_hours_old": 24}, config, include_previously_seen=False
        )
        assert "New Job" in report
        assert "Updated Job" in report
        # Unchanged job should NOT appear as a detailed card unless include_previously_seen is true
        assert "Old Job" not in report

    def test_unchanged_excluded_from_detail(self):
        """Unchanged jobs get only a compact note."""
        classified = {
            "new": [],
            "updated": [],
            "unchanged": [_make_job()] * 10,
        }
        config = self._make_config()
        config.analysis_scope.include_all_current_jobs = False
        report = generate_incremental_report(
            classified, {"scrape_hours_old": 24}, config, include_previously_seen=False
        )
        assert "| Previously seen | 10 |" in report

    def test_zero_new_report_is_short(self):
        """Report with 0 new and 0 updated is concise."""
        classified = {"new": [], "updated": [], "unchanged": []}
        config = self._make_config()
        config.analysis_scope.include_all_current_jobs = False
        report = generate_incremental_report(
            classified, {"scrape_hours_old": 24}, config, include_previously_seen=False
        )
        assert "| **New jobs** | **0** |" in report
        assert len(report) < 3000  # Should be concise

    def test_report_includes_run_summary(self):
        """Report includes run summary table."""
        classified = {"new": [_make_job()], "updated": [], "unchanged": []}
        report = generate_incremental_report(
            classified,
            {"scrape_hours_old": 48, "scraped_count": 200, "unique_count": 50, "ai_analyzed_count": 5},
            self._make_config()
        )
        assert "Current Job Market Snapshot" in report
        assert "48 hours" in report


# ---------------------------------------------------------------------------
# Email Tests
# ---------------------------------------------------------------------------


class TestIncrementalEmail:
    def test_subject_with_new_and_updated(self):
        subject = build_incremental_email_subject(
            date(2026, 6, 13), 18, 4
        )
        assert "18 new" in subject
        assert "4 updated" in subject
        assert "2026-06-13" in subject

    def test_subject_zero_new(self):
        subject = build_incremental_email_subject(
            date(2026, 6, 13), 0, 0
        )
        assert "No new jobs" in subject

    def test_subject_only_new(self):
        subject = build_incremental_email_subject(
            date(2026, 6, 13), 10, 0
        )
        assert "10 new" in subject
        assert "updated" not in subject

    def test_zero_new_email_body(self):
        body = build_zero_new_email_body()
        assert "No new or materially updated" in body


# ---------------------------------------------------------------------------
# JD Preprocessor Tests
# ---------------------------------------------------------------------------


class TestJDPreprocessor:
    def test_strip_eeo(self):
        text = "Requirements: Python, React.\n\nWe are an equal opportunity employer. We do not discriminate based on race.\n\nApply now."
        result = strip_boilerplate(text)
        assert "equal opportunity" not in result.lower()
        assert "Python" in result

    def test_truncation(self):
        long_text = "A" * 20000
        result = preprocess_for_ai(long_text, max_chars=1000)
        assert len(result) <= 1000

    def test_truncation_at_sentence(self):
        text = "First sentence. " * 1000
        result = preprocess_for_ai(text, max_chars=200)
        assert result.endswith(".")


# ---------------------------------------------------------------------------
# Backfill Migration Tests
# ---------------------------------------------------------------------------


class TestBackfillMigration:
    def test_backfill_populates_history(self, mem_db_with_jobs_table):
        """Existing jobs are backfilled into job_history."""
        db = mem_db_with_jobs_table
        # Insert some legacy jobs
        db.execute(
            "INSERT INTO jobs (url, title, company, location, source, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("https://example.com/1", "Engineer", "Acme", "NYC", "linkedin", "Build stuff", "2026-06-01T00:00:00Z"),
        )
        db.execute(
            "INSERT INTO jobs (url, title, company, location, source, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("https://example.com/2", "Designer", "BigCo", "SF", "indeed", "Design things", "2026-06-02T00:00:00Z"),
        )
        db.commit()

        count = backfill_from_jobs_table(db)
        assert count == 2

        # Verify records exist
        rows = db.execute("SELECT COUNT(*) as cnt FROM job_history").fetchone()
        assert rows["cnt"] == 2

    def test_backfill_idempotent(self, mem_db_with_jobs_table):
        """Running backfill twice doesn't create duplicates."""
        db = mem_db_with_jobs_table
        db.execute(
            "INSERT INTO jobs (url, title, company, description, created_at) VALUES (?, ?, ?, ?, ?)",
            ("https://example.com/1", "Engineer", "Acme", "Build stuff", "2026-06-01T00:00:00Z"),
        )
        db.commit()

        count1 = backfill_from_jobs_table(db)
        count2 = backfill_from_jobs_table(db)
        assert count1 == 1
        assert count2 == 0

        rows = db.execute("SELECT COUNT(*) as cnt FROM job_history").fetchone()
        assert rows["cnt"] == 1


# ---------------------------------------------------------------------------
# Report and Archive Generator Tests
# ---------------------------------------------------------------------------

from utils.report_generator import generate_incremental_report, _deduplicate_insights
from utils.watch_config import JobWatchConfig, ReportConfig, AnalysisScopeConfig
import re

def test_report_has_toc_and_anchors():
    config = JobWatchConfig(target_roles=["SWE"], locations=[])
    config.report = ReportConfig(evidence_examples_per_insight=3, include_evidence_appendix=True)
    report = generate_incremental_report(
        classified_jobs={"new": [{"title": "Job1"}]},
        run_stats={},
        config=config,
    )
    
    assert "## Table of Contents" in report
    assert "[Executive Current Market Snapshot](#1-executive-current-market-snapshot)" in report
    assert "- [SWE Intelligence](#2-swe-intelligence)" in report

def test_repeated_insight_deduplication():
    # Setup summary with repeated insights
    summary = {
        "role_analyses": {
            "Engineering": {
                "role_specific_insights": ["Must know Python very well"],
                "resume_actions": ["Learn Rust", "Must know Python very well"]
            },
            "Data": {
                "role_specific_insights": ["Must know Python very well", "Learn SQL"]
            }
        }
    }
    
    _deduplicate_insights(summary)
    
    # "Must know Python very well" is seen in both roles. Should become a cross role pattern.
    assert "cross_role_patterns" in summary
    assert any("Must know Python very well" in p for p in summary["cross_role_patterns"])
    # It also stays in the roles but deduplicated internally.
    assert "Must know Python very well" in summary["role_analyses"]["Engineering"]["role_specific_insights"]
    assert "Must know Python very well" not in summary["role_analyses"]["Engineering"]["resume_actions"]
    assert "Learn Rust" in summary["role_analyses"]["Engineering"]["resume_actions"]

def test_all_current_jobs_detailed_and_compact():
    config = JobWatchConfig(target_roles=["SWE"], locations=[])
    config.analysis_scope = AnalysisScopeConfig(detailed_current_jobs_limit=2, include_all_current_jobs=True)
    
    jobs = [
        {"title": "Job1", "_stable_identity": "j1", "matched_target_role": "SWE", "match_state": "matched"},
        {"title": "Job2", "_stable_identity": "j2", "matched_target_role": "SWE", "match_state": "matched"},
        {"title": "Job3", "_stable_identity": "j3", "matched_target_role": "SWE", "match_state": "matched"}
    ]
    
    report = generate_incremental_report(
        classified_jobs={"new": [jobs[0], jobs[1]], "unchanged": [jobs[2]]},
        run_stats={},
        config=config,
    )
    
    assert "Detailed Current Jobs Grouped by Role" in report
    assert "### SWE" in report
    assert "Job1 @" in report
    assert "#### Additional SWE Jobs" in report
    assert "Job3" in report

def test_report_size_limits():
    from utils.report_generator import _truncate_words
    
    assert _truncate_words("One two three four five", 3) == "One two three..."
    assert _truncate_words("One two", 3) == "One two"
    
    config = JobWatchConfig(target_roles=["Dev"], locations=[])
    config.report = ReportConfig(max_executive_words=5, max_pattern_words=4)
    
    ai_summary = {
        "configured_roles": ["Dev"],
        "market_snapshot": {
            "executive_summary": ["This is a very long sentence that needs to be truncated safely."]
        },
        "role_analyses": {
            "Dev": {
                "job_count": 1,
                "role_specific_insights": ["This explanation is also excessively long."]
            }
        }
    }
    
    report = generate_incremental_report(
        classified_jobs={"new": []},
        run_stats={},
        config=config,
        ai_market_summary=ai_summary
    )
    
    assert "This is a very long..." in report
    assert "This explanation is also excessively long." in report
