from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

def _truncate_words(text: str, num_words: int) -> str:
    """Truncate text to a maximum number of words."""
    if not isinstance(text, str):
        return ""
    words = text.split()
    if len(words) <= num_words:
        return text
    return " ".join(words[:num_words]) + "..."

from utils.watch_config import JobWatchConfig
from utils.jd_analyzer import (
    extract_keyword_counts,
    summarize_job_description,
    group_jobs_by_skill_cluster,
    build_market_trend_summary,
    build_skill_gap_summary,
    extract_job_requirements,
    get_top_skills_overall,
    build_role_to_skill_matrix
)


def _format_job_compact(job: Dict[str, Any], keyword_groups: Optional[Dict[str, List[str]]] = None, include_excerpt: bool = False, excerpt_limit: int = 500) -> str:
    """Format a single job record into a compact card."""
    title = job.get("title", "Unknown Title")
    company = job.get("company", "Unknown Company")
    location = job.get("location", "Unknown Location")
    url = job.get("url", "#")
    source = job.get("source", "unknown")
    matched_role = job.get("matched_role") or "None"
    matched_keywords = ", ".join(job.get("matched_keywords", [])) or "None"
    
    summary = summarize_job_description(job, keyword_groups)
    reqs = extract_job_requirements(job, keyword_groups)
    
    lines = [
        f"#### [{title} @ {company}]({url})",
        f"- **Location:** {location} | **Source:** {source}",
        f"- **Matched Role:** {matched_role} | **Keywords:** {matched_keywords}",
        "",
        "**Summary:**",
        summary,
        ""
    ]
    
    if reqs["hard_skills"]:
        lines.append(f"- **Hard Skills:** {', '.join(f'`{s}`' for s in reqs['hard_skills'][:5])}")
    if reqs["soft_skills"]:
        lines.append(f"- **Soft Skills:** {', '.join(f'`{s}`' for s in reqs['soft_skills'][:5])}")
        
    if include_excerpt and job.get("description"):
        desc = job.get("description", "").replace("\n", " ")[:excerpt_limit]
        lines.append(f"<details><summary>Raw Excerpt</summary>{desc}...</details>")
        lines.append("")
        
    return "\n".join(lines)


