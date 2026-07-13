"""
Job filtering and ranking logic for the Daily Job Watch MVP.

Implements config-driven evaluation to score and filter raw job records based
on the user's YAML configuration.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from utils.watch_config import JobWatchConfig


word_to_num = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10
}

def text_to_int(text: str) -> int:
    text = text.lower().strip()
    if text in word_to_num:
        return word_to_num[text]
    try:
        return int(text)
    except ValueError:
        return 0

def extract_max_yoe(text: str) -> int:
    """Extract maximum years of experience from job description text."""
    patterns = [
        r"(\d+)(?:\s*(?:-|to)\s*\d+)?\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)",
        r"(?:minimum|at least|requires|requiring)\s+(?:of\s+)?(\d+)\+?\s*(?:years?|yrs?)",
        r"(one|two|three|four|five|six|seven|eight|nine|ten)(?:\s*(?:-|to)\s*(?:\w+))?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)",
        r"(\d+)(?:\s*(?:-|to)\s*\d+)?\+?\s*(?:years?|yrs?)\s+(?:of\s+|in\s+|working\s+|with\s+|as\s+|building\s+|developing\s+)",
        r"(\d+)(?:\s*(?:-|to)\s*\d+)?\+?\s*(?:years?|yrs?)['’]\s*(?:experience|exp)"
    ]
    max_yoe = 0
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            val = text_to_int(m.group(1))
            if 0 < val < 20: # ignore weirdly large numbers
                max_yoe = max(max_yoe, val)
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


def _find_role_matches(title: str, desc: str, targets: List[str], aliases: Dict[str, List[str]]) -> List[Dict[str, str]]:
    """
    Find all matching roles for a job title and description.
    Returns a list of dicts: {"role": str, "reason": str, "confidence": str}
    """
    matches = []
    norm_title = normalize_text(title)
    norm_desc = normalize_text(desc)
    
    # 1. Check exact targets
    for target in targets:
        if normalize_text(target) in norm_title:
            matches.append({
                "role": target,
                "reason": f"Exact title match: {target}",
                "confidence": "high"
            })
            
    # 2. Check aliases
    duty_evidence = ["customer", "implementation", "solution", "architecture", "deployment", "integration", "workflow", "client", "deploy", "design", "data", "develop", "engineer", "product", "machine learning"]
    
    for target, alias_list in aliases.items():
        if target not in targets:
            continue
            
        for alias in alias_list:
            if normalize_text(alias) in norm_title:
                # Avoid duplicate matches
                if any(m["role"] == target for m in matches):
                    continue
                    
                # Require some evidence in description to prevent over-broadening adjacent titles
                evidence_found = any(normalize_text(kw) in norm_desc for kw in duty_evidence)
                # Also check if part of the target name itself is in the description
                if not evidence_found:
                    target_parts = [p for p in normalize_text(target).split() if len(p) > 3]
                    evidence_found = any(p in norm_desc for p in target_parts)
                
                if evidence_found:
                    matches.append({
                        "role": target,
                        "reason": f"Alias match with duty evidence: {alias} -> {target}",
                        "confidence": "high"
                    })
                else:
                    matches.append({
                        "role": target,
                        "reason": f"Alias match without duty evidence: {alias} -> {target}",
                        "confidence": "low"
                    })
                
    return matches


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
        
    if contains_any(title_and_desc, config.exclude_keywords):
        return -1, {}
        
    if getattr(config.preferences, "max_years_of_experience", None) is not None:
        yoe = extract_max_yoe(description)
        if yoe > config.preferences.max_years_of_experience:
            return -1, {}

    # Scoring & Metadata tracking
    matched_keywords = []
    is_preferred_company = False
    matched_target_role = None
    role_match_reason = None
    matched_location = None
    
    # 1. Target Role (+30)
    role_matches = _find_role_matches(title, description, config.target_roles, config.role_aliases)
    
    if role_matches:
        score += 30
        
        # Determine primary role and state
        high_conf_matches = [m for m in role_matches if m["confidence"] == "high"]
        low_conf_matches = [m for m in role_matches if m["confidence"] == "low"]
        
        if len(high_conf_matches) == 1:
            matched_target_role = high_conf_matches[0]["role"]
            role_match_reason = high_conf_matches[0]["reason"]
            role_match_confidence = "high"
            match_state = "matched"
            secondary_matched_roles = [m["role"] for m in low_conf_matches]
        elif len(high_conf_matches) > 1:
            matched_target_role = high_conf_matches[0]["role"]
            role_match_reason = "Multiple high confidence matches"
            role_match_confidence = "high"
            match_state = "ambiguous"
            secondary_matched_roles = [m["role"] for m in high_conf_matches[1:]] + [m["role"] for m in low_conf_matches]
        elif len(low_conf_matches) > 0:
            matched_target_role = low_conf_matches[0]["role"]
            role_match_reason = low_conf_matches[0]["reason"]
            role_match_confidence = "low"
            match_state = "ambiguous"
            secondary_matched_roles = [m["role"] for m in low_conf_matches[1:]]
    else:
        match_state = "unmatched"
        role_match_confidence = "none"
        secondary_matched_roles = []

    # 2. Target Location (+20)
    # Reusing find matches logic loosely for locations (just checking exact text overlap)
    norm_loc = normalize_text(location)
    for loc in config.locations:
        if normalize_text(loc) in norm_loc:
            matched_location = loc
            break
    if not matched_location:
        for loc, aliases in config.location_aliases.items():
            for alias in aliases:
                if normalize_text(alias) in norm_loc:
                    matched_location = loc
                    break
            if matched_location: break
                    
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
        "matched_target_role": matched_target_role,
        "role_match_reason": role_match_reason,
        "role_match_confidence": role_match_confidence,
        "secondary_matched_roles": secondary_matched_roles,
        "match_state": match_state,
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
