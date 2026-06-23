"""
Unit tests for the report_generator module.
"""

from utils.report_generator import (
    _truncate_description,
    generate_markdown_report,
    generate_incremental_report,
)
from utils.job_filter import extract_max_yoe
from utils.watch_config import JobWatchConfig


def get_mock_config() -> JobWatchConfig:
    return JobWatchConfig(
        target_roles=["AI Engineer"],
        locations=["Remote"],
    )


def test_truncate_description():
    assert _truncate_description(None) == "*No description provided.*"
    assert _truncate_description("") == "*No description provided.*"
    
    short_desc = "This is a short description."
    assert _truncate_description(short_desc, 100) == short_desc
    
    long_desc = "A " * 1000
    truncated = _truncate_description(long_desc, 800)
    assert len(truncated) <= 803  # 800 + "..."
    assert truncated.endswith("...")


def test_generate_markdown_report():
    config = get_mock_config()
    jobs = [
        {
            "title": "AI Engineer",
            "company": "OpenAI",
            "location": "Remote",
            "url": "http://example.com/1",
            "is_preferred_company": True,
            "match_score": 90,
            "matched_role": "AI Engineer",
            "matched_keywords": ["python", "LLM"],
        },
    ]

    run_stats = {
        "total_scraped": 100,
        "total_inserted": 50,
        "total_duplicates": 50,
        "total_recent_checked": 60,
    }

    markdown = generate_markdown_report(jobs, run_stats, config)
    assert "Total Scraped:** 100" in markdown
    assert "Daily Job Intelligence Report" in markdown


# ── Incremental report section-order tests ──────────────────────────────────


def test_incremental_report_section_order():
    """Sections appear in the new user-first order."""
    config = JobWatchConfig(target_roles=["SWE"], locations=[])
    report = generate_incremental_report(
        classified_jobs={"new": [{"title": "SWE", "company": "Co", "url": "#"}]},
        run_stats={},
        config=config,
    )
    idx_snapshot = report.index("## 1. Executive Snapshot")
    idx_opps = report.index("## 2. New & Updated Opportunities")
    idx_means = report.index("## 3. What This Means for Me")
    idx_skills = report.index("## 4. Skills to Learn")
    idx_cross = report.index("## 5. Cross-Role Skill Patterns")
    idx_role = report.index("## 6. What Employers Want by Role")
    idx_reqpref = report.index("## 7. Required vs Preferred Skills")
    idx_trends = report.index("## 8. Industry & Hiring Trends")
    idx_changes = report.index("## 9. Changes Since Previous Run")
    idx_prev = report.index("## 10. Previously Seen Jobs")

    assert idx_snapshot < idx_opps < idx_means < idx_skills < idx_cross
    assert idx_cross < idx_role < idx_reqpref < idx_trends < idx_changes < idx_prev


def test_incremental_report_compact_job_cards():
    """New jobs render as compact cards without full JD."""
    config = JobWatchConfig(target_roles=["SWE"], locations=[])
    ai = {"id1": {"job_seeker_takeaway": "Great entry-level role."}}
    report = generate_incremental_report(
        classified_jobs={"new": [{"title": "SWE", "company": "Co", "url": "#", "_stable_identity": "id1"}]},
        run_stats={},
        config=config,
        ai_job_analyses=ai,
    )
    assert "Great entry-level role." in report
    assert "Required Skills:" not in report.split("## 3.")[0]  # no skills dump in the jobs section


def test_incremental_report_collapsible_evidence():
    """Industry trend evidence is inside a <details> block."""
    config = JobWatchConfig(target_roles=["SWE"], locations=[])
    summary = {
        "current_market_trends": [{
            "trend": "AI Boom",
            "explanation": "AI is growing.",
            "deterministic_evidence": ["Evidence line 1"],
            "affected_role_clusters": [],
            "example_jobs": [],
        }],
    }
    report = generate_incremental_report(
        classified_jobs={"new": []},
        run_stats={},
        config=config,
        ai_market_summary=summary,
    )
    assert "<details><summary>📊 Evidence</summary>" in report
    assert "Evidence line 1" in report


def test_incremental_report_collapsible_changes():
    """Changes section is collapsible."""
    config = JobWatchConfig(target_roles=["SWE"], locations=[])
    summary = {"changes_since_previous_run": ["Market shifted."]}
    report = generate_incremental_report(
        classified_jobs={"new": []},
        run_stats={},
        config=config,
        ai_market_summary=summary,
    )
    changes_section = report.split("## 9. Changes Since Previous Run")[1].split("## 10.")[0]
    assert "<details>" in changes_section
    assert "Market shifted." in changes_section


def test_incremental_report_role_collapsible():
    """Per-role sections are inside <details> blocks."""
    config = JobWatchConfig(target_roles=["SWE"], locations=[])
    summary = {
        "role_analyses": {
            "SWE": {
                "job_count": 3,
                "role_specific_insights": ["Insight 1"],
                "required_skill_frequencies": [],
                "preferred_skill_frequencies": [],
                "responsibility_frequencies": [],
                "ideal_candidate_profile": [],
                "resume_keywords": [],
                "resume_actions": [],
                "linkedin_actions": [],
                "portfolio_recommendations": [],
                "case_study_recommendations": [],
            }
        }
    }
    report = generate_incremental_report(
        classified_jobs={"new": []},
        run_stats={},
        config=config,
        ai_market_summary=summary,
    )
    role_section = report.split("## 6. What Employers Want by Role")[1].split("## 7.")[0]
    assert "<details>" in role_section
    assert "SWE" in role_section
    assert "Insight 1" in role_section


def test_incremental_report_required_vs_preferred_split():
    """Required and preferred skills are separated into sub-sections."""
    config = JobWatchConfig(target_roles=["SWE"], locations=[])
    summary = {
        "required_vs_preferred_patterns": [
            "Figma is required as a baseline tool.",
            "Motion graphics is preferred or a nice-to-have.",
            "Some general observation.",
        ]
    }
    report = generate_incremental_report(
        classified_jobs={"new": []},
        run_stats={},
        config=config,
        ai_market_summary=summary,
    )
    reqpref = report.split("## 7. Required vs Preferred Skills")[1].split("## 8.")[0]
    assert "Typically Required" in reqpref
    assert "Typically Preferred" in reqpref


# ── YoE extraction tests ───────────────────────────────────────────────────


def test_extract_max_yoe_basic():
    assert extract_max_yoe("5+ years of experience in React") == 5
    assert extract_max_yoe("Requires 2-4 yrs exp") == 2
    assert extract_max_yoe("Minimum of 3 years working") == 3
    assert extract_max_yoe("10 years of experience") == 10


def test_extract_max_yoe_no_match():
    assert extract_max_yoe("No mention of duration") == 0
    assert extract_max_yoe("") == 0


def test_extract_max_yoe_ignores_large():
    assert extract_max_yoe("25 years of experience") == 0
