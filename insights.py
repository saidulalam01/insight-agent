"""
Core insight engine — runs SQL queries against the database
and computes alerts, trends, and anomalies.
"""

import pandas as pd
from db import run_query, run_scalar
from config import THRESHOLDS


# ---------------------------------------------------------------------------
# DAILY INSIGHTS
# ---------------------------------------------------------------------------

def revenue_daily():
    """Revenue per day for the last 14 days, with 7-day rolling avg."""
    df = run_query("""
        SELECT
            DATE(created_at) AS date,
            COUNT(*)         AS orders,
            SUM(total_amount) AS revenue
        FROM core.purchases
        WHERE status = 1
          AND created_at >= CURRENT_DATE - INTERVAL '14 days'
        GROUP BY DATE(created_at)
        ORDER BY date
    """)
    if df.empty:
        return {"data": df, "alerts": ["No revenue data found for last 14 days"]}

    df["date"] = pd.to_datetime(df["date"])
    df["revenue"] = df["revenue"].astype(float)
    df["rolling_7d_avg"] = df["revenue"].rolling(7, min_periods=3).mean()

    alerts = []
    if len(df) >= 2:
        yesterday = df.iloc[-1]
        avg = df["rolling_7d_avg"].iloc[-1]
        if avg and avg > 0:
            pct_change = ((yesterday["revenue"] - avg) / avg) * 100
            if pct_change < -THRESHOLDS["revenue_drop_pct"]:
                alerts.append(
                    f"REVENUE DROP: Yesterday's revenue (${yesterday['revenue']:,.0f}) "
                    f"is {abs(pct_change):.1f}% below the 7-day avg (${avg:,.0f})"
                )
        if yesterday["revenue"] == 0 and THRESHOLDS["zero_revenue_alert"]:
            alerts.append("ZERO REVENUE: No completed orders yesterday!")

    return {"data": df, "alerts": alerts}


def signups_daily():
    """New customer signups per day for the last 14 days."""
    df = run_query("""
        SELECT
            DATE(created_at) AS date,
            COUNT(*)         AS signups
        FROM core.users
        WHERE created_at >= CURRENT_DATE - INTERVAL '14 days'
        GROUP BY DATE(created_at)
        ORDER BY date
    """)
    if df.empty:
        return {"data": df, "alerts": ["No signup data found"]}

    df["date"] = pd.to_datetime(df["date"])
    df["rolling_7d_avg"] = df["signups"].rolling(7, min_periods=3).mean()

    alerts = []
    if len(df) >= 2:
        yesterday = df.iloc[-1]
        avg = df["rolling_7d_avg"].iloc[-1]
        if avg and avg > 0:
            pct_change = ((yesterday["signups"] - avg) / avg) * 100
            if pct_change < -THRESHOLDS["signup_drop_pct"]:
                alerts.append(
                    f"SIGNUP DROP: Yesterday ({yesterday['signups']:,}) is "
                    f"{abs(pct_change):.1f}% below the 7-day avg ({avg:,.0f})"
                )

    return {"data": df, "alerts": alerts}


def breach_summary():
    """Account breaches yesterday, grouped by reason."""
    df = run_query("""
        SELECT
            violation_reason                    AS breach_reason,
            COUNT(*)                      AS count
        FROM core.user_accounts
        WHERE violated IS NOT NULL
          AND updated_at >= CURRENT_DATE - INTERVAL '1 day'
          AND updated_at < CURRENT_DATE
        GROUP BY violation_reason
        ORDER BY count DESC
    """)
    total = df["count"].sum() if not df.empty else 0

    alerts = []
    return {"data": df, "total": int(total), "alerts": alerts}


def payouts_daily():
    """Payout totals for the last 14 days."""
    df = run_query("""
        SELECT
            DATE(created_at)    AS date,
            COUNT(*)            AS payout_count,
            SUM(amount)         AS total_paid
        FROM core.auto_disbursements
        WHERE created_at >= CURRENT_DATE - INTERVAL '14 days'
        GROUP BY DATE(created_at)
        ORDER BY date
    """)
    if df.empty:
        return {"data": df, "alerts": ["No payout data in last 14 days"]}

    df["date"] = pd.to_datetime(df["date"])
    df["total_paid"] = df["total_paid"].astype(float).abs()
    df["rolling_7d_avg"] = df["total_paid"].rolling(7, min_periods=3).mean()

    alerts = []
    if len(df) >= 2:
        yesterday = df.iloc[-1]
        avg = df["rolling_7d_avg"].iloc[-1]
        if avg and avg > 0:
            pct_change = ((yesterday["total_paid"] - avg) / avg) * 100
            if pct_change > THRESHOLDS["payout_spike_pct"]:
                alerts.append(
                    f"PAYOUT SPIKE: Yesterday's payouts (${yesterday['total_paid']:,.0f}) "
                    f"are {pct_change:.1f}% above the 7-day avg (${avg:,.0f})"
                )

    return {"data": df, "alerts": alerts}


