"""Tests for the email_sender module – multi-recipient + HTML + attachment support."""

import os
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

from utils.email_sender import (
    _normalize_recipients,
    _resolve_recipients,
    build_email_subject,
    validate_email_settings,
    send_email_report,
)
from utils.watch_config import EmailConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides):
    """Return an EmailConfig with sensible defaults, easily overridden."""
    defaults = dict(
        enabled=True,
        send_html=True,
        attach_markdown=True,
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_user="user@example.com",
        sender_email="sender@example.com",
        recipient_email="",
        recipient_emails=[],
        subject_prefix="Test Subject",
    )
    defaults.update(overrides)
    return EmailConfig(**defaults)


def _base_env(**overrides):
    """Return a minimal valid env dict, easily overridden."""
    env = {"JOBWATCH_EMAIL_PASSWORD": "secret"}
    env.update(overrides)
    return env


# ===================================================================
# build_email_subject
# ===================================================================

class TestBuildEmailSubject:
    def test_without_preferred_hits(self):
        subj = build_email_subject(date(2026, 6, 12), 50, 0, "Daily Job Intelligence Report")
        assert subj == "Daily Job Intelligence Report — 2026-06-12 — 50 jobs analyzed"

    def test_with_preferred_hits(self):
        subj = build_email_subject(date(2026, 6, 12), 50, 12, "Daily Job Intelligence Report")
        assert subj == "Daily Job Intelligence Report — 2026-06-12 — 50 jobs analyzed, 12 preferred-company hits"


# ===================================================================
# _normalize_recipients
# ===================================================================

class TestNormalizeRecipients:
    def test_single_address(self):
        assert _normalize_recipients(["a@b.com"]) == ["a@b.com"]

    def test_comma_separated(self):
        result = _normalize_recipients(["a@b.com,c@d.com"])
        assert result == ["a@b.com", "c@d.com"]

    def test_whitespace_trimmed(self):
        result = _normalize_recipients(["  a@b.com , c@d.com  "])
        assert result == ["a@b.com", "c@d.com"]

    def test_blank_entries_removed(self):
        result = _normalize_recipients(["a@b.com,,, ,c@d.com"])
        assert result == ["a@b.com", "c@d.com"]

    def test_duplicate_removal_case_insensitive(self):
        result = _normalize_recipients(["A@B.COM", "a@b.com", "C@D.com"])
        assert result == ["A@B.COM", "C@D.com"]

    def test_preserves_order(self):
        result = _normalize_recipients(["z@z.com", "a@a.com", "m@m.com"])
        assert result == ["z@z.com", "a@a.com", "m@m.com"]

    def test_empty_input(self):
        assert _normalize_recipients([]) == []
        assert _normalize_recipients([""]) == []
        assert _normalize_recipients(["  ", " , "]) == []


# ===================================================================
# _resolve_recipients  (precedence tests)
# ===================================================================

class TestResolveRecipients:
    def test_env_recipients_wins_over_all(self):
        config = _make_config(
            recipient_email="yaml_single@x.com",
            recipient_emails=["yaml_list@x.com"],
        )
        env = {
            "JOBWATCH_EMAIL_RECIPIENTS": "env_multi@x.com",
            "JOBWATCH_EMAIL_RECIPIENT": "env_single@x.com",
        }
        assert _resolve_recipients(config, env) == ["env_multi@x.com"]

    def test_env_recipient_wins_over_yaml(self):
        config = _make_config(
            recipient_email="yaml_single@x.com",
            recipient_emails=["yaml_list@x.com"],
        )
        env = {"JOBWATCH_EMAIL_RECIPIENT": "env_single@x.com"}
        assert _resolve_recipients(config, env) == ["env_single@x.com"]

    def test_yaml_list_wins_over_yaml_single(self):
        config = _make_config(
            recipient_email="yaml_single@x.com",
            recipient_emails=["list1@x.com", "list2@x.com"],
        )
        result = _resolve_recipients(config, {})
        assert result == ["list1@x.com", "list2@x.com"]

    def test_yaml_single_fallback(self):
        config = _make_config(recipient_email="solo@x.com")
        assert _resolve_recipients(config, {}) == ["solo@x.com"]

    def test_empty_when_nothing_set(self):
        config = _make_config()
        assert _resolve_recipients(config, {}) == []

    def test_env_recipients_comma_separated(self):
        config = _make_config()
        env = {"JOBWATCH_EMAIL_RECIPIENTS": "a@b.com, c@d.com, e@f.com"}
        result = _resolve_recipients(config, env)
        assert result == ["a@b.com", "c@d.com", "e@f.com"]

    def test_blank_env_recipients_falls_through(self):
        """Empty JOBWATCH_EMAIL_RECIPIENTS should NOT block lower sources."""
        config = _make_config(recipient_email="fallback@x.com")
        env = {"JOBWATCH_EMAIL_RECIPIENTS": "   "}
        assert _resolve_recipients(config, env) == ["fallback@x.com"]