def generate_markdown_report(
    jobs: List[Dict[str, Any]], 
    run_stats: Dict[str, int], 
    config: JobWatchConfig, 
    ai_analysis: Optional[str] = None
) -> str:
    """
    Generate a formatted Markdown JD Intelligence report.
    """
    today_str = date.today().strftime("%Y-%m-%d")
    kw_groups = getattr(config, "keyword_groups", None)
    
    # Analyze jobs
    clusters = group_jobs_by_skill_cluster(jobs)
    trends = build_market_trend_summary(jobs, kw_groups)
    skill_gaps = build_skill_gap_summary(jobs, kw_groups)
    keyword_counts = extract_keyword_counts(jobs, kw_groups)
    top_skills = get_top_skills_overall(jobs, kw_groups)
    matrix = build_role_to_skill_matrix(jobs, kw_groups)
    
    total_matched = len(jobs)
    
    companies = [j.get("company") for j in jobs if j.get("company")]
    locations = [j.get("location") for j in jobs if j.get("location")]
    
    top_companies_str = ", ".join([f"{c} ({n})" for c, n in Counter(companies).most_common(5)]) or "None"
    top_locations_str = ", ".join([f"{l} ({n})" for l, n in Counter(locations).most_common(5)]) or "None"
    top_clusters = sorted([(k, len(v)) for k, v in clusters.items()], key=lambda x: x[1], reverse=True)[:3]
    top_clusters_str = ", ".join([f"{c} ({n})" for c, n in top_clusters]) or "None"
    
    lines = []
    lines.append(f"# Daily Job Intelligence Report - {today_str}")
    lines.append("")
    
    # 1. Executive Summary
    lines.append("## 📊 1. Executive Summary")
    lines.append(f"- **Total Scraped:** {run_stats.get('total_scraped', 0)}")
    lines.append(f"- **Total Unique Jobs Analyzed:** {run_stats.get('total_recent_checked', 0)}")
    lines.append(f"- **Total Jobs Included in Report:** {total_matched}")
    lines.append(f"- **Top Companies:** {top_companies_str}")
    lines.append(f"- **Top Locations:** {top_locations_str}")
    lines.append(f"- **Top Role Clusters:** {top_clusters_str}")
    lines.append("")
    lines.append("**Today's Job Market Trend Summary:**")
    for t in trends.get("top_trends", []):
        lines.append(f"- {t}")
    lines.append("")
    lines.append("### What This Means for Me")
    for advice in trends.get("what_this_means", []):
        lines.append(f"- {advice}")
    lines.append("")
    
    # New: Top 10 Skills
    lines.append("### 🏆 Top 10 Skills to Prioritize")
    for skill, count in top_skills:
        lines.append(f"- `{skill}` (**{count}** mentions)")
    lines.append("")
    
    # 2. Today's Job Market Trends
    lines.append("## 📈 2. Today's Job Market Trends")
    for trend in trends.get("detailed_trends", []):
        lines.append(f"### Trend: {trend['title']}")
        lines.append(f"**Explanation:**\n{trend['explanation']}\n")
        lines.append("**Evidence:**")
        for ev in trend["evidence"]:
            lines.append(f"- {ev}")
        lines.append("\n**Example Jobs:**")
        for ex in trend["examples"]:
            lines.append(f"- {ex.get('title')} — {ex.get('company')}")
        lines.append("")
        
    # New: Role-to-Skill Matrix
    lines.append("## 🧮 Role-to-Skill Matrix")
    if kw_groups and matrix:
        headers = ["Role Cluster"] + [g.replace("_", " ").title() for g in kw_groups.keys()]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for cluster, groups in matrix.items():
            row = [cluster]
            for g in kw_groups.keys():
                top_3 = ", ".join(groups.get(g, [])[:3])
                row.append(top_3 if top_3 else "-")
            lines.append("| " + " | ".join(row) + " |")
    else:
        lines.append("*Keyword groups not configured for matrix generation.*")
    lines.append("")

    # 3. Specific Job Requirements by Role Type
    lines.append("## 🛠️ 3. Specific Job Requirements by Role Type")
    for role, data in skill_gaps.get("role_specific_data", {}).items():
        lines.append(f"### {role}")
        if data.get("companies_hiring"):
            lines.append(f"**Top Companies Hiring:** {', '.join(data['companies_hiring'])}")
        lines.append("\n**Required Hard Skills:**")
        for skill in data.get("hard_skills", []):
            lines.append(f"- `{skill}`")
        lines.append("\n**Required Soft/Collaboration Skills:**")
        for skill in data.get("soft_skills", []):
            lines.append(f"- `{skill}`")
        lines.append("\n**Repeated JD Phrases:**")
        for resp in data.get("phrases", []):
            lines.append(f"- \"{resp}\"")
        lines.append("\n**Example Jobs:**")
        for ex in data.get("example_jobs", []):
            lines.append(f"- {ex.get('title')} — {ex.get('company')}")
        lines.append("")
        
    # 4. Skill Demand Overview
    lines.append("## ⚡ 4. Skill Demand Overview")
    for group, counts in keyword_counts.items():
        lines.append(f"### {group.replace('_', ' ').title()}")
        for kw, kw_data in counts.items():
            examples = ", ".join([j.get("title", "") for j in kw_data.get("jobs", [])])
            lines.append(f"- `{kw}` (**{kw_data['count']}** mentions): e.g., {examples}")
        lines.append("")
        
    # 5. Repeated Responsibilities Across Jobs
    lines.append("## 🔄 5. Repeated Responsibilities Across Jobs")
    for resp in skill_gaps.get("repeated_responsibilities", []):
        lines.append(f"- {resp}")
    lines.append("")
        
    # 6. Resume / Portfolio Keyword Recommendations
    lines.append("## 💡 6. Resume & Portfolio Recommendations")
    
    lines.append("### Resume Keywords")
    for kw in skill_gaps.get("resume_keywords", []):
        lines.append(f"- `{kw}`")
        
    lines.append("\n### Portfolio Case Study Angles")
    for kw in skill_gaps.get("portfolio_angles", []):
        lines.append(f"- {kw}")
        
    lines.append("\n### LinkedIn Headline/About Keywords")
    for kw in skill_gaps.get("linkedin_keywords", []):
        lines.append(f"- `{kw}`")
        
    lines.append("\n### Skills to Learn or Strengthen")
    for kw in skill_gaps.get("skills_to_learn", []):
        lines.append(f"- `{kw}`")
    lines.append("")
    
    # 7. Job Clusters
    lines.append("## 🗂️ 7. Analyzed Job Listings")
    include_excerpt = getattr(config, "analysis", None) and config.analysis.include_raw_description_excerpt
    excerpt_chars = getattr(config, "analysis", None) and config.analysis.raw_description_excerpt_chars or 500
    
    for cluster_name, cluster_jobs in clusters.items():
        lines.append(f"### {cluster_name}")
        for job in cluster_jobs[:5]:
            lines.append(_format_job_compact(job, kw_groups, include_excerpt, excerpt_chars))
            
    # 8. Individual Job Appendix
    lines.append("## 8. Individual Job Appendix")
    for job in jobs:
        title = job.get("title", "Unknown Title")
        company = job.get("company", "Unknown Company")
        location = job.get("location", "Unknown Location")
        url = job.get("url", "#")
        top_kws = ", ".join(job.get("matched_keywords", [])[:3])
        lines.append(f"- **[{title} @ {company}]({url})** | {location} | Top Keywords: {top_kws}")

    return "\n".join(lines)


