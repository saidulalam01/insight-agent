"""
Builds an HTML email report from insight results.
"""

from datetime import datetime
import pandas as pd


def _severity_badge(text):
    if any(w in text.upper() for w in ["DROP", "DECLINE", "ZERO", "STALE", "ERROR"]):
        return '<span style="background:#dc3545;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">ALERT</span>'
    elif any(w in text.upper() for w in ["SPIKE", "HIGH"]):
        return '<span style="background:#fd7e14;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">WARNING</span>'
    return '<span style="background:#0d6efd;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">INFO</span>'


def _df_to_html(df, max_rows=15):
    if df is None or df.empty:
        return '<p style="color:#888;">No data available</p>'
    df_display = df.head(max_rows).copy()
    for col in df_display.columns:
        if df_display[col].dtype in ["float64", "float32"]:
            df_display[col] = df_display[col].apply(lambda x: f"{x:,.2f}" if pd.notna(x) else "—")
    return df_display.to_html(index=False, border=0, classes="data-table")


def _sparkline(values, width=200, height=40):
    """Simple SVG sparkline."""
    if not values or len(values) < 2:
        return ""
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return ""
    mn, mx = min(vals), max(vals)
    rng = mx - mn if mx != mn else 1
    step = width / (len(vals) - 1)
    points = " ".join(
        f"{i * step},{height - ((v - mn) / rng) * (height - 4) - 2}" for i, v in enumerate(vals)
    )
    color = "#28a745" if vals[-1] >= vals[0] else "#dc3545"
    return f'''<svg width="{width}" height="{height}" style="vertical-align:middle;">
        <polyline fill="none" stroke="{color}" stroke-width="2" points="{points}"/>
        <circle cx="{(len(vals)-1)*step}" cy="{height - ((vals[-1]-mn)/rng)*(height-4)-2}" r="3" fill="{color}"/>
    </svg>'''


