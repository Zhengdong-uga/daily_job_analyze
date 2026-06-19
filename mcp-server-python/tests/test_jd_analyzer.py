"""
Unit tests for the jd_analyzer module.
"""

from utils.jd_analyzer import (
    normalize_description_text,
    extract_keyword_counts,
    extract_job_requirements,
    group_jobs_by_skill_cluster,
    build_market_trend_summary
)


def test_normalize_description_text():
    raw = "<b>Hello</b> world! [Link](http://example.com) **Bold** text.\n\n   Spaces."
    cleaned = normalize_description_text(raw)
    assert cleaned == "Hello world! Link Bold text. Spaces."


def test_extract_keyword_counts():
    jobs = [
        {"title": "AI Engineer", "description": "We need Python and generative AI."},
        {"title": "Frontend", "description": "React and TypeScript."}
    ]
    groups = {
        "ai_ml": ["AI", "generative AI"],
        "frontend": ["React", "TypeScript", "Vue"]
    }
    
    counts = extract_keyword_counts(jobs, groups)
    
    assert "ai_ml" in counts
    assert "AI" in counts["ai_ml"] # Lowercased in dict? Wait, the dict keys are the exact keyword strings provided.
    # The function uses original casing for keys
    assert "AI" in counts["ai_ml"]
    assert counts["ai_ml"]["AI"]["count"] == 1
    assert "generative AI" in counts["ai_ml"]
    assert counts["ai_ml"]["generative AI"]["count"] == 1
    
    assert "frontend" in counts
    assert "React" in counts["frontend"]
    assert counts["frontend"]["React"]["count"] == 1
    assert "Vue" not in counts["frontend"] # Excluded if 0


def test_extract_job_requirements():
    job = {
        "description": "Must have strong React and generative AI skills. You will work cross-functional.\n* Build scalable systems.\n* Collaborate with product manager."
    }
    reqs = extract_job_requirements(job)
    
    assert "React/TypeScript" in reqs["hard_skills"]
    assert "LLMs/GenAI" in reqs["hard_skills"]
    assert "Cross-functional Collaboration" in reqs["soft_skills"]
    assert len(reqs["responsibilities"]) >= 1


def test_group_jobs_by_skill_cluster():
    jobs = [
        {"title": "AI Engineer"},
        {"title": "UX Engineer"},
        {"title": "Backend Dev", "description": "infrastructure"}
    ]
    clusters = group_jobs_by_skill_cluster(jobs)
    
    assert len(clusters["AI / ML Engineering"]) == 1
    assert len(clusters["UX Engineering / Design Engineering"]) == 1
    assert len(clusters["Infrastructure / Platform Engineering"]) == 1


def test_build_market_trend_summary():
    # Provide enough jobs to trigger the AI trend (>30%)
    jobs = [
        {"title": "Frontend", "description": "Using AI and LLM."},
        {"title": "Backend", "description": "Doing AI."},
        {"title": "Designer", "description": "Doing something else."}
    ]
    trends = build_market_trend_summary(jobs)
    
    assert len(trends["top_trends"]) > 0
    assert any("AI" in t for t in trends["top_trends"])