def write_daily_report(markdown: str, output_dir: Path, report_date: date) -> Path:
    """
    Save the markdown report to disk.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    date_str = report_date.strftime("%Y-%m-%d")
    filename = f"{date_str}-job-report.md"
    file_path = output_dir / filename
    
    file_path.write_text(markdown, encoding="utf-8")
    return file_path


# ---------------------------------------------------------------------------
# Incremental Report Generator & Honest Trends
# ---------------------------------------------------------------------------

def compute_skill_trends(
    current_jobs: List[Dict[str, Any]],
    previous_jobs: List[Dict[str, Any]],
    kw_groups: Dict[str, List[str]],
    trend_config: Any
) -> Dict[str, Any]:
    """
    Compute statistically honest skill trends comparing percentages between runs.
    """
    curr_total = len(current_jobs)
    prev_total = len(previous_jobs)
    
    # Flatten keywords
    all_kws = set()
    if kw_groups:
        for kws in kw_groups.values():
            all_kws.update(kw.lower() for kw in kws)
            
    # Helper to count
    def _count(jobs):
        counts = {kw: 0 for kw in all_kws}
        for job in jobs:
            desc = (job.get("description", "") or "").lower()
            for kw in all_kws:
                if kw in desc:
                    counts[kw] += 1
        return counts

    curr_counts = _count(current_jobs)
    prev_counts = _count(previous_jobs)
    
    trends = []
    
    min_curr = getattr(trend_config, "min_current_jobs", 5)
    min_prev = getattr(trend_config, "min_previous_jobs", 5)
    min_diff = getattr(trend_config, "min_percentage_point_change", 10.0)
    
    insufficient_data = curr_total < min_curr or prev_total < min_prev
    
    if insufficient_data:
        return {
            "insufficient_data": True, 
            "trends": [], 
            "message": f"Insufficient evidence to identify a reliable directional trend. Minimum {min_curr} current and {min_prev} previous jobs required."
        }
        
    for kw in all_kws:
        curr_ct = curr_counts[kw]
        prev_ct = prev_counts[kw]
        
        curr_pct = (curr_ct / curr_total) * 100 if curr_total else 0
        prev_pct = (prev_ct / prev_total) * 100 if prev_total else 0
        
        diff = curr_pct - prev_pct
        
        if diff >= min_diff:
            trends.append({
                "skill": kw,
                "current_count": curr_ct,
                "current_percent": round(curr_pct, 1),
                "previous_count": prev_ct,
                "previous_percent": round(prev_pct, 1),
                "percentage_point_change": round(diff, 1)
            })
            
    # Sort by point change descending
    trends.sort(key=lambda x: x["percentage_point_change"], reverse=True)
    return {"insufficient_data": False, "trends": trends}


def _format_ai_job_card(job: Dict[str, Any], ai_result: Optional[Dict[str, Any]] = None) -> str:
    """Format a new job card with AI analysis (or rule-based fallback)."""
    title = job.get("title", "Unknown Title")
    company = job.get("company", "Unknown Company")
    location = job.get("location", "Unknown Location")
    url = job.get("url", "#")

    lines = [f"#### [{title} @ {company}]({url})"]
    if location and location.lower() != "unknown location":
        lines.append(f"📍 {location}")

    if ai_result and ai_result.get("summary"):
        lines.append(f"\n**Summary:** {ai_result['summary']}")
        lines.append("") # Blank line to start list block
        if ai_result.get("required_skills"):
            lines.append(f"- **Required Skills:** {', '.join(ai_result['required_skills'][:8])}")
        if ai_result.get("preferred_skills"):
            lines.append(f"- **Preferred Skills:** {', '.join(ai_result['preferred_skills'][:5])}")
        if ai_result.get("core_responsibilities"):
            lines.append("- **Key Responsibilities:**")
            for r in ai_result["core_responsibilities"][:3]:
                clean_r = r.lstrip("-• ").strip()
                lines.append(f"    - {clean_r}")
        if ai_result.get("job_seeker_takeaway"):
            lines.append(f"- **💡 Takeaway:** {ai_result['job_seeker_takeaway']}")
    else:
        # Rule-based fallback
        desc = job.get("description", "")
        if desc:
            snippet = desc[:300].replace("\n", " ").strip()
            lines.append(f"\n> {snippet}...")
            lines.append("")

    lines.append("")
    return "\n".join(lines)


def _format_updated_job_card(job: Dict[str, Any], change_analysis: Optional[Dict[str, Any]] = None) -> str:
    """Format an updated job card showing what changed."""
    title = job.get("title", "Unknown Title")
    company = job.get("company", "Unknown Company")
    url = job.get("url", "#")

    lines = [f"#### [{title} @ {company}]({url})"]
    location = job.get("location", "")
    if location and location.lower() != "unknown location":
        lines.append(f"📍 {location}")

    if change_analysis:
        if change_analysis.get("change_summary"):
            lines.append("**What Changed:**")
            lines.append("")
            for change in change_analysis["change_summary"]:
                clean_c = change.lstrip("-• ").strip()
                lines.append(f"- {clean_c}")
        if change_analysis.get("new_requirements"):
            lines.append("**New Requirements:**")
            lines.append("")
            for req in change_analysis["new_requirements"]:
                clean_r = req.lstrip("-•➕ ").strip()
                lines.append(f"- ➕ {clean_r}")
        if change_analysis.get("removed_requirements"):
            lines.append("**Removed Requirements:**")
            lines.append("")
            for req in change_analysis["removed_requirements"]:
                clean_r = req.lstrip("-•➖ ").strip()
                lines.append(f"- ➖ {clean_r}")
        if change_analysis.get("changed_responsibilities"):
            lines.append("**Changed Responsibilities:**")
            lines.append("")
            for resp in change_analysis["changed_responsibilities"]:
                clean_r = resp.lstrip("-•🔄 ").strip()
                lines.append(f"- 🔄 {clean_r}")
    else:
        lines.append("*Content hash changed since last seen. Detailed diff unavailable (AI disabled).*")
        lines.append("")

    lines.append("")
    return "\n".join(lines)


def _normalize_text(text: str) -> str:
    import string
    return text.lower().translate(str.maketrans('', '', string.punctuation)).strip()

def _deduplicate_insights(summary: dict) -> None:
    """Deduplicate insights independently within each role. Collect exact matches into cross_role_patterns."""
    cross_role_tracker = {}
    
    if summary.get("role_analyses"):
        for role, data in summary["role_analyses"].items():
            seen_in_role = set()
            
            for key in ["role_specific_insights", "ideal_candidate_profile", "case_study_recommendations", "portfolio_recommendations", "resume_actions", "linkedin_actions"]:
                if key in data and isinstance(data[key], list):
                    deduped = []
                    for item in data[key]:
                        if not isinstance(item, str): continue
                        norm = _normalize_text(item)
                        if not norm: continue
                        if norm not in seen_in_role:
                            seen_in_role.add(norm)
                            deduped.append(item)
                            
                            if norm not in cross_role_tracker:
                                cross_role_tracker[norm] = {"count": 1, "original": item, "roles": [role]}
                            else:
                                cross_role_tracker[norm]["count"] += 1
                                cross_role_tracker[norm]["roles"].append(role)
                    data[key] = deduped

    # Generate cross-role patterns if an insight appeared in > 1 role
    if "cross_role_patterns" not in summary:
        summary["cross_role_patterns"] = []
    
    for norm, info in cross_role_tracker.items():
        if info["count"] > 1:
            roles_str = ", ".join(info["roles"])
            pattern = f"{info['original']} (Seen in: {roles_str})"
            if pattern not in summary["cross_role_patterns"]:
                summary["cross_role_patterns"].append(pattern)

def generate_incremental_report(
    classified_jobs: Dict[str, List[Dict[str, Any]]],
    run_stats: Dict[str, Any],
    config: "JobWatchConfig",
    previous_run: Optional[Dict[str, Any]] = None,
    ai_job_analyses: Optional[Dict[str, Dict[str, Any]]] = None,
    ai_update_analyses: Optional[Dict[str, Dict[str, Any]]] = None,
    ai_market_summary: Optional[Dict[str, Any]] = None,
    include_previously_seen: bool = True,
    chart_cid: str = "",
    banner_cid: str = "",
) -> str:
    """
    Generate the incremental Job Intelligence Report using the Current Market Snapshot schema.
    """
    ai_job_analyses = ai_job_analyses or {}
    ai_update_analyses = ai_update_analyses or {}
    ai_market_summary = ai_market_summary or {}

    if ai_market_summary:
        _deduplicate_insights(ai_market_summary)

    new_jobs = classified_jobs.get("new", [])
    updated_jobs = classified_jobs.get("updated", [])
    unchanged_jobs = classified_jobs.get("unchanged", [])
    
    if getattr(config.analysis_scope, "include_all_current_jobs", False):
        include_previously_seen = True

    today_str = date.today().strftime("%Y-%m-%d")
    evidence_limit = getattr(config.report, "evidence_examples_per_insight", 3)
    include_appendix = getattr(config.report, "include_evidence_appendix", True)
    max_executive_words = getattr(config.report, "max_executive_words", 250)
    
    appendix_items = []

    def _process_evidence(evidence_list: List[str], context: str) -> List[str]:
        if not evidence_list:
            return []
        shown = evidence_list[:evidence_limit]
        overflow = evidence_list[evidence_limit:]
        result = []
        for ev in shown:
            result.append(f"- {ev}")
        if overflow and include_appendix:
            appendix_items.append((context, overflow))
            safe_id = "".join(c if c.isalnum() else "-" for c in context.lower())
            result.append(f"- *See [Evidence Appendix](#appendix-{safe_id}) for {len(overflow)} more examples.*")
        return result

    # ── Pre-build Detailed Current Jobs ──
    all_active_jobs = []
    all_active_jobs.extend(new_jobs)
    all_active_jobs.extend(updated_jobs)
    if include_previously_seen:
        all_active_jobs.extend(unchanged_jobs)
        
    all_active_jobs.sort(key=lambda j: j.get("match_score", 0), reverse=True)
    
    roles = ai_market_summary.get("configured_roles", getattr(config, "target_roles", []))
    grouped_jobs = {role: [] for role in roles}
        
    for job in all_active_jobs:
        identity = job.get("_stable_identity", "")
        ai_result = ai_job_analyses.get(identity)
        change_result = ai_update_analyses.get(identity) if job in updated_jobs else None
        
        assigned = job.get("matched_target_role")
        match_state = job.get("match_state", "unmatched")
        
        if match_state == "unmatched" or not assigned or assigned not in roles:
            continue
            
        if change_result:
            grouped_jobs[assigned].append((job, _format_updated_job_card(job, change_result)))
        else:
            grouped_jobs[assigned].append((job, _format_ai_job_card(job, ai_result)))
            
    limit_per_role = getattr(config.analysis_scope, "detailed_current_jobs_limit", 15)
    
    jobs_lines = []
    jobs_lines.append(f"## 2. Detailed Current Jobs Grouped by Role")
    jobs_lines.append("")
    for role in roles:
        if grouped_jobs[role]:
            jobs_lines.append(f"### {role}")
            jobs_lines.append("")
            for job_tuple in grouped_jobs[role][:limit_per_role]:
                jobs_lines.append(job_tuple[1])
            if len(grouped_jobs[role]) > limit_per_role:
                jobs_lines.append(f"#### Additional {role} Jobs")
                for job_tuple in grouped_jobs[role][limit_per_role:]:
                    jobs_lines.append(_format_job_compact(job_tuple[0]))
                jobs_lines.append("")

    # ── Table of Contents ──
    toc_lines = []
    toc_lines.append("## Table of Contents")
    toc_lines.append("- [Executive Current Market Snapshot](#1-executive-current-market-snapshot)")
    if getattr(config, "my_arsenal", []):
        toc_lines.append("- [My Arsenal Gap Analysis](#15-my-arsenal-gap-analysis)")
    toc_lines.append("- [Detailed Current Jobs](#2-detailed-current-jobs-grouped-by-role)")
    
    for i, role in enumerate(roles, start=3):
        safe_id = "".join(c if c.isalnum() else "-" for c in role.lower())
        toc_lines.append(f"- [{role} Intelligence](#{i}-{safe_id}-intelligence)")
        
    sec_num = len(roles) + 3
    toc_lines.append(f"- [Cross-Role Patterns](#{sec_num}-cross-role-patterns)")
    
    if getattr(config.report, "include_role_history_changes", False) and ai_market_summary.get("optional_role_changes"):
        sec_num += 1
        toc_lines.append(f"- [Notable Changes](#{sec_num}-notable-changes)")
        
    toc_lines.append("")

    # ── Assemble Report ──
    lines = []
    
    if banner_cid:
        lines.append(f'<div align="center"><a href="https://github.com/Zhengdong-uga"><img src="cid:{banner_cid}" alt="GitHub Banner" style="width: 100%; max-width: 800px; border-radius: 8px; margin-bottom: 20px;"></a></div>\n')
    else:
        branding = getattr(config, "branding", None)
        if branding:
            if branding.logo_url:
                lines.append(f'<div align="center"><img src="{branding.logo_url}" width="200" alt="Logo" style="margin-bottom: 20px;"></div>\n')
            if branding.intro_text:
                lines.append(f'<div class="newsletter-intro" style="font-size: 16px; color: #4b5563; line-height: 1.6; margin-bottom: 30px; border-left: 4px solid #4f46e5; padding-left: 15px;">{branding.intro_text}</div>\n')

    lines.extend([f"# Current Job Market Snapshot — {today_str}", ""])
    lines.extend(toc_lines)

    # ── Section 1: Executive Current Market Snapshot ──
    lines.append("## 1. Executive Current Market Snapshot")
    lines.append("")

    if chart_cid:
        lines.append(f"![Top Skills Chart](cid:{chart_cid})")
        lines.append("")

    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Scrape window | Last {run_stats.get('scrape_hours_old', '?')} hours |")
    lines.append(f"| Unique jobs analyzed | {run_stats.get('unique_count', 0)} |")
    lines.append(f"| **New jobs** | **{len(new_jobs)}** |")
    lines.append(f"| **Updated jobs** | **{len(updated_jobs)}** |")
    lines.append(f"| Previously seen | {len(unchanged_jobs)} |")
    lines.append(f"| AI/Cache extractions | {run_stats.get('ai_analyzed_count', 0)} ({run_stats.get('cache_hits', 0)} cached, {run_stats.get('fallback_count', 0)} rule fallbacks) |")
    lines.append("")
    
    snapshot = ai_market_summary.get("market_snapshot", {})
    if snapshot and snapshot.get("executive_summary"):
        for t in snapshot["executive_summary"][:5]:
            lines.append(f"- {_truncate_words(t, max_executive_words)}")
        lines.append("")

    my_arsenal = getattr(config, "my_arsenal", [])
    if my_arsenal and ai_market_summary.get("role_analyses"):
        lines.append("## 1.5 My Arsenal Gap Analysis")
        lines.append("")
        
        missing_skills = {}
        my_arsenal_lower = {s.lower().strip() for s in my_arsenal}
        
        for role, data in ai_market_summary["role_analyses"].items():
            for req in data.get("required_skill_frequencies", []):
                skill_name = req.get("skill", "")
                if not skill_name: continue
                
                if skill_name.lower().strip() not in my_arsenal_lower:
                    if skill_name not in missing_skills:
                        missing_skills[skill_name] = 0
                    missing_skills[skill_name] += req.get("count", 0)
                    
        sorted_missing = sorted(missing_skills.items(), key=lambda x: x[1], reverse=True)
        # Only show skills that appeared at least once
        top_missing = [s for s in sorted_missing if s[1] > 0][:5]
        
        if top_missing:
            lines.append("**High-demand skills required by the market but currently missing from your arsenal:**")
            lines.append("")
            for skill, count in top_missing:
                lines.append(f"- **{skill}** (Mentioned {count} times) -> Recommended for your learning plan")
        else:
            lines.append("*Excellent! All high-frequency core skills required by the current market are already in your arsenal.*")
            
        lines.append("")

    # ── Section 2: Detailed Current Jobs ──
    lines.extend(jobs_lines)

    # ── Section 3+: Role-by-Role Market Intelligence ──
    role_analyses = ai_market_summary.get("role_analyses", {})
    for i, role in enumerate(roles, start=3):
        safe_id = "".join(c if c.isalnum() else "-" for c in role.lower())
        lines.append(f"## {i}. {role} Intelligence")
        lines.append("")
        
        data = role_analyses.get(role)
        if not data:
            lines.append("*No data available for this role in the current window.*")
            lines.append("")
            continue
            
        total_role_jobs = data.get('job_count', 0)
        lines.append(f"**Based on {total_role_jobs} recent jobs.**")
        lines.append("")
        
        if data.get("role_specific_insights"):
            lines.append("### Snapshot")
            for insight in data["role_specific_insights"]:
                lines.append(f"- {insight}")
            lines.append("")
            
        if data.get("responsibility_frequencies"):
            lines.append("### Key Responsibilities")
            lines.append("| Responsibility | Frequency |")
            lines.append("|---|---|")
            for r in data["responsibility_frequencies"][:5]:
                pct = r.get('percentage', 0)
                count = r.get('count', 0)
                lines.append(f"| {r.get('responsibility', '')} | {count} of {total_role_jobs} jobs ({pct}%) |")
            lines.append("")
            
        req_freqs = {s.get("skill", ""): s for s in data.get("required_skill_frequencies", [])}
        pref_freqs = {s.get("skill", ""): s for s in data.get("preferred_skill_frequencies", [])}
        
        if req_freqs or pref_freqs:
            lines.append("### Required vs Preferred Skills")
            lines.append("| Skill | Required | Preferred | Mentioned/Unclear | Total Role Jobs |")
            lines.append("|---|---:|---:|---:|---:|")
            
            all_skills = list(set(list(req_freqs.keys()) + list(pref_freqs.keys())))
            all_skills.sort(key=lambda x: req_freqs.get(x, {}).get("count", 0) + pref_freqs.get(x, {}).get("count", 0), reverse=True)
            
            for skill in all_skills[:15]:
                req_count = req_freqs.get(skill, {}).get("count", 0)
                req_pct = req_freqs.get(skill, {}).get("percentage", 0)
                
                pref_count = pref_freqs.get(skill, {}).get("count", 0)
                pref_pct = pref_freqs.get(skill, {}).get("percentage", 0)
                
                req_str = f"{req_count} of {total_role_jobs} jobs ({req_pct}%)" if req_count else "-"
                pref_str = f"{pref_count} of {total_role_jobs} jobs ({pref_pct}%)" if pref_count else "-"
                
                lines.append(f"| {skill} | {req_str} | {pref_str} | - | {total_role_jobs} |")
            lines.append("")
            
        if data.get("ideal_candidate_profile"):
            lines.append("### Ideal Candidate Profile")
            for p in data["ideal_candidate_profile"]:
                lines.append(f"- {p}")
            lines.append("")
            
        lines.append("### Recommendations")
        recs = []
        if data.get("case_study_recommendations"):
            recs.append("**Recommended Case Study / Project:**")
            for r in data["case_study_recommendations"]:
                recs.append(f"- {r}")
        if data.get("portfolio_recommendations"):
            recs.append("**Portfolio Presentation Recommendations:**")
            for r in data["portfolio_recommendations"]:
                recs.append(f"- {r}")
        if data.get("resume_keywords"):
            recs.append(f"**Resume Keywords:** {', '.join(data['resume_keywords'])}")
        if data.get("resume_actions"):
            recs.append("**Resume Actions:**")
            for r in data["resume_actions"]:
                recs.append(f"- {r}")
        if data.get("linkedin_actions"):
            recs.append("**LinkedIn Actions:**")
            for r in data["linkedin_actions"]:
                recs.append(f"- {r}")
            
        lines.extend(recs)
        lines.append("")

    sec_num = len(roles) + 3
    
    # ── Cross-Role Patterns ──
    lines.append(f"## {sec_num}. Cross-Role Patterns")
    lines.append("")
    if ai_market_summary.get("cross_role_patterns"):
        for pattern in ai_market_summary["cross_role_patterns"]:
            lines.append(f"- {pattern}")
    else:
        lines.append("*No cross-role patterns generated.*")
    lines.append("")
    sec_num += 1
    
    # ── Optional Changes ──
    if getattr(config.report, "include_role_history_changes", False) and ai_market_summary.get("optional_role_changes"):
        lines.append(f"## {sec_num}. Notable Changes")
        lines.append("")
        for change in ai_market_summary["optional_role_changes"]:
            lines.append(f"- {change}")
        lines.append("")
        sec_num += 1

    # ── Evidence Appendix ──
    if include_appendix and appendix_items:
        lines.append(f"## {sec_num}. Evidence Appendix")
        lines.append("")
        for context, overflow in appendix_items:
            safe_id = "".join(c if c.isalnum() else "-" for c in context.lower())
            lines.append(f'### <a id="appendix-{safe_id}"></a>{context}')
            for ev in overflow:
                lines.append(f"- {ev}")
            lines.append("")

    return "\n".join(lines)
