import pytest
import logging
from unittest.mock import patch, MagicMock

@pytest.fixture
def mock_dependencies():
    with patch("scripts.run_daily_job_watch.parse_args") as mock_parse_args, \
         patch("scripts.run_daily_job_watch.load_config") as mock_load_config, \
         patch("scripts.run_daily_job_watch.get_history_connection") as mock_conn, \
         patch("scripts.run_daily_job_watch._resolve_ai_provider") as mock_resolve_provider, \
         patch("scripts.run_daily_job_watch.query_recent_jobs") as mock_query, \
         patch("scripts.run_daily_job_watch.filter_and_rank_jobs") as mock_filter, \
         patch("scripts.run_daily_job_watch.classify_jobs") as mock_classify, \
         patch("scripts.run_daily_job_watch.generate_incremental_report") as mock_report, \
         patch("scripts.run_daily_job_watch.write_daily_report") as mock_write:
         
        yield {
            "args": mock_parse_args,
            "config": mock_load_config,
            "provider": mock_resolve_provider,
            "classify": mock_classify,
            "filter": mock_filter,
            "query": mock_query,
            "report": mock_report
        }

def test_synthesis_flow_validation(mock_dependencies, caplog):
    caplog.set_level(logging.INFO)
    
    # Mock args
    args = MagicMock()
    args.report_only = True
    args.dry_run = True
    args.ai = True
    args.reanalyze_all = False
    args.include_previously_seen = False
    args.max_ai_jobs = 100
    args.send_email = False
    args.hours_old = 24
    args.hours = 24
    mock_dependencies["args"].return_value = args
    
    # Mock config
    config = MagicMock()
    config.ai_analysis.enabled = True
    config.ai_analysis.analyze_new_jobs = True
    config.ai_analysis.analyze_updated_jobs = True
    config.ai_analysis.analyze_unchanged_jobs = False
    config.ai_analysis.generate_comparative_summary = True
    config.ai_analysis.cache_results = True
    config.ai_analysis.bootstrap_uncached_jobs = False
    config.analysis_scope.include_rule_fallback_results = True
    config.target_roles = ["AI Engineer", "Data Scientist", "Forward Deployed Engineer"]
    mock_dependencies["config"].return_value = config
    
    # Mock AI provider
    provider = MagicMock()
    provider.provider_name = "mock"
    provider.extraction_model = "mock"
    provider.synthesis_model = "mock"
    # Fresh analyses succeed
    provider.analyze_job.return_value = {"matched_keywords": ["Python"]}
    
    # Simulate a 503 for synthesis (or any failure that returns empty/None)
    provider.generate_market_summary.return_value = {} # Empty triggers invalid -> fallback
    
    mock_dependencies["provider"].return_value = (provider, "v1")
    
    # Mock jobs
    # 15 new (fresh), 12 unchanged (cached), 1 updated (fallback)
    # Total 28
    
    jobs = []
    
    # 15 fresh (new)
    new_jobs = []
    for i in range(15):
        j = {"_stable_identity": f"new_{i}", "_content_hash": f"hash_{i}", "matched_target_role": "AI Engineer", "match_state": "matched", "title": "Fresh AI", "company": "Co"}
        new_jobs.append(j)
        jobs.append(j)
        
    # 12 cached (unchanged)
    unchanged_jobs = []
    for i in range(12):
        j = {"_stable_identity": f"cache_{i}", "_content_hash": f"hash_c_{i}", "matched_target_role": "Data Scientist", "match_state": "matched", "title": "Cached DS", "company": "Co"}
        unchanged_jobs.append(j)
        jobs.append(j)
        
    # 1 fallback (updated but API fails)
    updated_jobs = [{"_stable_identity": "fall_1", "_content_hash": "hash_f_1", "matched_target_role": "Forward Deployed Engineer", "match_state": "matched", "title": "Fall FDE", "company": "Co"}]
    jobs.extend(updated_jobs)
    
    mock_dependencies["query"].return_value = jobs
    mock_dependencies["filter"].return_value = jobs
    
    classified = {
        "new": new_jobs,
        "updated": updated_jobs,
        "unchanged": unchanged_jobs
    }
    mock_dependencies["classify"].return_value = classified
    
    # Mock cache: hits for unchanged, miss for new/updated
    with patch("scripts.run_daily_job_watch.get_cached_analysis") as mock_get_cache:
        def cache_side_effect(conn, identity, *args, **kwargs):
            if identity.startswith("cache_"):
                return {"cached_data": True}
            return None
        mock_get_cache.side_effect = cache_side_effect
        
        # Make analyze_job fail for updated to trigger rule fallback
        def analyze_side_effect(job, *args, **kwargs):
            if job["_stable_identity"].startswith("fall_"):
                return None
            return {"fresh_data": True}
        provider.analyze_job.side_effect = analyze_side_effect
        
        # Run
        from scripts.run_daily_job_watch import run_pipeline
        run_pipeline()
        
    logs = caplog.text
    
    # Validations
    assert "Fresh analyses: 15" in logs
    assert "Cached analyses: 12" in logs
    assert "Rule fallbacks: 1" in logs
    assert "Total analysis objects: 28" in logs
    assert "Structured synthesis input: 28" in logs
    assert "Generating deterministic fallback synthesis from per-job AI results." in logs
    
    # Verify the report was called with correct data
    report_call = mock_dependencies["report"].call_args
    ai_job_analyses = report_call.kwargs["ai_job_analyses"]
    
    assert len(ai_job_analyses) == 28
    
    # Verify metadata was enriched
    sample_fresh = ai_job_analyses["new_0"]
    assert sample_fresh["analysis_source"] == "fresh"
    assert sample_fresh["matched_target_role"] == "AI Engineer"
    
    sample_cache = ai_job_analyses["cache_0"]
    assert sample_cache["analysis_source"] == "cache"
    assert sample_cache["matched_target_role"] == "Data Scientist"
    
    sample_rule = ai_job_analyses["fall_1"]
    assert sample_rule["analysis_source"] == "rule"
    assert sample_rule["matched_target_role"] == "Forward Deployed Engineer"
    
    # Verify fallback generated populated deterministic roles
    ai_market_summary = report_call.kwargs["ai_market_summary"]
    role_analyses = ai_market_summary.get("role_analyses", {})
    assert "AI Engineer" in role_analyses
    assert "Data Scientist" in role_analyses
    assert "Forward Deployed Engineer" in role_analyses
    
    assert role_analyses["AI Engineer"]["job_count"] == 15
    assert role_analyses["Data Scientist"]["job_count"] == 12
    assert role_analyses["Forward Deployed Engineer"]["job_count"] == 1

