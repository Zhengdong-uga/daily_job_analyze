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


def _format_ai_job_card(job: Dict[str, Any], ai_result: Optional[Dict[str, Any]] = None) -> str:
    """Format a new job card with AI analysis (or rule-based fallback)."""
    title = job.get("title", "Unknown Title")
    company = job.get("company", "Unknown Company")
    location = job.get("location", "Unknown Location")
    url = job.get("url", "#")

    lines = [f"#### [{title} @ {company}]({url})", f"📍 {location}"]

    if ai_result and ai_result.get("summary"):
        lines.append(f"\n**Summary:** {ai_result['summary']}")
        if ai_result.get("required_skills"):
            lines.append(f"- **Required Skills:** {', '.join(ai_result['required_skills'][:8])}")
        if ai_result.get("preferred_skills"):
            lines.append(f"- **Preferred Skills:** {', '.join(ai_result['preferred_skills'][:5])}")
        if ai_result.get("core_responsibilities"):
            lines.append("- **Key Responsibilities:**")
            for r in ai_result["core_responsibilities"][:3]:
                lines.append(f"  - {r}")
        if ai_result.get("job_seeker_takeaway"):
            lines.append(f"- **💡 Takeaway:** {ai_result['job_seeker_takeaway']}")
    else:
        # Rule-based fallback
        desc = job.get("description", "")
        if desc:
            snippet = desc[:300].replace("\n", " ").strip()
            lines.append(f"\n> {snippet}...")

    lines.append(f"- 🔗 [Apply]({url})")
    lines.append("")
    return "\n".join(lines)