def build_report(insights, report_type="daily"):
    """Build full HTML email report."""
    now = datetime.now()
    title = f"{'Weekly Deep Dive' if report_type == 'weekly' else 'Daily Digest'} — {now.strftime('%B %d, %Y')}"

    # Collect all alerts
    all_alerts = []
    for section_name, section_data in insights.items():
        if isinstance(section_data, dict) and "alerts" in section_data:
            for alert in section_data["alerts"]:
                all_alerts.append((section_name, alert))

    alert_count = len(all_alerts)
    alert_color = "#dc3545" if alert_count > 0 else "#28a745"

    html = f"""<!DOCTYPE html>
<html>
<head>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; margin: 0; padding: 20px; color: #333; }}
    .container {{ max-width: 700px; margin: 0 auto; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: #fff; padding: 28px 32px; }}
    .header h1 {{ margin: 0 0 4px 0; font-size: 22px; font-weight: 600; }}
    .header p {{ margin: 0; opacity: 0.7; font-size: 14px; }}
    .alert-banner {{ background: {alert_color}; color: #fff; padding: 12px 32px; font-size: 14px; font-weight: 500; }}
    .content {{ padding: 24px 32px; }}
    .section {{ margin-bottom: 28px; }}
    .section h2 {{ font-size: 16px; color: #1a1a2e; margin: 0 0 12px 0; padding-bottom: 8px; border-bottom: 2px solid #e9ecef; }}
    .alert-item {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 10px 14px; margin: 8px 0; border-radius: 0 6px 6px 0; font-size: 13px; }}
    .alert-item.critical {{ background: #f8d7da; border-left-color: #dc3545; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin: 12px 0; }}
    .metric-card {{ background: #f8f9fa; border-radius: 8px; padding: 14px; text-align: center; }}
    .metric-card .value {{ font-size: 22px; font-weight: 700; color: #1a1a2e; }}
    .metric-card .label {{ font-size: 11px; color: #888; text-transform: uppercase; margin-top: 4px; }}
    .data-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    .data-table th {{ background: #f8f9fa; padding: 8px 12px; text-align: left; font-weight: 600; font-size: 11px; text-transform: uppercase; color: #666; }}
    .data-table td {{ padding: 8px 12px; border-bottom: 1px solid #f0f0f0; }}
    .data-table tr:hover td {{ background: #f8f9fa; }}
    .footer {{ padding: 16px 32px; background: #f8f9fa; text-align: center; font-size: 12px; color: #999; }}
    .trend-up {{ color: #28a745; }} .trend-down {{ color: #dc3545; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>{title}</h1>
        <p>Automated insight report from your data warehouse</p>
    </div>
    <div class="alert-banner">
        {'&#9888; ' + str(alert_count) + ' alert(s) detected — review below' if alert_count > 0 else '&#10003; All metrics within normal range'}
    </div>
    <div class="content">
"""

    # --- ALERTS SECTION ---
    if all_alerts:
        html += '<div class="section"><h2>Alerts & Anomalies</h2>'
        for section_name, alert_text in all_alerts:
            is_critical = any(w in alert_text.upper() for w in ["DROP", "DECLINE", "ZERO", "STALE"])
            html += f'<div class="alert-item {"critical" if is_critical else ""}">{_severity_badge(alert_text)} {alert_text}</div>'
        html += "</div>"

    # --- REVENUE ---
    rev = insights.get("revenue", {})
    rev_data = rev.get("data", pd.DataFrame())
    if not rev_data.empty:
        yesterday_rev = rev_data.iloc[-1]["revenue"] if len(rev_data) > 0 else 0
        yesterday_orders = rev_data.iloc[-1]["orders"] if len(rev_data) > 0 else 0
        avg_rev = rev_data["revenue"].mean()
        html += f'''<div class="section"><h2>Revenue</h2>
            <div class="metric-grid">
                <div class="metric-card"><div class="value">${float(yesterday_rev):,.0f}</div><div class="label">Yesterday</div></div>
                <div class="metric-card"><div class="value">{int(yesterday_orders):,}</div><div class="label">Orders</div></div>
                <div class="metric-card"><div class="value">${float(avg_rev):,.0f}</div><div class="label">14-Day Avg</div></div>
            </div>
            <div style="text-align:center;margin:8px 0;">{_sparkline(rev_data["revenue"].tolist(), 400, 50)}</div>
            {_df_to_html(rev_data)}
        </div>'''

    # --- SIGNUPS ---
    sig = insights.get("signups", {})
    sig_data = sig.get("data", pd.DataFrame())
    if not sig_data.empty:
        yesterday_signups = sig_data.iloc[-1]["signups"] if len(sig_data) > 0 else 0
        avg_signups = sig_data["signups"].mean()
        html += f'''<div class="section"><h2>Signups</h2>
            <div class="metric-grid">
                <div class="metric-card"><div class="value">{int(yesterday_signups):,}</div><div class="label">Yesterday</div></div>
                <div class="metric-card"><div class="value">{int(avg_signups):,}</div><div class="label">14-Day Avg</div></div>
            </div>
            {_sparkline(sig_data["signups"].tolist(), 400, 50)}
        </div>'''

    # --- BREACHES ---
    breach = insights.get("breaches", {})
    breach_data = breach.get("data", pd.DataFrame())
    html += f'''<div class="section"><h2>Account Breaches (Yesterday)</h2>
        <div class="metric-card" style="display:inline-block;"><div class="value">{breach.get("total", 0):,}</div><div class="label">Total Breaches</div></div>
        {_df_to_html(breach_data)}
    </div>'''

    # --- PAYOUTS ---
    pay = insights.get("payouts", {})
    pay_data = pay.get("data", pd.DataFrame())
    if not pay_data.empty:
        yesterday_payout = pay_data.iloc[-1]["total_paid"] if len(pay_data) > 0 else 0
        html += f'''<div class="section"><h2>Payouts</h2>
            <div class="metric-card" style="display:inline-block;"><div class="value">${float(yesterday_payout):,.0f}</div><div class="label">Yesterday</div></div>
            {_sparkline(pay_data["total_paid"].tolist(), 400, 50)}
            {_df_to_html(pay_data)}
        </div>'''

    # --- ORDER STATUS ---
    os_data = insights.get("order_status", {}).get("data", pd.DataFrame())
    if not os_data.empty:
        html += f'<div class="section"><h2>Order Status (Yesterday)</h2>{_df_to_html(os_data)}</div>'

    # --- WEEKLY SECTIONS ---
    if report_type == "weekly":
        # Revenue Trend
        rt = insights.get("revenue_trend", {})
        rt_data = rt.get("data", pd.DataFrame())
        if not rt_data.empty:
            html += f'''<div class="section"><h2>Weekly Revenue Trend (8 Weeks)</h2>
                {_sparkline(rt_data["revenue"].tolist(), 500, 60)}
                {_df_to_html(rt_data)}
            </div>'''

        # Funnel
        fn = insights.get("funnel", {})
        fn_data = fn.get("data", pd.DataFrame())
        if not fn_data.empty:
            html += f'<div class="section"><h2>Conversion Funnel (Weekly)</h2>{_df_to_html(fn_data)}</div>'

        # Top Countries
        tc = insights.get("top_countries", {})
        tc_data = tc.get("data", pd.DataFrame())
        if not tc_data.empty:
            html += f'<div class="section"><h2>Top Countries by Revenue (This Week)</h2>{_df_to_html(tc_data)}</div>'

        # Payout Ratio
        pr = insights.get("payout_ratio", {})
        pr_data = pr.get("data", pd.DataFrame())
        if not pr_data.empty:
            html += f'''<div class="section"><h2>Payout vs Revenue Ratio</h2>
                {_df_to_html(pr_data)}
            </div>'''

        # Plan Breakdown
        pb = insights.get("plan_breakdown", {})
        pb_data = pb.get("data", pd.DataFrame())
        if not pb_data.empty:
            html += f'<div class="section"><h2>Revenue by Plan (This Week)</h2>{_df_to_html(pb_data)}</div>'

        # Data Freshness
        df_check = insights.get("data_freshness", {})
        df_data = df_check.get("data", pd.DataFrame())
        if not df_data.empty:
            html += f'<div class="section"><h2>Data Pipeline Health</h2>{_df_to_html(df_data)}</div>'

    html += f"""
    </div>
    <div class="footer">
        Generated at {now.strftime('%Y-%m-%d %H:%M:%S')} &middot; Insight Agent v1.0
    </div>
</div>
</body>
</html>"""

    return html, all_alerts
