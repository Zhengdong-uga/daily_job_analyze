"""
Configuration loader and validator for the Daily Job Watch MVP.

Loads preferences from a YAML configuration file, validates required fields,
and provides a typed dataclass for the pipeline to use.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from utils.path_resolution import get_repo_root


class ConfigValidationError(Exception):
    """Raised when the job watch configuration is invalid."""

    pass


@dataclass
class PreferencesConfig:
    include_remote: bool = True
    include_hybrid: bool = True
    include_onsite: bool = True
    include_internship: bool = False
    include_entry_level: bool = True
    include_mid_level: bool = True
    include_senior: bool = False
    minimum_match_score: int = 40
    max_jobs_in_report: int = 50


@dataclass
class ScrapeConfig:
    sites: List[str] = field(default_factory=lambda: ["linkedin"])
    results_wanted: int = 30
    hours_old: int = 24
    require_description: bool = True


@dataclass
class ReportConfig:
    output_dir: str = "reports/daily"
    format: str = "markdown"


@dataclass
class EmailConfig:
    enabled: bool = False
    send_html: bool = True
    attach_markdown: bool = True
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    sender_email: str = ""
    recipient_email: str = ""
    recipient_emails: List[str] = field(default_factory=list)
    subject_prefix: str = "Daily Job Watch Report"


@dataclass
class AiSummaryConfig:
    enabled: bool = False
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    max_jobs: int = 20


@dataclass
class AnalysisConfig:
    enabled: bool = True
    dedupe_by_url: bool = True
    show_match_scores: bool = False
    include_raw_description_excerpt: bool = False
    raw_description_excerpt_chars: int = 500
    top_keywords_limit: int = 30
    max_examples_per_keyword: int = 3
    max_examples_per_trend: int = 5


@dataclass
class JobWatchConfig:
    target_roles: List[str]
    locations: List[str]
    role_aliases: Dict[str, List[str]] = field(default_factory=dict)
    location_aliases: Dict[str, List[str]] = field(default_factory=dict)
    preferred_companies: List[str] = field(default_factory=list)
    exclude_companies: List[str] = field(default_factory=list)
    include_keywords: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    preferences: PreferencesConfig = field(default_factory=PreferencesConfig)
    scrape: ScrapeConfig = field(default_factory=ScrapeConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    ai_summary: AiSummaryConfig = field(default_factory=AiSummaryConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    keyword_groups: Dict[str, List[str]] = field(default_factory=dict)


def _parse_list(data: Dict[str, Any], key: str, default: Optional[List[str]] = None) -> List[str]:
    """Extract a list of strings from a dictionary safely."""
    val = data.get(key)
    if val is None:
        return default if default is not None else []
    if not isinstance(val, list):
        raise ConfigValidationError(f"Expected list for '{key}', got {type(val).__name__}")
    return [str(item) for item in val]


def _parse_dict_of_lists(data: Dict[str, Any], key: str) -> Dict[str, List[str]]:
    """Extract a dictionary of string lists safely."""
    val = data.get(key, {})
    if not isinstance(val, dict):
        raise ConfigValidationError(f"Expected dict for '{key}', got {type(val).__name__}")
    
    result = {}
    for k, v in val.items():
        if not isinstance(v, list):
            raise ConfigValidationError(f"Expected list for '{key}.{k}', got {type(v).__name__}")
        result[str(k)] = [str(item) for item in v]
    return result


def load_config(config_path: Path) -> JobWatchConfig:
    """
    Load, validate, and parse a YAML configuration file.
    
    Args:
        config_path: Path to the YAML configuration file
        
    Returns:
        JobWatchConfig dataclass instance
        
    Raises:
        ConfigValidationError: If the configuration is missing or invalid
    """
    if not config_path.exists() or not config_path.is_file():
        raise ConfigValidationError(f"Configuration file not found: {config_path}")
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigValidationError(f"Invalid YAML format in {config_path}: {e}") from e
        
    if not data or not isinstance(data, dict):
        raise ConfigValidationError(f"Configuration file {config_path} is empty or not a mapping")
        
    # Required fields
    target_roles = _parse_list(data, "target_roles")
    if not target_roles:
        raise ConfigValidationError("'target_roles' is required and must not be empty")
        
    locations = _parse_list(data, "locations")
    if not locations:
        raise ConfigValidationError("'locations' is required and must not be empty")
        
    # Optional sections
    prefs_data = data.get("preferences", {})
    remote_data = prefs_data.get("remote", {})
    seniority_data = prefs_data.get("seniority", {})
    
    preferences = PreferencesConfig(
        include_remote=remote_data.get("include_remote", True),
        include_hybrid=remote_data.get("include_hybrid", True),
        include_onsite=remote_data.get("include_onsite", True),
        include_internship=seniority_data.get("include_internship", False),
        include_entry_level=seniority_data.get("include_entry_level", True),
        include_mid_level=seniority_data.get("include_mid_level", True),
        include_senior=seniority_data.get("include_senior", False),
        minimum_match_score=prefs_data.get("minimum_match_score", 40),
        max_jobs_in_report=prefs_data.get("max_jobs_in_report", 50),
    )
    
    scrape_data = data.get("scrape", {})
    scrape = ScrapeConfig(
        sites=_parse_list(scrape_data, "sites", ["linkedin"]),
        results_wanted=scrape_data.get("results_wanted", 30),
        hours_old=scrape_data.get("hours_old", 24),
        require_description=scrape_data.get("require_description", True),
    )
    
    report_data = data.get("report", {})
    report = ReportConfig(
        output_dir=report_data.get("output_dir", "reports/daily"),
        format=report_data.get("format", "markdown"),
    )
    
    email_data = data.get("email", {})
    email = EmailConfig(
        enabled=email_data.get("enabled", False),
        send_html=email_data.get("send_html", True),
        attach_markdown=email_data.get("attach_markdown", True),
        smtp_host=email_data.get("smtp_host", "smtp.gmail.com"),
        smtp_port=email_data.get("smtp_port", 587),
        smtp_user=email_data.get("smtp_user", ""),
        sender_email=email_data.get("sender_email", ""),
        recipient_email=email_data.get("recipient_email", ""),
        recipient_emails=_parse_list(email_data, "recipient_emails"),
        subject_prefix=email_data.get("subject_prefix", "Daily Job Watch Report"),
    )
    
    ai_data = data.get("ai_summary", {})
    ai_summary = AiSummaryConfig(
        enabled=ai_data.get("enabled", False),
        provider=ai_data.get("provider", "openai"),
        model=ai_data.get("model", "gpt-4o-mini"),
        max_jobs=ai_data.get("max_jobs", 20),
    )
    
    analysis_data = data.get("analysis", {})
    analysis = AnalysisConfig(
        enabled=analysis_data.get("enabled", True),
        dedupe_by_url=analysis_data.get("dedupe_by_url", True),
        show_match_scores=analysis_data.get("show_match_scores", False),
        include_raw_description_excerpt=analysis_data.get("include_raw_description_excerpt", False),
        raw_description_excerpt_chars=analysis_data.get("raw_description_excerpt_chars", 500),
        top_keywords_limit=analysis_data.get("top_keywords_limit", 30),
        max_examples_per_keyword=analysis_data.get("max_examples_per_keyword", 3),
        max_examples_per_trend=analysis_data.get("max_examples_per_trend", 5),
    )

    return JobWatchConfig(
        target_roles=target_roles,
        locations=locations,
        role_aliases=_parse_dict_of_lists(data, "role_aliases"),
        location_aliases=_parse_dict_of_lists(data, "location_aliases"),
        preferred_companies=_parse_list(data, "preferred_companies"),
        exclude_companies=_parse_list(data, "exclude_companies"),
        include_keywords=_parse_list(data, "include_keywords"),
        exclude_keywords=_parse_list(data, "exclude_keywords"),
        preferences=preferences,
        scrape=scrape,
        report=report,
        email=email,
        ai_summary=ai_summary,
        analysis=analysis,
        keyword_groups=_parse_dict_of_lists(data, "keyword_groups"),
    )
