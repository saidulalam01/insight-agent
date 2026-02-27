import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from shared import _qc, metric_delta
from db import run_query


# Module-level functions (no closure dependencies):
@st.cache_data(ttl=600)
def _br_load_regions():
    df = run_query("SELECT DISTINCT region FROM reporting.geo_regions WHERE region IS NOT NULL ORDER BY 1")
    return df["region"].tolist()

@st.cache_data(ttl=600)
def _br_load_all_countries():
    df = run_query("SELECT DISTINCT name FROM reporting.geo_regions ORDER BY 1")
    return df["name"].tolist()

def _sql_list_br(values):
    return ",".join("'" + v.replace("'", "''") + "'" for v in values)

def _bval(df, phase, col):
    row = df[df["phase"] == phase]
    return int(row[col].iloc[0]) if not row.empty else 0

def _bval_f(df, phase, col):
    row = df[df["phase"] == phase]
    return float(row[col].iloc[0]) if not row.empty else 0.0


def render():
    st.header("Breach & Repurchase")

    # ── Filters (inside a form so changes don't trigger rerun until Apply) ──
    _ALL_BREACH_REASONS = [
        "Daily Loss Limit", "Monthly Loss Limit", "Profit Target Reached",
        "Admin", "Month End Partially Profit", "Platform Switch",
        "Month Ended in Loss", "Account Pause", "Account Deleted",
        "Account Migrated", "Phase 2 Account Reset", "Account merge",
    ]
    _DEFAULT_REASONS = ["Daily Loss Limit", "Monthly Loss Limit"]
    _ALL_MODELS = ["Standard 2-Phase", "Standard 1-Phase", "Basic Lite", "Direct Start", "Evaluation", "Express"]
    _ALL_SIZES = [2000, 5000, 6000, 10000, 15000, 20000, 25000, 50000, 100000, 200000]

    with st.form("breach_filters"):
        _fd1, _fd2, _fd3 = st.columns([1, 1, 2])
        with _fd1:
            _br_start = st.date_input("From", value=datetime.now().date() - timedelta(days=1), key="br_start")
        with _fd2:
            _br_end = st.date_input("To", value=datetime.now().date() - timedelta(days=1), key="br_end")
        with _fd3:
            _br_compare = st.radio("Compare to", ["Previous Period", "Same Period Last Month", "Same Period Last Year"], horizontal=True, key="br_compare")

        sel_reasons = st.multiselect("Breach Reason", _ALL_BREACH_REASONS, default=_DEFAULT_REASONS, key="br_reason")

        _fc1, _fc2 = st.columns(2)
        with _fc1:
            sel_regions = st.multiselect("Region", _br_load_regions(), default=[], key="br_region")
        with _fc2:
            sel_countries = st.multiselect("Country", _br_load_all_countries(), default=[], key="br_country")

        _fc3, _fc4 = st.columns(2)
        with _fc3:
            sel_models = st.multiselect("Model", _ALL_MODELS, default=[], key="br_model")
        with _fc4:
            sel_sizes = st.multiselect("Account Size", [f"${s:,}" for s in _ALL_SIZES], default=[], key="br_size")

        st.form_submit_button("Apply Filters", use_container_width=True, type="primary")

    # Convert size labels back to ints
    _sel_size_ints = [int(s.replace("$", "").replace(",", "")) for s in sel_sizes] if sel_sizes else []

    # Compute comparison range
    _br_days = (_br_end - _br_start).days + 1
    if _br_compare == "Previous Period":
        _br_comp_start = _br_start - timedelta(days=_br_days)
        _br_comp_end = _br_end - timedelta(days=_br_days)
    elif _br_compare == "Same Period Last Year":
        _br_comp_start = _br_start - relativedelta(years=1)
        _br_comp_end = _br_end - relativedelta(years=1)
    else:
        _br_comp_start = _br_start - relativedelta(months=1)
        _br_comp_end = _br_end - relativedelta(months=1)

    # Functions that reference closure vars (_aj, _aw_clause, _BREACH_FILTER, etc.) stay inside render():
    def _br_geo_join(alias="a", cid_col="user_id"):
        if not sel_regions and not sel_countries:
            return "", ""
        joins = (f" JOIN core.users _gc ON {alias}.{cid_col} = _gc.id"
                 f" JOIN core.regions _gco ON _gc.country_id = _gco.id"
                 f" JOIN reporting.geo_regions _gr ON _gco.short_name = _gr.short_name")
        wheres = []
        if sel_regions:
            wheres.append(f"_gr.region IN ({_sql_list_br(sel_regions)})")
        if sel_countries:
            wheres.append(f"_gr.name IN ({_sql_list_br(sel_countries)})")
        return joins, " AND ".join(wheres)

    # Model filter: map selection to SQL ILIKE conditions on a.type
    def _model_filter():
        if not sel_models:
            return ""
        conds = []
        for m in sel_models:
            conds.append(f"a.type ILIKE '%{m}%'")
        return " AND (" + " OR ".join(conds) + ")"

    # Size filter: join plans and filter on initialBalance
    def _size_join_filter():
        if not _sel_size_ints:
            return "", ""
        size_list = ",".join(str(s) for s in _sel_size_ints)
        return (' JOIN core.subscription_plans _pl ON a.plan_id = _pl.id',
                f' AND _pl."initialBalance"::int IN ({size_list})')

    _geo_key = (tuple(sel_regions), tuple(sel_countries), tuple(sel_reasons),
                tuple(sel_models), tuple(_sel_size_ints))
    _aj, _aw = _br_geo_join("a")
    _aw_clause = f" AND {_aw}" if _aw else ""
    _model_clause = _model_filter()
    _sj, _sw_clause = _size_join_filter()
    # Append size join and where to account joins/clauses
    _aj = _aj + _sj
    _aw_clause = _aw_clause + _sw_clause

    _CFD_ONLY = "a.type NOT ILIKE '%Futures%' AND a.type NOT ILIKE '%Platform-E%'"
    if sel_reasons:
        _BREACH_FILTER = f"a.violation_reason IN ({_sql_list_br(sel_reasons)}) AND {_CFD_ONLY}{_model_clause}"
    else:
        _BREACH_FILTER = f"a.violation_reason IS NOT NULL AND {_CFD_ONLY}{_model_clause}"

    # ── SQL templates (date range) ────────────────────────
    _PHASE_CASE = """CASE
                    WHEN a.type ILIKE '%Demo P1%' THEN 'P1 (Demo)'
                    WHEN a.type ILIKE '%Demo P2%' THEN 'P2'
                    WHEN a.type ILIKE '%Real%' THEN 'Real'
                    WHEN a.type ILIKE '%Instant%' THEN 'Instant'
                    WHEN a.type ILIKE '%Demo%' THEN 'P1 (Demo)'
                    ELSE 'Other'
                END"""

    def _sql_br_by_phase(s, e):
        return f"""
            SELECT {_PHASE_CASE} AS phase,
                COUNT(*) AS logins,
                COUNT(DISTINCT a.user_id) AS customers
            FROM core.user_accounts a {_aj}
            WHERE {_BREACH_FILTER}
              AND a.updated_at >= '{s}'::date AND a.updated_at < '{e}'::date + 1
              {_aw_clause}
            GROUP BY 1
        """

    def _sql_br_repurchase_by_phase(s, e):
        return f"""
            WITH violated AS (
                SELECT a.user_id, {_PHASE_CASE} AS phase,
                       MAX(a.updated_at) AS breach_at
                FROM core.user_accounts a {_aj}
                WHERE {_BREACH_FILTER}
                  AND a.updated_at >= '{s}'::date AND a.updated_at < '{e}'::date + 1
                  {_aw_clause}
                GROUP BY 1, 2
            ),
            violated_primary AS (
                SELECT DISTINCT ON (user_id) user_id, phase, breach_at
                FROM violated
                ORDER BY user_id,
                    CASE phase WHEN 'Real' THEN 1 WHEN 'Instant' THEN 2
                               WHEN 'P2' THEN 3 WHEN 'P1 (Demo)' THEN 4 ELSE 5 END
            )
            SELECT b.phase,
                   COUNT(DISTINCT o.user_id) AS repurchased_customers,
                   COUNT(o.id) AS repurchase_orders,
                   COALESCE(AVG(o.total_amount), 0) AS avg_order_value
            FROM violated_primary b
            LEFT JOIN core.purchases o
                ON o.user_id = b.user_id
                AND o.status = 1 AND o.order_type = 1
                AND o.created_at > b.breach_at
            GROUP BY 1
        """

    def _sql_br_totals(s, e):
        return f"""
            SELECT COUNT(*) AS logins,
                   COUNT(DISTINCT a.user_id) AS customers
            FROM core.user_accounts a {_aj}
            WHERE {_BREACH_FILTER}
              AND a.updated_at >= '{s}'::date AND a.updated_at < '{e}'::date + 1
              {_aw_clause}
        """

    def _sql_br_repurchase_total(s, e):
        return f"""
            WITH violated AS (
                SELECT a.user_id, MAX(a.updated_at) AS breach_at
                FROM core.user_accounts a {_aj}
                WHERE {_BREACH_FILTER}
                  AND a.updated_at >= '{s}'::date AND a.updated_at < '{e}'::date + 1
                  {_aw_clause}
                GROUP BY 1
            )
            SELECT COUNT(DISTINCT o.user_id) AS repurchased_customers,
                   COUNT(o.id) AS repurchase_orders,
                   COALESCE(AVG(o.total_amount), 0) AS avg_order_value
            FROM violated b
            LEFT JOIN core.purchases o
                ON o.user_id = b.user_id
                AND o.status = 1 AND o.order_type = 1
                AND o.created_at > b.breach_at
        """

    def _sql_br_news_pct(s, e):
        start_yr, end_yr = int(s[:4]), int(e[:4])
        tbl = f"reporting.user_trades_{s[:4]}"
        if start_yr != end_yr:
            tbl = (f"(SELECT account_id, symbol, close_time FROM reporting.user_trades_{s[:4]}"
                   f" UNION ALL SELECT account_id, symbol, close_time FROM reporting.user_trades_{e[:4]})")
        return f"""
            WITH violated AS (
                SELECT a.id AS account_id, a.user_id, {_PHASE_CASE} AS phase
                FROM core.user_accounts a {_aj}
                WHERE {_BREACH_FILTER}
                  AND a.updated_at >= '{s}'::date AND a.updated_at < '{e}'::date + 1
                  {_aw_clause}
            ),
            restricted_news AS (
                SELECT DISTINCT country, date
                FROM core.event_calendars
                WHERE is_blocked = 1
                  AND date >= '{s}'::date AND date < '{e}'::date + 1
                  AND country NOT IN ('All', 'ALL')
            ),
            news_breach AS (
                SELECT DISTINCT b.account_id, b.phase
                FROM violated b
                JOIN {tbl} t ON t.account_id = b.account_id
                JOIN restricted_news rn ON t.symbol ILIKE '%' || rn.country || '%'
                WHERE t.open_time <= rn.date + INTERVAL '5 minutes'
                  AND t.close_time >= rn.date - INTERVAL '5 minutes'
            )
            SELECT b.phase,
                   COUNT(*) AS total_violated,
                   COUNT(nb.account_id) AS news_violated
            FROM violated b
            LEFT JOIN news_breach nb ON b.account_id = nb.account_id AND b.phase = nb.phase
            GROUP BY 1
        """

    # Breach reason breakdown: ignores breach reason filter, uses all other filters
    _REASON_FILTER_BASE = f"a.violation_reason IS NOT NULL AND {_CFD_ONLY}{_model_clause}"

    def _sql_br_reason_breakdown(s, e):
        return f"""
            WITH all_violated AS (
                SELECT a.id,
                    CASE
                        WHEN a.violation_reason = 'Daily Loss Limit' THEN 'Daily Loss Limit'
                        WHEN a.violation_reason = 'Monthly Loss Limit' THEN 'Monthly Loss Limit'
                        WHEN a.violation_reason = 'Profit Target Reached' THEN 'Profit Target Reached'
                        WHEN a.violation_reason = 'Inactivity' THEN 'Inactivity'
                        ELSE 'Other'
                    END AS reason
                FROM core.user_accounts a {_aj}
                WHERE {_REASON_FILTER_BASE}
                  AND a.updated_at >= '{s}'::date AND a.updated_at < '{e}'::date + 1
                  {_aw_clause}
            )
            SELECT reason, COUNT(*) AS cnt
            FROM all_violated
            GROUP BY 1
        """

    # ── Load data (SQL string = cache key, no closures) ──
    _sel_s = str(_br_start)
    _sel_e = str(_br_end)
    _cmp_s = str(_br_comp_start)
    _cmp_e = str(_br_comp_end)

    with st.spinner("Loading breach data..."):
        br_y = _qc(_sql_br_by_phase(_sel_s, _sel_e))
        br_db = _qc(_sql_br_by_phase(_cmp_s, _cmp_e))
        rep_y = _qc(_sql_br_repurchase_by_phase(_sel_s, _sel_e))
        rep_db = _qc(_sql_br_repurchase_by_phase(_cmp_s, _cmp_e))
        br_tot_y = _qc(_sql_br_totals(_sel_s, _sel_e))
        br_tot_db = _qc(_sql_br_totals(_cmp_s, _cmp_e))
        rep_tot_y = _qc(_sql_br_repurchase_total(_sel_s, _sel_e))
        rep_tot_db = _qc(_sql_br_repurchase_total(_cmp_s, _cmp_e))
        news_y = _qc(_sql_br_news_pct(_sel_s, _sel_e))
        news_db = _qc(_sql_br_news_pct(_cmp_s, _cmp_e))
        reason_y = _qc(_sql_br_reason_breakdown(_sel_s, _sel_e))
        reason_db = _qc(_sql_br_reason_breakdown(_cmp_s, _cmp_e))

    # ── Helpers ───────────────────────────────────────────
    phases = ["P1 (Demo)", "P2", "Real", "Instant"]
    phase_labels = ["P1 / Demo", "P2", "Real", "Instant"]

    # ── Breach Reason Breakdown ────────────────────────────
    _reason_order = ["Daily Loss Limit", "Monthly Loss Limit", "Profit Target Reached", "Inactivity", "Other"]
    _reason_short = ["DLL", "MLL", "Profit Target", "Inactivity", "Other"]

    def _rval(df, reason):
        row = df[df["reason"] == reason]
        return int(row["cnt"].iloc[0]) if not row.empty else 0

    _reason_total_y = int(reason_y["cnt"].sum()) if not reason_y.empty else 0
    _reason_total_db = int(reason_db["cnt"].sum()) if not reason_db.empty else 0

    st.subheader("Breach Reason Breakdown")
    if _br_start == _br_end:
        st.caption(f"{_br_start.strftime('%b %d, %Y')}  —  all breach reasons (ignores reason filter)")
    else:
        st.caption(f"{_br_start.strftime('%b %d')} to {_br_end.strftime('%b %d, %Y')}  —  all breach reasons (ignores reason filter)")

    _rc = st.columns(len(_reason_order))
    for i, (reason, short) in enumerate(zip(_reason_order, _reason_short)):
        cnt_y = _rval(reason_y, reason)
        cnt_db = _rval(reason_db, reason)
        pct_y = (cnt_y / _reason_total_y * 100) if _reason_total_y > 0 else 0
        pct_db = (cnt_db / _reason_total_db * 100) if _reason_total_db > 0 else 0
        with _rc[i]:
            st.metric(short, f"{pct_y:.1f}%", metric_delta(pct_y, pct_db))
            st.caption(f"{cnt_y:,} accounts")

    st.divider()

    # ── Breach Counts ─────────────────────────────────────
    if _br_start == _br_end:
        st.subheader(f"Breaches — {_br_start.strftime('%b %d, %Y')}")
    else:
        st.subheader(f"Breaches — {_br_start.strftime('%b %d')} to {_br_end.strftime('%b %d, %Y')}")
    st.caption(f"Compared to {_br_comp_start.strftime('%b %d')} – {_br_comp_end.strftime('%b %d, %Y')}")

    cols = st.columns(len(phases) + 1)
    for i, (ph, label) in enumerate(zip(phases, phase_labels)):
        y_logins = _bval(br_y, ph, "logins")
        y_custs = _bval(br_y, ph, "customers")
        db_logins = _bval(br_db, ph, "logins")
        db_custs = _bval(br_db, ph, "customers")
        with cols[i]:
            st.caption(f"**{label}**")
            st.metric("Accounts", f"{y_logins:,}", metric_delta(y_logins, db_logins))
            st.metric("Customers", f"{y_custs:,}", metric_delta(y_custs, db_custs))

    # Total (deduplicated)
    _tot_logins_y = int(br_tot_y.iloc[0]["logins"]) if not br_tot_y.empty else 0
    _tot_custs_y = int(br_tot_y.iloc[0]["customers"]) if not br_tot_y.empty else 0
    _tot_logins_db = int(br_tot_db.iloc[0]["logins"]) if not br_tot_db.empty else 0
    _tot_custs_db = int(br_tot_db.iloc[0]["customers"]) if not br_tot_db.empty else 0
    with cols[-1]:
        st.caption("**TOTAL**")
        st.metric("Accounts", f"{_tot_logins_y:,}", metric_delta(_tot_logins_y, _tot_logins_db))
        st.metric("Customers", f"{_tot_custs_y:,}", metric_delta(_tot_custs_y, _tot_custs_db))

    # ── Breach Share (% of total) ────────────────────────
    st.caption("**Breach Share by Phase**")
    _br_share_cols = st.columns(len(phases) + 1)
    for i, (ph, label) in enumerate(zip(phases, phase_labels)):
        y_custs = _bval(br_y, ph, "customers")
        share = (y_custs / _tot_custs_y * 100) if _tot_custs_y > 0 else 0
        db_custs = _bval(br_db, ph, "customers")
        db_share = (db_custs / _tot_custs_db * 100) if _tot_custs_db > 0 else 0
        with _br_share_cols[i]:
            st.metric(f"{label}", f"{share:.1f}%", metric_delta(share, db_share))
    with _br_share_cols[-1]:
        st.metric("TOTAL", "100%")

    # ── News Impact (% violated during restricted news) ──
    st.caption("**News Impact (% violated during restricted news)**")
    _news_cols = st.columns(len(phases) + 1)
    _news_tot_y = int(news_y["news_violated"].sum()) if not news_y.empty else 0
    _news_all_y = int(news_y["total_violated"].sum()) if not news_y.empty else 0
    _news_tot_db = int(news_db["news_violated"].sum()) if not news_db.empty else 0
    _news_all_db = int(news_db["total_violated"].sum()) if not news_db.empty else 0

    for i, (ph, label) in enumerate(zip(phases, phase_labels)):
        n_all = _bval(news_y, ph, "total_violated")
        n_news = _bval(news_y, ph, "news_violated")
        pct = (n_news / n_all * 100) if n_all > 0 else 0
        n_all_db = _bval(news_db, ph, "total_violated")
        n_news_db = _bval(news_db, ph, "news_violated")
        pct_db = (n_news_db / n_all_db * 100) if n_all_db > 0 else 0
        with _news_cols[i]:
            st.metric(f"{label}", f"{pct:.1f}%", metric_delta(pct, pct_db))
    _total_news_pct_y = (_news_tot_y / _news_all_y * 100) if _news_all_y > 0 else 0
    _total_news_pct_db = (_news_tot_db / _news_all_db * 100) if _news_all_db > 0 else 0
    with _news_cols[-1]:
        st.metric("TOTAL", f"{_total_news_pct_y:.1f}%", metric_delta(_total_news_pct_y, _total_news_pct_db))

    st.divider()

    # ── Repurchase ────────────────────────────────────────
    st.subheader("Repurchase from Breached")

    cols2 = st.columns(len(phases) + 1)
    # Pre-compute per-phase repurchase values for share calculation
    _phase_rep_custs_y = {}
    _phase_rep_rate_y = {}
    for ph in phases:
        violated_custs = _bval(br_y, ph, "customers")
        rep_custs = _bval(rep_y, ph, "repurchased_customers")
        _phase_rep_custs_y[ph] = rep_custs
        _phase_rep_rate_y[ph] = (rep_custs / violated_custs * 100) if violated_custs > 0 else 0

    total_rep_cust_y = int(rep_tot_y.iloc[0]["repurchased_customers"]) if not rep_tot_y.empty else 0
    total_rep_avg_y = float(rep_tot_y.iloc[0]["avg_order_value"]) if not rep_tot_y.empty else 0
    total_rate_y = (total_rep_cust_y / _tot_custs_y * 100) if _tot_custs_y > 0 else 0

    total_rep_cust_db = int(rep_tot_db.iloc[0]["repurchased_customers"]) if not rep_tot_db.empty else 0
    total_rep_avg_db = float(rep_tot_db.iloc[0]["avg_order_value"]) if not rep_tot_db.empty else 0
    total_rate_db = (total_rep_cust_db / _tot_custs_db * 100) if _tot_custs_db > 0 else 0

    for i, (ph, label) in enumerate(zip(phases, phase_labels)):
        violated_custs = _bval(br_y, ph, "customers")
        rep_custs = _phase_rep_custs_y[ph]
        avg_ov = _bval_f(rep_y, ph, "avg_order_value")
        rate = _phase_rep_rate_y[ph]

        db_violated = _bval(br_db, ph, "customers")
        db_rep_custs = _bval(rep_db, ph, "repurchased_customers")
        db_rate = (db_rep_custs / db_violated * 100) if db_violated > 0 else 0
        db_avg_ov = _bval_f(rep_db, ph, "avg_order_value")

        with cols2[i]:
            st.caption(f"**{label}**")
            st.metric("Repurchase %", f"{rate:.1f}%", metric_delta(rate, db_rate))
            st.metric("Customers", f"{rep_custs:,}", metric_delta(rep_custs, db_rep_custs))
            st.metric("Avg Order", f"${avg_ov:,.0f}", metric_delta(avg_ov, db_avg_ov))

    with cols2[-1]:
        st.caption("**TOTAL**")
        st.metric("Repurchase %", f"{total_rate_y:.1f}%", metric_delta(total_rate_y, total_rate_db))
        st.metric("Customers", f"{total_rep_cust_y:,}", metric_delta(total_rep_cust_y, total_rep_cust_db))
        st.metric("Avg Order", f"${total_rep_avg_y:,.0f}", metric_delta(total_rep_avg_y, total_rep_avg_db))

    # ── Repurchase Share (% of total repurchases) ─────────
    st.caption("**Repurchase Share by Phase**")
    _rep_share_cols = st.columns(len(phases) + 1)
    for i, (ph, label) in enumerate(zip(phases, phase_labels)):
        rep_custs = _phase_rep_custs_y[ph]
        share = (rep_custs / total_rep_cust_y * 100) if total_rep_cust_y > 0 else 0
        db_rep_custs = _bval(rep_db, ph, "repurchased_customers")
        db_share = (db_rep_custs / total_rep_cust_db * 100) if total_rep_cust_db > 0 else 0
        with _rep_share_cols[i]:
            st.metric(f"{label}", f"{share:.1f}%", metric_delta(share, db_share))
    with _rep_share_cols[-1]:
        st.metric("TOTAL", "100%")

    # ── News Impact (same metric repeated for context) ───
    st.caption("**News Impact (% violated during restricted news)**")
    _news_cols2 = st.columns(len(phases) + 1)
    for i, (ph, label) in enumerate(zip(phases, phase_labels)):
        n_all = _bval(news_y, ph, "total_violated")
        n_news = _bval(news_y, ph, "news_violated")
        pct = (n_news / n_all * 100) if n_all > 0 else 0
        n_all_db = _bval(news_db, ph, "total_violated")
        n_news_db = _bval(news_db, ph, "news_violated")
        pct_db = (n_news_db / n_all_db * 100) if n_all_db > 0 else 0
        with _news_cols2[i]:
            st.metric(f"{label}", f"{pct:.1f}%", metric_delta(pct, pct_db))
    with _news_cols2[-1]:
        st.metric("TOTAL", f"{_total_news_pct_y:.1f}%", metric_delta(_total_news_pct_y, _total_news_pct_db))
