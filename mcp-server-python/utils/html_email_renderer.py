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
    background-color: #f4f4f7;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                 Helvetica, Arial, sans-serif, 'Apple Color Emoji',
                 'Segoe UI Emoji';
    font-size: 15px;
    line-height: 1.6;
    color: #1a1a2e;
}
.container {
    max-width: 760px;
    margin: 0 auto;
    padding: 24px 20px;
    background-color: #ffffff;
}
h1 {
    font-size: 24px;
    font-weight: 700;
    color: #0f0f23;
    border-bottom: 2px solid #e0e0e8;
    padding-bottom: 8px;
    margin-top: 28px;
    margin-bottom: 12px;
}
h2 {
    font-size: 20px;
    font-weight: 600;
    color: #16213e;
    border-bottom: 1px solid #e8e8f0;
    padding-bottom: 6px;
    margin-top: 24px;
    margin-bottom: 10px;
}
h3 {
    font-size: 17px;
    font-weight: 600;
    color: #1a1a40;
    margin-top: 20px;
    margin-bottom: 8px;
}
h4 {
    font-size: 15px;
    font-weight: 600;
    color: #333366;
    margin-top: 16px;
    margin-bottom: 6px;
}
p {
    margin: 8px 0;
}
a {
    color: #1a73e8;
    text-decoration: underline;
}
ul, ol {
    padding-left: 24px;
    margin: 8px 0;
}
li {
    margin: 3px 0;
}
table {
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;
    font-size: 14px;
}
th {
    background-color: #f0f0f5;
    border: 1px solid #d0d0d8;
    padding: 8px 10px;
    text-align: left;
    font-weight: 600;
}
td {
    border: 1px solid #d0d0d8;
    padding: 8px 10px;
}
tr:nth-child(even) {
    background-color: #fafafe;
}
blockquote {
    border-left: 4px solid #c0c0d0;
    margin: 12px 0;
    padding: 8px 16px;
    color: #555;
    background-color: #f9f9fc;
}
code {
    background-color: #f0f0f5;
    padding: 2px 5px;
    border-radius: 3px;
    font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
    font-size: 13px;
}
pre {
    background-color: #f0f0f5;
    padding: 12px 16px;
    border-radius: 4px;
    overflow-x: auto;
    font-size: 13px;
    line-height: 1.4;
}
pre code {
    background: none;
    padding: 0;
}
hr {
    border: none;
    border-top: 1px solid #e0e0e8;
    margin: 20px 0;
}
details {
    margin: 8px 0;
    padding: 6px 0;
}
summary {
    cursor: pointer;
    font-weight: 600;
    color: #1a73e8;
}
strong {
    font-weight: 600;
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