def order_status_breakdown():
    """Yesterday's order status breakdown (completed, failed, refunded)."""
    df = run_query("""
        SELECT
            CASE status
                WHEN 1 THEN 'Completed'
                WHEN 2 THEN 'Refunded'
                ELSE 'Failed/Pending'
            END AS status_label,
            COUNT(*) AS count,
            COALESCE(SUM(total_amount), 0) AS total_value
        FROM core.purchases
        WHERE created_at >= CURRENT_DATE - INTERVAL '1 day'
          AND created_at < CURRENT_DATE
        GROUP BY status
        ORDER BY count DESC
    """)
    df["total_value"] = df["total_value"].astype(float) if not df.empty else df["total_value"]

    alerts = []
    if not df.empty:
        refunded = df[df["status_label"] == "Refunded"]
        completed = df[df["status_label"] == "Completed"]
        if not refunded.empty and not completed.empty:
            refund_rate = refunded["count"].sum() / max(completed["count"].sum(), 1) * 100
            if refund_rate > 5:
                alerts.append(f"HIGH REFUND RATE: {refund_rate:.1f}% of completed orders were refunded yesterday")

    return {"data": df, "alerts": alerts}


# ---------------------------------------------------------------------------
# WEEKLY INSIGHTS
# ---------------------------------------------------------------------------

def revenue_weekly_trend():
    """Revenue by week for the last 8 weeks."""
    df = run_query("""
        SELECT
            DATE_TRUNC('week', created_at)::date AS week_start,
            COUNT(*)                              AS orders,
            SUM(total_amount)                      AS revenue
        FROM core.purchases
        WHERE status = 1
          AND created_at >= CURRENT_DATE - INTERVAL '8 weeks'
        GROUP BY DATE_TRUNC('week', created_at)
        ORDER BY week_start
    """)
    if df.empty:
        return {"data": df, "alerts": ["No weekly revenue data"]}

    df["revenue"] = df["revenue"].astype(float)

    alerts = []
    if len(df) >= 3:
        recent = df["revenue"].iloc[-1]
        prev = df["revenue"].iloc[-2]
        if prev > 0:
            wow_change = ((recent - prev) / prev) * 100
            if wow_change < -THRESHOLDS["revenue_drop_pct"]:
                alerts.append(
                    f"WEEKLY REVENUE DECLINE: This week (${recent:,.0f}) vs last week "
                    f"(${prev:,.0f}) = {wow_change:+.1f}%"
                )

        # Check for consecutive declines
        revenues = df["revenue"].tolist()
        consecutive_drops = 0
        for i in range(len(revenues) - 1, 0, -1):
            if revenues[i] < revenues[i - 1]:
                consecutive_drops += 1
            else:
                break
        if consecutive_drops >= 3:
            alerts.append(
                f"CONTINUOUS DECLINE: Revenue has dropped for {consecutive_drops} "
                f"consecutive weeks"
            )

    return {"data": df, "alerts": alerts}


