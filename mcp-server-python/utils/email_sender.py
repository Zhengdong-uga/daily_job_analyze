"""
Email Sender module for Daily Job Watch.

Handles validation of email settings, composing the message,
and dispatching the Markdown report via SMTP.

Supports:
  - Multiple recipients (env vars + YAML, with precedence chain)
  - Multipart/alternative emails (plain-text + HTML body)
  - Multiple file attachments with correct MIME types

Recipient precedence (highest → lowest):
  1. JOBWATCH_EMAIL_RECIPIENTS
  2. JOBWATCH_EMAIL_RECIPIENT
  3. email.recipient_emails
  4. email.recipient_email
"""

import logging
import mimetypes
import os
import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Ensure .md gets a sensible MIME type
mimetypes.add_type("text/markdown", ".md")


def _normalize_recipients(raw: List[str]) -> List[str]:
    """
    Normalize a list of recipient strings.

    - Splits comma-separated entries
    - Strips whitespace
    - Removes blank entries
    - Deduplicates case-insensitively while preserving order and original casing
    """
    expanded: List[str] = []
    for entry in raw:
        for addr in entry.split(","):
            addr = addr.strip()
            if addr:
                expanded.append(addr)

    # Deduplicate case-insensitively, preserving first occurrence order/casing
    seen: set[str] = set()
    deduped: List[str] = []
    for addr in expanded:
        key = addr.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(addr)
    return deduped


def _resolve_recipients(
    config_email: Any,
    env: Dict[str, str],
) -> List[str]:
    """
    Resolve the final recipient list using the precedence chain.

    Precedence (first non-empty wins):
        1. JOBWATCH_EMAIL_RECIPIENTS env var (comma-separated)
        2. JOBWATCH_EMAIL_RECIPIENT  env var (single)
        3. config_email.recipient_emails (YAML list)
        4. config_email.recipient_email  (YAML string)

    Returns:
        Normalized, deduplicated list of recipient addresses.
    """
    # 1. JOBWATCH_EMAIL_RECIPIENTS env var
    env_recipients = env.get("JOBWATCH_EMAIL_RECIPIENTS", "")
    if env_recipients.strip():
        return _normalize_recipients([env_recipients])

    # 2. JOBWATCH_EMAIL_RECIPIENT env var
    env_recipient = env.get("JOBWATCH_EMAIL_RECIPIENT", "")
    if env_recipient.strip():
        return _normalize_recipients([env_recipient])

    # 3. config_email.recipient_emails (YAML list)
    yaml_list = getattr(config_email, "recipient_emails", []) or []
    if yaml_list:
        return _normalize_recipients(yaml_list)

    # 4. config_email.recipient_email (YAML string)
    yaml_single = getattr(config_email, "recipient_email", "") or ""
    if yaml_single.strip():
        return _normalize_recipients([yaml_single])

    return []


def build_email_subject(
    report_date: date,
    matched_count: int,
    preferred_count: int,
    subject_prefix: str,
) -> str:
    """Build the dynamic email subject line."""
    date_str = report_date.strftime("%Y-%m-%d")
    base = f"{subject_prefix} — {date_str} — {matched_count} jobs analyzed"
    if preferred_count > 0:
        base += f", {preferred_count} preferred-company hits"
    return base


def build_incremental_email_subject(
    report_date: date,
    new_count: int,
    updated_count: int,
    subject_prefix: str = "Job Intelligence Report",
) -> str:
    """
    Build an incremental email subject showing new/updated counts.

    Examples:
        "Job Intelligence Report — 2026-06-13 — 18 new, 4 updated"
        "Job Intelligence Report — 2026-06-13 — No new jobs"
    """
    date_str = report_date.strftime("%Y-%m-%d")

    if new_count == 0 and updated_count == 0:
        return f"{subject_prefix} — {date_str} — No new jobs"

    parts = []
    if new_count > 0:
        parts.append(f"{new_count} new")
    if updated_count > 0:
        parts.append(f"{updated_count} updated")

    return f"{subject_prefix} — {date_str} — {', '.join(parts)}"


def build_zero_new_email_body() -> str:
    """
    Return a short email body for when there are no new or updated jobs.
    """
    return (
        "No new or materially updated matching jobs were found "
        "since the previous successful run.\n\n"
        "Run the pipeline again later or expand the scrape window "
        "with --hours-old to check a wider time range."
    )


