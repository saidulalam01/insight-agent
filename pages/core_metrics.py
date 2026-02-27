"""Core Metrics page — extracted from app.py (lines 522-1031)."""

import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from shared import _qc, metric_delta, fmt_num, safe_float
from db import run_query


# ── Module-level helpers (no closure dependencies) ────────

@st.cache_data(ttl=600)
def _m_load_regions():
    df = run_query("SELECT DISTINCT region FROM reporting.geo_regions WHERE region IS NOT NULL ORDER BY 1")
    return df["region"].tolist()


@st.cache_data(ttl=600)
def _m_load_countries():
    df = run_query("SELECT DISTINCT name FROM reporting.geo_regions ORDER BY 1")
    return df["name"].tolist()


def _m_sql_list(vals):
    return ",".join("'" + v.replace("'", "''") + "'" for v in vals)


def _mv(df, col, as_int=False):
    if df.empty:
        return 0
    v = df.iloc[0].get(col, 0)
    v = safe_float(v)
    return int(v) if as_int else v


def _mret_v(df, cat):
    if df.empty:
        return 0
    row = df[df["retention_category"] == cat]
    return int(row.iloc[0]["cnt"]) if not row.empty else 0


def _pct_from(df, b_col, r_col):
    b = _mv(df, b_col, True)
    r = _mv(df, r_col, True)
    return (r / b * 100) if b > 0 else 0


# ── Page render function ──────────────────────────────────

