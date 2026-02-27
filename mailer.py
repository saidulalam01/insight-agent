"""
Email sender via SMTP (supports Gmail, Outlook, etc.)
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import EMAIL_CONFIG


def send_report(subject, html_body, plain_text_summary=""):
    """Send an HTML email report to configured recipients."""
    cfg = EMAIL_CONFIG

    if not cfg["sender_email"] or not cfg["sender_password"]:
        print("[MAILER] SMTP credentials not configured. Skipping email.")
        print(f"[MAILER] Set SENDER_EMAIL and SENDER_PASSWORD in .env")
        return False

    if not cfg["recipients"]:
        print("[MAILER] No recipients configured. Set REPORT_RECIPIENTS in .env")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["sender_email"]
    msg["To"] = ", ".join(cfg["recipients"])

    # Plain text fallback
    if plain_text_summary:
        msg.attach(MIMEText(plain_text_summary, "plain"))

    # HTML body
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
            server.starttls()
            server.login(cfg["sender_email"], cfg["sender_password"])
            server.sendmail(cfg["sender_email"], cfg["recipients"], msg.as_string())
        print(f"[MAILER] Report sent to {', '.join(cfg['recipients'])}")
        return True
    except Exception as e:
        print(f"[MAILER] Failed to send email: {e}")
        return False