def funnel_conversion():
    """Weekly funnel: Signups → Purchases → P2 Upgrades → Real Accounts."""
    df = run_query("""
        WITH weekly_signups AS (
            SELECT
                DATE_TRUNC('week', created_at)::date AS week_start,
                COUNT(*) AS signups
            FROM core.users
            WHERE created_at >= CURRENT_DATE - INTERVAL '8 weeks'
            GROUP BY 1
        ),
        weekly_purchases AS (
            SELECT
                DATE_TRUNC('week', created_at)::date AS week_start,
                COUNT(*) FILTER (WHERE order_type = 1)
                    AS new_purchases,
                COUNT(*) FILTER (WHERE order_type = 3)
                    AS phase_upgrades,
                SUM(total_amount) AS total_revenue
            FROM core.purchases
            WHERE status = 1
              AND created_at >= CURRENT_DATE - INTERVAL '8 weeks'
            GROUP BY 1
        ),
        weekly_accounts AS (
            SELECT
                DATE_TRUNC('week', created_at)::date AS week_start,
                COUNT(*) FILTER (WHERE type ILIKE '%P1%' OR type ILIKE '%Demo%')
                    AS p1_accounts,
                COUNT(*) FILTER (WHERE type ILIKE '%P2%')
                    AS p2_accounts,
                COUNT(*) FILTER (WHERE type ILIKE '%Real%')
                    AS real_accounts
            FROM core.user_accounts
            WHERE created_at >= CURRENT_DATE - INTERVAL '8 weeks'
            GROUP BY 1
        )
        SELECT
            COALESCE(s.week_start, p.week_start, a.week_start) AS week_start,
            COALESCE(s.signups, 0)        AS signups,
            COALESCE(p.new_purchases, 0)  AS purchases,
            COALESCE(p.phase_upgrades, 0) AS p2_upgrades,
            COALESCE(a.real_accounts, 0)  AS real_accounts,
            COALESCE(p.total_revenue, 0)  AS revenue
        FROM weekly_signups s
        FULL OUTER JOIN weekly_purchases p ON s.week_start = p.week_start
        FULL OUTER JOIN weekly_accounts a ON s.week_start = a.week_start
        ORDER BY week_start
    """)
    if df.empty:
        return {"data": df, "alerts": []}

    df["revenue"] = df["revenue"].astype(float)

    alerts = []
    if len(df) >= 2:
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        if prev["signups"] > 0 and latest["signups"] > 0:
            prev_conv = prev["purchases"] / prev["signups"] * 100
            curr_conv = latest["purchases"] / latest["signups"] * 100
            conv_change = curr_conv - prev_conv
            if conv_change < -THRESHOLDS["conversion_drop_pct"]:
                alerts.append(
                    f"CONVERSION DROP: Purchase conversion fell from {prev_conv:.1f}% "
                    f"to {curr_conv:.1f}% week-over-week"
                )

    return {"data": df, "alerts": alerts}


def top_countries_revenue():
    """Top 10 countries by revenue this week vs last week."""
    df = run_query("""
        SELECT
            co.name AS country,
            SUM(CASE WHEN o.created_at >= DATE_TRUNC('week', CURRENT_DATE)
                     THEN o.total_amount ELSE 0 END) AS this_week,
            SUM(CASE WHEN o.created_at >= DATE_TRUNC('week', CURRENT_DATE) - INTERVAL '1 week'
                      AND o.created_at < DATE_TRUNC('week', CURRENT_DATE)
                     THEN o.total_amount ELSE 0 END) AS last_week
        FROM core.purchases o
        JOIN core.users c ON o.user_id = c.id
        JOIN core.regions co ON c.country_id = co.id
        WHERE o.status = 1
          AND o.created_at >= DATE_TRUNC('week', CURRENT_DATE) - INTERVAL '1 week'
        GROUP BY co.name
        ORDER BY this_week DESC
        LIMIT 15
    """)
    if not df.empty:
        df["this_week"] = df["this_week"].astype(float)
        df["last_week"] = df["last_week"].astype(float)
        df["wow_change_pct"] = df.apply(
            lambda r: ((r["this_week"] - r["last_week"]) / r["last_week"] * 100)
            if r["last_week"] > 0 else None, axis=1
        )

    return {"data": df, "alerts": []}