def render():
    st.header("Core Metrics")

    # ── Filters ────────────────────────────────────────────
    _m_dc1, _m_dc2, _m_dc3 = st.columns([2, 2, 2])
    with _m_dc1:
        _m_start = st.date_input("From", value=date(datetime.now().year, datetime.now().month, 1), key="main_start")
    with _m_dc2:
        _m_end = st.date_input("To", value=datetime.now().date() - timedelta(days=1), key="main_end")
    with _m_dc3:
        _m_compare = st.selectbox("Compare with", ["Previous Period", "Same Period Last Month"], key="main_compare")
    _m_fc1, _m_fc2 = st.columns(2)
    with _m_fc1:
        _m_regions = st.multiselect("Region", _m_load_regions(), default=[], key="main_region")
    with _m_fc2:
        _m_countries = st.multiselect("Country", _m_load_countries(), default=[], key="main_country")

    # ── Comparison period calculation ─────────────────────
    _m_days = (_m_end - _m_start).days + 1
    if _m_compare == "Previous Period":
        _m_prev_end = _m_start - timedelta(days=1)
        _m_prev_start = _m_start - timedelta(days=_m_days)
    else:
        _m_prev_start = _m_start - relativedelta(months=1)
        _m_prev_end = _m_end - relativedelta(months=1)

    # ── Build SQL filter fragments ────────────────────────
    _m_gj_ord = ""
    _m_gw_ord = ""
    if _m_regions or _m_countries:
        _m_gj_ord = (" JOIN core.users _gc ON o.user_id = _gc.id"
                      " JOIN core.regions _gco ON _gc.country_id = _gco.id"
                      " JOIN reporting.geo_regions _gr ON _gco.short_name = _gr.short_name")
        _gw = []
        if _m_regions:
            _gw.append(f"_gr.region IN ({_m_sql_list(_m_regions)})")
        if _m_countries:
            _gw.append(f"_gr.name IN ({_m_sql_list(_m_countries)})")
        _m_gw_ord = " AND " + " AND ".join(_gw)

    _m_gj_cust = ""
    _m_gw_cust = ""
    if _m_regions or _m_countries:
        _m_gj_cust = (" JOIN core.regions _gco ON cu.country_id = _gco.id"
                       " JOIN reporting.geo_regions _gr ON _gco.short_name = _gr.short_name")
        _gw = []
        if _m_regions:
            _gw.append(f"_gr.region IN ({_m_sql_list(_m_regions)})")
        if _m_countries:
            _gw.append(f"_gr.name IN ({_m_sql_list(_m_countries)})")
        _m_gw_cust = " AND " + " AND ".join(_gw)

    # Generic geo join for tables with user_id
    def _m_gj_generic(alias, cid_col="user_id"):
        if not _m_regions and not _m_countries:
            return "", ""
        j = (f" JOIN core.users _gc ON {alias}.{cid_col} = _gc.id"
             f" JOIN core.regions _gco ON _gc.country_id = _gco.id"
             f" JOIN reporting.geo_regions _gr ON _gco.short_name = _gr.short_name")
        _gw = []
        if _m_regions:
            _gw.append(f"_gr.region IN ({_m_sql_list(_m_regions)})")
        if _m_countries:
            _gw.append(f"_gr.name IN ({_m_sql_list(_m_countries)})")
        return j, " AND " + " AND ".join(_gw)
    _m_wj, _m_ww = _m_gj_generic("wt")
    _m_aj, _m_aw = _m_gj_generic("a")

    # ── SQL query builders ──────────────────────────────────
    _ms = str(_m_start)
    _me = str(_m_end)
    _ps = str(_m_prev_start)
    _pe = str(_m_prev_end)

    def _m_sql_core(s, e):
        """Row 1: Revenue, orders, signups, conversion. Excludes futures."""
        return f"""
        WITH signups AS (
            SELECT cu.id, cu.created_at, TO_CHAR(cu.created_at, 'YYYY-MM') AS signup_month
            FROM core.users cu
            {_m_gj_cust}
            WHERE cu.created_at >= '{s}'::date AND cu.created_at < '{e}'::date + 1{_m_gw_cust}
        ),
        all_orders AS (
            SELECT o.user_id, o.total_amount
            FROM core.purchases o
            JOIN core.user_accounts a ON o.account_id = a.id
            {_m_gj_ord}
            WHERE o.status = 1
              AND a.type NOT ILIKE '%futures%' AND a.type NOT ILIKE '%platform-e%'
              AND o.created_at >= '{s}'::date AND o.created_at < '{e}'::date + 1{_m_gw_ord}
        ),
        converted AS (
            SELECT DISTINCT s.id
            FROM signups s
            JOIN core.purchases o2 ON o2.user_id = s.id
            JOIN core.user_accounts a2 ON o2.account_id = a2.id
            WHERE o2.status = 1 AND a2.type NOT ILIKE '%futures%' AND a2.type NOT ILIKE '%platform-e%'
              AND TO_CHAR(o2.created_at, 'YYYY-MM') = s.signup_month
        )
        SELECT
            (SELECT COUNT(*) FROM signups) AS signups,
            (SELECT COUNT(*) FROM converted) AS converted_signups,
            COALESCE(SUM(ao.total_amount), 0) AS revenue,
            COUNT(*) AS orders,
            COUNT(DISTINCT ao.user_id) AS purchase_clients
        FROM all_orders ao
        """

    def _m_sql_aov(s, e):
        """Row 3: AOV per model. Excludes futures."""
        return f"""
        SELECT
            COALESCE(AVG(o.total_amount), 0) AS aov,
            COALESCE(AVG(o.total_amount) FILTER (WHERE a.type ILIKE '%standard 1-phase%'), 0) AS aov_1step,
            COALESCE(AVG(o.total_amount) FILTER (WHERE a.type ILIKE '%standard 2-phase%'), 0) AS aov_2step,
            COALESCE(AVG(o.total_amount) FILTER (WHERE a.type ILIKE '%basic lite%'), 0) AS aov_lite,
            COALESCE(AVG(o.total_amount) FILTER (WHERE a.type ILIKE '%direct start%'), 0) AS aov_instant
        FROM core.purchases o
        JOIN core.user_accounts a ON o.account_id = a.id
        {_m_gj_ord}
        WHERE o.status = 1
          AND a.type NOT ILIKE '%futures%' AND a.type NOT ILIKE '%platform-e%'
          AND o.created_at >= '{s}'::date AND o.created_at < '{e}'::date + 1{_m_gw_ord}
        """

    def _m_sql_payouts(s, e):
        """Row 1 payout total + Row 4 avg payout per model."""
        return f"""
        WITH payout_base AS (
            SELECT wt.user_id, ABS(wt.amount) AS pay_amt, a.type AS acc_type
            FROM core.wallet_transfers wt
            JOIN core.user_accounts a ON wt.account_id = a.id
            {_m_wj}
            WHERE wt.type = 1 AND wt.status = 8
              AND a.type NOT ILIKE '%futures%' AND a.type NOT ILIKE '%platform-e%'
              AND wt.created_at >= '{s}'::date AND wt.created_at < '{e}'::date + 1{_m_ww}
        )
        SELECT
            COALESCE(SUM(pay_amt), 0) AS total_payouts,
            COUNT(DISTINCT user_id) AS payout_clients,
            COALESCE(AVG(pay_amt), 0) AS avg_payout,
            COALESCE(AVG(pay_amt) FILTER (WHERE acc_type ILIKE '%standard 1-phase%'), 0) AS avg_pay_1step,
            COALESCE(AVG(pay_amt) FILTER (WHERE acc_type ILIKE '%standard 2-phase%'), 0) AS avg_pay_2step,
            COALESCE(AVG(pay_amt) FILTER (WHERE acc_type ILIKE '%basic lite%'), 0) AS avg_pay_lite,
            COALESCE(AVG(pay_amt) FILTER (WHERE acc_type ILIKE '%direct start%'), 0) AS avg_pay_instant
        FROM payout_base
        """

    def _m_sql_row2(s, e):
        """Row 2: Free trial + competition counts (accounts & customers)."""
        _ft_gj, _ft_gw = _m_gj_generic("ft", "user_id")
        _cp_gj, _cp_gw = _m_gj_generic("ca", "user_id")
        return f"""
        WITH ft_stats AS (
            SELECT COUNT(*) AS accounts, COUNT(DISTINCT ft.user_id) AS customers
            FROM core.trial_accounts ft
            {_ft_gj}
            WHERE ft.created_at >= '{s}'::date AND ft.created_at < '{e}'::date + 1{_ft_gw}
        ),
        comp_stats AS (
            SELECT COUNT(*) AS accounts, COUNT(DISTINCT ca.user_id) AS customers
            FROM core.contest_accounts ca
            {_cp_gj}
            WHERE ca.created_at >= '{s}'::date AND ca.created_at < '{e}'::date + 1{_cp_gw}
        )
        SELECT ft.accounts AS ft_accounts, ft.customers AS ft_customers,
               comp.accounts AS comp_accounts, comp.customers AS comp_customers
        FROM ft_stats ft, comp_stats comp
        """

    def _m_sql_retention(s, e):
        """Rows 5-6: Retention category counts (all 10 categories incl. Reacquisition)."""
        return f"""
        WITH target_customers AS (
            SELECT DISTINCT o.user_id
            FROM core.purchases o
            JOIN core.user_accounts a ON o.account_id = a.id
            JOIN core.subscription_plans p ON a.plan_id = p.id
            {_m_gj_ord}
            WHERE o.status = 1 AND p.category_id = 1
              AND o.created_at >= '{s}'::date AND o.created_at < '{e}'::date + 1{_m_gw_ord}
        ),
        customer_orders AS (
            SELECT o.user_id, o.created_at,
                   MIN(o.created_at) OVER (PARTITION BY o.user_id) AS first_order_at,
                   LAG(o.created_at) OVER (PARTITION BY o.user_id ORDER BY o.created_at, o.id) AS prev_order_at,
                   ROW_NUMBER() OVER (PARTITION BY o.user_id ORDER BY o.created_at, o.id) AS order_seq
            FROM core.purchases o
            JOIN core.user_accounts a ON o.account_id = a.id
            JOIN core.subscription_plans p ON a.plan_id = p.id
            WHERE o.status = 1 AND p.category_id = 1
              AND o.user_id IN (SELECT user_id FROM target_customers)
        ),
        pre_classified AS (
            SELECT user_id, created_at,
                   EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0 AS days_since_last,
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
        ),
        active_traders AS (
            SELECT DISTINCT a.user_id
            FROM core.user_accounts a
            JOIN core.performance_metrics am ON am.account_id = a.id
            WHERE a.user_id IN (
                SELECT DISTINCT user_id FROM pre_classified
                WHERE retention_category = '_long_absence'
                  AND created_at >= '{s}'::date AND created_at < '{e}'::date + 1
            )
              AND am."isActiveDay" = '1'
              AND am."reportDate" >= '{s}'::date - 180
              AND am."reportDate" < '{s}'::date
        ),
        final_classified AS (
            SELECT retention_category
            FROM pre_classified
            WHERE retention_category != '_long_absence'
              AND created_at >= '{s}'::date AND created_at < '{e}'::date + 1
            UNION ALL
            SELECT
                CASE
                    WHEN at2.user_id IS NOT NULL AND pc.days_since_last <= 365 THEN 'Annual Retention'
                    WHEN at2.user_id IS NOT NULL THEN 'Late Retention'
                    ELSE 'Reacquisition'
                END AS retention_category
            FROM pre_classified pc
            LEFT JOIN active_traders at2 ON pc.user_id = at2.user_id
            WHERE pc.retention_category = '_long_absence'
              AND pc.created_at >= '{s}'::date AND pc.created_at < '{e}'::date + 1
        )
        SELECT retention_category, COUNT(*) AS cnt
        FROM final_classified
        GROUP BY retention_category
        """

    def _m_sql_breaches(s, e):
        """Rows 7-8: Breach login counts + customer counts by phase."""
        return f"""
        SELECT
            COUNT(*) AS total_breach_logins,
            COUNT(*) FILTER (WHERE a.type ILIKE '%P1%') AS p1_logins,
            COUNT(*) FILTER (WHERE a.type ILIKE '%P2%') AS p2_logins,
            COUNT(*) FILTER (WHERE a.type ILIKE '%Real%') AS real_logins,
            COUNT(*) FILTER (WHERE a.type ILIKE '%Instant%') AS instant_logins,
            COUNT(DISTINCT a.user_id) AS total_breach_customers,
            COUNT(DISTINCT a.user_id) FILTER (WHERE a.type ILIKE '%P1%') AS p1_customers,
            COUNT(DISTINCT a.user_id) FILTER (WHERE a.type ILIKE '%P2%') AS p2_customers,
            COUNT(DISTINCT a.user_id) FILTER (WHERE a.type ILIKE '%Real%') AS real_customers,
            COUNT(DISTINCT a.user_id) FILTER (WHERE a.type ILIKE '%Instant%') AS instant_customers
        FROM core.user_accounts a
        {_m_aj}
        WHERE a.violated = 1
          AND a.type NOT ILIKE '%futures%' AND a.type NOT ILIKE '%platform-e%'
          AND a.updated_at >= '{s}'::date AND a.updated_at < '{e}'::date + 1{_m_aw}
        """

    # ── Load core data (fast: 4 queries) ──────────────────
    _m_filter_parts = [f"{_m_start.strftime('%b %d, %Y')} \u2013 {_m_end.strftime('%b %d, %Y')}",
                       f"vs {_m_compare.lower()}: {_m_prev_start.strftime('%b %d')} \u2013 {_m_prev_end.strftime('%b %d')}"]
    if _m_regions:
        _m_filter_parts.append(f"Region: {', '.join(_m_regions)}")
    if _m_countries:
        _m_filter_parts.append(f"Country: {', '.join(_m_countries)}")
    st.caption("  |  ".join(_m_filter_parts))

    with st.spinner("Loading core metrics..."):
        _mc = _qc(_m_sql_core(_ms, _me))
        _mc_p = _qc(_m_sql_core(_ps, _pe))
        _mp = _qc(_m_sql_payouts(_ms, _me))
        _mp_p = _qc(_m_sql_payouts(_ps, _pe))
        _ma = _qc(_m_sql_aov(_ms, _me))
        _ma_p = _qc(_m_sql_aov(_ps, _pe))

    # Row 1
    _signups = _mv(_mc, "signups", True)
    _converted = _mv(_mc, "converted_signups", True)
    _conv_pct = (_converted / _signups * 100) if _signups > 0 else 0
    _revenue = _mv(_mc, "revenue")
    _payout_total = _mv(_mp, "total_payouts")
    _payout_ratio = (_payout_total / _revenue * 100) if _revenue > 0 else 0
    _p_signups = _mv(_mc_p, "signups", True)
    _p_converted = _mv(_mc_p, "converted_signups", True)
    _p_conv_pct = (_p_converted / _p_signups * 100) if _p_signups > 0 else 0
    _p_revenue = _mv(_mc_p, "revenue")
    _p_payout_total = _mv(_mp_p, "total_payouts")
    _p_payout_ratio = (_p_payout_total / _p_revenue * 100) if _p_revenue > 0 else 0

    # ── Display Row 1 ────────────────────────────────────
    st.markdown("##### Core Metrics")
    r1c1, r1c2, r1c3, r1c4, r1c5 = st.columns(5)
    r1c1.metric("Signups", fmt_num(_signups), metric_delta(_signups, _p_signups))
    r1c2.metric("Signup \u2192 Purchase %", f"{_conv_pct:.1f}%", metric_delta(_conv_pct, _p_conv_pct))
    r1c3.metric("Revenue", fmt_num(_revenue, prefix="$"), metric_delta(_revenue, _p_revenue))
    r1c4.metric("Payout", fmt_num(_payout_total, prefix="$"), metric_delta(_payout_total, _p_payout_total), delta_color="inverse")
    r1c5.metric("Payout Ratio", f"{_payout_ratio:.1f}%", metric_delta(_payout_ratio, _p_payout_ratio), delta_color="inverse")

    # Row 2: Purchase counts from core query + payout clients
    _purchase_clients = _mv(_mc, "purchase_clients", True)
    _payout_clients = _mv(_mp, "payout_clients", True)
    _purchase_logins = _mv(_mc, "orders", True)
    _p_purchase_clients = _mv(_mc_p, "purchase_clients", True)
    _p_payout_clients = _mv(_mp_p, "payout_clients", True)
    _p_purchase_logins = _mv(_mc_p, "orders", True)

    r2c1, r2c2, r2c3, r2c4, r2c5 = st.columns(5)
    r2c1.metric("Purchase Login Count", fmt_num(_purchase_logins), metric_delta(_purchase_logins, _p_purchase_logins))
    r2c2.metric("Purchase Client Count", fmt_num(_purchase_clients), metric_delta(_purchase_clients, _p_purchase_clients))
    r2c3.metric("Payout Client Count", fmt_num(_payout_clients), metric_delta(_payout_clients, _p_payout_clients), delta_color="inverse")
    r2c4.empty()
    r2c5.empty()

    st.divider()

    # Row 3: AOV (from AOV query)
    st.markdown("##### Average Order Value")
    r3c1, r3c2, r3c3, r3c4, r3c5 = st.columns(5)
    r3c1.metric("Overall AOV", fmt_num(_mv(_ma, 'aov'), prefix="$"), metric_delta(_mv(_ma, 'aov'), _mv(_ma_p, 'aov')))
    r3c2.metric("1-Step AOV", fmt_num(_mv(_ma, 'aov_1step'), prefix="$"), metric_delta(_mv(_ma, 'aov_1step'), _mv(_ma_p, 'aov_1step')))
    r3c3.metric("2-Step AOV", fmt_num(_mv(_ma, 'aov_2step'), prefix="$"), metric_delta(_mv(_ma, 'aov_2step'), _mv(_ma_p, 'aov_2step')))
    r3c4.metric("Lite AOV", fmt_num(_mv(_ma, 'aov_lite'), prefix="$"), metric_delta(_mv(_ma, 'aov_lite'), _mv(_ma_p, 'aov_lite')))
    r3c5.metric("Instant AOV", fmt_num(_mv(_ma, 'aov_instant'), prefix="$"), metric_delta(_mv(_ma, 'aov_instant'), _mv(_ma_p, 'aov_instant')))

    # Row 4: Avg Payout (from payout query, already loaded)
    st.markdown("##### Average Payout")
    r4c1, r4c2, r4c3, r4c4, r4c5 = st.columns(5)
    r4c1.metric("Overall Avg Payout", fmt_num(_mv(_mp, 'avg_payout'), prefix="$"), metric_delta(_mv(_mp, 'avg_payout'), _mv(_mp_p, 'avg_payout')), delta_color="inverse")
    r4c2.metric("1-Step Avg Payout", fmt_num(_mv(_mp, 'avg_pay_1step'), prefix="$"), metric_delta(_mv(_mp, 'avg_pay_1step'), _mv(_mp_p, 'avg_pay_1step')), delta_color="inverse")
    r4c3.metric("2-Step Avg Payout", fmt_num(_mv(_mp, 'avg_pay_2step'), prefix="$"), metric_delta(_mv(_mp, 'avg_pay_2step'), _mv(_mp_p, 'avg_pay_2step')), delta_color="inverse")
    r4c4.metric("Lite Avg Payout", fmt_num(_mv(_mp, 'avg_pay_lite'), prefix="$"), metric_delta(_mv(_mp, 'avg_pay_lite'), _mv(_mp_p, 'avg_pay_lite')), delta_color="inverse")
    r4c5.metric("Instant Avg Payout", fmt_num(_mv(_mp, 'avg_pay_instant'), prefix="$"), metric_delta(_mv(_mp, 'avg_pay_instant'), _mv(_mp_p, 'avg_pay_instant')), delta_color="inverse")

    st.divider()

    # ── Free Trial & Competition (behind toggle -- scans millions of rows) ──
    _m_show_ftc = st.toggle("Free Trial & Competition", value=False, key="main_ftc")
    if _m_show_ftc:
        with st.spinner("Loading free trial & competition data..."):
            _mr2 = _qc(_m_sql_row2(_ms, _me))
            _mr2_p = _qc(_m_sql_row2(_ps, _pe))
        _r2c1, _r2c2, _r2c3, _r2c4 = st.columns(4)
        _r2c1.metric("Free Trial Accounts", fmt_num(_mv(_mr2, 'ft_accounts', True)), metric_delta(_mv(_mr2, 'ft_accounts', True), _mv(_mr2_p, 'ft_accounts', True)))
        _r2c2.metric("Free Trial Customers", fmt_num(_mv(_mr2, 'ft_customers', True)), metric_delta(_mv(_mr2, 'ft_customers', True), _mv(_mr2_p, 'ft_customers', True)))
        _r2c3.metric("Competition Accounts", fmt_num(_mv(_mr2, 'comp_accounts', True)), metric_delta(_mv(_mr2, 'comp_accounts', True), _mv(_mr2_p, 'comp_accounts', True)))
        _r2c4.metric("Competition Customers", fmt_num(_mv(_mr2, 'comp_customers', True)), metric_delta(_mv(_mr2, 'comp_customers', True), _mv(_mr2_p, 'comp_customers', True)))

    st.divider()

    # ── Retention (behind toggle -- heavy window function query) ──
    _m_show_ret = st.toggle("Retention", value=False, key="main_retention")
    if _m_show_ret:
        with st.spinner("Loading retention data..."):
            _mret = _qc(_m_sql_retention(_ms, _me))
            _mret_p = _qc(_m_sql_retention(_ps, _pe))

        _ret_cats = ["First Purchase", "Acquisition Burst", "Weekly Retention",
                     "Bi-weekly Retention", "Monthly Retention", "Quarterly Retention",
                     "Bi-annual Retention", "Annual Retention", "Late Retention", "Reacquisition"]
        _ret_vals = {c: _mret_v(_mret, c) for c in _ret_cats}
        _ret_total = sum(_ret_vals.values()) or 1
        def _rl(cat):
            pct = _ret_vals[cat] / _ret_total * 100
            return f"{cat} ({pct:.1f}%)"

        r5c1, r5c2, r5c3, r5c4, r5c5 = st.columns(5)
        r5c1.metric(_rl("First Purchase"), fmt_num(_ret_vals['First Purchase']), metric_delta(_ret_vals['First Purchase'], _mret_v(_mret_p, 'First Purchase')))
        r5c2.metric(_rl("Acquisition Burst"), fmt_num(_ret_vals['Acquisition Burst']), metric_delta(_ret_vals['Acquisition Burst'], _mret_v(_mret_p, 'Acquisition Burst')))
        r5c3.metric(_rl("Weekly Retention"), fmt_num(_ret_vals['Weekly Retention']), metric_delta(_ret_vals['Weekly Retention'], _mret_v(_mret_p, 'Weekly Retention')))
        r5c4.metric(_rl("Bi-weekly Retention"), fmt_num(_ret_vals['Bi-weekly Retention']), metric_delta(_ret_vals['Bi-weekly Retention'], _mret_v(_mret_p, 'Bi-weekly Retention')))
        r5c5.metric(_rl("Monthly Retention"), fmt_num(_ret_vals['Monthly Retention']), metric_delta(_ret_vals['Monthly Retention'], _mret_v(_mret_p, 'Monthly Retention')))

        r6c1, r6c2, r6c3, r6c4, r6c5 = st.columns(5)
        r6c1.metric(_rl("Quarterly Retention"), fmt_num(_ret_vals['Quarterly Retention']), metric_delta(_ret_vals['Quarterly Retention'], _mret_v(_mret_p, 'Quarterly Retention')))
        r6c2.metric(_rl("Bi-annual Retention"), fmt_num(_ret_vals['Bi-annual Retention']), metric_delta(_ret_vals['Bi-annual Retention'], _mret_v(_mret_p, 'Bi-annual Retention')))
        r6c3.metric(_rl("Annual Retention"), fmt_num(_ret_vals['Annual Retention']), metric_delta(_ret_vals['Annual Retention'], _mret_v(_mret_p, 'Annual Retention')))
        r6c4.metric(_rl("Late Retention"), fmt_num(_ret_vals['Late Retention']), metric_delta(_ret_vals['Late Retention'], _mret_v(_mret_p, 'Late Retention')))
        r6c5.metric(_rl("Reacquisition"), fmt_num(_ret_vals['Reacquisition']), metric_delta(_ret_vals['Reacquisition'], _mret_v(_mret_p, 'Reacquisition')))

    st.divider()

    # ── Breach Counts (behind toggle) ─────────────────────
    _m_show_breach = st.toggle("Breach Counts", value=False, key="main_breach")
    if _m_show_breach:
        with st.spinner("Loading breach data..."):
            _mbr = _qc(_m_sql_breaches(_ms, _me))
            _mbr_p = _qc(_m_sql_breaches(_ps, _pe))

        st.markdown("###### Logins")
        r7c1, r7c2, r7c3, r7c4, r7c5 = st.columns(5)
        r7c1.metric("Total", fmt_num(_mv(_mbr, 'total_breach_logins', True)), metric_delta(_mv(_mbr, 'total_breach_logins', True), _mv(_mbr_p, 'total_breach_logins', True)), delta_color="inverse")
        r7c2.metric("P1", fmt_num(_mv(_mbr, 'p1_logins', True)), metric_delta(_mv(_mbr, 'p1_logins', True), _mv(_mbr_p, 'p1_logins', True)), delta_color="inverse")
        r7c3.metric("P2", fmt_num(_mv(_mbr, 'p2_logins', True)), metric_delta(_mv(_mbr, 'p2_logins', True), _mv(_mbr_p, 'p2_logins', True)), delta_color="inverse")
        r7c4.metric("Real", fmt_num(_mv(_mbr, 'real_logins', True)), metric_delta(_mv(_mbr, 'real_logins', True), _mv(_mbr_p, 'real_logins', True)), delta_color="inverse")
        r7c5.metric("Instant", fmt_num(_mv(_mbr, 'instant_logins', True)), metric_delta(_mv(_mbr, 'instant_logins', True), _mv(_mbr_p, 'instant_logins', True)), delta_color="inverse")

        st.markdown("###### Customers")
        r8c1, r8c2, r8c3, r8c4, r8c5 = st.columns(5)
        r8c1.metric("Total", fmt_num(_mv(_mbr, 'total_breach_customers', True)), metric_delta(_mv(_mbr, 'total_breach_customers', True), _mv(_mbr_p, 'total_breach_customers', True)), delta_color="inverse")
        r8c2.metric("P1", fmt_num(_mv(_mbr, 'p1_customers', True)), metric_delta(_mv(_mbr, 'p1_customers', True), _mv(_mbr_p, 'p1_customers', True)), delta_color="inverse")
        r8c3.metric("P2", fmt_num(_mv(_mbr, 'p2_customers', True)), metric_delta(_mv(_mbr, 'p2_customers', True), _mv(_mbr_p, 'p2_customers', True)), delta_color="inverse")
        r8c4.metric("Real", fmt_num(_mv(_mbr, 'real_customers', True)), metric_delta(_mv(_mbr, 'real_customers', True), _mv(_mbr_p, 'real_customers', True)), delta_color="inverse")
        r8c5.metric("Instant", fmt_num(_mv(_mbr, 'instant_customers', True)), metric_delta(_mv(_mbr, 'instant_customers', True), _mv(_mbr_p, 'instant_customers', True)), delta_color="inverse")

    st.divider()

    # ── Purchase % from Breached Clients (behind toggle) ──
    _m_show_breach_pct = st.toggle("Breach Repurchase %", value=False, key="main_breach_repurch")
    if _m_show_breach_pct:
        with st.spinner("Loading breach repurchase data..."):
            def _m_sql_breach_repurch(s, e):
                return f"""
                WITH violated AS (
                    SELECT a.user_id,
                           CASE
                               WHEN a.type ILIKE '%P1%' THEN 'P1'
                               WHEN a.type ILIKE '%P2%' THEN 'P2'
                               WHEN a.type ILIKE '%Real%' THEN 'Real'
                               WHEN a.type ILIKE '%Instant%' THEN 'Instant'
                               ELSE 'Other'
                           END AS phase
                    FROM core.user_accounts a
                    {_m_aj}
                    WHERE a.violated = 1
                      AND a.type NOT ILIKE '%futures%' AND a.type NOT ILIKE '%platform-e%'
                      AND a.updated_at >= '{s}'::date AND a.updated_at < '{e}'::date + 1{_m_aw}
                ),
                repurchased AS (
                    SELECT DISTINCT b.user_id, b.phase
                    FROM violated b
                    JOIN core.purchases o ON o.user_id = b.user_id
                    WHERE o.status = 1
                      AND o.created_at >= '{s}'::date AND o.created_at < '{e}'::date + 1
                )
                SELECT
                    COUNT(DISTINCT b.user_id) AS total_b,
                    COUNT(DISTINCT r.user_id) AS total_r,
                    COUNT(DISTINCT b.user_id) FILTER (WHERE b.phase = 'P1') AS p1_b,
                    COUNT(DISTINCT r.user_id) FILTER (WHERE r.phase = 'P1') AS p1_r,
                    COUNT(DISTINCT b.user_id) FILTER (WHERE b.phase = 'P2') AS p2_b,
                    COUNT(DISTINCT r.user_id) FILTER (WHERE r.phase = 'P2') AS p2_r,
                    COUNT(DISTINCT b.user_id) FILTER (WHERE b.phase = 'Real') AS real_b,
                    COUNT(DISTINCT r.user_id) FILTER (WHERE r.phase = 'Real') AS real_r,
                    COUNT(DISTINCT b.user_id) FILTER (WHERE b.phase = 'Instant') AS instant_b,
                    COUNT(DISTINCT r.user_id) FILTER (WHERE r.phase = 'Instant') AS instant_r
                FROM violated b
                LEFT JOIN repurchased r ON b.user_id = r.user_id AND b.phase = r.phase
                """
            _brr = _qc(_m_sql_breach_repurch(_ms, _me))
            _brr_p = _qc(_m_sql_breach_repurch(_ps, _pe))

        _bp_total = _pct_from(_brr, "total_b", "total_r")
        _bp_p1 = _pct_from(_brr, "p1_b", "p1_r")
        _bp_p2 = _pct_from(_brr, "p2_b", "p2_r")
        _bp_real = _pct_from(_brr, "real_b", "real_r")
        _bp_instant = _pct_from(_brr, "instant_b", "instant_r")
        _p_bp_total = _pct_from(_brr_p, "total_b", "total_r")
        _p_bp_p1 = _pct_from(_brr_p, "p1_b", "p1_r")
        _p_bp_p2 = _pct_from(_brr_p, "p2_b", "p2_r")
        _p_bp_real = _pct_from(_brr_p, "real_b", "real_r")
        _p_bp_instant = _pct_from(_brr_p, "instant_b", "instant_r")

        r9c1, r9c2, r9c3, r9c4, r9c5 = st.columns(5)
        r9c1.metric("Total", f"{_bp_total:.1f}%", metric_delta(_bp_total, _p_bp_total))
        r9c2.metric("P1 Breached", f"{_bp_p1:.1f}%", metric_delta(_bp_p1, _p_bp_p1))
        r9c3.metric("P2 Breached", f"{_bp_p2:.1f}%", metric_delta(_bp_p2, _p_bp_p2))
        r9c4.metric("Real Breached", f"{_bp_real:.1f}%", metric_delta(_bp_real, _p_bp_real))
        r9c5.metric("Instant Breached", f"{_bp_instant:.1f}%", metric_delta(_bp_instant, _p_bp_instant))
