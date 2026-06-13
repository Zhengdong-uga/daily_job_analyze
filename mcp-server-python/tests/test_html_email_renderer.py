"""Tests for the html_email_renderer module."""

import re

import pytest

from utils.html_email_renderer import markdown_to_email_html, _escape_html


# ---------------------------------------------------------------------------
# Sample Markdown content for tests
# ---------------------------------------------------------------------------

SAMPLE_MD = """\
# Daily Job Intelligence Report - 2026-06-12

## 1. Executive Summary

- **Total Scraped:** 120
- **Total Jobs Included:** 42

## 2. Job Market Trends

### Trend: AI Engineering Demand

**Explanation:**
AI engineering roles are growing rapidly.

**Evidence:**
- 15 new AI Engineer postings
- 8 LLM-specific roles

## Job Listings

#### [AI Engineer @ OpenAI](https://openai.com/careers)
- **Location:** San Francisco | **Source:** linkedin
- **Matched Role:** AI Engineer | **Keywords:** LLM, AI

---

| Skill | Count |
|-------|-------|
| Python | 30 |
| React  | 15 |
| LLM    | 12 |

> This is a blockquote about market conditions.

Here is some `inline code` and a block:

```python
def hello():
    return "world"
```

1. First item
2. Second item
3. Third item

*Italic text* and **bold text** together.
"""


# ===================================================================
# markdown_to_email_html
# ===================================================================

class TestMarkdownToEmailHtml:
    def test_returns_html_document(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_headings_rendered(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert "<h1>" in html or "<h1 " in html
        assert "<h2>" in html
        assert "<h3>" in html
        assert "<h4>" in html

    def test_bullet_lists_rendered(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert "<ul>" in html
        assert "<li>" in html

    def test_numbered_lists_rendered(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert "<ol>" in html

    def test_tables_rendered(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert "<table>" in html or "<table " in html
        assert "<th>" in html or "<th " in html
        assert "<td>" in html or "<td " in html

    def test_links_clickable(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert 'href="https://openai.com/careers"' in html

    def test_bold_and_italic(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert "<strong>" in html
        assert "<em>" in html

    def test_horizontal_rule(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert "<hr" in html

    def test_blockquote(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert "<blockquote>" in html

    def test_code_blocks(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert "<code>" in html
        assert "<pre>" in html

    def test_inline_code(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert "<code>inline code</code>" in html

    def test_has_style_block(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert "<style>" in html

    def test_has_inline_styles_on_body(self):
        """Gmail strips <style> blocks, so critical styles must be inline."""
        html = markdown_to_email_html(SAMPLE_MD)
        assert 'style="' in html

    def test_max_width_container(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert "max-width:760px" in html or "max-width: 760px" in html

    def test_no_javascript(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert "<script" not in html.lower()

    def test_no_external_css(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert 'rel="stylesheet"' not in html

    def test_title_default(self):
        html = markdown_to_email_html(SAMPLE_MD)
        assert "<title>" in html

    def test_title_custom_no_duplicate_h1(self):
        """When markdown already has an H1, don't inject a visible duplicate."""
        html = markdown_to_email_html(SAMPLE_MD, title="Custom Title")
        # The <title> should use the custom title
        assert "Custom Title" in html
        # Count visible H1 elements — should be exactly 1 (from the markdown)
        h1_count = len(re.findall(r"<h1\b", html, re.IGNORECASE))
        assert h1_count == 1

    def test_title_injected_when_no_h1(self):
        """When markdown lacks an H1, the title should become a visible H1."""
        md_no_h1 = "## Section\n\nSome text."
        html = markdown_to_email_html(md_no_h1, title="Report Title")
        h1_count = len(re.findall(r"<h1\b", html, re.IGNORECASE))
        assert h1_count == 1
        assert "Report Title" in html

    def test_empty_markdown(self):
        """Empty input should still produce valid HTML structure."""
        html = markdown_to_email_html("")
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html


# ===================================================================
# _escape_html
# ===================================================================

class TestEscapeHtml:
    def test_ampersand(self):
        assert _escape_html("a & b") == "a &amp; b"

    def test_angle_brackets(self):
        assert _escape_html("<div>") == "&lt;div&gt;"

    def test_quotes(self):
        assert _escape_html('"hello"') == "&quot;hello&quot;"

    def test_no_escaping_needed(self):
        assert _escape_html("hello world") == "hello world"


# ===================================================================
# HTML rendering failure fallback
# ===================================================================

class TestHtmlRenderingFallback:
    def test_bad_markdown_extension_does_not_crash(self):
        """markdown_to_email_html should handle all valid Markdown without errors."""
        weird_md = "# Title\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- item\n"
        html = markdown_to_email_html(weird_md)
        assert "<table>" in html or "<table " in html
