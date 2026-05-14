#!/usr/bin/env python3
"""Email sender module for blog-analysis agents.
Sends via Resend.com API (HTTPS), falls back to local file save.
SMTP is also attempted as secondary method.
"""

import json
import os
import re
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

ARCHIVE_DIR = "/root/blog-analysis/agents/email_archive"


def _save_local(subject, body, html=None):
    """Save email locally as fallback."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    if html:
        fname = f"mail_{ts}.html"
        content = html
    else:
        fname = f"mail_{ts}.txt"
        content = f"Subject: {subject}\n\n{body}"
    path = os.path.join(ARCHIVE_DIR, fname)
    with open(path, "w") as f:
        f.write(content)
    print(f"[mailer] Email saved locally: {path}")


def load_config(path=None):
    """Load email config from .mailcfg file or environment variables."""
    if path is None:
        for p in [
            Path(__file__).parent.parent / "agents" / ".mailcfg",
            Path("/root/blog-analysis/agents/.mailcfg"),
            Path(".mailcfg"),
        ]:
            if p.exists():
                path = p
                break

    if path and Path(path).exists():
        with open(path) as f:
            cfg = json.load(f)
        return cfg

    return {
        "smtp_host": os.environ.get("MAIL_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.environ.get("MAIL_PORT", 587)),
        "username": os.environ.get("MAIL_USER"),
        "password": os.environ.get("MAIL_PASS"),
        "resend_api_key": os.environ.get("RESEND_API_KEY"),
        "from_addr": os.environ.get("MAIL_FROM", os.environ.get("MAIL_USER")),
        "to_addr": os.environ.get("MAIL_TO"),
    }


def send(subject, body, html=None, attachments=None, cfg=None, config_path=None, in_reply_to=None, references=None):
    """Send an email. Tries Resend API first, then SMTP, then local save."""
    if cfg is None:
        cfg = load_config(config_path)

    # 1. Try Resend API via HTTPS
    if cfg.get("resend_api_key"):
        if _send_resend(cfg["resend_api_key"], subject, body, html, attachments, cfg, in_reply_to, references):
            return True
    else:
        print("[mailer] No resend_api_key configured, skipping Resend API")

    # 2. Try SMTP
    if _send_smtp(subject, body, html, attachments, cfg):
        return True

    # 3. Fallback: save locally
    _save_local(subject, body, html)
    return False


def _send_resend(api_key, subject, body, html=None, attachments=None, cfg=None, in_reply_to=None, references=None):
    """Send via Resend.com HTTPS API."""
    try:
        import requests as req
    except ImportError:
        print("[mailer] requests not installed, skipping Resend API")
        return False

    payload = {
        "from": "onboarding@resend.dev",
        "to": [cfg.get("to_addr", "eddy.super1@gmail.com")],
        "subject": subject,
        "text": body,
    }
    if html:
        payload["html"] = html
    headers = {}
    if in_reply_to:
        headers["In-Reply-To"] = in_reply_to
    if references:
        headers["References"] = references
    if headers:
        payload["headers"] = headers

    if attachments:
        file_attachments = []
        for filepath in attachments:
            fpath = Path(filepath)
            if fpath.is_dir():
                continue
            try:
                with open(fpath, "rb") as f:
                    import base64
                    b64 = base64.b64encode(f.read()).decode()
                file_attachments.append({
                    "filename": fpath.name,
                    "content": b64,
                })
            except Exception as e:
                print(f"[mailer] Failed to read attachment {filepath}: {e}")
        if file_attachments:
            payload["attachments"] = file_attachments

    try:
        r = req.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        if r.status_code == 200:
            print(f"[mailer] Resend sent: {subject}")
            return True
        else:
            print(f"[mailer] Resend API error {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        print(f"[mailer] Resend API exception: {e}")
        return False


def _send_smtp(subject, body, html=None, attachments=None, cfg=None):
    """Internal SMTP send. Returns True on success, False on failure."""
    if not cfg.get("username") or not cfg.get("password"):
        return False

    msg = MIMEMultipart()
    msg["From"] = cfg.get("from_addr", cfg["username"])
    msg["To"] = cfg.get("to_addr")
    msg["Subject"] = subject

    if html:
        msg.attach(MIMEText(html, "html"))
    msg.attach(MIMEText(body, "plain"))

    if attachments:
        for filepath in attachments:
            fpath = Path(filepath)
            if fpath.is_dir():
                continue
            try:
                with open(fpath, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={fpath.name}",
                    )
                    msg.attach(part)
            except Exception as e:
                print(f"[mailer] Failed to attach {filepath}: {e}")

    try:
        server = smtplib.SMTP(cfg["smtp_host"], cfg.get("smtp_port", 587), timeout=5)
        server.starttls()
        server.login(cfg["username"], cfg["password"])
        server.send_message(msg)
        server.quit()
        print(f"[mailer] SMTP sent: {subject}")
        return True
    except Exception as e:
        print(f"[mailer] SMTP FAILED ({type(e).__name__}): {e}")
        return False


def send_report(subject, markdown_body, attachments=None, cfg=None):
    """Send a markdown report as a formatted email."""
    plain = re.sub(r"\*\*(.*?)\*\*", r"\1", markdown_body)
    plain = re.sub(r"#{1,6}\s+", "", plain)
    plain = re.sub(r"`([^`]+)`", r"\1", plain)
    plain = re.sub(r"\|.*\|", "", plain)
    plain = re.sub(r"^[-*]\s+", "  \u2022 ", plain, flags=re.MULTILINE)
    plain = re.sub(r"\n{3,}", "\n\n", plain).strip()
    return send(subject, plain, attachments=attachments, cfg=cfg)


if __name__ == "__main__":
    cfg = load_config()
    send("Test from blog-analysis", "This is a test message via Resend.", cfg=cfg)
