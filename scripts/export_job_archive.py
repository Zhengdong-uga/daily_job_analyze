#!/usr/bin/env python3
"""
Generates a searchable HTML archive of all historical jobs and serves it locally with delete capabilities.
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
import http.server
import socketserver
import urllib.parse

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
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 20px; background-color: #f9f9f9; }
        h1 { color: #2c3e50; text-align: center; }
        .container { max-width: 1200px; margin: 0 auto; }
        .controls { display: flex; flex-wrap: wrap; gap: 15px; margin-bottom: 20px; background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        input[type="text"], select { padding: 8px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; flex: 1; min-width: 200px; }
        .job-count { font-weight: bold; margin-bottom: 15px; color: #666; }
        
        .job-card { background: white; border-radius: 8px; padding: 20px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border-left: 4px solid #3498db; position: relative; }
        .job-card h3 { margin: 0 0 10px 0; color: #2c3e50; padding-right: 80px; }
        .job-card h3 a { color: #2980b9; text-decoration: none; }
        .job-card h3 a:hover { text-decoration: underline; }
        .meta { font-size: 13px; color: #7f8c8d; margin-bottom: 10px; display: flex; gap: 15px; flex-wrap: wrap; }
        
        details { margin-top: 15px; background: #fdfdfd; padding: 10px; border: 1px solid #eee; border-radius: 4px; }
        summary { font-weight: bold; cursor: pointer; color: #34495e; outline: none; }
        .jd-content { font-size: 14px; white-space: pre-wrap; margin-top: 10px; background: #fff; padding: 15px; border: 1px solid #ddd; border-radius: 4px; max-height: 400px; overflow-y: auto; }
        .status-badge { float: right; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; background: #eee; margin-left: 10px; }
        
        .delete-btn { position: absolute; top: 20px; right: 20px; background-color: #e74c3c; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: bold; transition: background 0.2s; }
        .delete-btn:hover { background-color: #c0392b; }
        .delete-btn:disabled { background-color: #95a5a6; cursor: not-allowed; }
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

    <script id="jobData" type="application/json">
        {job_json_data}
    </script>

    <script>
        function showInitializationError(error) {
            console.error("Failed to initialize archive:", error);
            const container = document.getElementById("jobList");
            if (container) {
                container.replaceChildren();
                const message = document.createElement("p");
                message.textContent = "The job archive could not be loaded. Open the browser console for details.";
                container.appendChild(message);
            }
            const count = document.getElementById("jobCount");
            if (count) count.textContent = "Error loading jobs.";
        }

        function initializeArchive(jobs) {
            const searchInput = document.getElementById('searchInput');
            const sortSelect = document.getElementById('sortSelect');
            const statusFilter = document.getElementById('statusFilter');
            const jobList = document.getElementById('jobList');
            const jobCount = document.getElementById('jobCount');
        
            function formatDate(dateStr) {
                if (!dateStr) return "Unknown";
                const d = new Date(dateStr);
                if (isNaN(d)) return dateStr;
                return d.toLocaleDateString() + " " + d.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
            }
            
            function isValidUrl(url) {
                if (!url) return false;
                try {
                    const parsed = new URL(url);
                    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
                } catch(e) {
                    return false;
                }
            }
            
            window.deleteJob = async function(jobId, buttonElement) {
                if (!confirm('Are you sure you want to delete this job? This cannot be undone.')) return;
                
                buttonElement.disabled = true;
                buttonElement.textContent = 'Deleting...';
                
                try {
                    const response = await fetch('/delete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ job_id: jobId })
                    });
                    
                    if (response.ok) {
                        jobs = jobs.filter(j => j.job_id !== jobId);
                        applyFilters();
                    } else {
                        alert('Failed to delete job.');
                        buttonElement.disabled = false;
                        buttonElement.textContent = 'Delete';
                    }
                } catch (error) {
                    console.error('Error deleting job:', error);
                    alert('Error deleting job.');
                    buttonElement.disabled = false;
                    buttonElement.textContent = 'Delete';
                }
            };

            function renderJobs(filteredJobs) {
                jobList.innerHTML = '';
                jobCount.textContent = `Showing ${filteredJobs.length} of ${jobs.length} jobs`;
                
                const fragment = document.createDocumentFragment();
                
                filteredJobs.forEach(job => {
                    const card = document.createElement('div');
                    card.className = 'job-card';
                    
                    const deleteBtn = document.createElement('button');
                    deleteBtn.className = 'delete-btn';
                    deleteBtn.textContent = 'Delete';
                    deleteBtn.onclick = function() { window.deleteJob(job.job_id, this); };
                    card.appendChild(deleteBtn);
                    
                    const statusBadge = document.createElement('span');
                    statusBadge.className = 'status-badge';
                    statusBadge.textContent = job.status || 'Archived';
                    card.appendChild(statusBadge);
                    
                    const h3 = document.createElement('h3');
                    if (isValidUrl(job.url)) {
                        const link = document.createElement('a');
                        link.href = job.url;
                        link.target = "_blank";
                        link.rel = "noopener noreferrer";
                        link.textContent = job.title;
                        h3.appendChild(link);
                    } else {
                        h3.textContent = job.title || 'Unknown Title';
                    }
                    const companySpan = document.createElement('span');
                    companySpan.textContent = ` @ ${job.company}`;
                    h3.appendChild(companySpan);
                    card.appendChild(h3);
                    
                    const meta = document.createElement('div');
                    meta.className = 'meta';
                    
                    const locSpan = document.createElement('span');
                    locSpan.textContent = `📍 ${job.location || 'Unknown'}`;
                    meta.appendChild(locSpan);
                    
                    const capturedSpan = document.createElement('span');
                    capturedSpan.textContent = `🗓️ Captured: ${formatDate(job.captured_at || job.created_at)}`;
                    meta.appendChild(capturedSpan);
                    
                    if (job.source) {
                        const sourceSpan = document.createElement('span');
                        sourceSpan.textContent = `📌 Source: ${job.source}`;
                        meta.appendChild(sourceSpan);
                    }
                    
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
                });
                
                jobList.appendChild(fragment);
            }
            
            function applyFilters() {
                const query = searchInput.value.toLowerCase();
                const sort = sortSelect.value;
                const status = statusFilter.value;
                
                const now = new Date();
                const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
                
                let filtered = jobs.filter(job => {
                    const textToSearch = [
                        job.title, 
                        job.company, 
                        job.location, 
                        job.source,
                        job.description
                    ].join(' ').toLowerCase();
                    
                    if (query && !textToSearch.includes(query)) return false;
                    
                    if (status === 'recent') {
                        const captured = new Date(job.captured_at || job.created_at);
                        if (isNaN(captured) || captured < sevenDaysAgo) return false;
                    } else if (status === 'old') {
                        const captured = new Date(job.captured_at || job.created_at);
                        if (!isNaN(captured) && captured >= sevenDaysAgo) return false;
                    }
                    
                    return true;
                });
                
                filtered.sort((a, b) => {
                    const getCaptured = (job) => new Date(job.captured_at || job.created_at || 0);
                    if (sort === 'captured_desc') return getCaptured(b) - getCaptured(a);
                    if (sort === 'captured_asc') return getCaptured(a) - getCaptured(b);
                    if (sort === 'company_asc') return (a.company || '').localeCompare(b.company || '');
                    if (sort === 'title_asc') return (a.title || '').localeCompare(b.title || '');
                    return 0;
                });
                
                renderJobs(filtered);
            }
            
            searchInput.addEventListener('input', applyFilters);
            sortSelect.addEventListener('change', applyFilters);
            statusFilter.addEventListener('change', applyFilters);
            
            applyFilters();
        }

        try {
            const rawData = document.getElementById("jobData").textContent;
            const jobs = JSON.parse(rawData);

            if (!Array.isArray(jobs)) {
                throw new TypeError("Embedded job data is not an array.");
            }

            initializeArchive(jobs);
        } catch (error) {
            showInitializationError(error);
        }
    </script>
</body>
</html>
"""