def test_gemini_never_called_with_empty_input(mock_dependencies, caplog):
    caplog.set_level(logging.INFO)
    
    # Mock args
    args = MagicMock()
    args.report_only = True
    args.dry_run = True
    args.ai = True
    args.reanalyze_all = False
    args.max_ai_jobs = 100
    args.hours_old = 24
    args.hours = 24
    args.send_email = False
    mock_dependencies["args"].return_value = args
    
    # Mock config
    config = MagicMock()
    config.ai_analysis.enabled = True
    config.ai_analysis.generate_comparative_summary = True
    config.target_roles = ["AI Engineer"]
    mock_dependencies["config"].return_value = config
    
    provider = MagicMock()
    provider.provider_name = "mock"
    mock_dependencies["provider"].return_value = (provider, "v1")
    
    # Mock jobs but analysis returns nothing (no fallback, no cache, no fresh)
    jobs = [{"_stable_identity": "j1", "_content_hash": "hash_1", "matched_target_role": "AI Engineer", "match_state": "matched"}]
    mock_dependencies["query"].return_value = jobs
    mock_dependencies["filter"].return_value = jobs
    
    # Assume classification
    mock_dependencies["classify"].return_value = {"new": jobs, "updated": [], "unchanged": []}
    
    # Make API return None, and disable fallback
    config.analysis_scope.include_rule_fallback_results = False
    provider.analyze_job.return_value = None
    
    with patch("scripts.run_daily_job_watch.get_cached_analysis", return_value=None):
        from scripts.run_daily_job_watch import run_pipeline
        run_pipeline()
        
    # Check that synthesis was bypassed
    assert "High-severity data-flow error: matched jobs exist but current_analyses_list is empty. Bypassing Gemini API." in caplog.text
    provider.generate_market_summary.assert_not_called()
