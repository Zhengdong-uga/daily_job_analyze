from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _truncate_description(description: Optional[str], max_chars: int = 800) -> str:
    """Truncate a description to a maximum number of characters."""
    if not description:
        return "*No description provided.*"
    if len(description) <= max_chars:
        return description
    return description[:max_chars] + "..."


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
        f"**Summary:**",
        summary,
        ""
    ]
    
    if reqs["hard_skills"]:
        lines.append(f"- **Hard Skills:** {', '.join(reqs['hard_skills'][:5])}")
    if reqs["soft_skills"]:
        lines.append(f"- **Soft Skills:** {', '.join(reqs['soft_skills'][:5])}")
        
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
    lines.append("## 1. Executive Summary")
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
    lines.append("### Top 10 Skills to Prioritize")
    for skill, count in top_skills:
        lines.append(f"- **{skill}** ({count} mentions)")
    lines.append("")
    
    # 2. Today's Job Market Trends
    lines.append("## 2. Today's Job Market Trends")
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
    lines.append("## Role-to-Skill Matrix")
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
    lines.append("## 3. Specific Job Requirements by Role Type")
    for role, data in skill_gaps.get("role_specific_data", {}).items():
        lines.append(f"### {role}")
        if data.get("companies_hiring"):
            lines.append(f"**Top Companies Hiring:** {', '.join(data['companies_hiring'])}")
        lines.append("\n**Required Hard Skills:**")
        for skill in data.get("hard_skills", []):
            lines.append(f"- {skill}")
        lines.append("\n**Required Soft/Collaboration Skills:**")
        for skill in data.get("soft_skills", []):
            lines.append(f"- {skill}")
        lines.append("\n**Repeated JD Phrases:**")
        for resp in data.get("phrases", []):
            lines.append(f"- \"{resp}\"")
        lines.append("\n**Example Jobs:**")
        for ex in data.get("example_jobs", []):
            lines.append(f"- {ex.get('title')} — {ex.get('company')}")
        lines.append("")
        
    # 4. Skill Demand Overview
    lines.append("## 4. Skill Demand Overview")
    for group, counts in keyword_counts.items():
        lines.append(f"### {group.replace('_', ' ').title()}")
        for kw, kw_data in counts.items():
            examples = ", ".join([j.get("title", "") for j in kw_data.get("jobs", [])])
            lines.append(f"- **{kw}** ({kw_data['count']} mentions): e.g., {examples}")
        lines.append("")
        
    # 5. Repeated Responsibilities Across Jobs
    lines.append("## 5. Repeated Responsibilities Across Jobs")
    for resp in skill_gaps.get("repeated_responsibilities", []):
        lines.append(f"- {resp}")
    lines.append("")
        
    # 6. Resume / Portfolio Keyword Recommendations
    lines.append("## 6. Resume / Portfolio Keyword Recommendations")
    
    lines.append("### Resume Keywords")
    for kw in skill_gaps.get("resume_keywords", []):
        lines.append(f"- {kw}")
        
    lines.append("\n### Portfolio Case Study Angles")
    for kw in skill_gaps.get("portfolio_angles", []):
        lines.append(f"- {kw}")
        
    lines.append("\n### LinkedIn Headline/About Keywords")
    for kw in skill_gaps.get("linkedin_keywords", []):
        lines.append(f"- {kw}")
        
    lines.append("\n### Skills to Learn or Strengthen")
    for kw in skill_gaps.get("skills_to_learn", []):
        lines.append(f"- {kw}")
    lines.append("")
    
    # 7. Job Clusters
    lines.append("## 7. Job Clusters")
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


# ---------------------------------------------------------------------------
# Compact job card formatters for incremental report
# ---------------------------------------------------------------------------


def _format_new_job_compact(job: Dict[str, Any], ai_result: Optional[Dict[str, Any]] = None) -> str:
    """Format a new job as a compact card: title + link + location + takeaway."""
    title = job.get("title", "Unknown Title")
    company = job.get("company", "Unknown Company")
    location = job.get("location", "Unknown Location")
    url = job.get("url", "#")

    lines = [f"#### [{title} @ {company}]({url})", f"📍 {location}"]

    if ai_result and ai_result.get("job_seeker_takeaway"):
        lines.append(f"💡 {ai_result['job_seeker_takeaway']}")
    elif ai_result and ai_result.get("summary"):
        lines.append(f"> {ai_result['summary']}")

    lines.append(f"🔗 [Apply]({url})")
    lines.append("")
    return "\n".join(lines)


