import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env from parent directory and local .env
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent / ".env", override=True)

# Database
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

# Email
EMAIL_CONFIG = {
    "smtp_host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
    "smtp_port": int(os.getenv("SMTP_PORT", 587)),
    "sender_email": os.getenv("SENDER_EMAIL"),
    "sender_password": os.getenv("SENDER_PASSWORD"),
    "recipients": [e.strip() for e in os.getenv("REPORT_RECIPIENTS", "").split(",") if e.strip()],
}

# Thresholds for alerts
THRESHOLDS = {
    "revenue_drop_pct": 15,        # Alert if daily revenue drops >15% vs 7-day avg
    "signup_drop_pct": 20,         # Alert if signups drop >20% vs 7-day avg
    "payout_spike_pct": 30,        # Alert if payouts spike >30% vs 7-day avg
    "breach_rate_threshold": 95,   # Alert if breach rate exceeds 95%
    "conversion_drop_pct": 10,     # Alert if funnel conversion drops >10%
    "zero_revenue_alert": True,    # Alert if any day has zero revenue
}