# ===================================================================
# validate_email_settings
# ===================================================================

class TestValidateEmailSettings:
    def test_single_recipient_from_env(self):
        config = _make_config()
        env = _base_env(JOBWATCH_EMAIL_RECIPIENT="recip@example.com")
        settings = validate_email_settings(config, env=env)

        assert settings["recipients"] == ["recip@example.com"]
        assert settings["recipient_email"] == "recip@example.com"

    def test_multiple_recipients_from_env(self):
        config = _make_config()
        env = _base_env(JOBWATCH_EMAIL_RECIPIENTS="a@x.com, b@x.com")
        settings = validate_email_settings(config, env=env)

        assert settings["recipients"] == ["a@x.com", "b@x.com"]
        assert settings["recipient_email"] == "a@x.com"  # first one

    def test_env_overrides_yaml(self):
        config = _make_config(
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_user="configuser@example.com",
            sender_email="configsender@example.com",
            recipient_email="configrecip@example.com",
        )
        env = _base_env(
            JOBWATCH_EMAIL_SENDER="envsender@example.com",
            JOBWATCH_EMAIL_RECIPIENT="envrecip@example.com",
        )
        settings = validate_email_settings(config, env=env)

        assert settings["smtp_host"] == "smtp.example.com"
        assert settings["smtp_port"] == 465
        assert settings["smtp_user"] == "configuser@example.com"
        assert settings["sender_email"] == "envsender@example.com"
        assert settings["recipients"] == ["envrecip@example.com"]
        assert settings["subject_prefix"] == "Test Subject"

    def test_missing_password_raises(self):
        config = _make_config(recipient_email="r@x.com")
        with pytest.raises(ValueError, match="smtp_password"):
            validate_email_settings(config, env={})

    def test_missing_recipient_raises(self):
        config = _make_config()
        env = _base_env()
        with pytest.raises(ValueError, match="recipient_email"):
            validate_email_settings(config, env=env)

    def test_default_smtp_user_from_sender(self):
        config = _make_config(
            smtp_user="",
            sender_email="sender@example.com",
            recipient_email="r@example.com",
        )
        env = _base_env()
        settings = validate_email_settings(config, env=env)
        assert settings["smtp_user"] == "sender@example.com"

    def test_send_html_and_attach_markdown_passed_through(self):
        config = _make_config(
            send_html=False,
            attach_markdown=False,
            recipient_email="r@x.com",
        )
        env = _base_env()
        settings = validate_email_settings(config, env=env)
        assert settings["send_html"] is False
        assert settings["attach_markdown"] is False


# ===================================================================
# send_email_report — plain text only
# ===================================================================

class TestSendEmailReportPlainText:
    def test_dry_run_single_recipient(self):
        result = send_email_report(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test",
            smtp_password="test",
            sender_email="sender@example.com",
            recipients=["recip@example.com"],
            subject="Test Subject",
            plain_text_body="# Hello",
            dry_run=True,
        )
        assert result["sent"] is False
        assert result["dry_run"] is True
        assert result["recipients"] == ["recip@example.com"]
        assert result["recipient"] == "recip@example.com"
        assert result["subject"] == "Test Subject"
        assert result["html"] is False
        assert result["attachments"] == []

    def test_dry_run_multiple_recipients(self):
        result = send_email_report(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test",
            smtp_password="test",
            sender_email="sender@example.com",
            recipients=["a@x.com", "b@x.com", "c@x.com"],
            subject="Multi Test",
            plain_text_body="# Hello",
            dry_run=True,
        )
        assert result["recipients"] == ["a@x.com", "b@x.com", "c@x.com"]
        assert result["recipient"] == "a@x.com, b@x.com, c@x.com"
        assert result["dry_run"] is True

    def test_backward_compat_recipient_email_kwarg(self):
        """Legacy callers passing recipient_email= still work."""
        result = send_email_report(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test",
            smtp_password="test",
            sender_email="sender@example.com",
            recipient_email="legacy@example.com",
            subject="Legacy Test",
            plain_text_body="# Hello",
            dry_run=True,
        )
        assert result["recipients"] == ["legacy@example.com"]

    def test_backward_compat_markdown_body_kwarg(self):
        """Legacy callers passing markdown_body= still work."""
        result = send_email_report(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test",
            smtp_password="test",
            sender_email="sender@example.com",
            recipients=["r@x.com"],
            subject="Legacy Body",
            markdown_body="# Legacy body content",
            dry_run=True,
        )
        assert result["sent"] is False
        assert result["recipients"] == ["r@x.com"]

    def test_no_recipient_raises(self):
        with pytest.raises(ValueError, match="At least one recipient"):
            send_email_report(
                smtp_host="smtp.gmail.com",
                smtp_port=587,
                smtp_user="test",
                smtp_password="test",
                sender_email="sender@example.com",
                subject="Fail",
                plain_text_body="# Hello",
                dry_run=True,
            )


