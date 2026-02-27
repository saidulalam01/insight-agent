"""Shared utilities used across multiple pages."""

import streamlit as st
import pandas as pd
from db import run_query, run_scalar


# ── Theme ──────────────────────────────────────────────────
_THEMES = {
    "dark": {
        "tbl_bg": "#12121e", "tbl_hdr_bg": "#0e0e1a",
        "tbl_border": "#2a2a3e", "tbl_row_border": "#1e1e30",
        "tbl_text": "#e0e0e0", "tbl_hdr_text": "#a0a8b4",
        "tbl_tot_bg": "#16162a", "tbl_tot_border": "#3a3a5e",
        "tbl_tot_text": "#ffffff",
        "card_bg": "linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)",
        "card_label": "#8b95a5", "card_title": "#e0e0e0", "card_body": "#c0c0c0",
        "badge_neutral_bg": "#333", "badge_neutral_text": "#ccc",
        "dur_bg": "#2d2d44", "dur_text": "#a0a0c0",
        "code_bg": "#0d1b2a", "code_border": "#4361ee", "code_text": "#4cc9f0",
        "title_text": "#e8e8e8", "body_text": "#b0b8c4", "date_text": "#8b95a5",
        "hl_pct": "#4cc9f0", "hl_dollar": "#f0c14c", "hl_model": "#a78bfa",
        "hl_term": "#f97316",
    },
    "light": {
        "tbl_bg": "#ffffff", "tbl_hdr_bg": "#f5f6fa",
        "tbl_border": "#dfe3ea", "tbl_row_border": "#ebedf2",
        "tbl_text": "#2c3e50", "tbl_hdr_text": "#6c7a8a",
        "tbl_tot_bg": "#f0f2f8", "tbl_tot_border": "#c5cad4",
        "tbl_tot_text": "#1a1a2e",
        "card_bg": "linear-gradient(135deg, #f0f4ff 0%, #e8edf5 100%)",
        "card_label": "#6c7a8a", "card_title": "#2c3e50", "card_body": "#4a5568",
        "badge_neutral_bg": "#e2e6ec", "badge_neutral_text": "#4a5568",
        "dur_bg": "#e2e6ec", "dur_text": "#5a6578",
        "code_bg": "#eef2ff", "code_border": "#4361ee", "code_text": "#2d4aab",
        "title_text": "#1a202c", "body_text": "#4a5568", "date_text": "#6c7a8a",
        "hl_pct": "#0e7490", "hl_dollar": "#b45309", "hl_model": "#6d28d9",
        "hl_term": "#c2410c",
    },
}


def get_theme():
    """Return the active theme dict based on session state."""
    return _THEMES[st.session_state.get("theme", "dark")]


# ── Generic cached runners ─────────────────────────────────
@st.cache_data(ttl=300)
def _qc(sql):
    """Cache-by-SQL: the SQL text IS the cache key."""
    return run_query(sql)


@st.cache_data(ttl=300)
def _qsc(sql):
    """Cache-by-SQL scalar variant."""
    return run_scalar(sql)


# ── Constants ──────────────────────────────────────────────
_NO_FUT = "AND a.type NOT ILIKE '%futures%' AND a.type NOT ILIKE '%platform-e%'"


# ── Helpers ────────────────────────────────────────────────
def metric_delta(current, previous):
    if previous and previous > 0:
        pct = ((current - previous) / previous) * 100
        return f"{pct:+.1f}%"
    if current and current > 0:
        return "New"
    return None


def safe_float(val):
    try:
        return float(val)
    except:
        return 0.0


def fmt_num(v, prefix="", suffix="", decimals=1):
    """Auto-format large numbers: 1234 -> 1.2K, 1234567 -> 1.2M, etc."""
    neg = v < 0
    v = abs(v)
    if v >= 1_000_000_000:
        s = f"{v / 1_000_000_000:.{decimals}f}B"
    elif v >= 1_000_000:
        s = f"{v / 1_000_000:.{decimals}f}M"
    elif v >= 10_000:
        s = f"{v / 1_000:.{decimals}f}K"
    elif isinstance(v, float) and v != int(v):
        s = f"{v:,.{max(decimals, 2)}f}"
    else:
        s = f"{int(v):,}"
    return f"{'-' if neg else ''}{prefix}{s}{suffix}"