def _format_updated_job_card(job: Dict[str, Any], change_analysis: Optional[Dict[str, Any]] = None) -> str:
    """Format an updated job card showing what changed."""
    title = job.get("title", "Unknown Title")
    company = job.get("company", "Unknown Company")
    url = job.get("url", "#")

    lines = [f"#### [{title} @ {company}]({url})"]

    if change_analysis:
        if change_analysis.get("change_summary"):
            lines.append("**What Changed:**")
            for change in change_analysis["change_summary"]:
                lines.append(f"- {change}")
        if change_analysis.get("new_requirements"):
            lines.append("**New Requirements:**")
            for req in change_analysis["new_requirements"]:
                lines.append(f"- ➕ {req}")
        if change_analysis.get("removed_requirements"):
            lines.append("**Removed Requirements:**")
            for req in change_analysis["removed_requirements"]:
                lines.append(f"- ➖ {req}")
        if change_analysis.get("changed_responsibilities"):
            lines.append("**Changed Responsibilities:**")
            for resp in change_analysis["changed_responsibilities"]:
                lines.append(f"- 🔄 {resp}")
    else:
        lines.append("*Content hash changed since last seen. Detailed diff unavailable (AI disabled).*")

    lines.append(f"- 🔗 [Apply]({url})")
    lines.append("")
    return "\n".join(lines)


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
    Generate the incremental Job Intelligence Report using the Current Market Snapshot schema.
    """
    ai_job_analyses = ai_job_analyses or {}
    ai_update_analyses = ai_update_analyses or {}
    ai_market_summary = ai_market_summary or {}

    new_jobs = classified_jobs.get("new", [])
    updated_jobs = classified_jobs.get("updated", [])
    unchanged_jobs = classified_jobs.get("unchanged", [])

    today_str = date.today().strftime("%Y-%m-%d")
    kw_groups = getattr(config, "keyword_groups", None)

    lines = [f"# Current Job Market Snapshot — {today_str}", ""]

    # ── Section 1: Executive Market Snapshot ──
    lines.append("## 1. Executive Market Snapshot")
    lines.append("")
    
    # Overview Table
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Scrape window | Last {run_stats.get('scrape_hours_old', '?')} hours |")
    lines.append(f"| Unique jobs analyzed | {run_stats.get('unique_count', 0)} |")
    lines.append(f"| **New jobs** | **{len(new_jobs)}** |")
    lines.append(f"| **Updated jobs** | **{len(updated_jobs)}** |")
    lines.append(f"| Previously seen | {len(unchanged_jobs)} |")
    lines.append(f"| AI/Cache extractions | {run_stats.get('ai_analyzed_count', 0)} ({run_stats.get('cache_hits', 0)} cached, {run_stats.get('fallback_count', 0)} rule fallbacks) |")
    lines.append("")
    
    snapshot = ai_market_summary.get("market_snapshot", {})
    if snapshot:
        if snapshot.get("executive_summary"):
            lines.append("### Key Takeaways")
            for t in snapshot["executive_summary"]:
                lines.append(f"- {t}")
            lines.append("")
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

    # ── Section 2: Current Industry and Hiring Trends ──
    lines.append("## 2. Current Industry and Hiring Trends")
    lines.append("")
    if ai_market_summary.get("current_market_trends"):
        for trend in ai_market_summary["current_market_trends"]:
            lines.append(f"### {trend.get('trend', 'Trend')}")
            lines.append(f"**Explanation:** {trend.get('explanation', '')}")
            lines.append("")
            if trend.get("deterministic_evidence"):
                lines.append("**Evidence:**")
                for ev in trend["deterministic_evidence"]:
                    lines.append(f"- {ev}")
            if trend.get("affected_role_clusters"):
                lines.append(f"\n**Affected Roles:** {', '.join(trend['affected_role_clusters'])}")
            if trend.get("example_jobs"):
                lines.append(f"\n**Example Jobs:** {', '.join(trend['example_jobs'])}")
            lines.append("")
    else:
        lines.append("*No AI trend insights generated.*")
        lines.append("")

    # ── Section 3: What Employers Are Looking For by Role ──
    lines.append("## 3. What Employers Are Looking For by Role")
    lines.append("")
    if ai_market_summary.get("role_specific_requirements"):
        for role, reqs in ai_market_summary["role_specific_requirements"].items():
            lines.append(f"### {role}")
            if reqs.get("what_the_role_does"):
                lines.append("**What the Role Does:**")
                for item in reqs["what_the_role_does"]:
                    lines.append(f"- {item}")
            if reqs.get("required_skills"):
                lines.append("\n**Required Skills:**")
                for item in reqs["required_skills"]:
                    lines.append(f"- {item}")
            if reqs.get("common_responsibilities"):
                lines.append("\n**Common Responsibilities:**")
                for item in reqs["common_responsibilities"]:
                    lines.append(f"- {item}")
            lines.append("")
    else:
        lines.append("*No role-specific insights generated.*")
        lines.append("")

    # ── Section 4: Required vs Preferred Skills ──
    lines.append("## 4. Required vs Preferred Skills")
    lines.append("")
    if ai_market_summary.get("required_vs_preferred_patterns"):
        for pattern in ai_market_summary["required_vs_preferred_patterns"]:
            lines.append(f"- {pattern}")
    else:
        lines.append("*No required vs preferred pattern insights generated.*")
    lines.append("")

    # ── Section 5: Cross-Role Skill Patterns ──
    lines.append("## 5. Cross-Role Skill Patterns")
    lines.append("")
    if ai_market_summary.get("cross_role_skill_patterns"):
        for pattern in ai_market_summary["cross_role_skill_patterns"]:
            lines.append(f"- {pattern}")
    else:
        lines.append("*No cross-role patterns generated.*")
    lines.append("")

    # ── Section 6: What This Means for Me ──
    lines.append("## 6. What This Means for Me")
    lines.append("")
    if ai_market_summary:
        if ai_market_summary.get("resume_recommendations"):
            lines.append("### Resume Recommendations")
            for rec in ai_market_summary["resume_recommendations"]:
                lines.append(f"- {rec}")
            lines.append("")
        if ai_market_summary.get("portfolio_recommendations"):
            lines.append("### Portfolio Recommendations")
            for rec in ai_market_summary["portfolio_recommendations"]:
                lines.append(f"- {rec}")
            lines.append("")
        if ai_market_summary.get("linkedin_recommendations"):
            lines.append("### LinkedIn Recommendations")
            for rec in ai_market_summary["linkedin_recommendations"]:
                lines.append(f"- {rec}")
            lines.append("")
        if ai_market_summary.get("skills_to_learn"):
            lines.append("### Skills to Learn")
            for rec in ai_market_summary["skills_to_learn"]:
                lines.append(f"- {rec}")
            lines.append("")

    # ── Section 7: Changes Since the Previous Run ──
    lines.append("## 7. Changes Since the Previous Run")
    lines.append("")
    
    # Honest trends
    computed_trends = run_stats.get("computed_trends", {})
    if computed_trends.get("insufficient_data"):
        lines.append(f"*{computed_trends.get('message', 'Insufficient data for deterministic trends')}*")
        lines.append("")
    elif computed_trends.get("trends"):
        lines.append("### Deterministic Skill Shifts")
        for trend in computed_trends["trends"][:5]:
            lines.append(f"- **{trend['skill'].title()}**: Grew by {trend['percentage_point_change']}% (from {trend['previous_percent']}% to {trend['current_percent']}%)")
        lines.append("")

    if ai_market_summary.get("changes_since_previous_run"):
        lines.append("### AI Identified Changes")
        for change in ai_market_summary["changes_since_previous_run"]:
            lines.append(f"- {change}")
        lines.append("")

    # ── Section 8: Current Job Details ──
    lines.append("## 8. Current Job Details")
    lines.append("")
    
    if new_jobs:
        lines.append("### New Opportunities")
        for job in new_jobs:
            identity = job.get("_stable_identity", "")
            ai_result = ai_job_analyses.get(identity)
            lines.append(_format_ai_job_card(job, ai_result))
            
    if updated_jobs:
        lines.append("### Materially Updated Jobs")
        for job in updated_jobs:
            identity = job.get("_stable_identity", "")
            change_result = ai_update_analyses.get(identity)
            lines.append(_format_updated_job_card(job, change_result))
            
    if include_previously_seen and unchanged_jobs:
        lines.append("### Active Previously Seen Jobs")
        lines.append("<details><summary>Click to view unchanged active jobs</summary>")
        lines.append("")
        for job in unchanged_jobs:
            identity = job.get("_stable_identity", "")
            ai_result = ai_job_analyses.get(identity)
            if ai_result:
                lines.append(_format_ai_job_card(job, ai_result))
            else:
                title = job.get("title", "Unknown")
                company = job.get("company", "Unknown")
                url = job.get("url", "#")
                lines.append(f"- **[{title} @ {company}]({url})**")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)
