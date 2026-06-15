"""
AI Provider abstraction for Job Intelligence analysis.

Supports Gemini (google-genai SDK) and OpenAI, with a NoOp fallback
for when AI is disabled or unavailable.

All providers:
- Accept preprocessed JD text
- Return structured JSON dicts
- Handle errors gracefully (never crash the pipeline)
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from utils.jd_preprocessor import preprocess_for_ai

logger = logging.getLogger(__name__)

# Prompt version — bump this when prompt content changes materially
PROMPT_VERSION = "v1.0"

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_JOB_ANALYSIS_PROMPT = """Analyze this job description and return a JSON object with the following fields.
Be precise: distinguish required skills from preferred skills. Do not invent qualifications not present in the text.
Preserve short evidence snippets (1-2 sentences) from the JD for important conclusions.

Required JSON schema:
{{
  "summary": "2-3 sentence summary of the role",
  "role_cluster": "one of: AI/ML Engineering, Forward Deployed/Customer-Facing Engineering, Product Design/UX, UX Engineering/Design Engineering, Frontend Engineering, Product/Strategy, Data/Research/Evaluation, Infrastructure/Platform, Other",
  "seniority": "one of: intern, entry-level, mid-level, senior, staff, lead, principal, director, unknown",
  "core_responsibilities": ["list of key responsibilities"],
  "required_skills": ["skills explicitly listed as required"],
  "preferred_skills": ["skills listed as preferred/nice-to-have/bonus"],
  "tools_and_technologies": ["specific tools, frameworks, platforms mentioned"],
  "soft_skills": ["interpersonal and collaboration skills mentioned"],
  "years_of_experience": "string like '3-5 years' or null if not specified",
  "education_requirements": ["degree requirements mentioned"],
  "domain_experience": ["industry/domain experience mentioned"],
  "portfolio_signals": ["what portfolio evidence would strengthen an application"],
  "resume_keywords": ["exact phrases to include in a resume for ATS matching"],
  "job_seeker_takeaway": "1-2 sentence actionable insight for a job seeker",
  "evidence": ["short JD snippets supporting key conclusions"]
}}

Job Title: {title}
Company: {company}
Location: {location}

Job Description:
{description}

Return ONLY valid JSON, no markdown fences, no explanation."""

_JOB_UPDATE_PROMPT = """Compare the OLD and NEW versions of this job description. Identify what materially changed.
Only make claims supported by the text. Do not speculate.

Return a JSON object:
{{
  "change_summary": ["list of material changes"],
  "new_requirements": ["requirements added in the new version"],
  "removed_requirements": ["requirements present in old but absent in new"],
  "changed_responsibilities": ["responsibilities that changed"],
  "changed_seniority_or_experience": ["changes to seniority or experience requirements"]
}}

OLD JOB DESCRIPTION:
{old_description}

NEW JOB DESCRIPTION:
{new_description}

Return ONLY valid JSON, no markdown fences, no explanation."""

_MARKET_SUMMARY_PROMPT = """You are a job market analyst. Based on the data below, synthesize an incremental market intelligence report.

RULES:
- Do NOT invent counts or statistics. All numeric totals come from the deterministic metrics provided.
- Analyze ONLY the jobs supplied below. Do not assume information about jobs not shown.
- Clearly distinguish: today's new evidence, historical baseline, and your interpretation.
- Every trend must cite specific evidence from the job data.

CURRENT RUN METRICS:
{run_metrics}

PREVIOUS SUCCESSFUL RUN METRICS:
{previous_metrics}

CURRENT JOB ANALYSES ({current_count} jobs):
{current_analyses}

