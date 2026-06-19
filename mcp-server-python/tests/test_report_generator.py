"""
Unit tests for the report_generator module.
"""

from utils.report_generator import _truncate_words, generate_markdown_report
from utils.watch_config import JobWatchConfig


def get_mock_config() -> JobWatchConfig:
    return JobWatchConfig(
        target_roles=["AI Engineer"],
        locations=["Remote"],
    )


def test_truncate_words():
    assert _truncate_words(None, 10) == ""
    assert _truncate_words("", 10) == ""
    
    short_desc = "This is a short description."
    assert _truncate_words(short_desc, 100) == short_desc
    
    long_desc = "word " * 1000
    truncated = _truncate_words(long_desc, 10)
    assert len(truncated.split()) == 10
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
            "matched_target_role": "AI Engineer",
            "matched_keywords": ["python", "LLM"]
        },
        {
            "title": "Backend Engineer",
            "company": "Tech Corp",
            "location": "Remote",
            "url": "http://example.com/2",
            "is_preferred_company": False,
            "match_score": 65,
        },
        {
            "title": "Junior Dev",
            "company": "Small Biz",
            "location": "Remote",
            "url": "http://example.com/3",
            "is_preferred_company": False,
            "match_score": 45,
        }
    ]
    
    run_stats = {
        "total_scraped": 100,
        "total_inserted": 50,
        "total_duplicates": 50,
        "total_recent_checked": 60,
    }
    
    markdown = generate_markdown_report(jobs, run_stats, config)
    
    # Check stats are present
    assert "Total Scraped:** 100" in markdown
    assert "Total Jobs Included in Report:** 3" in markdown
    
    # Check sections
    assert "## 1. Executive Summary" in markdown
    assert "## 8. Individual Job Appendix" in markdown
    
    # Check job rendering
    assert "[AI Engineer @ OpenAI](http://example.com/1)" in markdown
    assert "Top Keywords: python, LLM" in markdown

def test_regression_no_duplicate_required_column():
    """
    Asserts that the rendered table header contains only one 'Required' column.
    """
    from utils.report_generator import generate_incremental_report
    from utils.watch_config import JobWatchConfig
    
    config = JobWatchConfig(
        target_roles=["Data Scientist"],
        locations=["Remote"]
    )
    
    ai_summary = {
        "role_analyses": {
            "Data Scientist": {
                "job_count": 1,
                "required_skill_frequencies": [{"skill": "Python", "count": 1, "percentage": 100}],
                "preferred_skill_frequencies": [{"skill": "R", "count": 1, "percentage": 100}]
            }
        }
    }
    
    classified = {"new": [], "updated": [], "unchanged": []}
    
    report = generate_incremental_report(
        classified_jobs=classified,
        run_stats={},
        config=config,
        ai_market_summary=ai_summary,
        include_previously_seen=False
    )
    
    assert "| Skill | Required | Preferred | Mentioned/Unclear | Total Role Jobs |" in report
    assert "| Skill | Required | Required | Preferred | Mentioned/Unclear | Total Role Jobs |" not in report