# ── Retention Definition Constants ─────────────────────────
RETENTION_ORDER = [
    "First Purchase", "Acquisition Burst", "Weekly Retention", "Bi-weekly Retention",
    "Monthly Retention", "Quarterly Retention", "Bi-annual Retention",
    "Annual Retention", "Late Retention", "Reacquisition",
]

RETENTION_COLORS = {
    "First Purchase": "#4361ee",
    "Acquisition Burst": "#7209b7",
    "Weekly Retention": "#2a9d8f",
    "Bi-weekly Retention": "#4cc9f0",
    "Monthly Retention": "#e9c46a",
    "Quarterly Retention": "#f4a261",
    "Bi-annual Retention": "#e76f51",
    "Annual Retention": "#d62828",
    "Late Retention": "#6c757d",
    "Reacquisition": "#264653",
}

ORDER_TYPE_NAMES = {1: "Subscription", 2: "Reset", 3: "Topup"}


# ── Retention Query Functions ──────────────────────────────
def _build_retention_sql(start_date, end_date):
    return f"""
    WITH target_customers AS (
        SELECT DISTINCT o.user_id
        FROM core.purchases o
        JOIN core.user_accounts a ON o.account_id = a.id
        JOIN core.subscription_plans p ON a.plan_id = p.id
        WHERE o.status = 1
          AND o.created_at >= '{start_date}'::date
          AND o.created_at < '{end_date}'::date + 1
          AND p.category_id = 1
    ),
    customer_orders AS (
        SELECT o.user_id, o.id AS order_id, o.total_amount, o.order_type,
               o.created_at, o.account_id,
               MIN(o.created_at) OVER (PARTITION BY o.user_id) AS first_order_at,
               LAG(o.created_at) OVER (PARTITION BY o.user_id ORDER BY o.created_at, o.id) AS prev_order_at,
               ROW_NUMBER() OVER (PARTITION BY o.user_id ORDER BY o.created_at, o.id) AS order_seq
        FROM core.purchases o
        JOIN core.user_accounts a ON o.account_id = a.id
        JOIN core.subscription_plans p ON a.plan_id = p.id
        WHERE o.status = 1
          AND o.user_id IN (SELECT user_id FROM target_customers)
          AND p.category_id = 1
    )
    SELECT user_id, order_id, total_amount, order_type, created_at, account_id,
           DATE(created_at) AS order_date,
           order_seq,
           EXTRACT(EPOCH FROM (created_at - first_order_at)) / 86400.0 AS days_since_first,
           CASE WHEN prev_order_at IS NOT NULL
                THEN EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0
                ELSE NULL END AS days_since_last,
           CASE
               WHEN order_seq = 1 THEN 'First Purchase'
               WHEN EXTRACT(EPOCH FROM (created_at - first_order_at)) / 86400.0 <= 7 THEN 'Acquisition Burst'
               WHEN EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0 <= 7 THEN 'Weekly Retention'
               WHEN EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0 <= 14 THEN 'Bi-weekly Retention'
               WHEN EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0 <= 30 THEN 'Monthly Retention'
               WHEN EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0 <= 90 THEN 'Quarterly Retention'
               WHEN EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0 <= 180 THEN 'Bi-annual Retention'
               ELSE '_long_absence'
           END AS retention_category
    FROM customer_orders
    WHERE created_at >= '{start_date}'::date AND created_at < '{end_date}'::date + 1
    """


