#!/usr/bin/env python3
"""
CLI entrypoint for the config-driven Daily Job Watch MVP.

Orchestrates scraping, normalization, database insertion, filtering, ranking,
and report generation based on a YAML configuration file.
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

# Cleanly add mcp-server-python to sys.path so we can import internal modules
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "mcp-server-python"))

from db.jobs_ingest_writer import JobsIngestWriter
from db.jobs_reader import get_connection, query_recent_jobs
from utils.job_filter import filter_and_rank_jobs
from utils.path_resolution import get_repo_root, resolve_repo_relative_path
from utils.report_generator import generate_markdown_report, write_daily_report
from utils.scrape_normalizer import normalize_and_filter, serialize_payload
from utils.watch_config import ConfigValidationError, load_config
from utils.email_sender import build_email_subject, validate_email_settings, send_email_report
from utils.html_email_renderer import markdown_to_email_html


def parse_args():
    parser = argparse.ArgumentParser(description="Daily Job Watch MVP Pipeline")
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
    return parser.parse_args()


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )


def run_pipeline():
    args = parse_args()
    setup_logging(args.verbose)
    
    config_path = resolve_repo_relative_path(args.config)
    try:
        config = load_config(config_path)
    except ConfigValidationError as e:
        logging.error(f"Configuration error: {e}")
        sys.exit(1)
        
    hours_old = args.hours if args.hours is not None else config.scrape.hours_old
    
    # Initialize run stats
    run_stats = {
        "total_scraped": 0,
        "total_inserted": 0,
        "total_duplicates": 0,
        "total_recent_checked": 0,
    }
    
    # Stage 1: Scrape & Ingest
    if not args.report_only:
        logging.info(f"Starting scrape for {len(config.target_roles)} roles across {len(config.locations)} locations...")
        
        try:
            from utils.jobspy_adapter import scrape_jobs_for_term
        except ImportError:
            logging.error("python-jobspy is required for scraping. Install it with: pip install python-jobspy")
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
                sys.exit(1)
        elif args.dry_run:
            logging.info(f"DRY RUN: Would have inserted {len(all_cleaned_records)} records.")
            
    # Stage 2: Query Recent Jobs
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
            sys.exit(1)
        else:
            logging.warning("Continuing dry run using only memory-scraped records.")
            recent_jobs = all_cleaned_records if not args.report_only else []
            
    if not recent_jobs:
        logging.warning("No jobs found to evaluate. Exiting.")
        sys.exit(0)
        
    # Stage 3: Filter and Rank
    logging.info("Filtering and ranking jobs based on configuration...")
    matched_jobs = filter_and_rank_jobs(recent_jobs, config)
    logging.info(f"Found {len(matched_jobs)} matched jobs meeting criteria.")
    
    # Stage 4: Generate Report
    logging.info("Generating markdown report...")
    markdown_report = generate_markdown_report(matched_jobs, run_stats, config)
    
    # Stage 5: Save Report
    if args.output:
        report_path = Path(args.output).resolve()
    else:
        output_dir = resolve_repo_relative_path(config.report.output_dir)
        report_path = output_dir / f"{date.today().strftime('%Y-%m-%d')}-job-report.md"
        
    try:
        write_daily_report(markdown_report, report_path.parent, date.today())
        # If output was specified exactly, rename it
        if args.output:
            generated = report_path.parent / f"{date.today().strftime('%Y-%m-%d')}-job-report.md"
            if generated != report_path:
                generated.rename(report_path)
        logging.info(f"Report saved to: {report_path}")
    except Exception as e:
        logging.error(f"Failed to save report: {e}")
        
    # Stage 6: Send Email
    email_status = "Not requested"
    email_recipients = []
    email_subject = "N/A"
    email_html_used = False
    email_attachments: list[str] = []
    
    if args.send_email:
        logging.info("Email requested, validating settings...")
        try:
            email_settings = validate_email_settings(config.email)
            pref_count = sum(1 for j in matched_jobs if j.get('is_preferred_company'))
            
            subject = build_email_subject(
                date.today(),
                len(matched_jobs),
                pref_count,
                email_settings["subject_prefix"]
            )
            
            # Render HTML body if configured
            html_report = None
            if email_settings.get("send_html", True):
                try:
                    html_report = markdown_to_email_html(
                        markdown_report,
                        title=subject,
                    )
                    email_html_used = True
                    logging.info("HTML email body rendered successfully.")
                except Exception as e:
                    logging.warning(f"HTML rendering failed, falling back to plain text: {e}")
                    html_report = None
            
            # Build attachment list
            attachment_paths: list[Path] = []
            if email_settings.get("attach_markdown", True) and report_path.exists():
                attachment_paths.append(report_path)
            
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
                plain_text_body=markdown_report,
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
            sys.exit(1)
        except Exception as e:
            logging.error(f"Error during email dispatch: {e}")
            sys.exit(1)
            
    # Terminal Summary
    print("\n" + "="*50)
    print("DAILY JOB WATCH SUMMARY")
    print("="*50)
    if not args.report_only:
        print(f"Scraped from provider: {run_stats['total_scraped']}")
        if not args.dry_run:
            print(f"New inserts to DB:     {run_stats['total_inserted']}")
            print(f"Deduplicated:          {run_stats['total_duplicates']}")
    print(f"Recent jobs evaluated: {run_stats['total_recent_checked']}")
    print(f"Jobs matching criteria:{len(matched_jobs)}")
    print(f"Preferred company hits:{sum(1 for j in matched_jobs if j.get('is_preferred_company'))}")
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