def validate_email_settings(
    config_email: Any,
    env: Dict[str, str] = os.environ,
) -> Dict[str, Any]:
    """
    Validate and merge email configuration from YAML and environment variables.

    Args:
        config_email: EmailConfig dataclass object from watch_config.
        env: Environment dictionary (defaults to os.environ).

    Returns:
        Dict of validated settings ready for use.
        ``recipients`` is always a ``list[str]``.
        ``recipient_email`` is kept for backward compat (first recipient).

    Raises:
        ValueError: If required fields are missing.
    """
    settings: Dict[str, Any] = {
        "smtp_host": getattr(config_email, "smtp_host", "smtp.gmail.com"),
        "smtp_port": getattr(config_email, "smtp_port", 587),
        "smtp_user": getattr(config_email, "smtp_user", ""),
        "sender_email": getattr(config_email, "sender_email", ""),
        "subject_prefix": getattr(
            config_email, "subject_prefix", "Daily Job Intelligence Report"
        ),
        "send_html": getattr(config_email, "send_html", True),
        "attach_markdown": getattr(config_email, "attach_markdown", True),
    }

    # Environment overrides for sender
    if "JOBWATCH_EMAIL_SENDER" in env:
        settings["sender_email"] = env["JOBWATCH_EMAIL_SENDER"]

    if not settings["smtp_user"] and settings["sender_email"]:
        settings["smtp_user"] = settings["sender_email"]

    settings["smtp_password"] = env.get("JOBWATCH_EMAIL_PASSWORD", "")

    # Resolve recipients via the full precedence chain
    recipients = _resolve_recipients(config_email, env)
    settings["recipients"] = recipients
    # Backward compat: first recipient (or empty)
    settings["recipient_email"] = recipients[0] if recipients else ""

    # Validation
    missing: List[str] = []
    if not settings["smtp_host"]:
        missing.append("smtp_host")
    if not settings["smtp_port"]:
        missing.append("smtp_port")
    if not settings["smtp_user"]:
        missing.append("smtp_user")
    if not settings["smtp_password"]:
        missing.append("smtp_password (set JOBWATCH_EMAIL_PASSWORD env var)")
    if not settings["sender_email"]:
        missing.append("sender_email")
    if not recipients:
        missing.append(
            "recipient_email (set JOBWATCH_EMAIL_RECIPIENTS or "
            "JOBWATCH_EMAIL_RECIPIENT env var, or configure in YAML)"
        )

    if missing:
        raise ValueError(f"Missing required email settings: {', '.join(missing)}")

    return settings


def _guess_mime(path: Path) -> tuple[str, str]:
    """Return (maintype, subtype) for a file path."""
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        maintype, subtype = mime.split("/", 1)
        return maintype, subtype
    return "application", "octet-stream"


def send_email_report(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    sender_email: str,
    recipients: Optional[List[str]] = None,
    subject: str = "",
    plain_text_body: str = "",
    html_body: Optional[str] = None,
    attachment_paths: Optional[List[Path]] = None,
    dry_run: bool = False,
    *,
    # ----- backward-compat aliases -----
    recipient_email: Optional[str] = None,
    markdown_body: Optional[str] = None,
    attachment_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Send the report via SMTP or simulate it in dry-run mode.

    Supports multipart/alternative (plain-text + HTML) and multiple
    file attachments with auto-detected MIME types.

    Backward-compatible kwargs:
        ``recipient_email``  → merged into ``recipients``
        ``markdown_body``    → used as ``plain_text_body`` if that is empty
        ``attachment_path``  → merged into ``attachment_paths``

    Returns:
        Dict summarizing the outcome.
    """
    # ---- backward compat: resolve legacy kwargs ----
    if recipients is None:
        if recipient_email:
            recipients = _normalize_recipients([recipient_email])
        else:
            recipients = []

    if not plain_text_body and markdown_body:
        plain_text_body = markdown_body

    if attachment_paths is None:
        attachment_paths = []
    if attachment_path is not None:
        attachment_paths = [attachment_path] + list(attachment_paths)

    # ---- validation ----
    if not recipients:
        raise ValueError("At least one recipient is required")

    # ---- compose message ----
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = ", ".join(recipients)

    # Set the body: plain-text always, HTML when provided
    msg.set_content(plain_text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    # ---- attach files ----
    attached_names: List[str] = []
    for fpath in attachment_paths:
        if fpath is None:
            continue
        if not fpath.exists():
            logger.debug("Skipping missing attachment: %s", fpath)
            continue
        maintype, subtype = _guess_mime(fpath)
        with open(fpath, "rb") as f:
            data = f.read()
        msg.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=fpath.name,
        )
        attached_names.append(fpath.name)

    # ---- result dict builder ----
    def _result(sent: bool, is_dry_run: bool) -> Dict[str, Any]:
        return {
            "sent": sent,
            "recipients": list(recipients),
            "recipient": ", ".join(recipients),
            "subject": subject,
            "html": html_body is not None,
            "attachments": attached_names,
            "attachment": attached_names[0] if attached_names else None,
            "dry_run": is_dry_run,
        }

    if dry_run:
        return _result(sent=False, is_dry_run=True)

    # ---- actual SMTP send ----
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        return _result(sent=True, is_dry_run=False)
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError(
            "SMTP authentication failed. Check your credentials "
            "(password is not logged for security)."
        )
    except Exception as e:
        # Sanitize: never expose smtp_password in error messages
        err_msg = str(e)
        if smtp_password and smtp_password in err_msg:
            err_msg = err_msg.replace(smtp_password, "****")
        raise RuntimeError(f"Failed to send email: {err_msg}") from e