def payout_vs_revenue():
    """Weekly payout-to-revenue ratio over last 8 weeks."""
    df = run_query("""
        WITH weekly_rev AS (
            SELECT
                DATE_TRUNC('week', created_at)::date AS week_start,
                SUM(total_amount) AS revenue
            FROM core.purchases
            WHERE status = 1
              AND created_at >= CURRENT_DATE - INTERVAL '8 weeks'
            GROUP BY 1
        ),
        weekly_payout AS (
            SELECT
                DATE_TRUNC('week', created_at)::date AS week_start,
                SUM(ABS(amount)) AS payouts
            FROM core.auto_disbursements
            WHERE created_at >= CURRENT_DATE - INTERVAL '8 weeks'
            GROUP BY 1
        )
        SELECT
            COALESCE(r.week_start, p.week_start) AS week_start,
            COALESCE(r.revenue, 0)   AS revenue,
            COALESCE(p.payouts, 0)   AS payouts
        FROM weekly_rev r
        FULL OUTER JOIN weekly_payout p ON r.week_start = p.week_start
        ORDER BY week_start
    """)
    if df.empty:
        return {"data": df, "alerts": []}

    df["revenue"] = df["revenue"].astype(float)
    df["payouts"] = df["payouts"].astype(float)
    df["payout_ratio_pct"] = df.apply(
        lambda r: (r["payouts"] / r["revenue"] * 100) if r["revenue"] > 0 else 0, axis=1
    )

    alerts = []
    if len(df) >= 2:
        latest_ratio = df["payout_ratio_pct"].iloc[-1]
        avg_ratio = df["payout_ratio_pct"].mean()
        if latest_ratio > avg_ratio * 1.3:
            alerts.append(
                f"PAYOUT RATIO HIGH: This week's payout ratio ({latest_ratio:.1f}%) "
                f"exceeds the 8-week avg ({avg_ratio:.1f}%) by >30%"
            )

    return {"data": df, "alerts": alerts}


def revenue_by_plan_size():
    """Revenue breakdown by account size (this week)."""
    df = run_query("""
        SELECT
            p.title                   AS plan,
            p."initialBalance"       AS account_size,
            COUNT(*)                  AS orders,
            SUM(o.total_amount)        AS revenue
        FROM core.purchases o
        JOIN core.user_accounts a ON o.account_id = a.id
        JOIN core.subscription_plans p ON a.plan_id = p.id
        WHERE o.status = 1
          AND o.created_at >= DATE_TRUNC('week', CURRENT_DATE)
        GROUP BY p.title, p."initialBalance"
        ORDER BY revenue DESC
        LIMIT 15
    """)
    if not df.empty:
        df["revenue"] = df["revenue"].astype(float)
        df["account_size"] = df["account_size"].astype(float)
    return {"data": df, "alerts": []}


def data_freshness():
    """Check if key tables have recent data — detect data pipeline gaps."""
    checks = {
        "core.purchases": "SELECT MAX(created_at) FROM core.purchases",
        "core.users": "SELECT MAX(created_at) FROM core.users",
        "core.user_accounts": "SELECT MAX(created_at) FROM core.user_accounts",
        "core.auto_disbursements": "SELECT MAX(created_at) FROM core.auto_disbursements",
        "analytics.trading_accounts": "SELECT MAX(created_at) FROM analytics.trading_accounts",
        "analytics.trading_accrual": "SELECT MAX(signup_date) FROM analytics.trading_accrual",
    }
    results = []
    alerts = []
    for table, sql in checks.items():
        try:
            latest = run_scalar(sql)
            results.append({"table": table, "latest_record": str(latest)})
            if latest:
                from datetime import datetime, timedelta
                if hasattr(latest, "date"):
                    age = datetime.now() - latest
                else:
                    age = datetime.now() - datetime.combine(latest, datetime.min.time())
                if age > timedelta(days=2):
                    alerts.append(f"STALE DATA: {table} — last record is {age.days} days old ({latest})")
        except Exception as e:
            results.append({"table": table, "latest_record": f"ERROR: {e}"})
            alerts.append(f"QUERY ERROR: {table} — {e}")

    df = pd.DataFrame(results)
    return {"data": df, "alerts": alerts}


# ---------------------------------------------------------------------------
# AGGREGATE RUNNERS
# ---------------------------------------------------------------------------

def run_daily_insights():
    """Run all daily insight checks and return structured results."""
    return {
        "revenue": revenue_daily(),
        "signups": signups_daily(),
        "breaches": breach_summary(),
        "payouts": payouts_daily(),
        "order_status": order_status_breakdown(),
    }


def run_weekly_insights():
    """Run all weekly deep-dive insights."""
    daily = run_daily_insights()
    weekly = {
        "revenue_trend": revenue_weekly_trend(),
        "funnel": funnel_conversion(),
        "top_countries": top_countries_revenue(),
        "payout_ratio": payout_vs_revenue(),
        "plan_breakdown": revenue_by_plan_size(),
        "data_freshness": data_freshness(),
    }
    return {**daily, **weekly}
