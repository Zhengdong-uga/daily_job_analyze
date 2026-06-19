import pytest
from utils.watch_config import load_config, ConfigValidationError
from utils.job_filter import calculate_match_score

def test_dynamic_roles_config_parsing(tmp_path):
    yaml_path = tmp_path / "config.yaml"
    yaml_content = """
target_roles:
  - name: "Forward Deployed Engineer"
    aliases:
      - "Forward Deployed Software Engineer"
      - "AI Solutions Engineer"
  - "Data Scientist"
locations:
  - "Remote"
preferences:
  minimum_match_score: 40
  max_jobs_in_report: 50
scrape:
  sites: ["linkedin"]
  results_wanted: 10
  hours_old: 24
  require_description: true
report:
  output_dir: "reports/daily"
  format: "markdown"
"""
    yaml_path.write_text(yaml_content)
    
    config = load_config(yaml_path)
    
    # Check roles
    assert "Forward Deployed Engineer" in config.target_roles
    assert "Data Scientist" in config.target_roles
    
    # Check aliases
    assert "Forward Deployed Software Engineer" in config.role_aliases["Forward Deployed Engineer"]
    assert "AI Solutions Engineer" in config.role_aliases["Forward Deployed Engineer"]
    
def test_dynamic_roles_filtering(tmp_path):
    yaml_path = tmp_path / "config.yaml"
    yaml_content = """
target_roles:
  - name: "Data Scientist"
    aliases:
      - "Machine Learning Scientist"
locations:
  - "Remote"
preferences:
  minimum_match_score: 40
  max_jobs_in_report: 50
scrape:
  sites: ["linkedin"]
  results_wanted: 10
  hours_old: 24
  require_description: true
report:
  output_dir: "reports/daily"
  format: "markdown"
"""
    yaml_path.write_text(yaml_content)
    config = load_config(yaml_path)
    
    job1 = {"title": "Data Scientist", "company": "Example", "location": "Remote", "description": ""}
    score1, meta1 = calculate_match_score(job1, config)
    assert meta1["matched_target_role"] == "Data Scientist"
    assert meta1["role_match_reason"] == "Exact title match: Data Scientist"
    assert meta1["role_match_confidence"] == "high"
    
    job2 = {"title": "Machine Learning Scientist", "company": "Example", "location": "Remote", "description": ""}
    score2, meta2 = calculate_match_score(job2, config)
    assert meta2["matched_target_role"] == "Data Scientist"
    assert "Alias match without duty evidence: Machine Learning Scientist -> Data Scientist" in meta2["role_match_reason"]


def test_dynamic_role_report_generation(tmp_path):
    from utils.watch_config import JobWatchConfig
    from utils.report_generator import generate_incremental_report

    config = JobWatchConfig(
        target_roles=[
            "Data Scientist",
            "Forward Deployed Engineer",
            "Climate Data Specialist"
        ],
        locations=["Remote"]
    )
    # Ensure backwards compatible string roles work
    assert config.target_roles == ["Data Scientist", "Forward Deployed Engineer", "Climate Data Specialist"]

    classified = {
        "new": [
            {
                "title": "Data Scientist",
                "company": "Company A",
                "url": "http://a.com",
                "_stable_identity": "job_a",
                "match_state": "matched",
                "matched_target_role": "Data Scientist"
            },
            {
                "title": "Forward Deployed Engineer",
                "company": "Company B",
                "url": "http://b.com",
                "_stable_identity": "job_b",
                "match_state": "matched",
                "matched_target_role": "Forward Deployed Engineer"
            },
            {
                "title": "Unmatched Job",
                "company": "Company C",
                "url": "http://c.com",
                "_stable_identity": "job_c",
                "match_state": "unmatched"
            }
        ],
        "updated": [],
        "unchanged": []
    }

    ai_job_analyses = {}
    ai_update_analyses = {}
    ai_market_summary = {
        "role_analyses": {
            "Data Scientist": {
                "job_count": 5,
                "responsibility_frequencies": [{"responsibility": "Build models", "count": 4, "percentage": 80}],
                "required_skill_frequencies": [{"skill": "Python", "count": 5, "percentage": 100}],
                "preferred_skill_frequencies": [{"skill": "C++", "count": 2, "percentage": 40}],
                "case_study_recommendations": ["Showcase an end-to-end ML model"],
                "portfolio_recommendations": ["GitHub with clean notebooks"],
                "resume_keywords": ["Machine Learning", "Python"],
                "resume_actions": ["Trained models"],
                "linkedin_actions": ["Post about AI"]
            },
            "Climate Data Specialist": {
                "job_count": 2,
                "responsibility_frequencies": [{"responsibility": "Analyze climate data", "count": 2, "percentage": 100}],
                "required_skill_frequencies": [{"skill": "GIS", "count": 2, "percentage": 100}],
                "preferred_skill_frequencies": [{"skill": "Python", "count": 1, "percentage": 50}],
                "case_study_recommendations": ["Map visualizations"],
                "portfolio_recommendations": ["GIS Portfolio"],
                "resume_keywords": ["Climate", "Data"],
                "resume_actions": ["Analyzed spatial data"],
                "linkedin_actions": ["Share climate insights"]
            }
        }
    }

    # Generate the report (Simulating Gemini failure deterministic fallback, 
    # since we just pass the mock AI summary directly to the markdown generator)
    report = generate_incremental_report(
        classified_jobs=classified,
        run_stats={},
        config=config,
        ai_market_summary=ai_market_summary,
        include_previously_seen=False
    )

    # independent grouping and denominators per role
    assert "Based on 5 recent jobs." in report
    assert "Based on 2 recent jobs." in report

    # required versus preferred separation
    assert "Required vs Preferred Skills" in report
    assert "| Python | 5 of 5 jobs (100%) | 1 of 5 jobs (50%) |" in report or "| Python | 5 of 5 jobs (100%) | - |" in report
    
    # role-specific responsibilities
    assert "Build models" in report
    assert "Analyze climate data" in report

    # role-specific case-study recommendation
    assert "Showcase an end-to-end ML model" in report

    # portfolio recommendation
    assert "GitHub with clean notebooks" in report

    # resume keywords and actions
    assert "Machine Learning, Python" in report
    assert "Trained models" in report

    # unmatched jobs excluded from role statistics
    assert "Unmatched Job" not in report

    # current jobs grouped by configured role
    assert "### Data Scientist" in report
    assert "### Forward Deployed Engineer" in report

    # previously unseen role such as Climate Data Specialist
    assert "Climate Data Specialist Intelligence" in report