# ===================================================================
# send_email_report — HTML body (multipart/alternative)
# ===================================================================

class TestSendEmailReportHtml:
    def test_dry_run_with_html_body(self):
        result = send_email_report(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test",
            smtp_password="test",
            sender_email="sender@example.com",
            recipients=["r@x.com"],
            subject="HTML Test",
            plain_text_body="# Hello in plain text",
            html_body="<html><body><h1>Hello</h1></body></html>",
            dry_run=True,
        )
        assert result["html"] is True
        assert result["dry_run"] is True

    def test_no_html_body_flags_false(self):
        result = send_email_report(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test",
            smtp_password="test",
            sender_email="sender@example.com",
            recipients=["r@x.com"],
            subject="Plain Only",
            plain_text_body="# No HTML",
            dry_run=True,
        )
        assert result["html"] is False

    @patch("utils.email_sender.smtplib.SMTP")
    def test_smtp_sends_multipart(self, MockSMTP):
        """Verify send_message is called with the multipart message."""
        mock_server = MagicMock()
        MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
        MockSMTP.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email_report(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test",
            smtp_password="test",
            sender_email="sender@example.com",
            recipients=["a@x.com", "b@x.com"],
            subject="SMTP HTML Test",
            plain_text_body="Plain text fallback",
            html_body="<html><body><h1>Rich HTML</h1></body></html>",
            dry_run=False,
        )

        assert result["sent"] is True
        assert result["html"] is True
        assert result["recipients"] == ["a@x.com", "b@x.com"]
        mock_server.send_message.assert_called_once()

        # Inspect the actual message passed to send_message
        sent_msg = mock_server.send_message.call_args[0][0]
        msg_str = str(sent_msg)
        assert "multipart/alternative" in sent_msg.get_content_type() or "multipart" in msg_str.lower()


# ===================================================================
# send_email_report — attachments
# ===================================================================

class TestSendEmailReportAttachments:
    def test_multiple_attachments_dry_run(self, tmp_path):
        md_file = tmp_path / "report.md"
        md_file.write_text("# Report", encoding="utf-8")
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("Some notes", encoding="utf-8")

        result = send_email_report(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test",
            smtp_password="test",
            sender_email="sender@example.com",
            recipients=["r@x.com"],
            subject="Attach Test",
            plain_text_body="body",
            attachment_paths=[md_file, txt_file],
            dry_run=True,
        )
        assert result["attachments"] == ["report.md", "notes.txt"]
        assert result["attachment"] == "report.md"

    def test_missing_attachment_skipped(self, tmp_path):
        missing = tmp_path / "nonexistent.pdf"
        md_file = tmp_path / "report.md"
        md_file.write_text("# Report", encoding="utf-8")

        result = send_email_report(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test",
            smtp_password="test",
            sender_email="sender@example.com",
            recipients=["r@x.com"],
            subject="Missing File",
            plain_text_body="body",
            attachment_paths=[missing, md_file],
            dry_run=True,
        )
        # Only the existing file should be attached
        assert result["attachments"] == ["report.md"]

    def test_backward_compat_single_attachment_path(self, tmp_path):
        md_file = tmp_path / "report.md"
        md_file.write_text("# Report", encoding="utf-8")

        result = send_email_report(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test",
            smtp_password="test",
            sender_email="sender@example.com",
            recipients=["r@x.com"],
            subject="Legacy Attach",
            plain_text_body="body",
            attachment_path=md_file,
            dry_run=True,
        )
        assert result["attachments"] == ["report.md"]

    def test_no_attachments_result(self):
        result = send_email_report(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test",
            smtp_password="test",
            sender_email="sender@example.com",
            recipients=["r@x.com"],
            subject="No Attach",
            plain_text_body="body",
            dry_run=True,
        )
        assert result["attachments"] == []
        assert result["attachment"] is None

    @patch("utils.email_sender.smtplib.SMTP")
    def test_pdf_attachment_mime_type(self, MockSMTP, tmp_path):
        """PDF files should be attached as application/pdf."""
        mock_server = MagicMock()
        MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
        MockSMTP.return_value.__exit__ = MagicMock(return_value=False)

        pdf_file = tmp_path / "report.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")

        result = send_email_report(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test",
            smtp_password="test",
            sender_email="sender@example.com",
            recipients=["r@x.com"],
            subject="PDF MIME",
            plain_text_body="body",
            attachment_paths=[pdf_file],
            dry_run=False,
        )

        assert result["attachments"] == ["report.pdf"]
        # Check the actual message for application/pdf
        sent_msg = mock_server.send_message.call_args[0][0]
        msg_str = sent_msg.as_string()
        assert "application/pdf" in msg_str

    @patch("utils.email_sender.smtplib.SMTP")
    def test_markdown_attachment_mime_type(self, MockSMTP, tmp_path):
        """Markdown files should be attached as text/markdown."""
        mock_server = MagicMock()
        MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
        MockSMTP.return_value.__exit__ = MagicMock(return_value=False)

        md_file = tmp_path / "report.md"
        md_file.write_text("# Report content", encoding="utf-8")

        result = send_email_report(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="test",
            smtp_password="test",
            sender_email="sender@example.com",
            recipients=["r@x.com"],
            subject="MD MIME",
            plain_text_body="body",
            attachment_paths=[md_file],
            dry_run=False,
        )

        assert result["attachments"] == ["report.md"]
        sent_msg = mock_server.send_message.call_args[0][0]
        msg_str = sent_msg.as_string()
        assert "text/markdown" in msg_str


