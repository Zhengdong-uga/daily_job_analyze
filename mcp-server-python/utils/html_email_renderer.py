"""
HTML Email Renderer for Daily Job Watch.

Converts a Markdown report into email-safe HTML suitable for
inline display in Gmail and other email clients.

Uses the Python ``markdown`` library with table, fenced-code,
and sane-list extensions.  Output is wrapped in a minimal HTML
document with *inline-friendly* CSS that survives Gmail's
aggressive style stripping.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import markdown

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedded stylesheet (Gmail-compatible)
# ---------------------------------------------------------------------------
# Gmail strips <style> blocks but preserves most inline styles.
# We embed a <style> block for clients that support it (Apple Mail,
# Outlook.com, Thunderbird) and also inject critical inline styles
# via the wrapper markup.  This gives the best cross-client result
# without an external preprocessor like premailer.

_EMAIL_CSS = """\
body {
    margin: 0;
    padding: 0;
    background-color: #f3f4f6;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    color: #1f2937;
}
.container {
    max-width: 760px;
    margin: 20px auto;
    padding: 32px;
    background-color: #ffffff;
    border-radius: 12px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
}
h1 {
    font-size: 26px;
    font-weight: 800;
    color: #111827;
    border-bottom: 2px solid #e5e7eb;
    padding-bottom: 12px;
    margin-top: 10px;
    margin-bottom: 24px;
}
h2 {
    font-size: 20px;
    font-weight: 700;
    color: #1f2937;
    background-color: #f9fafb;
    border-left: 4px solid #4f46e5;
    padding: 10px 14px;
    margin-top: 32px;
    margin-bottom: 16px;
    border-radius: 0 6px 6px 0;
}
h3 {
    font-size: 17px;
    font-weight: 600;
    color: #374151;
    margin-top: 24px;
    margin-bottom: 12px;
}
h4 {
    font-size: 15px;
    font-weight: 600;
    color: #4b5563;
    margin-top: 20px;
    margin-bottom: 8px;
}
p {
    margin: 12px 0;
}
a {
    color: #4f46e5;
    text-decoration: none;
    font-weight: 500;
}
a:hover {
    text-decoration: underline;
}
ul, ol {
    padding-left: 24px;
    margin: 12px 0;
}
li {
    margin: 6px 0;
}
table {
    border-collapse: separate;
    border-spacing: 0;
    width: 100%;
    margin: 20px 0;
    font-size: 14px;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid #e5e7eb;
}
th {
    background-color: #f3f4f6;
    padding: 12px 16px;
    text-align: left;
    font-weight: 600;
    color: #374151;
    border-bottom: 1px solid #e5e7eb;
}
td {
    padding: 12px 16px;
    border-bottom: 1px solid #e5e7eb;
    color: #4b5563;
}
tr:last-child td {
    border-bottom: none;
}
tr:nth-child(even) {
    background-color: #f9fafb;
}
blockquote {
    border-left: 4px solid #818cf8;
    margin: 20px 0;
    padding: 16px 20px;
    color: #4b5563;
    background-color: #eef2ff;
    border-radius: 0 8px 8px 0;
    font-style: italic;
}
code {
    background-color: #e0e7ff;
    color: #3730a3;
    padding: 4px 10px;
    border-radius: 9999px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
}
pre {
    background-color: #1f2937;
    padding: 16px;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 13px;
    line-height: 1.5;
}
pre code {
    background: none;
    color: #e5e7eb;
    padding: 0;
    font-weight: normal;
    border-radius: 0;
    font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
}
hr {
    border: none;
    border-top: 1px solid #e5e7eb;
    margin: 32px 0;
}
details {
    margin: 16px 0;
    padding: 12px;
    background-color: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
}
summary {
    cursor: pointer;
    font-weight: 600;
    color: #4f46e5;
}
strong {
    font-weight: 700;
    color: #111827;
}
"""


def markdown_to_email_html(
    markdown_text: str,
    title: Optional[str] = None,
) -> str:
    """
    Convert a Markdown string into email-safe HTML.

    Args:
        markdown_text: Raw Markdown content (e.g. the daily report).
        title: Optional document title.  If the Markdown already starts
               with an H1, no duplicate visible title is inserted.

    Returns:
        A complete HTML document string ready for use as an email body.
    """
    # Convert markdown → HTML fragment
    md = markdown.Markdown(
        extensions=[
            "tables",
            "fenced_code",
            "sane_lists",
            "smarty",
            "nl2br",
        ],
        output_format="html",
    )
    html_fragment = md.convert(markdown_text)

    # Determine the <title> tag content
    doc_title = title or "Daily Job Intelligence Report"

    # Check if markdown already has an H1 so we don't duplicate it
    has_h1 = bool(re.search(r"<h1\b", html_fragment, re.IGNORECASE))

    # Build optional visible title (only when markdown lacks an H1)
    visible_title = ""
    if title and not has_h1:
        visible_title = f'<h1 style="font-size:24px;font-weight:700;color:#0f0f23;border-bottom:2px solid #e0e0e8;padding-bottom:8px;">{_escape_html(title)}</h1>\n'

    # Assemble the full HTML document
    html_doc = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_escape_html(doc_title)}</title>
<style>
{_EMAIL_CSS}
</style>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.6;color:#1a1a2e;">
<div class="container" style="max-width:760px;margin:0 auto;padding:24px 20px;background-color:#ffffff;">
{visible_title}{html_fragment}
</div>
</body>
</html>"""

    return html_doc


def _escape_html(text: str) -> str:
    """Minimal HTML escaping for attribute/title contexts."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
