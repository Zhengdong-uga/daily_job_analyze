"""
Job Description Analyzer for the Daily Job Watch MVP.

Provides rule-based intelligence and market trend analysis by extracting
requirements, skills, and clustering jobs from unstructured descriptions.
"""

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from utils.watch_config import JobWatchConfig


def normalize_description_text(text: Optional[str]) -> str:
    """Clean markdown, artifacts, and whitespace from descriptions."""
    if not text:
        return ""
    
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'[*_]{1,3}', '', text)
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def extract_keyword_counts(jobs: List[Dict[str, Any]], keyword_groups: Optional[Dict[str, List[str]]] = None) -> Dict[str, Dict[str, Any]]:
    """Group and count keywords, keeping track of example jobs."""
    if not keyword_groups:
        return {}
        
    results = {}
    for group_name, keywords in keyword_groups.items():
        results[group_name] = {}
        for kw in keywords:
            results[group_name][kw] = {"count": 0, "jobs": []}
            
    for job in jobs:
        title = job.get("title", "")
        desc = normalize_description_text(job.get("description", ""))
        text = f"{title} {desc}".lower()
        
        for group_name, keywords in keyword_groups.items():
            for kw in keywords:
                # Add word boundaries to avoid partial matches
                if re.search(rf'\b{re.escape(kw.lower())}\b', text):
                    results[group_name][kw]["count"] += 1
                    if len(results[group_name][kw]["jobs"]) < 3:
                        results[group_name][kw]["jobs"].append(job)
                        
    filtered_results = {}
    for group, items in results.items():
        filtered_items = {k: v for k, v in items.items() if v["count"] > 0}
        if filtered_items:
            filtered_results[group] = dict(sorted(filtered_items.items(), key=lambda x: x[1]["count"], reverse=True))
            
    return filtered_results


def extract_job_requirements(job: Dict[str, Any], keyword_groups: Optional[Dict[str, List[str]]] = None) -> Dict[str, List[str]]:
    """Lightweight rule-based extraction of skills and responsibilities."""
    desc = normalize_description_text(job.get("description", ""))
    
    requirements = {
        "responsibilities": [],
        "hard_skills": [],
        "soft_skills": [],
        "all_skills": []
    }
    
    # Heuristic: Find sentences/bullets that sound like actions
    # Look for bullet points starting with verbs
    action_verbs = r"(?:design|build|develop|collaborate|lead|partner|drive|create|deliver|implement|ship|architect)"
    resp_matches = re.findall(rf'(?:[•\-*]|^)\s*({action_verbs}[^\.\n]{{20,150}})[\.\n]?', job.get("description", ""), re.IGNORECASE | re.MULTILINE)
    
    # Clean the matches
    cleaned_resps = []
    for r in resp_matches:
        cleaned = normalize_description_text(r).strip()
        if len(cleaned) > 20 and len(cleaned) < 200:
            cleaned_resps.append(cleaned)
            
    requirements["responsibilities"] = list(set(cleaned_resps))[:5]
    
    # Extract skills using the provided keyword groups if available
    text_lower = desc.lower()
    
    if keyword_groups:
        for group, keywords in keyword_groups.items():
            for kw in keywords:
                if re.search(rf'\b{re.escape(kw.lower())}\b', text_lower):
                    requirements["all_skills"].append(kw)
                    if group in ["product_execution", "collaboration", "customer_deployment"]:
                        requirements["soft_skills"].append(kw)
                    else:
                        requirements["hard_skills"].append(kw)
    else:
        # Fallback if no config
        if re.search(r'\b(react|vue|angular|typescript|javascript)\b', text_lower):
            requirements["hard_skills"].append("React/TypeScript")
        if re.search(r'\b(machine learning|llm|generative ai|pytorch|agents|rag)\b', text_lower):
            requirements["hard_skills"].append("LLMs/GenAI")
        if re.search(r'\b(figma|prototype|design system)\b', text_lower):
            requirements["hard_skills"].append("Figma/Prototyping")
        if re.search(r'\b(cross-functional|stakeholder|customer-facing)\b', text_lower):
            requirements["soft_skills"].append("Cross-functional Collaboration")
            
    requirements["hard_skills"] = list(set(requirements["hard_skills"]))
    requirements["soft_skills"] = list(set(requirements["soft_skills"]))
    requirements["all_skills"] = list(set(requirements["all_skills"]))
        
    return requirements


