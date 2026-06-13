"""
Unit tests for the report_generator module.
"""

from utils.report_generator import _truncate_description, generate_markdown_report
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
    assert len(truncated) <= 803 # 800 + "..."
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
    assert "Total Matched Jobs:** 3" in markdown
    
    # Check sections
    assert "Section 1: Preferred Company Matches (1)" in markdown
    assert "Section 2: Strong Matches (1)" in markdown
    assert "Section 3: Other Matches (1)" in markdown
    
    # Check job rendering
    assert "### [AI Engineer @ OpenAI](http://example.com/1)" in markdown
    assert "**Keywords Found:** python, LLM" in markdown