# ===================================================================
# send_email_report — security
# ===================================================================

class TestSendEmailReportSecurity:
    @patch("utils.email_sender.smtplib.SMTP")
    def test_smtp_password_not_in_error(self, MockSMTP):
        """Ensure the SMTP password is never leaked in error messages."""
        mock_server = MagicMock()
        mock_server.send_message.side_effect = Exception(
            "Error with password=SUPERSECRET123"
        )
        MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
        MockSMTP.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(RuntimeError, match=r"\*\*\*\*"):
            send_email_report(
                smtp_host="smtp.gmail.com",
                smtp_port=587,
                smtp_user="test",
                smtp_password="SUPERSECRET123",
                sender_email="sender@example.com",
                recipients=["a@x.com"],
                subject="Leak Test",
                plain_text_body="# Hello",
                dry_run=False,
            )


# ===================================================================
# End-to-end: validate_email_settings → send_email_report
# ===================================================================

class TestEndToEnd:
    def test_yaml_list_recipients_dry_run(self):
        config = _make_config(
            recipient_emails=["p1@g.com", "p2@g.com"],
        )
        env = _base_env()
        settings = validate_email_settings(config, env=env)

        result = send_email_report(
            smtp_host=settings["smtp_host"],
            smtp_port=settings["smtp_port"],
            smtp_user=settings["smtp_user"],
            smtp_password=settings["smtp_password"],
            sender_email=settings["sender_email"],
            recipients=settings["recipients"],
            subject="E2E",
            plain_text_body="body",
            dry_run=True,
        )
        assert result["recipients"] == ["p1@g.com", "p2@g.com"]
        assert result["dry_run"] is True

    def test_env_recipients_dedup_and_trim(self):
        config = _make_config()
        env = _base_env(
            JOBWATCH_EMAIL_RECIPIENTS=" a@b.com , A@B.COM , c@d.com , c@D.com "
        )
        settings = validate_email_settings(config, env=env)
        assert settings["recipients"] == ["a@b.com", "c@d.com"]

    def test_html_with_attachment_e2e(self, tmp_path):
        config = _make_config(recipient_email="r@x.com")
        env = _base_env()
        settings = validate_email_settings(config, env=env)

        md_file = tmp_path / "report.md"
        md_file.write_text("# Report", encoding="utf-8")

        result = send_email_report(
            smtp_host=settings["smtp_host"],
            smtp_port=settings["smtp_port"],
            smtp_user=settings["smtp_user"],
            smtp_password=settings["smtp_password"],
            sender_email=settings["sender_email"],
            recipients=settings["recipients"],
            subject="E2E HTML",
            plain_text_body="# Plain text",
            html_body="<html><body><h1>HTML</h1></body></html>",
            attachment_paths=[md_file],
            dry_run=True,
        )
        assert result["html"] is True
        assert result["attachments"] == ["report.md"]
        assert result["recipients"] == ["r@x.com"]