def summarize_job_description(job: Dict[str, Any], keyword_groups: Optional[Dict[str, List[str]]] = None, max_chars: int = 400) -> str:
    """Create a concise summary utilizing extracted signals rather than raw text."""
    title = job.get("title", "")
    company = job.get("company", "")
    desc = normalize_description_text(job.get("description", ""))
    
    match = re.search(r'([A-Z].{50,250}?[\.])', desc)
    context = match.group(1) if match else "No context available."
    
    reqs = extract_job_requirements(job, keyword_groups)
    
    summary_lines = [f"> {context}", ""]
    
    if reqs["responsibilities"]:
        summary_lines.append("**Key Responsibilities:**")
        for r in reqs["responsibilities"][:2]:
            summary_lines.append(f"- {r}")
        summary_lines.append("")
        
    if reqs["all_skills"]:
        summary_lines.append(f"**Key Skills Expected:** {', '.join(reqs['all_skills'][:6])}")
        
    return "\n".join(summary_lines)


def group_jobs_by_skill_cluster(jobs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Assign jobs to clusters based on title and description signals."""
    clusters = {
        "AI / ML Engineering": [],
        "Forward Deployed / Customer-Facing Engineering": [],
        "Product Design / UX": [],
        "UX Engineering / Design Engineering": [],
        "Frontend Engineering": [],
        "Data / Research / Evaluation": [],
        "Infrastructure / Platform Engineering": [],
        "Product / Strategy / PM": [],
        "Other Relevant Roles": []
    }
    
    for job in jobs:
        title = job.get("title", "").lower()
        desc = job.get("description", "").lower()
        
        assigned = False
        if "forward deployed" in title or "solutions" in title or "customer" in title or "integration" in title:
            clusters["Forward Deployed / Customer-Facing Engineering"].append(job)
            assigned = True
        elif "product manager" in title or "pm" in title.split():
            clusters["Product / Strategy / PM"].append(job)
            assigned = True
        elif "design engineer" in title or "ux engineer" in title or "creative technologist" in title:
            clusters["UX Engineering / Design Engineering"].append(job)
            assigned = True
        elif "designer" in title or "product design" in title or "ux" in title:
            clusters["Product Design / UX"].append(job)
            assigned = True
        elif "frontend" in title or "front-end" in title or "react" in title or "full stack" in title or "full-stack" in title:
            clusters["Frontend Engineering"].append(job)
            assigned = True
        elif "machine learning" in title or "ml " in title or "ai engineer" in title or "generative ai" in title or "applied ai" in title:
            clusters["AI / ML Engineering"].append(job)
            assigned = True
        elif "data" in title or "evaluation" in title or "research" in title:
            clusters["Data / Research / Evaluation"].append(job)
            assigned = True
        elif "platform" in title or "infrastructure" in title or "backend" in title or "compute" in title:
            clusters["Infrastructure / Platform Engineering"].append(job)
            assigned = True
            
        if not assigned:
            if "forward deployed" in desc and "customer" in desc:
                clusters["Forward Deployed / Customer-Facing Engineering"].append(job)
            elif "frontend" in desc and "react" in desc:
                clusters["Frontend Engineering"].append(job)
            else:
                clusters["Other Relevant Roles"].append(job)
                
    return {k: v for k, v in clusters.items() if v}


def build_market_trend_summary(jobs: List[Dict[str, Any]], keyword_groups: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """Synthesize market trends from rule-based patterns and generate seeker advice."""
    trends = []
    
    # 1. Hybrid Roles
    hybrid_count = sum(1 for j in jobs if "design" in j.get("description", "").lower() and ("engineer" in j.get("description", "").lower() or "develop" in j.get("description", "").lower()))
    if hybrid_count > len(jobs) * 0.1:
        trends.append({
            "title": "Hybrid Roles on the Rise",
            "explanation": "Many roles are blurring the lines between design and engineering, expecting candidates to navigate both spaces.",
            "evidence": [f"{hybrid_count} jobs mention both 'design' and 'engineering'/'development'."],
            "examples": jobs[:2]
        })
        
    # 2. AI across disciplines
    ai_count = sum(1 for j in jobs if "ai" in j.get("description", "").lower() or "llm" in j.get("description", "").lower())
    if ai_count > len(jobs) * 0.2:
        trends.append({
            "title": "AI Product Experience is Becoming Cross-Functional",
            "explanation": "AI is no longer just for ML engineers. Product surfaces, UX, and frontend roles are increasingly asking for AI capability and prototyping experience.",
            "evidence": [f"{ai_count} jobs explicitly require AI/LLM context across different disciplines."],
            "examples": jobs[1:3] if len(jobs) > 2 else jobs[:1]
        })
        
    # 3. Fast Prototyping
    proto_count = sum(1 for j in jobs if "prototype" in j.get("description", "").lower() or "prototyping" in j.get("description", "").lower())
    if proto_count > len(jobs) * 0.1:
        trends.append({
            "title": "Emphasis on Rapid Prototyping",
            "explanation": "Speed to validation is highly valued. Companies are explicitly looking for individuals who can translate ambiguous problems into prototypes quickly.",
            "evidence": [f"{proto_count} jobs emphasize prototyping and fast iteration."],
            "examples": jobs[2:4] if len(jobs) > 4 else jobs[:1]
        })

    meaning_for_me = [
        "**Bridge the gap:** Emphasize your ability to work across engineering, design, and AI models rather than staying in a single silo.",
        "**Show, don't tell:** The demand for prototyping means your portfolio should highlight speed-to-value and functional proof-of-concepts.",
        "**Understand the LLM layer:** Even if you aren't training models, highlighting how you consume AI APIs and handle LLM UX challenges is a strong differentiator."
    ]

    return {
        "top_trends": [t["title"] for t in trends],
        "detailed_trends": trends,
        "what_this_means": meaning_for_me
    }


def get_top_skills_overall(jobs: List[Dict[str, Any]], keyword_groups: Optional[Dict[str, List[str]]] = None) -> List[tuple]:
    """Calculate the top 10 skills overall."""
    all_skills = []
    for job in jobs:
        reqs = extract_job_requirements(job, keyword_groups)
        all_skills.extend(reqs["all_skills"])
        
    counts = Counter(all_skills)
    return counts.most_common(10)


def build_role_to_skill_matrix(jobs: List[Dict[str, Any]], keyword_groups: Optional[Dict[str, List[str]]] = None) -> Dict[str, Dict[str, List[str]]]:
    """Generate a matrix of top skills for each role cluster."""
    clusters = group_jobs_by_skill_cluster(jobs)
    matrix = {}
    
    if not keyword_groups:
        return matrix
        
    for cluster_name, cluster_jobs in clusters.items():
        if not cluster_jobs:
            continue
            
        cluster_skills = defaultdict(list)
        for job in cluster_jobs:
            desc_lower = normalize_description_text(job.get("description", "")).lower()
            for group, keywords in keyword_groups.items():
                for kw in keywords:
                    if re.search(rf'\b{re.escape(kw.lower())}\b', desc_lower):
                        cluster_skills[group].append(kw)
                        
        # Get top 3 per group for this cluster
        matrix[cluster_name] = {}
        for group in keyword_groups.keys():
            top = [k for k, v in Counter(cluster_skills[group]).most_common(3)]
            matrix[cluster_name][group] = top
            
    return matrix


def build_skill_gap_summary(jobs: List[Dict[str, Any]], keyword_groups: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """Group skills into must-haves, recommendations, and role-specific blocks."""
    summary = {
        "resume_keywords": [
            "AI-powered user experiences",
            "End-to-end prototyping",
            "Cross-functional collaboration with product/design",
            "LLM API integration and prompt engineering"
        ],
        "portfolio_angles": [
            "Highlight a time you moved from ambiguous concept to functional AI prototype.",
            "Showcase how you designed or built a user interface that gracefully handles AI latency or errors.",
            "Demonstrate a project where you collaborated directly with users or customers to iterate on a solution."
        ],
        "linkedin_keywords": [
            "AI Product Engineer",
            "UX/UI Developer | GenAI",
            "Prototyping & AI Workflows",
            "Frontend + AI Integrations"
        ],
        "skills_to_learn": [
            "Advanced Prompt Engineering / DSPy",
            "RAG pipelines (Retrieval-Augmented Generation)",
            "Model Evaluation / A/B Testing for AI"
        ],
        "role_specific_data": defaultdict(dict),
        "repeated_responsibilities": []
    }
    
    clusters = group_jobs_by_skill_cluster(jobs)
    all_resps = []
    
    for cluster_name, cluster_jobs in clusters.items():
        if not cluster_jobs:
            continue
            
        companies_hiring = [j.get("company", "") for j in cluster_jobs if j.get("company")]
        top_companies = [c for c, _ in Counter(companies_hiring).most_common(3)]
        
        cluster_hard_skills = []
        cluster_soft_skills = []
        cluster_resps = []
        
        for job in cluster_jobs:
            reqs = extract_job_requirements(job, keyword_groups)
            cluster_hard_skills.extend(reqs["hard_skills"])
            cluster_soft_skills.extend(reqs["soft_skills"])
            cluster_resps.extend(reqs["responsibilities"])
            all_resps.extend(reqs["responsibilities"])
            
        summary["role_specific_data"][cluster_name] = {
            "companies_hiring": top_companies,
            "hard_skills": [k for k, _ in Counter(cluster_hard_skills).most_common(5)],
            "soft_skills": [k for k, _ in Counter(cluster_soft_skills).most_common(5)],
            "phrases": [k for k, _ in Counter(cluster_resps).most_common(4)],
            "example_jobs": cluster_jobs[:3]
        }
        
    # Find overall repeated responsibilities across all jobs (fuzzy matching or exact string)
    top_resps = [k for k, v in Counter(all_resps).most_common(8) if v > 1]
    if not top_resps:
        # Fallback if no exact dupes
        top_resps = list(set(all_resps))[:5]
        
    summary["repeated_responsibilities"] = top_resps
        
    return summary

