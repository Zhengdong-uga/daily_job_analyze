"""
Unit tests for the job_filter module.
"""

from typing import Dict, Any
from utils.job_filter import calculate_match_score, filter_and_rank_jobs, normalize_text
from utils.watch_config import JobWatchConfig, PreferencesConfig


def get_mock_config() -> JobWatchConfig:
    return JobWatchConfig(
        target_roles=["AI Engineer", "Backend Engineer"],
        locations=["New York", "Remote"],
        role_aliases={"AI Engineer": ["Machine Learning", "ML Engineer"]},
        location_aliases={"New York": ["NYC", "Manhattan"]},
        preferred_companies=["OpenAI", "Anthropic"],
        exclude_companies=["Revature"],
        include_keywords=["python", "react"],
        exclude_keywords=["director", "VP"],
        preferences=PreferencesConfig(minimum_match_score=40)
    )


def test_normalize_text():
    assert normalize_text("  Hello World  ") == "hello world"
    assert normalize_text(None) == ""


def test_calculate_match_score_exact_role_and_location():
    config = get_mock_config()
    job = {
        "title": "AI Engineer",
        "company": "Startup Inc",
        "location": "New York",
        "description": "Looking for an AI Engineer in New York."
    }
    
    score, metadata = calculate_match_score(job, config)
    # 30 (role) + 20 (location) = 50
    assert score == 50
    assert metadata["matched_role"] == "AI Engineer"
    assert metadata["matched_location"] == "New York"
    assert not metadata["is_preferred_company"]


def test_calculate_match_score_alias_match():
    config = get_mock_config()
    job = {
        "title": "Senior ML Engineer",
        "company": "Tech Co",
        "location": "NYC",
        "description": "Writing Python."
    }
    
    score, metadata = calculate_match_score(job, config)
    # 30 (role alias) + 20 (location alias) + 5 (python keyword) = 55
    assert score == 55
    assert metadata["matched_role"] == "AI Engineer"
    assert metadata["matched_location"] == "New York"
    assert "python" in metadata["matched_keywords"]


def test_calculate_match_score_preferred_company():
    config = get_mock_config()
    job = {
        "title": "Backend Engineer",
        "company": "OpenAI",
        "location": "Remote",
    }
    
    score, metadata = calculate_match_score(job, config)
    # 30 (role) + 20 (location) + 20 (company) = 70
    assert score == 70
    assert metadata["is_preferred_company"]


def test_calculate_match_score_exclude_keyword():
    config = get_mock_config()
    job = {
        "title": "Director of AI",
        "company": "OpenAI",
        "location": "Remote",
    }
    
    score, metadata = calculate_match_score(job, config)
    # Should be excluded because of "director"
    assert score == -1


def test_calculate_match_score_exclude_company():
    config = get_mock_config()
    job = {
        "title": "AI Engineer",
        "company": "Revature",
        "location": "Remote",
    }
    
    score, metadata = calculate_match_score(job, config)
    # Should be excluded because of company
    assert score == -1


def test_filter_and_rank_jobs():
    config = get_mock_config()
    
    jobs = [
        {"id": 1, "title": "Director", "company": "Tech", "location": "Remote"}, # score -1
        {"id": 2, "title": "Janitor", "company": "Tech", "location": "Remote"}, # score 20 (< min 40)
        {"id": 3, "title": "AI Engineer", "company": "Tech", "location": "NYC"}, # score 50
        {"id": 4, "title": "Backend Engineer", "company": "OpenAI", "location": "Remote"}, # score 70, preferred
    ]
    
    filtered = filter_and_rank_jobs(jobs, config)
    
    assert len(filtered) == 2
    # OpenAI job should be first (preferred company)
    assert filtered[0]["id"] == 4
    assert filtered[1]["id"] == 3