def _resolve_long_absence(df, reference_date_str):
    """Resolve _long_absence into Annual Retention, Late Retention, or Reacquisition."""
    long_abs_mask = df["retention_category"] == "_long_absence"
    if not long_abs_mask.any():
        return df

    user_ids = df.loc[long_abs_mask, "user_id"].unique().tolist()
    if not user_ids:
        return df

    ids_str = ",".join(str(int(c)) for c in user_ids)
    active_df = run_query(f"""
        SELECT DISTINCT a.user_id
        FROM core.user_accounts a
        JOIN core.performance_metrics am ON am.account_id = a.id
        WHERE a.user_id IN ({ids_str})
          AND am."isActiveDay" = '1'
          AND am."reportDate" >= '{reference_date_str}'::date - 180
          AND am."reportDate" < '{reference_date_str}'::date
    """)
    active_set = set(active_df["user_id"].tolist()) if not active_df.empty else set()

    is_active = df["user_id"].isin(active_set)
    days = df["days_since_last"].fillna(999)

    df.loc[long_abs_mask & is_active & (days <= 365), "retention_category"] = "Annual Retention"
    df.loc[long_abs_mask & is_active & (days > 365), "retention_category"] = "Late Retention"
    df.loc[long_abs_mask & ~is_active, "retention_category"] = "Reacquisition"

    return df


@st.cache_data(ttl=300)
def get_retention_classified(date_str):
    """Get retention-classified orders for a single day."""
    sql = _build_retention_sql(date_str, date_str)
    df = run_query(sql)
    if df.empty:
        return df
    df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce").fillna(0)
    df = _resolve_long_absence(df, date_str)
    df["order_type_name"] = df["order_type"].map(ORDER_TYPE_NAMES).fillna("Other")
    return df


@st.cache_data(ttl=300)
def get_retention_trend(start_str, end_str):
    """Get retention trend data aggregated by date (simplified: no active-trading check)."""
    sql = f"""
    WITH target_customers AS (
        SELECT DISTINCT o.user_id
        FROM core.purchases o
        JOIN core.user_accounts a ON o.account_id = a.id
        JOIN core.subscription_plans p ON a.plan_id = p.id
        WHERE o.status = 1
          AND o.created_at >= '{start_str}'::date
          AND o.created_at < '{end_str}'::date + 1
          AND p.category_id = 1
    ),
    customer_orders AS (
        SELECT o.user_id, o.id AS order_id, o.total_amount, o.order_type,
               o.created_at, o.account_id,
               MIN(o.created_at) OVER (PARTITION BY o.user_id) AS first_order_at,
               LAG(o.created_at) OVER (PARTITION BY o.user_id ORDER BY o.created_at, o.id) AS prev_order_at,
               ROW_NUMBER() OVER (PARTITION BY o.user_id ORDER BY o.created_at, o.id) AS order_seq
        FROM core.purchases o
        JOIN core.user_accounts a ON o.account_id = a.id
        JOIN core.subscription_plans p ON a.plan_id = p.id
        WHERE o.status = 1
          AND o.user_id IN (SELECT user_id FROM target_customers)
          AND p.category_id = 1
    ),
    classified AS (
        SELECT *,
               DATE(created_at) AS order_date,
               CASE
                   WHEN order_seq = 1 THEN 'First Purchase'
                   WHEN EXTRACT(EPOCH FROM (created_at - first_order_at)) / 86400.0 <= 7 THEN 'Acquisition Burst'
                   WHEN EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0 <= 7 THEN 'Weekly Retention'
                   WHEN EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0 <= 14 THEN 'Bi-weekly Retention'
                   WHEN EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0 <= 30 THEN 'Monthly Retention'
                   WHEN EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0 <= 90 THEN 'Quarterly Retention'
                   WHEN EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0 <= 180 THEN 'Bi-annual Retention'
                   WHEN EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0 <= 365 THEN 'Annual Retention'
                   ELSE 'Late Retention'
               END AS retention_category
        FROM customer_orders
        WHERE created_at >= '{start_str}'::date AND created_at < '{end_str}'::date + 1
    )
    SELECT order_date, retention_category,
           COUNT(*) AS orders,
           SUM(total_amount) AS revenue,
           COUNT(DISTINCT user_id) AS customers
    FROM classified
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = run_query(sql)
    if not df.empty:
        df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").fillna(0)
    return df
