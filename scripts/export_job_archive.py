#!/usr/bin/env python3
"""
Generates a standalone, searchable HTML archive of all historical jobs.
"""
import argparse
import json
import logging
import os
import sqlite3
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

# Add project root to path so we can import utils
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "mcp-server-python"))

from utils.watch_config import load_config
from utils.path_resolution import resolve_repo_relative_path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Archive</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 20px; background-color: #f9f9f9; }}
        h1 {{ color: #2c3e50; text-align: center; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .controls {{ display: flex; flex-wrap: wrap; gap: 15px; margin-bottom: 20px; background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        input[type="text"], select {{ padding: 8px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; flex: 1; min-width: 200px; }}
        .job-count {{ font-weight: bold; margin-bottom: 15px; color: #666; }}
        
        .job-card {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border-left: 4px solid #3498db; }}
        .job-card h3 {{ margin: 0 0 10px 0; color: #2c3e50; }}
        .job-card h3 a {{ color: #2980b9; text-decoration: none; }}
        .job-card h3 a:hover {{ text-decoration: underline; }}
        .meta {{ font-size: 13px; color: #7f8c8d; margin-bottom: 10px; display: flex; gap: 15px; flex-wrap: wrap; }}
        .badges {{ margin-bottom: 10px; }}
        .badge {{ display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; background-color: #ecf0f1; color: #34495e; margin-right: 5px; margin-bottom: 5px; }}
        .badge.skill {{ background-color: #e8f4f8; color: #2980b9; border: 1px solid #bce0fd; }}
        
        details {{ margin-top: 15px; background: #fdfdfd; padding: 10px; border: 1px solid #eee; border-radius: 4px; }}
        summary {{ font-weight: bold; cursor: pointer; color: #34495e; outline: none; }}
        .jd-content {{ font-size: 14px; white-space: pre-wrap; margin-top: 10px; background: #fff; padding: 15px; border: 1px solid #ddd; border-radius: 4px; max-height: 400px; overflow-y: auto; }}
        .hidden {{ display: none !important; }}
        .status-badge {{ float: right; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; background: #eee; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Historical Job Archive</h1>
        
        <div class="controls">
            <input type="text" id="searchInput" placeholder="Search title, company, location, or skill..." value="{initial_query}">
            <select id="sortSelect">
                <option value="captured_desc">Captured (Newest First)</option>
                <option value="captured_asc">Captured (Oldest First)</option>
                <option value="company_asc">Company (A-Z)</option>
                <option value="title_asc">Title (A-Z)</option>
            </select>
            <select id="statusFilter">
                <option value="all">All Jobs</option>
                <option value="recent">Seen Recently (Last 7 Days)</option>
                <option value="old">Older Jobs</option>
            </select>
        </div>
        
        <div class="job-count" id="jobCount">Loading jobs...</div>
        <div id="jobList"></div>
    </div>

    <!-- Inject job data safely via JSON -->
    <script id="jobData" type="application/json">
        {job_json_data}
    </script>

    <script>
        function showInitializationError(error) {{
            console.error("Failed to initialize archive:", error);

            const container = document.getElementById("jobList");
            if (container) {{
                container.replaceChildren();
                const message = document.createElement("p");
                message.textContent = "The job archive could not be loaded. Open the browser console for details.";
                container.appendChild(message);
            }}
            
            const count = document.getElementById("jobCount");
            if (count) count.textContent = "Error loading jobs.";
        }}

        function initializeArchive(jobs) {{
            const searchInput = document.getElementById('searchInput');
            const sortSelect = document.getElementById('sortSelect');
            const statusFilter = document.getElementById('statusFilter');
            const jobList = document.getElementById('jobList');
            const jobCount = document.getElementById('jobCount');
        
        function formatDate(dateStr) {{
            if (!dateStr) return "Unknown";
            const d = new Date(dateStr);
            if (isNaN(d)) return dateStr;
            return d.toLocaleDateString() + " " + d.toLocaleTimeString([], {{hour: '2-digit', minute:'2-digit'}});
        }}
        
        function isValidUrl(url) {{
            if (!url) return false;
            try {{
                const parsed = new URL(url);
                return parsed.protocol === 'http:' || parsed.protocol === 'https:';
            }} catch(e) {{
                return false;
            }}
        }}
        
        function renderJobs(filteredJobs) {{
            jobList.innerHTML = '';
            jobCount.textContent = `Showing ${{filteredJobs.length}} of ${{jobs.length}} jobs`;
            
            const fragment = document.createDocumentFragment();
            
            filteredJobs.forEach(job => {{
                const card = document.createElement('div');
                card.className = 'job-card';
                
                const statusBadge = document.createElement('span');
                statusBadge.className = 'status-badge';
                statusBadge.textContent = job.status || 'Archived';
                card.appendChild(statusBadge);
                
                const h3 = document.createElement('h3');
                if (isValidUrl(job.url)) {{
                    const link = document.createElement('a');
                    link.href = job.url;
                    link.target = "_blank";
                    link.rel = "noopener noreferrer";
                    link.textContent = job.title;
                    h3.appendChild(link);
                }} else {{
                    h3.textContent = job.title || 'Unknown Title';
                }}
                const companySpan = document.createElement('span');
                companySpan.textContent = ` @ ${{job.company}}`;
                h3.appendChild(companySpan);
                card.appendChild(h3);
                
                const meta = document.createElement('div');
                meta.className = 'meta';
                
                const locSpan = document.createElement('span');
                locSpan.textContent = `📍 ${{job.location || 'Unknown'}}`;
                meta.appendChild(locSpan);
                
                const capturedSpan = document.createElement('span');
                capturedSpan.textContent = `🗓️ Captured: ${{formatDate(job.captured_at || job.created_at)}}`;
                meta.appendChild(capturedSpan);
                
                if (job.source) {{
                    const sourceSpan = document.createElement('span');
                    sourceSpan.textContent = `📌 Source: ${{job.source}}`;
                    meta.appendChild(sourceSpan);
                }}
                
                card.appendChild(meta);
                

                const details = document.createElement('details');
                const summary = document.createElement('summary');
                summary.textContent = 'View Description';
                details.appendChild(summary);
                
                const jdContent = document.createElement('div');
                jdContent.className = 'jd-content';
                jdContent.textContent = job.description || 'No description available.';
                details.appendChild(jdContent);
                
                card.appendChild(details);
                fragment.appendChild(card);
            }});
            
            jobList.appendChild(fragment);
        }}
        
        function applyFilters() {{
            const query = searchInput.value.toLowerCase();
            const sort = sortSelect.value;
            const status = statusFilter.value;
            
            const now = new Date();
            const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
            
            let filtered = jobs.filter(job => {{
                const textToSearch = [
                    job.title, 
                    job.company, 
                    job.location, 
                    job.source,
                    job.description
                ].join(' ').toLowerCase();
                
                if (query && !textToSearch.includes(query)) return false;
                
                if (status === 'recent') {{
                    const captured = new Date(job.captured_at || job.created_at);
                    if (isNaN(captured) || captured < sevenDaysAgo) return false;
                }} else if (status === 'old') {{
                    const captured = new Date(job.captured_at || job.created_at);
                    if (!isNaN(captured) && captured >= sevenDaysAgo) return false;
                }}
                
                return true;
            }});
            
            filtered.sort((a, b) => {{
                const getCaptured = (job) => new Date(job.captured_at || job.created_at || 0);
                if (sort === 'captured_desc') return getCaptured(b) - getCaptured(a);
                if (sort === 'captured_asc') return getCaptured(a) - getCaptured(b);
                if (sort === 'company_asc') return (a.company || '').localeCompare(b.company || '');
                if (sort === 'title_asc') return (a.title || '').localeCompare(b.title || '');
                return 0;
            }});
            
            renderJobs(filtered);
        }}
        
        searchInput.addEventListener('input', applyFilters);
        sortSelect.addEventListener('change', applyFilters);
        statusFilter.addEventListener('change', applyFilters);
        
        applyFilters();
        }}

        try {{
            const rawData = document.getElementById("jobData").textContent;
            const jobs = JSON.parse(rawData);

            if (!Array.isArray(jobs)) {{
                throw new TypeError("Embedded job data is not an array.");
            }}

            initializeArchive(jobs);
        }} catch (error) {{
            showInitializationError(error);
        }}
    </script>
</body>
</html>
"""

def generate_archive(db_path: Path, output_path: Path, initial_query: str = ""):
    """Fetch all jobs from the SQLite database and generate the HTML archive."""
    if not db_path.exists():
        logging.error(f"Database not found at {db_path}")
        sys.exit(1)
        
    logging.info(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                id,
                job_id,
                title,
                company,
                description,
                url,
                location,
                source,
                status,
                captured_at,
                created_at,
                updated_at,
                run_id
            FROM jobs
            ORDER BY COALESCE(captured_at, created_at) DESC;
        """)
        rows = cursor.fetchall()
        
        jobs = [dict(r) for r in rows]
        logging.info(f"Extracted {len(jobs)} jobs from database.")
        
    except Exception as e:
        logging.error(f"Failed to extract jobs: {e}")
        sys.exit(1)
    finally:
        conn.close()
        
    # Serialize securely
    # Replace `<` with `\\u003c` so that `</script>` or malicious script tags cannot break out of the JSON block
    job_json = json.dumps(jobs).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\\u2028", "\\u2028").replace("\\u2029", "\\u2029")
    
    html = HTML_TEMPLATE.format(
        job_json_data=job_json,
        initial_query=initial_query.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
    )
    

    # JS Syntax Validation
    import tempfile
    import subprocess
    import shutil
    
    js_content = ""
    in_script = False
    for line in html.split('\n'):
        if '<script>' in line:
            in_script = True
            continue
        elif '</script>' in line and in_script:
            in_script = False
            break
        if in_script:
            js_content += line + '\n'
            
    if shutil.which("node"):
        with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
            f.write(js_content)
            tmp_path = f.name
        try:
            result = subprocess.run(["node", "--check", tmp_path], capture_output=True, text=True)
            if result.returncode != 0:
                logging.error(f"JavaScript syntax validation failed!\n{result.stderr}")
                sys.exit(1)
        finally:
            os.remove(tmp_path)
    else:
        logging.warning("Node.js not found, skipping JS syntax validation.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(html, encoding="utf-8")
    file_size = output_path.stat().st_size
    logging.info(f"Archive successfully generated at: {output_path} (Size: {file_size} bytes)")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate a searchable HTML job archive.")
    parser.add_argument("--config", type=str, default="job_watch_config.yaml", help="Path to config file")
    parser.add_argument("--query", type=str, default="", help="Initial search query")
    parser.add_argument("--open", action="store_true", help="Open the archive in the default web browser")
    
    args = parser.parse_args()
    
    # Load config mainly to respect potential path overrides if any
    config_path = resolve_repo_relative_path(args.config)
    if not config_path.exists():
        logging.warning(f"Config file {config_path} not found. Proceeding with defaults.")
        
    db_path = os.environ.get("JOBWORKFLOW_DB")
    if db_path:
        db_path = resolve_repo_relative_path(db_path)
    else:
        db_path = resolve_repo_relative_path("data/capture/jobs.db")
        
    output_path = resolve_repo_relative_path("reports/archive/job-archive.html")
    
    generated_file = generate_archive(db_path, output_path, args.query)
    
    if args.open:
        logging.info("Opening archive in browser...")
        webbrowser.open(f"file://{generated_file.absolute()}")


if __name__ == "__main__":
    main()
