# Job Intelligence Pipeline

An AI-powered, local-first Daily Job Intelligence System that automates the tracking, scraping, and synthesis of the job market into actionable daily reports.

## Overview

This tool was customized to solve the problem of overwhelming job boards and repeated notifications. Instead of just sending you a list of "new" jobs every day, this pipeline acts as an intelligent career agent. It scrapes current job listings, tracks them against a local historical database, and uses AI (like Gemini or OpenAI) to synthesize a "Current Market Snapshot" that tells you exactly what is happening in the hiring market.

### Key Custom Features

- **Incremental Tracking:** Uses a local SQLite database (`jobs.db`) to identify truly `new`, `updated`, and `unchanged` jobs, keeping API costs low and avoiding repetitive noise.
- **Decoupled AI Synthesis:** Extracts detailed requirements from new/updated jobs, then aggregates *all* active jobs to generate a macro-level market analysis.
- **Current Market Snapshot:** Generates a daily Markdown report detailing:
  - Executive market summaries
  - Current industry and hiring trends
  - What employers are looking for by role
  - Required vs. preferred skills
  - Cross-role skill patterns
  - Personalized resume and portfolio recommendations
- **Robust Fallbacks:** Integrates local deterministic logic and caching so that even if the AI budget is reached or the API fails, you still get a comprehensive breakdown of skill trends and active roles.
- **Automated Delivery:** Renders the rich Markdown report into a beautiful, Gmail-compatible HTML email format and sends it directly to your inbox.

*Note: This project is built upon the original JobWorkFlow/MCP scaffolding which provides the base SQLite ingestion and MCP tools.*

## Quick Start

### 1) Install Dependencies

```bash
uv sync --all-groups
# To enable AI (Gemini or OpenAI), install the extra dependencies:
uv sync --extra ai-gemini
# or
uv sync --extra ai-openai
```

### 2) Configuration

1. Copy the example configuration files:
   - `cp job_watch_config.example.yaml job_watch_config.yaml`
   - `cp .env.example .env`
2. Update `.env` with your email credentials and API keys (`GEMINI_API_KEY` or `OPENAI_API_KEY`).
3. Update `job_watch_config.yaml` with your target roles, locations, keyword groups, and AI preferences.

### 3) Run the Daily Pipeline

You can run the pipeline manually or set it up via cron/Windows Task Scheduler:

```bash
uv run python scripts/run_daily_job_watch.py \
  --config job_watch_config.yaml \
  --hours-old 24 \
  --ai \
  --ai-provider gemini \
  --max-ai-jobs 100 \
  --send-email
```

**Options:**
- `--ai`: Force enable AI (overrides config).
- `--reanalyze-all`: Ignore local AI cache and force a complete reanalysis of all currently active jobs.

## Available Commands

Here are the primary commands you will use to interact with the system:

### 1. Run the Daily Job Pipeline (Main Pipeline)
Scrapes the latest jobs, analyzes them with AI, and generates your daily report.
```bash
uv run python scripts/run_daily_job_watch.py \
  --config job_watch_config.yaml \
  --hours-old 24 \
  --ai \
  --ai-provider gemini \
  --max-ai-jobs 100 \
  --send-email
```
**Useful flags:**
- `--report-only`: Skips scraping and directly regenerates the report using existing database data (great for testing configuration changes).
- `--reanalyze-all`: Ignores the local AI cache and forces a fresh AI analysis of all currently active jobs.

### 2. Open the Interactive Job Archive
Starts a local web server to view all historical jobs, search through them, and **delete** irrelevant jobs directly from the database.
```bash
uv run python scripts/export_job_archive.py
```
*Note: This will automatically find an open port (like `8000`) and open it in your browser. Press `Ctrl+C` in the terminal to stop the server when you are done.*

### 3. Check for Duplicate Jobs (Manual Tool)
If you find a job on LinkedIn and want to quickly check if the system has already tracked it:
```bash
./scripts/check_job.sh "Job URL" "Company Name" "Position Name"
```

### 4. Install / Update Dependencies
If you need to update packages or switch AI providers:
```bash
uv sync --all-groups
uv sync --extra ai-gemini    # Ensure Gemini dependencies are installed
```

## Architecture

1. **Ingestion:** Scrapes jobs (via JobSpy) based on configured roles and locations.
2. **Filtration:** Matches jobs against keyword groups and deduplicates them using the local SQLite history.
3. **Extraction:** Uses AI (budget-aware) to extract required/soft skills from new or materially updated job descriptions.
4. **Synthesis:** Aggregates all extracted data alongside rule-based fallbacks to generate market trends and recommendations.
5. **Reporting:** Generates an 8-section Markdown report and emails it to the configured recipients.

## Historical Job Archive

To keep the daily email focused strictly on the current market, all historically scraped jobs (even those no longer active) are stored in the local database and can be viewed via an interactive, standalone HTML archive.

If you want to see the saved/fetched jobs, run the following command to generate and open the archive:

```bash
uv run python scripts/export_job_archive.py
```

**Features:**
- Client-side search by title, company, location, or skill.
- Sort by first seen, last seen, company, or title.
- Filter by recent vs older jobs.
- Expandable job descriptions with AI summaries.
- Completely offline capable.

## Direct SQLite Access

If you prefer to run custom analytical queries or manually inspect raw job data, you can directly query the SQLite database where all jobs are stored.

To find the database file:
```bash
find . -name "jobs.db"
```

To connect via the SQLite CLI:
```bash
sqlite3 data/capture/jobs.db
```

**Example Queries:**
```sql
-- View the latest 50 jobs
SELECT title, company, location, first_seen_at FROM jobs ORDER BY first_seen_at DESC LIMIT 50;

-- Search for a specific company
SELECT title, location, url FROM jobs WHERE company LIKE '%OpenAI%';

-- Search by title
SELECT title, company FROM jobs WHERE title LIKE '%Product Manager%';

-- Lookup full job description for a specific job
SELECT description FROM jobs WHERE id = 123;
```

## Privacy & Data Security

All sensitive tracking data, including your job database, templates, and customized `job_watch_config.yaml` are strictly ignored by `.gitignore` to ensure zero leakage of personal identifiable information or API keys when pushing to version control.