def get_job_data(db_path: Path):
    if not db_path.exists():
        logging.error(f"Database not found at {db_path}")
        return []
        
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                id, job_id, title, company, description, url, location,
                source, status, captured_at, created_at, updated_at, run_id
            FROM jobs
            ORDER BY COALESCE(captured_at, created_at) DESC;
        """)
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logging.error(f"Failed to extract jobs: {e}")
        return []
    finally:
        conn.close()

def delete_job_from_db(db_path: Path, job_id: str) -> bool:
    if not db_path.exists(): return False
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"Failed to delete job {job_id}: {e}")
        return False
    finally:
        conn.close()

def run_server(db_path: Path, port: int, initial_query: str = "", no_browser: bool = False):
    class ArchiveHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            parsed_path = urllib.parse.urlparse(self.path)
            if parsed_path.path in ('/', '/index.html'):
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                
                jobs = get_job_data(db_path)
                job_json = json.dumps(jobs).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\\u2028", "\\u2028").replace("\\u2029", "\\u2029")
                
                html = HTML_TEMPLATE.replace(
                    "{job_json_data}", job_json
                ).replace(
                    "{initial_query}", initial_query.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
                )
                self.wfile.write(html.encode("utf-8"))
            else:
                super().do_GET()

        def do_POST(self):
            if self.path == '/delete':
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                try:
                    data = json.loads(post_data.decode('utf-8'))
                    job_id = data.get('job_id')
                    if job_id and delete_job_from_db(db_path, job_id):
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
                        logging.info(f"Deleted job_id: {job_id}")
                        return
                except Exception as e:
                    logging.error(f"Error processing delete request: {e}")
                    
                self.send_response(400)
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    import socket
    while port < 65535:
        try:
            with ReusableTCPServer(("127.0.0.1", port), ArchiveHandler) as httpd:
                logging.info(f"Serving job archive on http://127.0.0.1:{port}")
                logging.info("Press Ctrl+C to stop the server.")
                if not no_browser:
                    try:
                        webbrowser.open(f"http://127.0.0.1:{port}")
                    except:
                        pass
                try:
                    httpd.serve_forever()
                except KeyboardInterrupt:
                    logging.info("Shutting down server...")
                break
        except OSError as e:
            if e.errno in (48, 98):
                logging.warning(f"Port {port} is in use, trying {port+1}...")
                port += 1
            else:
                raise

def main():
    parser = argparse.ArgumentParser(description="Serve a searchable HTML job archive with delete capabilities.")
    parser.add_argument("--config", type=str, default="job_watch_config.yaml", help="Path to config file")
    parser.add_argument("--query", type=str, default="", help="Initial search query")
    parser.add_argument("--port", type=int, default=8000, help="Port to serve the archive on")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
    parser.add_argument("--open", action="store_true", help="(Legacy) Open the archive in the browser (default behavior now)")
    
    args = parser.parse_args()
    
    db_path = os.environ.get("JOBWORKFLOW_DB")
    if db_path:
        db_path = resolve_repo_relative_path(db_path)
    else:
        db_path = resolve_repo_relative_path("data/capture/jobs.db")
        
    run_server(db_path, args.port, args.query, args.no_browser)

if __name__ == "__main__":
    main()