def _format_updated_job_compact(job: Dict[str, Any], change_analysis: Optional[Dict[str, Any]] = None) -> str:
    """Format an updated job showing what changed — compact."""
    title = job.get("title", "Unknown Title")
    company = job.get("company", "Unknown Company")
    url = job.get("url", "#")

    lines = [f"#### [{title} @ {company}]({url})"]

    if change_analysis and change_analysis.get("change_summary"):
        lines.append(f"🔄 {'; '.join(change_analysis['change_summary'][:2])}")
    else:
        lines.append("*Content changed since last seen.*")

    lines.append(f"🔗 [Apply]({url})")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main incremental report — restructured layout
# ---------------------------------------------------------------------------


def generate_incremental_report(
    classified_jobs: Dict[str, List[Dict[str, Any]]],
    run_stats: Dict[str, Any],
    config: "JobWatchConfig",
    previous_run: Optional[Dict[str, Any]] = None,
    ai_job_analyses: Optional[Dict[str, Dict[str, Any]]] = None,
    ai_update_analyses: Optional[Dict[str, Dict[str, Any]]] = None,
    ai_market_summary: Optional[Dict[str, Any]] = None,
    include_previously_seen: bool = False,
) -> str:
    """
    Generate the incremental Job Intelligence Report.

    Section order is optimised for a junior job-seeker who opens the email
    and wants to see *actionable* content first:

      1. Executive Snapshot (compact stats table)
      2. New & Updated Opportunities (compact cards)
      3. What This Means for Me (Resume / Portfolio / LinkedIn)
      4. Skills to Learn
      5. Cross-Role Skill Patterns
      6. What Employers Want by Role (collapsible per role)
      7. Required vs Preferred Skills (separated)
      8. Industry & Hiring Trends (evidence collapsible)
      9. Changes Since Previous Run (collapsible)
     10. Previously Seen Jobs (collapsible)
    """
    ai_job_analyses = ai_job_analyses or {}
    ai_update_analyses = ai_update_analyses or {}
    ai_market_summary = ai_market_summary or {}

    new_jobs = classified_jobs.get("new", [])
    updated_jobs = classified_jobs.get("updated", [])
    unchanged_jobs = classified_jobs.get("unchanged", [])

    today_str = date.today().strftime("%Y-%m-%d")

    # -- Build cross-role set for highlighting later --------------------------
    cross_role_patterns: List[str] = ai_market_summary.get("cross_role_skill_patterns", [])

    lines = [f"# Current Job Market Snapshot — {today_str}", ""]

    # ── Table of Contents ────────────────────────────────────────────────────
    lines.append("## Table of Contents")
    lines.append("- [Executive Snapshot](#1-executive-snapshot)")
    lines.append("- [New & Updated Opportunities](#2-new--updated-opportunities)")
    lines.append("- [What This Means for Me](#3-what-this-means-for-me)")
    lines.append("- [Skills to Learn](#4-skills-to-learn)")
    lines.append("- [Cross-Role Skill Patterns](#5-cross-role-skill-patterns)")
    lines.append("- [What Employers Want by Role](#6-what-employers-want-by-role)")
    lines.append("- [Required vs Preferred Skills](#7-required-vs-preferred-skills)")
    lines.append("- [Industry & Hiring Trends](#8-industry--hiring-trends)")
    lines.append("- [Changes Since Previous Run](#9-changes-since-previous-run)")
    lines.append("- [Previously Seen Jobs](#10-previously-seen-jobs)")
    lines.append("")

    # ══════════════════════════════════════════════════════════════════════════
    # §1  Executive Snapshot
    # ══════════════════════════════════════════════════════════════════════════
    lines.append("## 1. Executive Snapshot")
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
        for t in snapshot["executive_summary"]:
            lines.append(f"- {t}")
        lines.append("")

    # ══════════════════════════════════════════════════════════════════════════
    # §2  New & Updated Opportunities
    # ══════════════════════════════════════════════════════════════════════════
    lines.append("## 2. New & Updated Opportunities")
    lines.append("")

    if new_jobs:
        lines.append("### 🆕 New Jobs")
        for job in new_jobs:
            identity = job.get("_stable_identity", "")
            ai_result = ai_job_analyses.get(identity)
            lines.append(_format_new_job_compact(job, ai_result))

    if updated_jobs:
        lines.append("### 🔄 Updated Jobs")
        for job in updated_jobs:
            identity = job.get("_stable_identity", "")
            change_result = ai_update_analyses.get(identity)
            lines.append(_format_updated_job_compact(job, change_result))

    if not new_jobs and not updated_jobs:
        lines.append("*No new or updated jobs in this window.*")
        lines.append("")

    # ══════════════════════════════════════════════════════════════════════════
    # §3  What This Means for Me  (Resume / Portfolio / LinkedIn)
    # ══════════════════════════════════════════════════════════════════════════
    lines.append("## 3. What This Means for Me")
    lines.append("")

    has_personal = False

    if ai_market_summary.get("resume_recommendations"):
        has_personal = True
        lines.append("### 📄 Resume")
        for rec in ai_market_summary["resume_recommendations"]:
            lines.append(f"- {rec}")
        lines.append("")

    # Also pull per-role resume actions
    role_analyses = ai_market_summary.get("role_analyses", {})
    for role_name, ra in role_analyses.items():
        if ra.get("resume_actions"):
            has_personal = True
            lines.append(f"**{role_name}:**")
            for action in ra["resume_actions"]:
                lines.append(f"- {action}")
            lines.append("")

    if ai_market_summary.get("portfolio_recommendations"):
        has_personal = True
        lines.append("### 🎨 Portfolio")
        for rec in ai_market_summary["portfolio_recommendations"]:
            lines.append(f"- {rec}")
        lines.append("")

    for role_name, ra in role_analyses.items():
        if ra.get("portfolio_recommendations"):
            has_personal = True
            lines.append(f"**{role_name}:**")
            for rec in ra["portfolio_recommendations"]:
                lines.append(f"- {rec}")
            lines.append("")

    if ai_market_summary.get("linkedin_recommendations"):
        has_personal = True
        lines.append("### 🔗 LinkedIn")
        for rec in ai_market_summary["linkedin_recommendations"]:
            lines.append(f"- {rec}")
        lines.append("")

    for role_name, ra in role_analyses.items():
        if ra.get("linkedin_actions"):
            has_personal = True
            lines.append(f"**{role_name}:**")
            for action in ra["linkedin_actions"]:
                lines.append(f"- {action}")
            lines.append("")

    if not has_personal:
        lines.append("*No personalised recommendations generated.*")
        lines.append("")

    # ══════════════════════════════════════════════════════════════════════════
    # §4  Skills to Learn
    # ══════════════════════════════════════════════════════════════════════════
    lines.append("## 4. Skills to Learn")
    lines.append("")
    if ai_market_summary.get("skills_to_learn"):
        for rec in ai_market_summary["skills_to_learn"]:
            lines.append(f"- {rec}")
    else:
        lines.append("*No skill recommendations generated.*")
    lines.append("")

    # ══════════════════════════════════════════════════════════════════════════
    # §5  Cross-Role Skill Patterns
    # ══════════════════════════════════════════════════════════════════════════
    lines.append("## 5. Cross-Role Skill Patterns")
    lines.append("")
    if cross_role_patterns:
        for pattern in cross_role_patterns:
            lines.append(f"- {pattern}")
    else:
        lines.append("*No cross-role patterns generated.*")
    lines.append("")

    # ══════════════════════════════════════════════════════════════════════════
    # §6  What Employers Want by Role  (each role collapsible)
    # ══════════════════════════════════════════════════════════════════════════
    lines.append("## 6. What Employers Want by Role")
    lines.append("")

    # Try the newer role_analyses schema first, then fall back to
    # the older role_specific_requirements schema.
    if role_analyses:
        for role_name, ra in role_analyses.items():
            job_count = ra.get("job_count", 0)
            lines.append(f"<details><summary><strong>{role_name}</strong> ({job_count} jobs)</summary>")
            lines.append("")

            if ra.get("role_specific_insights"):
                lines.append("**Insights:**")
                for item in ra["role_specific_insights"]:
                    lines.append(f"- {item}")
                lines.append("")

            if ra.get("ideal_candidate_profile"):
                lines.append("**Ideal Candidate:**")
                for item in ra["ideal_candidate_profile"]:
                    lines.append(f"- {item}")
                lines.append("")

            if ra.get("responsibility_frequencies"):
                lines.append("**Common Responsibilities:**")
                for item in ra["responsibility_frequencies"]:
                    if isinstance(item, dict):
                        lines.append(f"- {item.get('responsibility', item)} ({item.get('count', '?')}×)")
                    else:
                        lines.append(f"- {item}")
                lines.append("")

            if ra.get("required_skill_frequencies"):
                lines.append("**Required Skills:**")
                for item in ra["required_skill_frequencies"]:
                    if isinstance(item, dict):
                        skill = item.get("skill", str(item))
                        # Highlight cross-role skills
                        marker = ""
                        if any(skill.lower() in p.lower() for p in cross_role_patterns):
                            marker = " ⭐"
                        lines.append(f"- {skill} ({item.get('count', '?')}×){marker}")
                    else:
                        lines.append(f"- {item}")
                lines.append("")

            if ra.get("preferred_skill_frequencies"):
                lines.append("**Preferred Skills:**")
                for item in ra["preferred_skill_frequencies"]:
                    if isinstance(item, dict):
                        lines.append(f"- {item.get('skill', item)} ({item.get('count', '?')}×)")
                    else:
                        lines.append(f"- {item}")
                lines.append("")

            if ra.get("resume_keywords"):
                lines.append(f"**ATS Keywords:** {', '.join(ra['resume_keywords'][:10])}")
                lines.append("")

            lines.append("</details>")
            lines.append("")

    elif ai_market_summary.get("role_specific_requirements"):
        for role, reqs in ai_market_summary["role_specific_requirements"].items():
            lines.append(f"<details><summary><strong>{role}</strong></summary>")
            lines.append("")
            if reqs.get("what_the_role_does"):
                lines.append("**What the Role Does:**")
                for item in reqs["what_the_role_does"]:
                    lines.append(f"- {item}")
            if reqs.get("required_skills"):
                lines.append("\n**Required Skills:**")
                for item in reqs["required_skills"]:
                    lines.append(f"- {item}")
            if reqs.get("preferred_skills"):
                lines.append("\n**Preferred Skills:**")
                for item in reqs["preferred_skills"]:
                    lines.append(f"- {item}")
            if reqs.get("common_responsibilities"):
                lines.append("\n**Common Responsibilities:**")
                for item in reqs["common_responsibilities"]:
                    lines.append(f"- {item}")
            lines.append("")
            lines.append("</details>")
            lines.append("")
    else:
        lines.append("*No role-specific insights generated.*")
        lines.append("")

    # ══════════════════════════════════════════════════════════════════════════
    # §7  Required vs Preferred Skills  (separated)
    # ══════════════════════════════════════════════════════════════════════════
    lines.append("## 7. Required vs Preferred Skills")
    lines.append("")

    if ai_market_summary.get("required_vs_preferred_patterns"):
        # The AI returns these as a flat list of strings.  Try to split them
        # into "required" and "preferred" buckets heuristically.
        required_items: List[str] = []
        preferred_items: List[str] = []
        other_items: List[str] = []

        for pattern in ai_market_summary["required_vs_preferred_patterns"]:
            lower = pattern.lower()
            if "required" in lower or "must" in lower or "essential" in lower or "baseline" in lower:
                required_items.append(pattern)
            elif "preferred" in lower or "nice" in lower or "bonus" in lower or "plus" in lower:
                preferred_items.append(pattern)
            else:
                other_items.append(pattern)

        if required_items:
            lines.append("### ✅ Typically Required")
            for item in required_items:
                lines.append(f"- {item}")
            lines.append("")

        if preferred_items:
            lines.append("### 💡 Typically Preferred / Nice-to-Have")
            for item in preferred_items:
                lines.append(f"- {item}")
            lines.append("")

        if other_items:
            lines.append("### General Patterns")
            for item in other_items:
                lines.append(f"- {item}")
            lines.append("")
    else:
        lines.append("*No required vs preferred pattern insights generated.*")
        lines.append("")

    # ══════════════════════════════════════════════════════════════════════════
    # §8  Industry & Hiring Trends  (evidence collapsible)
    # ══════════════════════════════════════════════════════════════════════════
    lines.append("## 8. Industry & Hiring Trends")
    lines.append("")

    if ai_market_summary.get("current_market_trends"):
        for trend in ai_market_summary["current_market_trends"]:
            lines.append(f"### {trend.get('trend', 'Trend')}")
            lines.append(f"{trend.get('explanation', '')}")
            lines.append("")

            if trend.get("affected_role_clusters"):
                lines.append(f"**Affected Roles:** {', '.join(trend['affected_role_clusters'])}")

            if trend.get("example_jobs"):
                lines.append(f"**Example Jobs:** {', '.join(trend['example_jobs'])}")

            # Evidence in a collapsible block
            if trend.get("deterministic_evidence"):
                lines.append("")
                lines.append("<details><summary>📊 Evidence</summary>")
                lines.append("")
                for ev in trend["deterministic_evidence"]:
                    lines.append(f"- {ev}")
                lines.append("")
                lines.append("</details>")

            lines.append("")
    else:
        lines.append("*No AI trend insights generated.*")
        lines.append("")

    # Also render snapshot patterns if present
    if snapshot:
        if snapshot.get("dominant_hiring_patterns"):
            lines.append("### Dominant Hiring Patterns")
            for t in snapshot["dominant_hiring_patterns"]:
                lines.append(f"- {t}")
            lines.append("")
        if snapshot.get("candidate_profile_employers_want"):
            lines.append("### Ideal Candidate Profile")
            for t in snapshot["candidate_profile_employers_want"]:
                lines.append(f"- {t}")
            lines.append("")

    # ══════════════════════════════════════════════════════════════════════════
    # §9  Changes Since Previous Run (collapsible)
    # ══════════════════════════════════════════════════════════════════════════
    lines.append("## 9. Changes Since Previous Run")
    lines.append("")

    has_changes = False
    change_lines: List[str] = []

    computed_trends = run_stats.get("computed_trends", {})
    if computed_trends.get("insufficient_data"):
        change_lines.append(f"*{computed_trends.get('message', 'Insufficient data for deterministic trends')}*")
        change_lines.append("")
    elif computed_trends.get("trends"):
        has_changes = True
        change_lines.append("### Deterministic Skill Shifts")
        for trend in computed_trends["trends"][:5]:
            change_lines.append(f"- **{trend['skill'].title()}**: Grew by {trend['percentage_point_change']}% (from {trend['previous_percent']}% to {trend['current_percent']}%)")
        change_lines.append("")

    if ai_market_summary.get("changes_since_previous_run"):
        has_changes = True
        change_lines.append("### AI Identified Changes")
        for change in ai_market_summary["changes_since_previous_run"]:
            change_lines.append(f"- {change}")
        change_lines.append("")

    if ai_market_summary.get("optional_role_changes"):
        for rc in ai_market_summary["optional_role_changes"]:
            if isinstance(rc, str):
                change_lines.append(f"- {rc}")
            elif isinstance(rc, dict):
                change_lines.append(f"- {rc.get('description', str(rc))}")
        change_lines.append("")

    if has_changes or change_lines:
        lines.append("<details><summary>Click to expand</summary>")
        lines.append("")
        lines.extend(change_lines)
        lines.append("</details>")
        lines.append("")
    else:
        lines.append("*No changes detected.*")
        lines.append("")

    # ══════════════════════════════════════════════════════════════════════════
    # §10  Previously Seen Jobs (collapsible)
    # ══════════════════════════════════════════════════════════════════════════
    lines.append("## 10. Previously Seen Jobs")
    lines.append("")

    if include_previously_seen and unchanged_jobs:
        lines.append(f"<details><summary>{len(unchanged_jobs)} active previously seen jobs</summary>")
        lines.append("")
        for job in unchanged_jobs:
            identity = job.get("_stable_identity", "")
            ai_result = ai_job_analyses.get(identity)
            title = job.get("title", "Unknown")
            company = job.get("company", "Unknown")
            location = job.get("location", "")
            url = job.get("url", "#")
            takeaway = ""
            if ai_result:
                takeaway = ai_result.get("job_seeker_takeaway", "") or ai_result.get("summary", "")
            if takeaway:
                lines.append(f"- **[{title} @ {company}]({url})** 📍 {location} — {takeaway}")
            else:
                lines.append(f"- **[{title} @ {company}]({url})** 📍 {location}")
        lines.append("")
        lines.append("</details>")
        lines.append("")
    else:
        lines.append("*No previously seen jobs to display.*")
        lines.append("")

    return "\n".join(lines)
