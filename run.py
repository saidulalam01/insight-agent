#!/usr/bin/env python3
"""
Insight Agent — Entry point

Usage:
    python run.py --daily          Run daily digest and email it
    python run.py --weekly         Run weekly deep dive and email it
    python run.py --daily --dry    Run daily but only print to terminal (no email)
    python run.py --weekly --dry   Run weekly but only print to terminal (no email)
    python run.py --schedule       Run on schedule (daily 8am + weekly Monday 8am)
"""

import argparse
import sys
import os
from datetime import datetime

# Ensure we can import from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_daily(dry_run=False):
    from insights import run_daily_insights
    from report import build_report
    from mailer import send_report

    print(f"\n{'='*60}")
    print(f"  DAILY INSIGHT DIGEST — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    print("[1/3] Running daily insight queries...")
    insights = run_daily_insights()

    print("[2/3] Building report...")
    html, alerts = build_report(insights, report_type="daily")

    # Print summary to terminal
    alert_count = len(alerts)
    print(f"\n  Alerts found: {alert_count}")
    for section, alert_text in alerts:
        print(f"  ⚠  [{section}] {alert_text}")

    if not alerts:
        print("  ✓  All metrics within normal range")

    # Save HTML locally
    out_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(out_dir, exist_ok=True)
    filename = f"daily_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    filepath = os.path.join(out_dir, filename)
    with open(filepath, "w") as f:
        f.write(html)
    print(f"\n  Report saved: {filepath}")

    # Send email
    if not dry_run:
        print("\n[3/3] Sending email...")
        subject = f"{'🚨 ' if alert_count > 0 else ''}Daily Insight Digest — {datetime.now().strftime('%b %d')}"
        plain = "\n".join(f"[{s}] {t}" for s, t in alerts) if alerts else "All metrics normal."
        send_report(subject, html, plain)
    else:
        print("\n[3/3] Dry run — email skipped.")

    print(f"\nDone.\n")
    return alerts


def run_weekly(dry_run=False):
    from insights import run_weekly_insights
    from report import build_report
    from mailer import send_report

    print(f"\n{'='*60}")
    print(f"  WEEKLY DEEP DIVE — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    print("[1/3] Running weekly insight queries (this may take a moment)...")
    insights = run_weekly_insights()

    print("[2/3] Building report...")
    html, alerts = build_report(insights, report_type="weekly")

    alert_count = len(alerts)
    print(f"\n  Alerts found: {alert_count}")
    for section, alert_text in alerts:
        print(f"  ⚠  [{section}] {alert_text}")

    if not alerts:
        print("  ✓  All metrics within normal range")

    out_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(out_dir, exist_ok=True)
    filename = f"weekly_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    filepath = os.path.join(out_dir, filename)
    with open(filepath, "w") as f:
        f.write(html)
    print(f"\n  Report saved: {filepath}")

    if not dry_run:
        print("\n[3/3] Sending email...")
        subject = f"{'🚨 ' if alert_count > 0 else '📊 '}Weekly Deep Dive — Week of {datetime.now().strftime('%b %d')}"
        plain = "\n".join(f"[{s}] {t}" for s, t in alerts) if alerts else "All metrics normal."
        send_report(subject, html, plain)
    else:
        print("\n[3/3] Dry run — email skipped.")

    print(f"\nDone.\n")
    return alerts


def run_scheduled():
    import schedule
    import time

    print("Insight Agent — Scheduled Mode")
    print("  Daily digest:  Every day at 08:00")
    print("  Weekly report:  Every Monday at 08:00")
    print("  Press Ctrl+C to stop\n")

    schedule.every().day.at("08:00").do(run_daily)
    schedule.every().monday.at("08:00").do(run_weekly)

    while True:
        schedule.run_pending()
        time.sleep(60)


def main():
    parser = argparse.ArgumentParser(description="Insight Agent — Database analytics and reporting")
    parser.add_argument("--daily", action="store_true", help="Run daily digest")
    parser.add_argument("--weekly", action="store_true", help="Run weekly deep dive")
    parser.add_argument("--schedule", action="store_true", help="Run on auto-schedule (daily + weekly)")
    parser.add_argument("--dry", action="store_true", help="Dry run — skip email, print to terminal only")

    args = parser.parse_args()

    if not any([args.daily, args.weekly, args.schedule]):
        parser.print_help()
        print("\nExamples:")
        print("  python run.py --daily --dry     # Test daily report (no email)")
        print("  python run.py --weekly --dry     # Test weekly report (no email)")
        print("  python run.py --daily            # Run daily + send email")
        print("  python run.py --schedule         # Auto-run on schedule")
        sys.exit(1)

    if args.schedule:
        run_scheduled()
    else:
        if args.daily:
            run_daily(dry_run=args.dry)
        if args.weekly:
            run_weekly(dry_run=args.dry)


if __name__ == "__main__":
    main()
