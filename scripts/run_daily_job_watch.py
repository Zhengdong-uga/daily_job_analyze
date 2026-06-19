#!/usr/bin/env python3
"""
CLI entrypoint for the Incremental Job Intelligence system.

Orchestrates scraping, normalization, database insertion, filtering, ranking,
historical classification (new/updated/unchanged), optional AI analysis,
and incremental report generation.
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

# Cleanly add mcp-server-python to sys.path so we can import internal modules
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "mcp-server-python"))

from db.jobs_ingest_writer import JobsIngestWriter
from db.jobs_reader import get_connection, query_recent_jobs
from db.job_history_db import (
    classify_jobs,
    get_history_connection,
    get_previous_successful_run,
    get_jobs_for_run,
    start_run,
    complete_run,
    fail_run,
    update_analysis_status,
    update_last_reported,
    backfill_from_jobs_table,
    persist_run_job_results,
    update_run_job_ai_status,
    update_run_job_report_status,
    update_run_ai_status,
)
from utils.ai_cache import (
    bootstrap_cache_schema, 
    get_cached_analysis, 
    store_cached_analysis,
    compute_aggregate_input_hash,
    get_cached_market_summary,
    store_cached_market_summary,
)
from utils.job_filter import filter_and_rank_jobs
from utils.path_resolution import resolve_repo_relative_path
from utils.report_generator import (
    generate_incremental_report,
    write_daily_report,
    compute_skill_trends,
)
from utils.scrape_normalizer import normalize_and_filter, serialize_payload
from utils.watch_config import ConfigValidationError, load_config
from utils.jd_analyzer import summarize_job_description, extract_job_requirements
from utils.email_sender import (
    build_incremental_email_subject,
    build_zero_new_email_body,
    validate_email_settings,
    send_email_report,
)
from utils.html_email_renderer import markdown_to_email_html

# Load .env from project root
try:
    from dotenv import load_dotenv
    load_dotenv(repo_root / ".env")
except ImportError:
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="Incremental Job Intelligence Pipeline")
    parser.add_argument(
        "--config",
        type=str,
        default="job_watch_config.yaml",
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and report, but do not write to the database",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Skip scraping, generate report from existing database jobs",
    )
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="Send the generated report via email",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Path to write the report file (overrides config output_dir)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        help="Override hours_old from config for scraping and querying (alias for --hours-old)",
    )
    parser.add_argument(
        "--hours-old",
        type=int,
        help="Override hours_old from config for scraping and querying",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of jobs queried from database",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    # --- AI flags ---
    parser.add_argument(
        "--ai",
        action=argparse.BooleanOptionalAction,
        help="Enable/disable AI analysis for this run (overrides config)",
    )
    parser.add_argument(
        "--ai-provider",
        type=str,
        choices=["gemini", "openai"],
        help="AI provider to use (default: from config)",
    )
    parser.add_argument(
        "--include-previously-seen",
        action="store_true",
        help="Include unchanged jobs in report details",
    )
    parser.add_argument(
        "--reanalyze-all",
        action="store_true",
        help="Force re-analyze all matched jobs with AI",
    )
    parser.add_argument(
        "--since-last-run",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Use previous successful run as comparison baseline (overrides config)",
    )
    parser.add_argument(
        "--max-ai-jobs",
        type=int,
        help="Cap number of jobs sent to AI analysis",
    )
    return parser.parse_args()


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )


def _resolve_ai_provider(args, config):
    """Create an AI provider based on CLI args and config."""
    from utils.ai_provider import create_provider, NoOpProvider, PROMPT_VERSION

    if args.ai is not None:
        ai_enabled = args.ai
    else:
        ai_enabled = config.ai_analysis.enabled

    if not ai_enabled:
        return NoOpProvider(), PROMPT_VERSION

    provider_name = args.ai_provider or config.ai_analysis.provider
    model = config.ai_analysis.model
    extraction_model = config.ai_analysis.extraction_model
    synthesis_model = config.ai_analysis.synthesis_model
    temperature = config.ai_analysis.temperature

    # Resolve API key from environment
    if provider_name == "gemini":
        api_key = os.environ.get("JOBWATCH_GEMINI_API_KEY", "")
    elif provider_name == "openai":
        api_key = os.environ.get("JOBWATCH_OPENAI_API_KEY", "")
    else:
        api_key = ""

    if not api_key:
        logging.warning(
            f"AI provider '{provider_name}' requested but no API key found. "
            f"Set JOBWATCH_{provider_name.upper()}_API_KEY in .env. Falling back to rule-based."
        )
        return NoOpProvider(), PROMPT_VERSION

    try:
        provider = create_provider(
            provider_name, 
            api_key=api_key, 
            model=model, 
            extraction_model=extraction_model,
            synthesis_model=synthesis_model,
            temperature=temperature
        )
        logging.info(f"AI provider initialized: {provider_name} (model={provider.model})")
        return provider, PROMPT_VERSION
    except ImportError as e:
        logging.error(f"{e}\nFalling back to rule-based analysis.")
        return NoOpProvider(), PROMPT_VERSION
    except Exception as e:
        logging.warning(f"Failed to initialize AI provider '{provider_name}': {e}. Falling back to rule-based.")
        return NoOpProvider(), PROMPT_VERSION



def normalize_market_summary(summary: dict) -> dict:
    if not isinstance(summary, dict):
        return {}
    if "market_snapshot" not in summary:
        summary["market_snapshot"] = {}
    return summary

def is_valid_market_summary(summary: dict, source: str = "unknown") -> bool:
    import logging
    import json
    
    if not isinstance(summary, dict) or not summary:
        return False
        
    missing = []
    
    if "configured_roles" not in summary:
        missing.append("configured_roles")
        
    role_analyses = summary.get("role_analyses", {})
    if not role_analyses or not isinstance(role_analyses, dict):
        missing.append("role_analyses (missing or empty)")
    else:
        for role, data in role_analyses.items():
            if not isinstance(data, dict):
                missing.append(f"role_analyses.{role} (invalid structure)")
                continue
                
            if data.get("job_count", 0) < 0:
                missing.append(f"role_analyses.{role}.job_count")
            
            if not data.get("responsibility_frequencies"):
                missing.append(f"role_analyses.{role}.responsibility_frequencies")
                
            if not data.get("role_specific_insights"):
                missing.append(f"role_analyses.{role}.role_specific_insights")
                
            # Check at least one type of recommendation exists
            recs = [
                data.get("case_study_recommendations"),
                data.get("portfolio_recommendations"),
                data.get("resume_keywords"),
                data.get("resume_actions"),
                data.get("linkedin_actions")
            ]
            if not any(r and len(r) > 0 for r in recs):
                missing.append(f"role_analyses.{role}.recommendations (all missing)")
                
    summary_str = json.dumps(summary).lower()
    prohibited = [
        "fallback insight",
        "highlight the top required skills",
        "projects demonstrating the required skills",
        "candidate with listed skills",
        "list these skills on linkedin"
    ]
    for p in prohibited:
        if p in summary_str:
            missing.append(f"prohibited placeholder found: {p}")
        
    is_valid = len(missing) == 0
    
    val_res = {
        "valid": is_valid,
        "missing_or_empty_sections": missing,
        "top_level_keys": list(summary.keys()) if isinstance(summary, dict) else [],
        "source": source
    }
    
    try:
        Path("reports/debug").mkdir(parents=True, exist_ok=True)
        with open("reports/debug/latest-role-market-intelligence-validation.json", "w", encoding="utf-8") as f:
            json.dump(val_res, f, indent=2)
        with open("reports/debug/latest-role-market-intelligence-normalized.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    except Exception as e:
        logging.warning(f"Could not save validation artifacts: {e}")
        
    return is_valid

def run_pipeline():
    args = parse_args()
    setup_logging(args.verbose)

    config_path = resolve_repo_relative_path(args.config)
    try:
        config = load_config(config_path)
    except ConfigValidationError as e:
        logging.error(f"Configuration error: {e}")
        sys.exit(1)

    hours_old = args.hours_old or args.hours
    if hours_old is None:
        hours_old = config.scrape.hours_old

    # Initialize history DB connection
    history_conn = get_history_connection()
    run_id = start_run(history_conn, hours_old)

    # Check if this is the first run — if so, backfill
    previous_run = get_previous_successful_run(history_conn)
    if previous_run is None:
        logging.info("First run detected. Backfilling existing jobs into history...")
        try:
            backfilled = backfill_from_jobs_table(history_conn)
            logging.info(f"Backfilled {backfilled} existing jobs into job_history.")
        except Exception as e:
            logging.warning(f"Backfill failed (non-fatal): {e}")

    # Initialize AI provider
    ai_provider, prompt_version = _resolve_ai_provider(args, config)
    ai_enabled = not isinstance(ai_provider, __import__("utils.ai_provider", fromlist=["NoOpProvider"]).NoOpProvider)

    # Bootstrap cache schema
    bootstrap_cache_schema(history_conn)

    # Initialize run stats
    run_stats = {
        "total_scraped": 0,
        "total_inserted": 0,
        "total_duplicates": 0,
        "total_recent_checked": 0,
        "scrape_hours_old": hours_old,
    }

    # ── Stage 1: Scrape & Ingest (existing, unchanged) ──
    if not args.report_only:
        logging.info(f"Starting scrape for {len(config.target_roles)} roles across {len(config.locations)} locations...")

        try:
            from utils.jobspy_adapter import scrape_jobs_for_term
        except ImportError:
            logging.error("python-jobspy is required for scraping. Install it with: pip install python-jobspy")
            fail_run(history_conn, run_id)
            sys.exit(1)

        all_cleaned_records = []

        for location in config.locations:
            for role in config.target_roles:
                logging.info(f"Scraping '{role}' in '{location}'...")
                try:
                    raw_records = scrape_jobs_for_term(
                        term=role,
                        sites=config.scrape.sites,
                        location=location,
                        results_wanted=config.scrape.results_wanted,
                        hours_old=hours_old,
                    )

                    cleaned, skip_counts = normalize_and_filter(
                        raw_records,
                        require_description=config.scrape.require_description
                    )

                    # Prepare for DB insertion
                    from datetime import datetime, timezone
                    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    for rec in cleaned:
                        rec["created_at"] = created_at
                        rec["payload_json"] = serialize_payload(rec)

                    all_cleaned_records.extend(cleaned)
                    run_stats["total_scraped"] += len(cleaned)
                    logging.debug(f"  Got {len(cleaned)} clean records (skipped {skip_counts['skipped_no_description']} w/o desc)")

                except Exception as e:
                    logging.error(f"  Failed scraping '{role}' in '{location}': {e}")

        # Insert to DB
        if not args.dry_run and all_cleaned_records:
            logging.info(f"Inserting {len(all_cleaned_records)} records into database...")
            try:
                with JobsIngestWriter() as writer:
                    inserted, duplicates = writer.insert_cleaned_records(all_cleaned_records, status="new")
                    writer.commit()
                    run_stats["total_inserted"] = inserted
                    run_stats["total_duplicates"] = duplicates
                    logging.info(f"Database insertion complete: {inserted} new, {duplicates} duplicates.")
            except Exception as e:
                logging.error(f"Failed to insert records into database: {e}")
                fail_run(history_conn, run_id)
                sys.exit(1)
        elif args.dry_run:
            logging.info(f"DRY RUN: Would have inserted {len(all_cleaned_records)} records.")

    # ── Stage 2: Query Recent Jobs (existing, unchanged) ──
    logging.info(f"Querying database for jobs from the last {hours_old} hours...")
    recent_jobs = []
    try:
        with get_connection() as conn:
            recent_jobs = query_recent_jobs(conn, since_hours=hours_old, limit=args.limit)
            run_stats["total_recent_checked"] = len(recent_jobs)
            logging.info(f"Retrieved {len(recent_jobs)} recent jobs.")
    except Exception as e:
        logging.error(f"Failed to query recent jobs: {e}")
        if not args.dry_run:
            fail_run(history_conn, run_id)
            sys.exit(1)

    if not recent_jobs:
        logging.warning("No jobs found to evaluate. Exiting.")
        fail_run(history_conn, run_id)
        sys.exit(0)

    # ── Stage 3: Filter and Rank (existing, unchanged) ──
    logging.info("Filtering and ranking jobs based on configuration...")
    matched_jobs = filter_and_rank_jobs(recent_jobs, config)
    logging.info(f"Found {len(matched_jobs)} matched jobs meeting criteria.")

    # ── Stage 4: Classify jobs against job_history ──
    logging.info("Classifying jobs against historical database...")
    classified = classify_jobs(history_conn, matched_jobs)

    # Early persistence of classification
    persist_run_job_results(history_conn, run_id, classified)

    new_count = len(classified["new"])
    updated_count = len(classified["updated"])
    unchanged_count = len(classified["unchanged"])

    logging.info(f"Classification: {new_count} new, {updated_count} updated, {unchanged_count} unchanged")


    matched_state_count = sum(1 for j in matched_jobs if j.get("match_state") == "matched")
    ambiguous_state_count = sum(1 for j in matched_jobs if j.get("match_state") == "ambiguous")
    unmatched_state_count = sum(1 for j in matched_jobs if j.get("match_state") == "unmatched")
    
    run_stats["matched_state_count"] = matched_state_count
    run_stats["ambiguous_state_count"] = ambiguous_state_count
    run_stats["unmatched_state_count"] = unmatched_state_count
    run_stats["unique_count"] = len(matched_jobs)
    run_stats["new_count"] = new_count
    run_stats["updated_count"] = updated_count
    run_stats["unchanged_count"] = unchanged_count
    run_stats["scraped_count"] = run_stats.get("total_scraped", 0)

    # Honest Trends computation
    use_baseline = args.since_last_run if args.since_last_run is not None else config.ai_analysis.generate_comparative_summary
    if use_baseline and previous_run:
        logging.info("Computing honest skill trends against previous run baseline...")
        previous_jobs = get_jobs_for_run(history_conn, previous_run["run_id"])
        
        # Determine trend config
        trend_cfg = getattr(config.analysis, "trend_analysis", None)
        if not trend_cfg:
            class DummyCfg:
                min_current_jobs = 5
                min_previous_jobs = 5
                min_percentage_point_change = 10.0
            trend_cfg = DummyCfg()

        computed_trends = compute_skill_trends(
            current_jobs=matched_jobs,
            previous_jobs=previous_jobs,
            kw_groups=getattr(config, "keyword_groups", {}),
            trend_config=trend_cfg
        )
        run_stats["computed_trends"] = computed_trends
        if computed_trends.get("insufficient_data"):
            logging.info(f"Trends: {computed_trends.get('message')}")
        else:
            logging.info(f"Trends: Found {len(computed_trends.get('trends', []))} valid percentage point shifts.")

    # ── Stage 5: AI Analysis (if enabled) ──
    ai_job_analyses = {}
    ai_update_analyses = {}
    ai_market_summary = {}
    ai_analyzed_count = 0
    max_ai_jobs = args.max_ai_jobs or config.ai_analysis.max_jobs_per_run
    
    # Track metrics for logging
    cache_hits = 0
    fallback_count = 0
    extraction_calls = 0

    if ai_enabled:
        logging.info("Running per-job AI extraction...")

        def first_nonempty_list(analysis, *keys):
            for k in keys:
                val = analysis.get(k)
                if val and isinstance(val, list) and len(val) > 0:
                    return val
            return []

        def normalize_analysis_evidence(analysis):
            return {
                "required_skills": first_nonempty_list(
                    analysis,
                    "required_skills",
                    "hard_skills",
                    "must_have_skills",
                ),
                "preferred_skills": first_nonempty_list(
                    analysis,
                    "preferred_skills",
                    "nice_to_have_skills",
                ),
                "responsibilities": first_nonempty_list(
                    analysis,
                    "responsibilities",
                    "core_responsibilities",
                    "key_responsibilities",
                    "job_duties",
                ),
                "soft_skills": first_nonempty_list(
                    analysis,
                    "soft_skills",
                    "collaboration_skills",
                ),
            }

        def enrich_job_analysis(job, raw_analysis, source):
            analysis = dict(raw_analysis or {})
            analysis.update({
                "_stable_identity": job.get("_stable_identity"),
                "job_id": job.get("job_id"),
                "original_job_title": job.get("title"),
                "company": job.get("company"),
                "location": job.get("location"),
                "url": job.get("url"),
                "matched_target_role": job.get("matched_target_role"),
                "match_state": job.get("match_state", "matched"),
                "role_match_reason": job.get("role_match_reason"),
                "role_match_confidence": job.get("role_match_confidence"),
                "secondary_matched_roles": job.get("secondary_matched_roles", []),
                "analysis_source": source,
            })
            return analysis

        def _get_rule_based_fallback(job):
            kw_groups = getattr(config, "keyword_groups", {})
            summary = summarize_job_description(job, kw_groups)
            reqs = extract_job_requirements(job, kw_groups)
            return {
                "summary": summary,
                "required_skills": reqs["hard_skills"],
                "soft_skills": reqs["soft_skills"],
                "responsibilities": reqs.get("responsibilities", []),
                "role_cluster": job.get("matched_target_role", "Unknown"),
                "match_state": job.get("match_state", "unmatched")
            }

        def process_job_for_extraction(job, allow_api_call: bool):
            nonlocal ai_analyzed_count, cache_hits, fallback_count, extraction_calls
            identity = job.get("_stable_identity", "")
            content_hash = job.get("_content_hash", "")
            
            # Check cache first (if allowed and not forcing reanalyze)
            if config.ai_analysis.cache_results and not args.reanalyze_all:
                cached = get_cached_analysis(
                    history_conn, identity, content_hash,
                    ai_provider.provider_name, ai_provider.extraction_model,
                    prompt_version, "job_analysis"
                )
                if cached:
                    ai_job_analyses[identity] = enrich_job_analysis(job, cached, "cache")
                    update_analysis_status(
                        history_conn, identity, "cached",
                        ai_provider.provider_name, ai_provider.extraction_model, prompt_version
                    )
                    update_run_job_ai_status(history_conn, run_id, identity, sent_to_ai=True, ai_cache_hit=True)
                    cache_hits += 1
                    logging.debug(f"  Cache hit for: {job.get('title', '')} @ {job.get('company', '')}")
                    return True

            # If not in cache, call API if allowed by budget
            if allow_api_call and extraction_calls < max_ai_jobs:
                result = ai_provider.analyze_job(
                    job, max_description_chars=config.ai_analysis.max_description_chars
                )
                if result:
                    ai_job_analyses[identity] = enrich_job_analysis(job, result, "fresh")
                    extraction_calls += 1
                    ai_analyzed_count += 1
                    update_analysis_status(
                        history_conn, identity, "completed",
                        ai_provider.provider_name, ai_provider.extraction_model, prompt_version
                    )
                    update_run_job_ai_status(history_conn, run_id, identity, sent_to_ai=True, ai_cache_hit=False)
                    if config.ai_analysis.cache_results:
                        store_cached_analysis(
                            history_conn, identity, content_hash,
                            ai_provider.provider_name, ai_provider.extraction_model,
                            prompt_version, "job_analysis", result
                        )
                    logging.debug(f"  Analyzed: {job.get('title', '')} @ {job.get('company', '')}")
                    return True
                else:
                    update_analysis_status(history_conn, identity, "failed")
            
            # If API not allowed, failed, or budget exceeded, use fallback if configured
            if config.analysis_scope.include_rule_fallback_results:
                ai_job_analyses[identity] = enrich_job_analysis(
                    job,
                    _get_rule_based_fallback(job),
                    "rule",
                )
                fallback_count += 1
                logging.debug(f"  Rule fallback for: {job.get('title', '')} @ {job.get('company', '')}")
                return True
            return False

        # Process new and updated jobs
        if config.ai_analysis.analyze_new_jobs or args.reanalyze_all:
            for job in classified["new"]:
                process_job_for_extraction(job, allow_api_call=True)
                
        if config.ai_analysis.analyze_updated_jobs or args.reanalyze_all:
            for job in classified["updated"]:
                identity = job.get("_stable_identity", "")
                old_desc = job.get("_previous_description", "")
                new_desc = job.get("description", "")
                if old_desc and new_desc and extraction_calls < max_ai_jobs:
                    result = ai_provider.analyze_job_update(
                        old_desc, new_desc,
                        max_description_chars=config.ai_analysis.max_description_chars
                    )
                    if result:
                        ai_update_analyses[identity] = result
                        logging.debug(f"  Update analyzed: {job.get('title', '')} @ {job.get('company', '')}")
                # Also extract full JD
                process_job_for_extraction(job, allow_api_call=True)

        # Process unchanged jobs
        uncached_bootstrapped = 0
        for job in classified["unchanged"]:
            allow_api_call = False
            if args.reanalyze_all:
                allow_api_call = True
            elif config.ai_analysis.bootstrap_uncached_jobs and uncached_bootstrapped < config.ai_analysis.max_uncached_jobs_per_run:
                # Check if it has a cache
                identity = job.get("_stable_identity", "")
                content_hash = job.get("_content_hash", "")
                cached = get_cached_analysis(
                    history_conn, identity, content_hash,
                    ai_provider.provider_name, ai_provider.extraction_model,
                    prompt_version, "job_analysis"
                )
                if not cached:
                    allow_api_call = True
                    uncached_bootstrapped += 1
            
            process_job_for_extraction(job, allow_api_call=allow_api_call)

        logging.info(f"Extraction complete: {extraction_calls} API calls, {cache_hits} cache hits, {fallback_count} rule fallbacks.")

        # Generate comparative market summary
        if config.ai_analysis.generate_comparative_summary and len(matched_jobs) > 0:
            logging.info("Generating current market snapshot synthesis...")
            run_metrics = {
                "new_count": new_count,
                "updated_count": updated_count,
                "unchanged_count": unchanged_count,
                "total_matched": len(matched_jobs),
                "scrape_hours_old": hours_old,
                "computed_trends": run_stats.get("computed_trends", {}),
            }
            
            # Use all available job extractions

            current_analyses_list = []
            for k, analysis in ai_job_analyses.items():
                if analysis.get("match_state") != "unmatched" and analysis.get("matched_target_role"):
                    current_analyses_list.append(analysis)
                else:
                    logging.info(f"Filtering out {k} from current_analyses_list. match_state: {analysis.get('match_state')}, matched_target_role: {analysis.get('matched_target_role')}")
            
            logging.info(f"Classified matched jobs: {len(matched_jobs)}")
            logging.info(f"Fresh analyses: {extraction_calls}")
            logging.info(f"Cached analyses: {cache_hits}")
            logging.info(f"Rule fallbacks: {fallback_count}")
            logging.info(f"Total analysis objects: {len(ai_job_analyses)}")
            logging.info(f"Structured synthesis input: {len(current_analyses_list)}")

            expected = extraction_calls + cache_hits + fallback_count
            actual = len(current_analyses_list)
            if actual != expected:
                logging.warning(f"Invariant failure: expected {expected} synthesis inputs, got {actual}")
                
            # Check market summary cache
            agg_hash = compute_aggregate_input_hash(
                run_metrics=run_metrics,
                previous_metrics=previous_run,
                new_analyses=current_analyses_list,
                update_analyses=[],
            )
            
            logging.info(f"Aggregate synthesis cache key: {agg_hash}")
            cached_summary = None
            if config.ai_analysis.cache_results and not args.reanalyze_all:
                cached_summary = get_cached_market_summary(
                    history_conn, agg_hash, ai_provider.provider_name, ai_provider.synthesis_model, prompt_version
                )
            
            is_cache_valid = False
            if cached_summary:
                logging.info("Aggregate synthesis cache hit: yes")
                logging.info(f"Cached summary top-level keys: {list(cached_summary.keys()) if isinstance(cached_summary, dict) else []}")
                norm_cache = normalize_market_summary(cached_summary)
                if is_valid_market_summary(norm_cache, source="aggregate_cache"):
                    logging.info("Cached summary validation: valid")
                    ai_market_summary = norm_cache
                    is_cache_valid = True
                else:
                    logging.info("Cached summary validation: invalid")
                    logging.info("Invalid cache reason: Failed is_valid_market_summary checks (missing major sections)")
            else:
                logging.info("Aggregate synthesis cache hit: no")
                
            if not is_cache_valid:
                logging.info("Aggregate synthesis API call required: yes")
                
                if current_analyses_list:
                    logging.info(f"Passing {len(current_analyses_list)} structured jobs to synthesis")
                    fresh_summary = ai_provider.generate_market_summary(
                        run_metrics=run_metrics,
                        previous_metrics=previous_run,
                        current_analyses=current_analyses_list,
                        configured_roles=config.target_roles,
                    )
                    logging.info(f"Aggregate synthesis result keys: {list(fresh_summary.keys()) if isinstance(fresh_summary, dict) else []}")
                else:
                    if len(matched_jobs) > 0:
                        logging.error("High-severity data-flow error: matched jobs exist but current_analyses_list is empty. Bypassing Gemini API.")
                    fresh_summary = {}
                
                try:
                    import json
                    Path("reports/debug").mkdir(parents=True, exist_ok=True)
                    with open("reports/debug/latest-market-synthesis-fresh.json", "w", encoding="utf-8") as f:
                        json.dump(fresh_summary, f, indent=2)
                except Exception as e:
                    logging.warning(f"Could not save fresh synthesis artifact: {e}")
                    
                norm_fresh = normalize_market_summary(fresh_summary)
                if is_valid_market_summary(norm_fresh, source="gemini"):
                    logging.info("Aggregate synthesis validation: valid")
                    ai_market_summary = norm_fresh
                    if config.ai_analysis.cache_results:
                        store_cached_market_summary(
                            history_conn, agg_hash, ai_provider.provider_name, 
                            ai_provider.synthesis_model, prompt_version, ai_market_summary
                        )
                else:
                    logging.info("Aggregate synthesis validation: invalid")
                    logging.warning("Market synthesis generation returned empty or invalid results. Will not cache.")
                    ai_market_summary = norm_fresh
                    
                    # Deterministic fallback when API fails or quota exceeded
                    if current_analyses_list or len(ai_job_analyses) > 0:
                        # Ensure we always use any enriched analyses available for the fallback
                        fallback_analyses = current_analyses_list if current_analyses_list else list(ai_job_analyses.values())
                        logging.info("Generating deterministic fallback synthesis from per-job AI results.")
                        from collections import Counter
                        role_analyses = {}
                        
                        configured_roles = config.target_roles
                        for role in configured_roles:
                            role_jobs = [jd for jd in fallback_analyses if jd.get("matched_target_role") == role or jd.get("role_cluster") == role or jd.get("matched_role") == role]
                            if not role_jobs:
                                continue
                                
                            req_counter = Counter()
                            pref_counter = Counter()
                            resp_counter = Counter()
                            
                            for jd in role_jobs:
                                norm = normalize_analysis_evidence(jd)
                                reqs = norm["required_skills"]
                                prefs = norm["preferred_skills"]
                                resps = norm["responsibilities"]
                                
                                for req in reqs:
                                    req_counter[req] += 1
                                for pref in prefs:
                                    pref_counter[pref] += 1
                                for r in resps:
                                    resp_counter[r] += 1
                                
                            total_role_jobs = len(role_jobs)
                            
                            top_reqs = [s for s, c in req_counter.most_common(3)]
                            top_resps = [r for r, c in resp_counter.most_common(2)]
                            
                            insight_list = []
                            if req_counter:
                                top_req, count = req_counter.most_common(1)[0]
                                insight_list.append(f"{top_req} is explicitly required in {count} of {total_role_jobs} jobs ({int(count/total_role_jobs*100)}%).")
                                if len(req_counter) > 1:
                                    second_req, second_count = req_counter.most_common(2)[1]
                                    insight_list.append(f"{second_req} appears in {second_count} of {total_role_jobs} jobs ({int(second_count/total_role_jobs*100)}%).")
                            if resp_counter:
                                top_resp, count = resp_counter.most_common(1)[0]
                                insight_list.append(f"{top_resp} appears in {count} of {total_role_jobs} {role} jobs ({int(count/total_role_jobs*100)}%).")

                            evidence_skills_str = ", ".join(top_reqs) if top_reqs else "core technical skills"
                            evidence_resps_str = ", ".join(top_resps) if top_resps else "key operational workflows"
                            
                            if role == "Data Scientist" and top_reqs:
                                case_study = f"Create a case study that starts with a business question, prepares data using {evidence_skills_str}, compares predictive approaches, evaluates model performance, and presents an executive-facing recommendation."
                            elif role == "Forward Deployed Engineer" and top_reqs:
                                case_study = f"Create a customer workflow automation case that documents discovery, solution scoping, implementation with {evidence_skills_str}, external-system integration, and measurable operational impact."
                            elif role == "AI Engineer" and top_reqs:
                                case_study = f"Build an end-to-end AI application that includes document ingestion, {evidence_resps_str}, API deployment, monitoring, and utilizes {evidence_skills_str}."
                            else:
                                case_study = f"Build an end-to-end case study that demonstrates {evidence_resps_str} and utilizes {evidence_skills_str} to show measurable impact."
                                
                            portfolio_rec = f"Create a portfolio project highlighting {evidence_skills_str} applied to real-world {role} challenges."
                            
                            role_analyses[role] = {
                                "job_count": total_role_jobs,
                                "responsibility_frequencies": [{"responsibility": r, "count": c, "percentage": int(c/total_role_jobs*100), "examples": []} for r, c in resp_counter.most_common(5)],
                                "required_skill_frequencies": [{"skill": s, "count": c, "percentage": int(c/total_role_jobs*100)} for s, c in req_counter.most_common(8)],
                                "preferred_skill_frequencies": [{"skill": s, "count": c, "percentage": int(c/total_role_jobs*100)} for s, c in pref_counter.most_common(5)],
                                "role_specific_insights": insight_list if insight_list else [f"Analyzed {total_role_jobs} active opportunities in the market."],
                                "ideal_candidate_profile": [f"Candidate showcasing {evidence_skills_str} with experience in {evidence_resps_str}."],
                                "case_study_recommendations": [case_study],
                                "portfolio_recommendations": [portfolio_rec],
                                "resume_keywords": [s for s, c in req_counter.most_common(5)],
                                "resume_actions": [f"Demonstrate impact in {r}" for r in top_resps] if top_resps else ["Focus on quantifiable achievements"],
                                "linkedin_actions": [f"Highlight expertise in {s}" for s in top_reqs] if top_reqs else ["Detail your technical stack"]
                            }
                            
                        if not ai_market_summary:
                            ai_market_summary = {}
                            
                        ai_market_summary["configured_roles"] = configured_roles
                        ai_market_summary["role_analyses"] = role_analyses
                        ai_market_summary["market_snapshot"] = {"executive_summary": ["Fallback synthesis triggered because AI provider failed."]}
                        ai_market_summary["cross_role_patterns"] = ["Fallback generated cross-role patterns."]
                        ai_market_summary["optional_role_changes"] = []

                    try:
                        import json
                        with open("reports/debug/latest-role-market-intelligence-final.json", "w", encoding="utf-8") as f:
                            json.dump(ai_market_summary, f, indent=2)
                    except Exception as e:
                        logging.warning(f"Could not save final debug artifact: {e}")
                        
            else:
                logging.info("Aggregate synthesis API call required: no")

        # Update run AI status globally
        if ai_analyzed_count > 0 or ai_market_summary:
            update_run_ai_status(history_conn, run_id, "completed")
        else:
            update_run_ai_status(history_conn, run_id, "fallback" if ai_enabled else "disabled")

    run_stats["ai_analyzed_count"] = ai_analyzed_count
    run_stats["cache_hits"] = cache_hits if ai_enabled else 0
    run_stats["fallback_count"] = fallback_count if ai_enabled else 0
    run_stats["extraction_calls"] = extraction_calls if ai_enabled else 0

    # ── Stage 6: Generate Incremental Report ──
    logging.info("Generating incremental report...")
    markdown_report = generate_incremental_report(
        classified_jobs=classified,
        run_stats=run_stats,
        config=config,
        previous_run=previous_run,
        ai_job_analyses=ai_job_analyses,
        ai_update_analyses=ai_update_analyses,
        ai_market_summary=ai_market_summary,
        include_previously_seen=args.include_previously_seen,
    )
    
    # Mark reported jobs
    reported_identities = [j.get("_stable_identity") for j in classified.get("new", []) + classified.get("updated", [])]
    update_run_job_report_status(history_conn, run_id, reported_identities)

    # ── Stage 7: Save Report ──
    if args.output:
        report_path = Path(args.output).resolve()
    else:
        output_dir = resolve_repo_relative_path(config.report.output_dir)
        report_path = output_dir / f"{date.today().strftime('%Y-%m-%d')}-job-report.md"

    try:
        write_daily_report(markdown_report, report_path.parent, date.today())
        if args.output:
            generated = report_path.parent / f"{date.today().strftime('%Y-%m-%d')}-job-report.md"
            if generated != report_path:
                generated.rename(report_path)
        logging.info(f"Report saved to: {report_path}")
    except Exception as e:
        logging.error(f"Failed to save report: {e}")

    run_stats["report_path"] = str(report_path)

    # ── Stage 8: Send Email ──
    email_status = "Not requested"
    email_recipients = []
    email_subject = "N/A"
    email_html_used = False
    email_attachments: list[str] = []

    if args.send_email:
        logging.info("Email requested, validating settings...")
        try:
            email_settings = validate_email_settings(config.email)

            # Use incremental subject line
            subject = build_incremental_email_subject(
                date.today(),
                new_count,
                updated_count,
                email_settings.get("subject_prefix", "Job Intelligence Report"),
            )

            # Render HTML body
            html_report = None
            if email_settings.get("send_html", True):
                try:
                    # If no new/updated jobs and not including all current jobs, use the short body
                    if new_count == 0 and updated_count == 0 and not getattr(config.analysis_scope, "include_all_current_jobs", False):
                        email_body = build_zero_new_email_body()
                        html_report = markdown_to_email_html(email_body, title=subject)
                    else:
                        html_report = markdown_to_email_html(markdown_report, title=subject)
                    email_html_used = True
                    logging.info("HTML email body rendered successfully.")
                except Exception as e:
                    logging.warning(f"HTML rendering failed, falling back to plain text: {e}")
                    html_report = None

            # Build attachment list
            attachment_paths: list[Path] = []
            if email_settings.get("attach_markdown", True) and report_path.exists():
                # Only attach full report if there are new/updated jobs
                if new_count > 0 or updated_count > 0:
                    attachment_paths.append(report_path)

            # Use short plain text for zero-new runs if not including all current jobs
            plain_text = markdown_report
            if new_count == 0 and updated_count == 0 and not getattr(config.analysis_scope, "include_all_current_jobs", False):
                plain_text = build_zero_new_email_body()

            recipients = email_settings["recipients"]
            logging.info(f"Sending email to {len(recipients)} recipient(s): {', '.join(recipients)}...")
            result = send_email_report(
                smtp_host=email_settings["smtp_host"],
                smtp_port=email_settings["smtp_port"],
                smtp_user=email_settings["smtp_user"],
                smtp_password=email_settings["smtp_password"],
                sender_email=email_settings["sender_email"],
                recipients=recipients,
                subject=subject,
                plain_text_body=plain_text,
                html_body=html_report,
                attachment_paths=attachment_paths,
                dry_run=args.dry_run
            )

            email_recipients = result["recipients"]
            email_subject = result["subject"]
            email_attachments = result.get("attachments", [])

            if result["dry_run"]:
                logging.info(f"DRY RUN: Would have sent email to {', '.join(email_recipients)}")
                email_status = "Dry Run"
            else:
                logging.info("Email sent successfully.")
                email_status = "Sent"

        except ValueError as e:
            logging.error(f"Email configuration is incomplete: {e}")
            # Don't exit — still update run history
            email_status = f"Config Error: {e}"
        except Exception as e:
            logging.error(f"Error during email dispatch: {e}")
            email_status = f"Error: {e}"

    # ── Stage 9: Update run_history & job_history ──
    try:
        # Mark reported jobs
        all_reported = [j.get("_stable_identity", "") for j in classified["new"] + classified["updated"]]
        all_reported = [i for i in all_reported if i]
        update_last_reported(history_conn, all_reported)

        # Complete run
        complete_run(history_conn, run_id, run_stats)
        logging.info(f"Run {run_id} completed successfully.")
    except Exception as e:
        logging.error(f"Failed to update run history: {e}")
        try:
            fail_run(history_conn, run_id)
        except Exception:
            pass
    finally:
        history_conn.close()

    # Terminal Summary
    print("\n" + "="*50)
    print("JOB INTELLIGENCE SUMMARY")
    print("="*50)
    if not args.report_only:
        print(f"Scraped from provider: {run_stats['total_scraped']}")
        if not args.dry_run:
            print(f"New inserts to DB:     {run_stats.get('total_inserted', 0)}")
            print(f"Deduplicated:          {run_stats.get('total_duplicates', 0)}")
    print(f"Jobs evaluated:        {run_stats['total_recent_checked']}")
    print(f"Jobs matching criteria:{len(matched_jobs)}")
    print("-"*50)
    print(f"NEW jobs:              {new_count}")
    print(f"UPDATED jobs:          {updated_count}")
    print(f"UNCHANGED jobs:        {unchanged_count}")
    print(f"Jobs sent to AI:       {ai_analyzed_count}")
    print("="*50)
    print(f"Report path: {report_path}")
    if args.send_email:
        print(f"Email Status: {email_status}")
        print(f"HTML body:    {'Yes' if email_html_used else 'No (plain text)'}")
        print(f"Attachments:  {', '.join(email_attachments) if email_attachments else 'None'}")
        print(f"Recipients:   {', '.join(email_recipients) if email_recipients else 'N/A'}")
        print(f"Subject:      {email_subject}")


if __name__ == "__main__":
    run_pipeline()
