# Alert & Reporting System

## The Question

How do we detect anomalies in daily metrics without someone manually checking dashboards? And how do we deliver those anomalies to stakeholders who won't log into a dashboard?

## Architecture

The alert system has three layers:

```
config.py (thresholds)
    ↓
insights.py (anomaly detection)
    ↓
report.py (HTML rendering)
    ↓
run.py (scheduler + email)
```

Each layer has a single responsibility and can be tested independently.

## Anomaly Detection (insights.py)

Every check function follows the same contract:

```python
def revenue_daily():
    # 1. Query last 14 days
    df = run_query("SELECT date, revenue FROM ...")

    # 2. Compute rolling average
    df["rolling_7d_avg"] = df["revenue"].rolling(7, min_periods=3).mean()

    # 3. Compare latest value to average
    latest = df.iloc[-1]
    avg = latest["rolling_7d_avg"]
    pct_change = ((latest["revenue"] - avg) / avg) * 100

    # 4. Generate alerts if threshold breached
    alerts = []
    if pct_change < -THRESHOLDS["revenue_drop_pct"]:
        alerts.append(f"Revenue dropped {abs(pct_change):.1f}% vs 7-day avg")

    return {"data": df, "alerts": alerts}
```

### Daily Checks

| Check | Threshold | Alert Condition |
|---|---|---|
| Revenue | 15% drop | Yesterday's revenue is >15% below 7-day rolling average |
| Revenue | Zero | Any day with $0 revenue |
| Signups | 20% drop | Yesterday's signups are >20% below 7-day rolling average |
| Payouts | 30% spike | Yesterday's payouts are >30% above 7-day rolling average |
| Refund rate | 5% | Refunded orders exceed 5% of total orders |

### Weekly Checks (added to the weekly report)

| Check | Alert Condition |
|---|---|
| Revenue trend | 3+ consecutive weeks of WoW decline |
| Conversion funnel | Signup-to-purchase conversion dropped >10% WoW |
| Payout-to-revenue ratio | Latest week's ratio is >30% above 8-week average |
| Data freshness | Any key table's latest record is >2 days old |

### Design Decisions

**Rolling average, not fixed benchmarks.** A fixed "$100K daily revenue" threshold becomes stale as the business grows. A rolling 7-day average adapts automatically.

**`min_periods=3` on the rolling window.** The rolling average requires at least 3 data points before generating alerts. This prevents false positives in the first few days of operation or after data gaps.

**Asymmetric thresholds.** Revenue drops trigger at 15% but payouts spike at 30%. Revenue is more stable and a 15% drop is genuinely concerning. Payouts are naturally volatile (large individual payouts) so the threshold is higher to avoid noise.

**Consecutive decline detection (weekly revenue):**

```python
consecutive_drops = 0
for i in range(len(revenues) - 1, 0, -1):
    if revenues[i] < revenues[i - 1]:
        consecutive_drops += 1
    else:
        break
if consecutive_drops >= 3:
    alerts.append(f"Revenue has declined {consecutive_drops} consecutive weeks")
```

A single bad week is noise. Three consecutive declining weeks is a trend that demands attention.

**Data freshness check.** Queries 6 key tables for `MAX(created_at)` and alerts if any is >2 days stale. This catches data pipeline failures before they corrupt analytics.

## Report Rendering (report.py)

The report builder transforms insight output into self-contained HTML emails.

### Severity Classification

Alert messages are classified by keyword:

```python
text_lower = alert_text.lower()
if any(word in text_lower for word in ["drop", "decline", "zero", "stale", "error"]):
    badge = "ALERT"   # Red
elif any(word in text_lower for word in ["spike", "high"]):
    badge = "WARNING"  # Orange
else:
    badge = "INFO"     # Blue
```

Keyword-based rather than structured severity because alert messages are free-text. Pragmatic tradeoff: adding a new alert just requires writing a message with the right keywords.

### SVG Sparklines

Trend visualization using inline SVG (no external dependencies, no image attachments):

```python
points = " ".join(
    f"{i * step},{height - ((v - min_val) / range) * (height - 4) - 2}"
    for i, v in enumerate(values)
)
color = "#28a745" if values[-1] >= values[0] else "#dc3545"
```

Green if trending up from start, red if trending down. Renders in every email client that supports SVG.

### Report Sections

| Section | Daily | Weekly |
|---|---|---|
| Alert banner (red/green) | Yes | Yes |
| Revenue + sparkline | Yes | Yes |
| Signups + sparkline | Yes | Yes |
| Breaches by reason | Yes | Yes |
| Payouts + sparkline | Yes | Yes |
| Order status breakdown | Yes | Yes |
| 8-week revenue trend | | Yes |
| Conversion funnel | | Yes |
| Top 15 countries WoW | | Yes |
| Payout-to-revenue ratio | | Yes |
| Revenue by plan | | Yes |
| Data pipeline health | | Yes |

## Scheduling (run.py)

### Execution Modes

```bash
python run.py --daily       # Run daily report now
python run.py --weekly      # Run weekly report now
python run.py --dry         # Run but don't email (for testing)
python run.py --schedule    # Run as daemon (daily at 08:00, weekly on Monday)
```

### Pipeline

```python
# 1. Run insights
insights = run_daily_insights()  # or run_weekly_insights()

# 2. Build HTML
html, alerts = build_daily_report(insights)  # or build_weekly_report()

# 3. Save locally (always, regardless of email)
with open(f"reports/daily_{timestamp}.html", "w") as f:
    f.write(html)

# 4. Send email (unless --dry)
if not dry_run:
    send_report(subject, html, recipients)
```

Reports are always saved to `reports/` as an audit trail, even if email delivery fails.

### Alert-Conditioned Subject Line

```python
subject = f"{'⚠️ ' if alert_count > 0 else '📊 '}Daily Insight Digest — {date}"
```

The emoji prefix makes alert emails stand out in an inbox without requiring the recipient to open the email.

## Threshold Configuration (config.py)

```python
THRESHOLDS = {
    "revenue_drop_pct": 15,
    "signup_drop_pct": 20,
    "payout_spike_pct": 30,
    "breach_rate_threshold": 95,
    "conversion_drop_pct": 10,
    "zero_revenue_alert": True,
}
```

Thresholds are **hard-coded in config.py**, not in `.env`. This is intentional — they represent analytical judgments that should be version-controlled and reviewed in code review, not silently changed via environment variables.

## What This Revealed

- **Zero-revenue alerts caught a data pipeline issue** within hours of deployment. A stale ETL job had stopped populating the orders table, and the zero-revenue alert fired before anyone noticed the dashboard was blank.

- **The consecutive-decline detector** surfaced a gradual revenue erosion that wasn't visible in daily reports (each day's drop was within the 15% threshold), but 4 consecutive weeks of decline triggered the weekly alert.

- **Payout ratio drift** identified a period where the payout-to-revenue ratio crept from 22% to 31% over 6 weeks. The weekly alert flagged it when it crossed the threshold, giving the finance team time to investigate before it became a cash flow problem.