Return a JSON object with this schema:
{{
  "market_snapshot": {{
    "executive_summary": ["string"],
    "dominant_hiring_patterns": ["string"],
    "candidate_profile_employers_want": ["string"]
  }},
  "current_market_trends": [
    {{
      "trend": "string",
      "explanation": "string",
      "deterministic_evidence": ["string"],
      "affected_role_clusters": ["string"],
      "example_jobs": ["string"]
    }}
  ],
  "role_specific_requirements": {{
    "role_cluster": {{
      "what_the_role_does": ["string"],
      "required_skills": ["string"],
      "preferred_skills": ["string"],
      "common_responsibilities": ["string"],
      "tools_and_technologies": ["string"],
      "candidate_profile": ["string"]
    }}
  }},
  "cross_role_skill_patterns": ["string"],
  "required_vs_preferred_patterns": ["string"],
  "resume_recommendations": ["string"],
  "portfolio_recommendations": ["string"],
  "linkedin_recommendations": ["string"],
  "skills_to_learn": ["string"],
  "changes_since_previous_run": ["string"]
}}

Return ONLY valid JSON, no markdown fences, no explanation."""


# ---------------------------------------------------------------------------
# JSON parsing helper
# ---------------------------------------------------------------------------


def _parse_json_response(text: str) -> Dict[str, Any]:
    """Parse JSON from an LLM response, handling common formatting issues."""
    if not text:
        return {}

    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        logger.warning("Failed to parse JSON from AI response: %s...", text[:200])
        return {}


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class AIProvider(ABC):
    """Abstract base class for AI providers."""

    def __init__(self, model: str = "", extraction_model: str = "", synthesis_model: str = "", temperature: float = 0.2):
        self.model = model
        self.extraction_model = extraction_model or model
        self.synthesis_model = synthesis_model or model
        self.temperature = temperature

    @abstractmethod
    def _call_model(self, prompt: str, target_model: str) -> str:
        """Send a prompt to the model and return raw text response."""
        ...

    def analyze_job(
        self,
        job: Dict[str, Any],
        max_description_chars: int = 12000,
    ) -> Dict[str, Any]:
        """
        Analyze a single job description.

        Returns structured analysis dict, or empty dict on failure.
        """
        description = preprocess_for_ai(
            job.get("description", ""), max_chars=max_description_chars
        )

        prompt = _JOB_ANALYSIS_PROMPT.format(
            title=job.get("title", "Unknown"),
            company=job.get("company", "Unknown"),
            location=job.get("location", "Unknown"),
            description=description,
        )

        try:
            response = self._call_model(prompt, self.extraction_model)
            return _parse_json_response(response)
        except Exception as e:
            logger.warning("AI job analysis failed: %s", e)
            return {}

    def analyze_job_update(
        self,
        old_description: str,
        new_description: str,
        max_description_chars: int = 12000,
    ) -> Dict[str, Any]:
        """
        Compare old and new JD versions.

        Returns structured change analysis dict, or empty dict on failure.
        """
        old_clean = preprocess_for_ai(old_description, max_chars=max_description_chars)
        new_clean = preprocess_for_ai(new_description, max_chars=max_description_chars)

        prompt = _JOB_UPDATE_PROMPT.format(
            old_description=old_clean,
            new_description=new_clean,
        )

        try:
            response = self._call_model(prompt, self.extraction_model)
            return _parse_json_response(response)
        except Exception as e:
            logger.warning("AI job update analysis failed: %s", e)
            return {}

    def generate_market_summary(
        self,
        run_metrics: Dict[str, Any],
        previous_metrics: Optional[Dict[str, Any]],
        current_analyses: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Synthesize a current market snapshot report based on all active jobs.

        Returns structured market summary dict, or empty dict on failure.
        """
        prompt = _MARKET_SUMMARY_PROMPT.format(
            run_metrics=json.dumps(run_metrics, indent=2),
            previous_metrics=json.dumps(previous_metrics, indent=2) if previous_metrics else "No previous run data available.",
            current_count=len(current_analyses),
            current_analyses=json.dumps(current_analyses[:40], indent=2, ensure_ascii=False),
        )

        try:
            response = self._call_model(prompt, self.synthesis_model)
            return _parse_json_response(response)
        except Exception as e:
            logger.warning("AI market summary generation failed: %s", e)
            return {}

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__.replace("Provider", "").lower()


# ---------------------------------------------------------------------------
# Gemini provider
# ---------------------------------------------------------------------------


