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
uv run python scripts/run_daily_job_watch.py --config job_watch_config.yaml --send-email
```

**Options:**
- `--ai`: Force enable AI (overrides config).
- `--reanalyze-all`: Ignore local AI cache and force a complete reanalysis of all currently active jobs.

## Architecture

1. **Ingestion:** Scrapes jobs (via JobSpy) based on configured roles and locations.
2. **Filtration:** Matches jobs against keyword groups and deduplicates them using the local SQLite history.
3. **Extraction:** Uses AI (budget-aware) to extract required/soft skills from new or materially updated job descriptions.
4. **Synthesis:** Aggregates all extracted data alongside rule-based fallbacks to generate market trends and recommendations.
5. **Reporting:** Generates an 8-section Markdown report and emails it to the configured recipients.

## Privacy & Data Security

All sensitive tracking data, including your job database, templates, and customized `job_watch_config.yaml` are strictly ignored by `.gitignore` to ensure zero leakage of personal identifiable information or API keys when pushing to version control.
