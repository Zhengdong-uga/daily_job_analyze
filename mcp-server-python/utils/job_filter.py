"""
Job filtering and ranking logic for the Daily Job Watch MVP.

Implements config-driven evaluation to score and filter raw job records based
on the user's YAML configuration.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from utils.watch_config import JobWatchConfig


def extract_max_yoe(text: str) -> int:
    """Extract the maximum years-of-experience number mentioned in text.

    Scans for common YoE patterns like '5+ years of experience',
    'minimum of 3 yrs exp', or '2-4 years experience'.  Returns the
    highest number found (capped at 20 to ignore outliers), or 0 if
    no pattern matches.
    """
    patterns = [
        r"(\d+)(?:\s*-\s*\d+)?\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)",
        r"(?:minimum|at least|requires|requiring)\s+(?:of\s+)?(\d+)\+?\s*(?:years?|yrs?)",
    ]
    max_yoe = 0
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            try:
                yoe = int(m.group(1))
                if yoe < 20:
                    max_yoe = max(max_yoe, yoe)
            except ValueError:
                pass
    return max_yoe


def normalize_text(text: Optional[str]) -> str:
    """Normalize text for case-insensitive matching."""
    if not text:
        return ""
    return text.lower().strip()


def contains_any(text: str, keywords: List[str]) -> bool:
    """Check if normalized text contains any of the normalized keywords."""
    norm_text = normalize_text(text)
    for kw in keywords:
        norm_kw = normalize_text(kw)
        if norm_kw and norm_kw in norm_text:
            return True
    return False


def _find_exact_or_alias_match(text: str, targets: List[str], aliases: Dict[str, List[str]]) -> Optional[str]:
    """
    Check if text matches a target or its aliases.
    Returns the canonical target name if a match is found.
    """
    norm_text = normalize_text(text)
    
    # 1. Check exact targets
    for target in targets:
        if normalize_text(target) in norm_text:
            return target
            
    # 2. Check aliases
    for target, alias_list in aliases.items():
        if target not in targets:
            continue # Only match aliases for active targets
            
        for alias in alias_list:
            if normalize_text(alias) in norm_text:
                return target
                
    return None


def calculate_match_score(job: Dict[str, Any], config: JobWatchConfig) -> Tuple[int, Dict[str, Any]]:
    """
    Calculate the match score for a job based on the configuration.
    
    Returns a tuple of (score, metadata_dict). If score is -1, the job is excluded.
    """
    score = 0
    title = job.get("title", "")
    company = job.get("company", "")
    location = job.get("location", "")
    description = job.get("description", "")
    
    title_and_desc = f"{title} {description}"
    
    # Exclude checks (return -1 immediately)
    if contains_any(company, config.exclude_companies):
        return -1, {}

    # Exclude keywords checked against TITLE ONLY (not description) to avoid
    # false positives when a junior JD mentions "report to senior lead" etc.
    if contains_any(title, config.exclude_keywords):
        return -1, {}

    # YoE filter: exclude jobs whose description requires more experience
    # than the configured maximum.
    if config.preferences.max_years_of_experience is not None:
        yoe = extract_max_yoe(description)
        if yoe > config.preferences.max_years_of_experience:
            return -1, {}

    # Scoring & Metadata tracking
    matched_keywords = []
    is_preferred_company = False
    matched_role = None
    matched_location = None
    
    # 1. Target Role (+30)
    matched_role = _find_exact_or_alias_match(title, config.target_roles, config.role_aliases)
    if matched_role:
        score += 30

    # 2. Target Location (+20)
    matched_location = _find_exact_or_alias_match(location, config.locations, config.location_aliases)
    if matched_location:
        score += 20
        
    # 3. Preferred Company (+20)
    if contains_any(company, config.preferred_companies):
        score += 20
        is_preferred_company = True
        
    # 4. Include Keywords (+5 each, max +25)
    kw_score = 0
    norm_title_and_desc = normalize_text(title_and_desc)
    for kw in config.include_keywords:
        norm_kw = normalize_text(kw)
        if norm_kw and norm_kw in norm_title_and_desc:
            matched_keywords.append(kw)
            if kw_score < 25:
                kw_score += 5
                
    score += kw_score
    
    metadata = {
        "match_score": score,
        "matched_keywords": matched_keywords,
        "is_preferred_company": is_preferred_company,
        "matched_role": matched_role,
        "matched_location": matched_location,
    }
    
    return score, metadata


def filter_and_rank_jobs(jobs: List[Dict[str, Any]], config: JobWatchConfig) -> List[Dict[str, Any]]:
    """
    Filter out weak/excluded jobs and rank the remainder.
    """
    scored_jobs = []
    
    for job in jobs:
        score, metadata = calculate_match_score(job, config)
        
        # Filter out excluded or low-scoring jobs
        if score < 0 or score < config.preferences.minimum_match_score:
            continue
            
        # Create a new job dict to avoid mutating the original
        enriched_job = dict(job)
        enriched_job.update(metadata)
        scored_jobs.append(enriched_job)
        
    # Sort: 1) preferred company (True first), 2) match score (descending), 3) captured_at (descending)
    scored_jobs.sort(
        key=lambda j: (
            j.get("is_preferred_company", False),
            j.get("match_score", 0),
            j.get("created_at") or j.get("captured_at") or ""
        ),
        reverse=True
    )
    
    # Deduplicate by URL
    if getattr(config, "analysis", None) and config.analysis.dedupe_by_url:
        seen_urls = set()
        deduped_jobs = []
        for job in scored_jobs:
            url = job.get("url")
            if url and url in seen_urls:
                continue
            seen_urls.add(url)
            deduped_jobs.append(job)
        scored_jobs = deduped_jobs
    
    # Limit final report size
    return scored_jobs[:config.preferences.max_jobs_in_report]
