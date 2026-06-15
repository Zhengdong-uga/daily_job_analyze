"""
JD Preprocessor for AI analysis.

Strips EEO statements, benefits boilerplate, legal disclaimers, and
generic company descriptions from job descriptions before sending
them to AI providers. Also handles truncation.
"""

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Boilerplate patterns to remove
# ---------------------------------------------------------------------------

_EEO_PATTERNS = [
    # Equal Employment Opportunity statements
    r"(?:equal\s+(?:employment\s+)?opportunity|eeo)\s+(?:employer|statement).*?(?:\n\n|\Z)",
    r"(?:we\s+are\s+(?:an?\s+)?(?:equal\s+opportunity|eeo)\s+employer).*?(?:\n\n|\Z)",
    r"(?:we\s+do\s+not\s+discriminate).*?(?:\n\n|\Z)",
    r"(?:all\s+qualified\s+applicants?\s+will\s+receive\s+consideration).*?(?:\n\n|\Z)",
    r"(?:regardless\s+of\s+race,?\s+color,?\s+religion).*?(?:\n\n|\Z)",
    r"(?:protected\s+(?:veteran|characteristic|class)).*?(?:\n\n|\Z)",
]

_BENEFITS_PATTERNS = [
    # Benefits sections
    r"(?:^|\n)#+\s*(?:benefits|perks|what\s+we\s+offer|compensation\s+(?:and|&)\s+benefits).*?(?=\n#|\Z)",
    r"(?:^|\n)\*{0,2}(?:benefits|perks|what\s+we\s+offer)\*{0,2}\s*[:.].*?(?=\n\n\n|\n#|\Z)",
    r"(?:health\s+insurance|dental\s+(?:and|&)\s+vision|401k|401\(k\)|unlimited\s+(?:pto|vacation)).*?(?:\n\n|\Z)",
]

_LEGAL_PATTERNS = [
    # Legal disclaimers and salary ranges
    r"(?:this\s+(?:job\s+)?description\s+is\s+not\s+(?:designed|intended)\s+to).*?(?:\n\n|\Z)",
    r"(?:salary\s+range|compensation\s+range|pay\s+range)\s*:?\s*\$[\d,]+.*?(?:\n\n|\Z)",
    r"(?:reasonable\s+accommodations?).*?(?:\n\n|\Z)",
    r"(?:background\s+check|drug\s+(?:test|screen)).*?(?:\n\n|\Z)",
]


def _compile_patterns():
    """Compile all boilerplate patterns into a single list."""
    all_patterns = _EEO_PATTERNS + _BENEFITS_PATTERNS + _LEGAL_PATTERNS
    return [re.compile(p, re.IGNORECASE | re.DOTALL) for p in all_patterns]


_COMPILED_PATTERNS = _compile_patterns()


def strip_boilerplate(text: str) -> str:
    """
    Remove EEO, benefits, legal, and generic boilerplate from a JD.

    Preserves the substantive job requirements, responsibilities,
    and qualifications.
    """
    if not text:
        return ""

    result = text
    for pattern in _COMPILED_PATTERNS:
        result = pattern.sub("", result)

    # Clean up excessive whitespace left by removals
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def truncate_description(text: str, max_chars: int = 12000) -> str:
    """
    Truncate description to max_chars, breaking at a sentence boundary
    when possible.
    """
    if not text or len(text) <= max_chars:
        return text

    # Try to break at the last sentence boundary before max_chars
    truncated = text[:max_chars]
    last_period = truncated.rfind(".")
    last_newline = truncated.rfind("\n")
    break_point = max(last_period, last_newline)

    if break_point > max_chars * 0.7:
        return truncated[:break_point + 1]

    return truncated


def preprocess_for_ai(
    description: str,
    max_chars: int = 12000,
) -> str:
    """
    Full preprocessing pipeline: strip boilerplate then truncate.

    Args:
        description: Raw job description text.
        max_chars: Maximum characters to send to AI.

    Returns:
        Cleaned, truncated description ready for AI analysis.
    """
    cleaned = strip_boilerplate(description)
    return truncate_description(cleaned, max_chars)
