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