class GeminiProvider(AIProvider):
    """Google Gemini API provider using google-genai SDK."""

    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, api_key: str, model: str = "", extraction_model: str = "", synthesis_model: str = "", temperature: float = 0.2):
        base_model = model or self.DEFAULT_MODEL
        super().__init__(model=base_model, extraction_model=extraction_model, synthesis_model=synthesis_model, temperature=temperature)
        self.api_key = api_key
        self._client = None
        self._get_client()

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "Gemini support is not installed. Run:\n"
                    "uv sync --extra ai-gemini\n"
                    "or:\n"
                    "uv pip install google-genai"
                )
        return self._client

    def _call_model(self, prompt: str, target_model: str) -> str:
        from google.genai import types
        client = self._get_client()
        response = client.models.generate_content(
            model=target_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=self.temperature,
                response_mime_type="application/json",
            ),
        )
        return response.text or ""

    @property
    def provider_name(self) -> str:
        return "gemini"


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------


class OpenAIProvider(AIProvider):
    """OpenAI API provider using openai SDK."""

    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, api_key: str, model: str = "", extraction_model: str = "", synthesis_model: str = "", temperature: float = 0.2):
        base_model = model or self.DEFAULT_MODEL
        super().__init__(model=base_model, extraction_model=extraction_model, synthesis_model=synthesis_model, temperature=temperature)
        self.api_key = api_key
        self._client = None
        self._get_client()

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "openai package is required for OpenAI provider. "
                    "Install with: uv sync --extra ai"
                )
        return self._client

    def _call_model(self, prompt: str, target_model: str) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=target_model,
            messages=[
                {"role": "system", "content": "You are a job market analyst. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""

    @property
    def provider_name(self) -> str:
        return "openai"


# ---------------------------------------------------------------------------
# NoOp provider (AI disabled)
# ---------------------------------------------------------------------------


class NoOpProvider(AIProvider):
    """No-op provider that returns empty results. Used when AI is disabled."""

    def __init__(self):
        super().__init__(model="none", extraction_model="none", synthesis_model="none", temperature=0)

    def _call_model(self, prompt: str, target_model: str) -> str:
        return "{}"

    def analyze_job(self, job: Dict[str, Any], max_description_chars: int = 12000) -> Dict[str, Any]:
        return {}

    def analyze_job_update(self, old_description: str, new_description: str, max_description_chars: int = 12000) -> Dict[str, Any]:
        return {}

    def generate_market_summary(self, run_metrics: Dict[str, Any], previous_metrics: Optional[Dict[str, Any]], current_analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {}

    @property
    def provider_name(self) -> str:
        return "noop"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_provider(
    provider_name: str,
    api_key: str = "",
    model: str = "",
    extraction_model: str = "",
    synthesis_model: str = "",
    temperature: float = 0.2,
) -> AIProvider:
    """
    Factory function to create an AI provider.

    Args:
        provider_name: "gemini", "openai", or "noop"
        api_key: API key for the provider
        model: Model name override (empty = provider default)
        extraction_model: Model for per-job extraction
        synthesis_model: Model for aggregate market summary
        temperature: Sampling temperature

    Returns:
        AIProvider instance

    Raises:
        ValueError: If provider_name is unknown
    """
    name = provider_name.lower().strip()

    if name == "gemini":
        if not api_key:
            raise ValueError("JOBWATCH_GEMINI_API_KEY is required for Gemini provider")
        return GeminiProvider(api_key=api_key, model=model, extraction_model=extraction_model, synthesis_model=synthesis_model, temperature=temperature)

    if name == "openai":
        if not api_key:
            raise ValueError("JOBWATCH_OPENAI_API_KEY is required for OpenAI provider")
        return OpenAIProvider(api_key=api_key, model=model, extraction_model=extraction_model, synthesis_model=synthesis_model, temperature=temperature)

    if name == "noop":
        return NoOpProvider()

    raise ValueError(f"Unknown AI provider: {provider_name}. Supported: gemini, openai, noop")
