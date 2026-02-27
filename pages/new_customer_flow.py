import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
from shared import get_theme, _qc
from db import run_query


# ── Module-level constants ────────────────────────────────
_NCF_MODELS = ["Standard 2-Phase", "Standard 1-Phase", "Basic Lite", "Direct Start",
                "Evaluation", "Express"]
_NCF_PATTERNS = {
    "Standard 2-Phase": "standard 2-phase",
    "Standard 1-Phase": "standard 1-phase",
    "Basic Lite": "basic lite",
    "Direct Start": "direct start",
    "Evaluation": "evaluation",
    "Express": "express",
}

_behaviors = ["No Subsequent Purchase", "Same Model Again Only",
              "Other Models Only", "Both Same + Other"]

_REP_BUCKETS = ["0 (first only)", "1", "2", "3", "4", "5", "6-10", "11+"]


# ── Module-level cached loaders ───────────────────────────
@st.cache_data(ttl=600)
def _ncf_load_regions():
    df = run_query("SELECT DISTINCT region FROM reporting.geo_regions WHERE region IS NOT NULL ORDER BY 1")
    return df["region"].tolist()

@st.cache_data(ttl=600)
def _ncf_load_countries():
    df = run_query("SELECT DISTINCT name FROM reporting.geo_regions ORDER BY 1")
    return df["name"].tolist()

@st.cache_data(ttl=600)
def _ncf_load_coupons():
    df = run_query(
        "SELECT DISTINCT c.code FROM core.promo_codes c"
        " JOIN core.purchases o ON o.promo_id = c.id"
        " WHERE o.status = 1 ORDER BY c.code"
    )
    return df["code"].tolist()


# ── Module-level pure helpers ─────────────────────────────
def _ncf_sql_list(vals):
    return ",".join("'" + v.replace("'", "''") + "'" for v in vals)


def _ncf_pass_rate(p1_b, p2_c, p2_b, real_c, rt):
    """Auto-detect model type from data and compute pass rate."""
    if p1_b == 0 and rt == 0 and p2_c == 0:
        return None  # Instant / no challenge
    if p2_c > 0:  # 2-step model
        d1 = p1_b + rt
        p1_pass = p2_c / d1 if d1 else 0
        p2_pass = real_c / p2_b if p2_b else 0
        return p1_pass * p2_pass * 100
    else:  # 1-step model
        d1 = p1_b + rt
        return (real_c / d1 * 100) if d1 else 0


# ── render() ──────────────────────────────────────────────
def render():
    _T = get_theme()
    st.header("New Customer Flow")
    st.caption("Post-purchase behavior: what do customers do after their first purchase of a model?")

    with st.form("ncf_filters"):
        _ncf_dc1, _ncf_dc2 = st.columns(2)
        with _ncf_dc1:
            _ncf_6m = datetime.now().date().month - 2
            _ncf_6y = datetime.now().date().year + (_ncf_6m - 1) // 12
            _ncf_6m = (_ncf_6m - 1) % 12 + 1
            _ncf_start = st.date_input("From", value=date(_ncf_6y, _ncf_6m, 1), key="ncf_start")
        with _ncf_dc2:
            _ncf_end = st.date_input("To", value=datetime.now().date() - timedelta(days=1), key="ncf_end")
        _ncf_fc1, _ncf_fc2, _ncf_fc3 = st.columns(3)
        with _ncf_fc1:
            _ncf_regions = st.multiselect("Region", _ncf_load_regions(), default=[], key="ncf_region")
        with _ncf_fc2:
            _ncf_countries = st.multiselect("Country", _ncf_load_countries(), default=[], key="ncf_country")
        with _ncf_fc3:
            _ncf_coupons = st.multiselect("Coupon", _ncf_load_coupons(), default=[], key="ncf_coupon")
        st.form_submit_button("Analyze", use_container_width=True, type="primary")

    # ── Build filter SQL fragments ────────────────────────────
    # Geo filter for orders table (alias o, via user_id)
    _ncf_gj_ord = ""
    _ncf_gw_ord = ""
    if _ncf_regions or _ncf_countries:
        _ncf_gj_ord = (" JOIN core.users _gc ON o.user_id = _gc.id"
                        " JOIN core.regions _gco ON _gc.country_id = _gco.id"
                        " JOIN reporting.geo_regions _gr"
                        " ON _gco.short_name = _gr.short_name")
        _gw = []
        if _ncf_regions:
            _gw.append(f"_gr.region IN ({_ncf_sql_list(_ncf_regions)})")
        if _ncf_countries:
            _gw.append(f"_gr.name IN ({_ncf_sql_list(_ncf_countries)})")
        _ncf_gw_ord = " AND " + " AND ".join(_gw)

    # Geo filter for customers table directly (alias cu, has country_id)
    _ncf_gj_cust = ""
    _ncf_gw_cust = ""
    if _ncf_regions or _ncf_countries:
        _ncf_gj_cust = (" JOIN core.regions _gco ON cu.country_id = _gco.id"
                         " JOIN reporting.geo_regions _gr"
                         " ON _gco.short_name = _gr.short_name")
        _gw = []
        if _ncf_regions:
            _gw.append(f"_gr.region IN ({_ncf_sql_list(_ncf_regions)})")
        if _ncf_countries:
            _gw.append(f"_gr.name IN ({_ncf_sql_list(_ncf_countries)})")
        _ncf_gw_cust = " AND " + " AND ".join(_gw)

    # Coupon filter for orders table (alias o, via promo_id)
    _ncf_cj = ""
    _ncf_cw = ""
    if _ncf_coupons:
        _ncf_cj = " JOIN core.promo_codes _cp ON o.promo_id = _cp.id"
        _ncf_cw = f" AND _cp.code IN ({_ncf_sql_list(_ncf_coupons)})"

    # ── SQL builder functions (closure vars from filter fragments) ──
    def _sql_ncf_signups(s, e):
        return f"""
        SELECT TO_CHAR(cu.created_at, 'YYYY-MM') AS month, COUNT(*) AS signups
        FROM core.users cu
        {_ncf_gj_cust}
        WHERE cu.created_at >= '{s}'::date AND cu.created_at < '{e}'::date + 1{_ncf_gw_cust}
        GROUP BY 1 ORDER BY 1
        """

    def _sql_ncf_dist(s, e):
        return f"""
        WITH first_cfd_order AS (
            SELECT DISTINCT ON (o.user_id)
                   o.user_id, o.created_at AS first_date,
                   CASE
                       WHEN a.type ILIKE '%direct start%' THEN 'Direct Start'
                       WHEN a.type ILIKE '%standard 1-phase%' THEN 'Standard 1-Phase'
                       WHEN a.type ILIKE '%standard 2-phase%' THEN 'Standard 2-Phase'
                       WHEN a.type ILIKE '%basic lite%' THEN 'Basic Lite'
                       WHEN a.type ILIKE '%evaluation%' THEN 'Evaluation'
                       WHEN a.type ILIKE '%express%' THEN 'Express'
                       ELSE 'Other'
                   END AS model
            FROM core.purchases o
            JOIN core.user_accounts a ON o.account_id = a.id
            {_ncf_gj_ord}{_ncf_cj}
            WHERE o.status = 1 AND a.type NOT ILIKE '%futures%'{_ncf_gw_ord}{_ncf_cw}
            ORDER BY o.user_id, o.created_at
        )
        SELECT TO_CHAR(f.first_date, 'YYYY-MM') AS month,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE
                   TO_CHAR(c.created_at, 'YYYY-MM') = TO_CHAR(f.first_date, 'YYYY-MM')
               ) AS same_month_signup,
               COUNT(*) FILTER (WHERE model = 'Direct Start') AS instant,
               COUNT(*) FILTER (WHERE model = 'Standard 1-Phase') AS one_step,
               COUNT(*) FILTER (WHERE model = 'Standard 2-Phase') AS two_step,
               COUNT(*) FILTER (WHERE model = 'Basic Lite') AS lite,
               COUNT(*) FILTER (WHERE model = 'Evaluation') AS evaluation,
               COUNT(*) FILTER (WHERE model = 'Express') AS express
        FROM first_cfd_order f
        JOIN core.users c ON f.user_id = c.id
        WHERE f.first_date >= '{s}'::date AND f.first_date < '{e}'::date + 1
        GROUP BY 1
        ORDER BY 1
        """

    def _sql_ncf_segment_monthly(s, e):
        return f"""
        WITH customer_first_cfd AS (
            SELECT o.user_id, MIN(o.created_at) AS first_ever_date
            FROM core.purchases o
            JOIN core.user_accounts a ON o.account_id = a.id
            {_ncf_gj_ord}
            WHERE o.status = 1 AND a.type NOT ILIKE '%futures%'{_ncf_gw_ord}
            GROUP BY o.user_id
        ),
        model_first AS (
            SELECT o.user_id,
                CASE
                    WHEN a.type ILIKE '%direct start%' THEN 'Direct Start'
                    WHEN a.type ILIKE '%standard 1-phase%' THEN 'Standard 1-Phase'
                    WHEN a.type ILIKE '%standard 2-phase%' THEN 'Standard 2-Phase'
                    WHEN a.type ILIKE '%basic lite%' THEN 'Basic Lite'
                    WHEN a.type ILIKE '%evaluation%' THEN 'Evaluation'
                    WHEN a.type ILIKE '%express%' THEN 'Express'
                    ELSE 'Other'
                END AS model,
                MIN(o.created_at) AS first_model_date
            FROM core.purchases o
            JOIN core.user_accounts a ON o.account_id = a.id
            {_ncf_gj_ord}{_ncf_cj}
            WHERE o.status = 1 AND a.type NOT ILIKE '%futures%'{_ncf_gw_ord}{_ncf_cw}
            GROUP BY o.user_id, 2
        ),
        segmented AS (
            SELECT mf.user_id, mf.model,
                TO_CHAR(mf.first_model_date, 'YYYY-MM') AS month,
                CASE WHEN mf.first_model_date = cfc.first_ever_date
                     THEN 'New' ELSE 'Prior Model' END AS segment
            FROM model_first mf
            JOIN customer_first_cfd cfc ON mf.user_id = cfc.user_id
            WHERE mf.first_model_date >= '{s}'::date
              AND mf.first_model_date <  '{e}'::date + 1
              AND mf.model != 'Other'
        )
        SELECT month, model, segment, COUNT(DISTINCT user_id) AS customers
        FROM segmented
        GROUP BY month, model, segment
        ORDER BY month, model, segment
        """

    def _sql_ncf(pat, s, e):
        return f"""
        WITH customer_first_order AS (
            SELECT o.user_id, MIN(o.created_at) AS first_ever_date
            FROM core.purchases o
            JOIN core.user_accounts a ON o.account_id = a.id
            {_ncf_gj_ord}
            WHERE o.status = 1 AND a.type NOT ILIKE '%futures%'{_ncf_gw_ord}
            GROUP BY o.user_id
        ),
        model_customers AS (
            SELECT o.user_id, MIN(o.created_at) AS first_model_date
            FROM core.purchases o
            JOIN core.user_accounts a ON o.account_id = a.id
            {_ncf_gj_ord}{_ncf_cj}
            WHERE o.status = 1 AND a.type ILIKE '%{pat}%'{_ncf_gw_ord}{_ncf_cw}
            GROUP BY o.user_id
        ),
        segmented AS (
            SELECT mc.user_id, mc.first_model_date,
                CASE WHEN mc.first_model_date = cfo.first_ever_date
                     THEN 'Direct Purchase' ELSE 'Prior Model' END AS segment
            FROM model_customers mc
            JOIN customer_first_order cfo ON mc.user_id = cfo.user_id
            WHERE mc.first_model_date >= '{s}'::date
              AND mc.first_model_date < '{e}'::date + 1
        ),
        post_purchase AS (
            SELECT s.user_id, s.segment,
                COALESCE(BOOL_OR(oa.type ILIKE '%{pat}%'), FALSE) AS bought_same,
                COALESCE(BOOL_OR(oa.type NOT ILIKE '%{pat}%'), FALSE) AS bought_other,
                COUNT(*) FILTER (WHERE oa.type ILIKE '%{pat}%') AS same_orders,
                COALESCE(SUM(oa.total_amount) FILTER (WHERE oa.type ILIKE '%{pat}%'), 0) AS same_revenue,
                COUNT(*) FILTER (WHERE oa.type NOT ILIKE '%{pat}%') AS other_orders,
                COALESCE(SUM(oa.total_amount) FILTER (WHERE oa.type NOT ILIKE '%{pat}%'), 0) AS other_revenue
            FROM segmented s
            LEFT JOIN (
                SELECT o.user_id, o.total_amount, o.created_at, a.type
                FROM core.purchases o
                JOIN core.user_accounts a ON o.account_id = a.id
                WHERE o.status = 1 AND a.type NOT ILIKE '%futures%'
            ) oa ON oa.user_id = s.user_id AND oa.created_at > s.first_model_date
            GROUP BY s.user_id, s.segment
        ),
        classified AS (
            SELECT user_id, segment,
                CASE
                    WHEN NOT bought_same AND NOT bought_other THEN 'No Subsequent Purchase'
                    WHEN bought_same AND NOT bought_other THEN 'Same Model Again Only'
                    WHEN NOT bought_same AND bought_other THEN 'Other Models Only'
                    ELSE 'Both Same + Other'
                END AS behavior,
                same_orders, same_revenue, other_orders, other_revenue
            FROM post_purchase
        ),
        acct_stats AS (
            SELECT c.user_id,
                COUNT(*) FILTER (WHERE a.type ILIKE '%{pat}%'
                    AND a.type ILIKE '%Demo%' AND a.type NOT ILIKE '%P2%'
                    AND a.violated IS NOT NULL) AS p1_violated,
                COUNT(*) FILTER (WHERE a.type ILIKE '%{pat}%'
                    AND a.type ILIKE '%P2%') AS p2_count,
                COUNT(*) FILTER (WHERE a.type ILIKE '%{pat}%'
                    AND a.type ILIKE '%P2%'
                    AND a.violated IS NOT NULL) AS p2_violated,
                COUNT(*) FILTER (WHERE a.type ILIKE '%{pat}%'
                    AND a.type ILIKE '%Real%') AS real_count
            FROM classified c
            JOIN core.user_accounts a ON a.user_id = c.user_id
            GROUP BY c.user_id
        ),
        reset_stats AS (
            SELECT c.user_id, COUNT(*) AS rt_count
            FROM classified c
            JOIN core.purchases o ON o.user_id = c.user_id
                AND o.status = 1 AND o.order_type IN (2, 3)
            JOIN core.user_accounts a ON o.account_id = a.id
                AND a.type ILIKE '%{pat}%'
            GROUP BY c.user_id
        ),
        all_rev AS (
            SELECT c.user_id, COALESCE(SUM(o.total_amount), 0) AS total_rev
            FROM classified c
            JOIN core.purchases o ON o.user_id = c.user_id AND o.status = 1
            JOIN core.user_accounts a ON o.account_id = a.id
                AND a.type NOT ILIKE '%futures%'
            GROUP BY c.user_id
        ),
        payout_stats AS (
            SELECT c.user_id, COALESCE(SUM(wt.amount - COALESCE(wt.fee_amount, 0)), 0) AS payout_amt
            FROM classified c
            JOIN core.wallet_transfers wt
                ON wt.user_id = c.user_id
                AND wt.type = 1 AND wt.status = 8
            GROUP BY c.user_id
        )
        SELECT c.segment, c.behavior,
            COUNT(*) AS customers,
            SUM(c.same_orders) AS same_orders,
            SUM(c.same_revenue) AS same_revenue,
            SUM(c.other_orders) AS other_orders,
            SUM(c.other_revenue) AS other_revenue,
            SUM(COALESCE(a.p1_violated, 0)) AS p1_violated,
            SUM(COALESCE(a.p2_count, 0)) AS p2_count,
            SUM(COALESCE(a.p2_violated, 0)) AS p2_violated,
            SUM(COALESCE(a.real_count, 0)) AS real_count,
            SUM(COALESCE(rs.rt_count, 0)) AS reset_topup,
            SUM(COALESCE(ar.total_rev, 0)) AS total_revenue,
            SUM(COALESCE(ps.payout_amt, 0)) AS payout_amount
        FROM classified c
        LEFT JOIN acct_stats a ON c.user_id = a.user_id
        LEFT JOIN reset_stats rs ON c.user_id = rs.user_id
        LEFT JOIN all_rev ar ON c.user_id = ar.user_id
        LEFT JOIN payout_stats ps ON c.user_id = ps.user_id
        GROUP BY c.segment, c.behavior
        ORDER BY c.segment,
            CASE c.behavior
                WHEN 'No Subsequent Purchase' THEN 1
                WHEN 'Same Model Again Only' THEN 2
                WHEN 'Other Models Only' THEN 3
                ELSE 4
            END
        """

    def _sql_ncf_repurchase(pat, s, e):
        return f"""
        WITH customer_first_cfd AS (
            SELECT o.user_id, MIN(o.created_at) AS first_ever_date
            FROM core.purchases o
            JOIN core.user_accounts a ON o.account_id = a.id
            {_ncf_gj_ord}
            WHERE o.status = 1 AND a.type NOT ILIKE '%futures%'{_ncf_gw_ord}
            GROUP BY o.user_id
        ),
        model_customers AS (
            SELECT o.user_id, MIN(o.created_at) AS first_model_date
            FROM core.purchases o
            JOIN core.user_accounts a ON o.account_id = a.id
            {_ncf_gj_ord}{_ncf_cj}
            WHERE o.status = 1 AND a.type ILIKE '%{pat}%'{_ncf_gw_ord}{_ncf_cw}
            GROUP BY o.user_id
        ),
        segmented AS (
            SELECT mc.user_id, mc.first_model_date,
                CASE WHEN mc.first_model_date = cfc.first_ever_date
                     THEN 'Direct' ELSE 'Prior Model' END AS segment
            FROM model_customers mc
            JOIN customer_first_cfd cfc ON mc.user_id = cfc.user_id
            WHERE mc.first_model_date >= '{s}'::date
              AND mc.first_model_date <  '{e}'::date + 1
        ),
        first_model_order AS (
            SELECT DISTINCT ON (s.user_id)
                   s.user_id, s.segment, o.total_amount AS first_gt
            FROM segmented s
            JOIN core.purchases o ON o.user_id = s.user_id AND o.status = 1
            JOIN core.user_accounts a ON o.account_id = a.id
                AND a.type ILIKE '%{pat}%'
            WHERE o.created_at >= s.first_model_date
            ORDER BY s.user_id, o.created_at
        ),
        post_orders AS (
            SELECT s.user_id, s.segment,
                o.total_amount, a.type AS acct_type,
                CASE WHEN a.type ILIKE '%{pat}%' THEN 'same' ELSE 'other' END AS mclass
            FROM segmented s
            JOIN core.purchases o ON o.user_id = s.user_id
                AND o.status = 1 AND o.created_at > s.first_model_date
            JOIN core.user_accounts a ON o.account_id = a.id
                AND a.type NOT ILIKE '%futures%'
        ),
        customer_agg AS (
            SELECT s.user_id, s.segment,
                COALESCE(COUNT(po.total_amount), 0) AS repurchase_count,
                COUNT(po.total_amount) FILTER (WHERE po.mclass = 'same') AS same_post_orders,
                COALESCE(SUM(po.total_amount) FILTER (WHERE po.mclass = 'same'), 0) AS same_post_rev,
                COUNT(po.total_amount) FILTER (WHERE po.mclass = 'other') AS other_orders,
                COALESCE(SUM(po.total_amount) FILTER (WHERE po.mclass = 'other'), 0) AS other_revenue
            FROM segmented s
            LEFT JOIN post_orders po ON po.user_id = s.user_id
            GROUP BY s.user_id, s.segment
        ),
        customer_full AS (
            SELECT ca.*,
                ca.same_post_orders + 1 AS same_orders,
                ca.same_post_rev + fmo.first_gt AS same_revenue,
                ca.other_orders AS other_orders_f,
                ca.other_revenue AS other_revenue_f
            FROM customer_agg ca
            JOIN first_model_order fmo ON ca.user_id = fmo.user_id
        ),
        all_rev AS (
            SELECT cf.user_id, COALESCE(SUM(o.total_amount), 0) AS total_rev
            FROM customer_full cf
            JOIN core.purchases o ON o.user_id = cf.user_id AND o.status = 1
            JOIN core.user_accounts a ON o.account_id = a.id AND a.type NOT ILIKE '%futures%'
            GROUP BY cf.user_id
        ),
        payout_overall AS (
            SELECT cf.user_id,
                COALESCE(SUM(wt.amount - COALESCE(wt.fee_amount, 0)), 0) AS pay_all
            FROM customer_full cf
            JOIN core.wallet_transfers wt ON wt.user_id = cf.user_id
                AND wt.type = 1 AND wt.status = 8
            GROUP BY cf.user_id
        ),
        payout_same AS (
            SELECT cf.user_id,
                COALESCE(SUM(wt.amount - COALESCE(wt.fee_amount, 0)), 0) AS pay_same
            FROM customer_full cf
            JOIN core.wallet_transfers wt ON wt.user_id = cf.user_id
                AND wt.type = 1 AND wt.status = 8
            JOIN core.user_accounts a ON wt.account_id = a.id
                AND a.type ILIKE '%{pat}%'
            GROUP BY cf.user_id
        ),
        payout_other AS (
            SELECT cf.user_id,
                COALESCE(SUM(wt.amount - COALESCE(wt.fee_amount, 0)), 0) AS pay_other
            FROM customer_full cf
            JOIN core.wallet_transfers wt ON wt.user_id = cf.user_id
                AND wt.type = 1 AND wt.status = 8
            JOIN core.user_accounts a ON wt.account_id = a.id
                AND a.type NOT ILIKE '%{pat}%' AND a.type NOT ILIKE '%futures%'
            GROUP BY cf.user_id
        ),
        acct_stats_same AS (
            SELECT cf.user_id,
                COUNT(*) FILTER (WHERE a.type ILIKE '%{pat}%'
                    AND a.type ILIKE '%Demo%' AND a.type NOT ILIKE '%P2%'
                    AND a.violated IS NOT NULL) AS s_p1b,
                COUNT(*) FILTER (WHERE a.type ILIKE '%{pat}%'
                    AND a.type ILIKE '%P2%') AS s_p2c,
                COUNT(*) FILTER (WHERE a.type ILIKE '%{pat}%'
                    AND a.type ILIKE '%P2%' AND a.violated IS NOT NULL) AS s_p2b,
                COUNT(*) FILTER (WHERE a.type ILIKE '%{pat}%'
                    AND a.type ILIKE '%Real%') AS s_rc
            FROM customer_full cf
            JOIN core.user_accounts a ON a.user_id = cf.user_id
            GROUP BY cf.user_id
        ),
        acct_stats_other AS (
            SELECT cf.user_id,
                COUNT(*) FILTER (WHERE a.type NOT ILIKE '%{pat}%'
                    AND a.type NOT ILIKE '%futures%'
                    AND a.type ILIKE '%Demo%' AND a.type NOT ILIKE '%P2%'
                    AND a.violated IS NOT NULL) AS o_p1b,
                COUNT(*) FILTER (WHERE a.type NOT ILIKE '%{pat}%'
                    AND a.type NOT ILIKE '%futures%'
                    AND a.type ILIKE '%P2%') AS o_p2c,
                COUNT(*) FILTER (WHERE a.type NOT ILIKE '%{pat}%'
                    AND a.type NOT ILIKE '%futures%'
                    AND a.type ILIKE '%P2%' AND a.violated IS NOT NULL) AS o_p2b,
                COUNT(*) FILTER (WHERE a.type NOT ILIKE '%{pat}%'
                    AND a.type NOT ILIKE '%futures%'
                    AND a.type ILIKE '%Real%') AS o_rc
            FROM customer_full cf
            JOIN core.user_accounts a ON a.user_id = cf.user_id
            GROUP BY cf.user_id
        ),
        reset_stats_same AS (
            SELECT cf.user_id, COUNT(*) AS s_rt
            FROM customer_full cf
            JOIN core.purchases o ON o.user_id = cf.user_id
                AND o.status = 1 AND o.order_type IN (2, 3)
            JOIN core.user_accounts a ON o.account_id = a.id
                AND a.type ILIKE '%{pat}%'
            GROUP BY cf.user_id
        ),
        reset_stats_other AS (
            SELECT cf.user_id, COUNT(*) AS o_rt
            FROM customer_full cf
            JOIN core.purchases o ON o.user_id = cf.user_id
                AND o.status = 1 AND o.order_type IN (2, 3)
            JOIN core.user_accounts a ON o.account_id = a.id
                AND a.type NOT ILIKE '%{pat}%' AND a.type NOT ILIKE '%futures%'
            GROUP BY cf.user_id
        ),
        bucketed AS (
            SELECT cf.*,
                CASE
                    WHEN cf.repurchase_count = 0  THEN '0 (first only)'
                    WHEN cf.repurchase_count = 1  THEN '1'
                    WHEN cf.repurchase_count = 2  THEN '2'
                    WHEN cf.repurchase_count = 3  THEN '3'
                    WHEN cf.repurchase_count = 4  THEN '4'
                    WHEN cf.repurchase_count = 5  THEN '5'
                    WHEN cf.repurchase_count BETWEEN 6 AND 10 THEN '6-10'
                    ELSE '11+'
                END AS bucket,
                CASE
                    WHEN cf.repurchase_count = 0  THEN 1
                    WHEN cf.repurchase_count = 1  THEN 2
                    WHEN cf.repurchase_count = 2  THEN 3
                    WHEN cf.repurchase_count = 3  THEN 4
                    WHEN cf.repurchase_count = 4  THEN 5
                    WHEN cf.repurchase_count = 5  THEN 6
                    WHEN cf.repurchase_count BETWEEN 6 AND 10 THEN 7
                    ELSE 8
                END AS bucket_sort,
                COALESCE(ar.total_rev, 0) AS total_rev,
                COALESCE(po_all.pay_all, 0) AS pay_all,
                COALESCE(ps.pay_same, 0) AS pay_same,
                COALESCE(pot.pay_other, 0) AS pay_other,
                COALESCE(ass.s_p1b, 0) AS s_p1b, COALESCE(ass.s_p2c, 0) AS s_p2c,
                COALESCE(ass.s_p2b, 0) AS s_p2b, COALESCE(ass.s_rc, 0) AS s_rc,
                COALESCE(aso.o_p1b, 0) AS o_p1b, COALESCE(aso.o_p2c, 0) AS o_p2c,
                COALESCE(aso.o_p2b, 0) AS o_p2b, COALESCE(aso.o_rc, 0) AS o_rc,
                COALESCE(rss.s_rt, 0) AS s_rt, COALESCE(rso.o_rt, 0) AS o_rt
            FROM customer_full cf
            LEFT JOIN all_rev ar ON cf.user_id = ar.user_id
            LEFT JOIN payout_overall po_all ON cf.user_id = po_all.user_id
            LEFT JOIN payout_same ps ON cf.user_id = ps.user_id
            LEFT JOIN payout_other pot ON cf.user_id = pot.user_id
            LEFT JOIN acct_stats_same ass ON cf.user_id = ass.user_id
            LEFT JOIN acct_stats_other aso ON cf.user_id = aso.user_id
            LEFT JOIN reset_stats_same rss ON cf.user_id = rss.user_id
            LEFT JOIN reset_stats_other rso ON cf.user_id = rso.user_id
        )
        SELECT segment, bucket, bucket_sort,
            COUNT(*) AS customers,
            SUM(same_orders) AS same_orders, SUM(same_revenue) AS same_revenue,
            SUM(other_orders_f) AS other_orders, SUM(other_revenue_f) AS other_revenue,
            SUM(total_rev) AS total_revenue,
            SUM(pay_all) AS pay_all, SUM(pay_same) AS pay_same, SUM(pay_other) AS pay_other,
            SUM(s_p1b) AS s_p1b, SUM(s_p2c) AS s_p2c, SUM(s_p2b) AS s_p2b, SUM(s_rc) AS s_rc,
            SUM(o_p1b) AS o_p1b, SUM(o_p2c) AS o_p2c, SUM(o_p2b) AS o_p2b, SUM(o_rc) AS o_rc,
            SUM(s_rt) AS s_rt, SUM(o_rt) AS o_rt
        FROM bucketed
        GROUP BY segment, bucket, bucket_sort
        ORDER BY segment, bucket_sort
        """

    def _sql_ncf_seg_counts(pat, s, e):
        return f"""
        WITH customer_first_cfd AS (
            SELECT o.user_id, MIN(o.created_at) AS first_ever_date
            FROM core.purchases o
            JOIN core.user_accounts a ON o.account_id = a.id
            {_ncf_gj_ord}
            WHERE o.status = 1 AND a.type NOT ILIKE '%futures%'{_ncf_gw_ord}
            GROUP BY o.user_id
        ),
        model_customers AS (
            SELECT o.user_id, MIN(o.created_at) AS first_model_date
            FROM core.purchases o
            JOIN core.user_accounts a ON o.account_id = a.id
            {_ncf_gj_ord}{_ncf_cj}
            WHERE o.status = 1 AND a.type ILIKE '%{pat}%'{_ncf_gw_ord}{_ncf_cw}
            GROUP BY o.user_id
        ),
        segmented AS (
            SELECT mc.user_id,
                CASE WHEN mc.first_model_date = cfc.first_ever_date
                     THEN 'Direct' ELSE 'Prior Model' END AS segment
            FROM model_customers mc
            JOIN customer_first_cfd cfc ON mc.user_id = cfc.user_id
            WHERE mc.first_model_date >= '{s}'::date
              AND mc.first_model_date <  '{e}'::date + 1
        )
        SELECT segment, COUNT(*) AS customers FROM segmented GROUP BY segment
        """

    def _sql_ncf_overall(s, e):
        return f"""
        WITH first_cfd AS (
            SELECT DISTINCT ON (o.user_id)
                o.user_id, o.created_at,
                CASE
                    WHEN a.type ILIKE '%direct start%' THEN 'Direct Start'
                    WHEN a.type ILIKE '%standard 1-phase%' THEN 'Standard 1-Phase'
                    WHEN a.type ILIKE '%standard 2-phase%' THEN 'Standard 2-Phase'
                    WHEN a.type ILIKE '%basic lite%' THEN 'Basic Lite'
                    WHEN a.type ILIKE '%evaluation%' THEN 'Evaluation'
                    WHEN a.type ILIKE '%express%' THEN 'Express'
                    ELSE 'Other'
                END AS model
            FROM core.purchases o
            JOIN core.user_accounts a ON o.account_id = a.id
            {_ncf_gj_ord}{_ncf_cj}
            WHERE o.status = 1 AND a.type NOT ILIKE '%futures%'{_ncf_gw_ord}{_ncf_cw}
            ORDER BY o.user_id, o.created_at
        )
        SELECT model, COUNT(*) AS customers
        FROM first_cfd
        WHERE created_at >= '{s}'::date AND created_at < '{e}'::date + 1
        GROUP BY model
        """

    # ── HTML builder functions (use _T from render scope) ──
    def _ncf_build_html(seg_df, seg_total, model_name):
        _bth = (f"padding:10px 14px;text-align:right;font-size:12px;"
                f"color:{_T['tbl_hdr_text']};border-bottom:2px solid {_T['tbl_border']};"
                f"white-space:nowrap;background:{_T['tbl_hdr_bg']};")
        _btd = (f"padding:9px 14px;text-align:right;font-size:13px;"
                f"color:{_T['tbl_text']};border-bottom:1px solid {_T['tbl_row_border']};"
                f"white-space:nowrap;")
        _btd_beh = (f"padding:9px 14px;text-align:left;font-size:13px;"
                    f"color:{_T['tbl_text']};border-bottom:1px solid {_T['tbl_row_border']};"
                    f"font-weight:500;white-space:nowrap;")
        _btd_tot = (f"padding:10px 14px;text-align:right;font-size:13px;"
                    f"color:{_T['tbl_tot_text']};border-top:2px solid {_T['tbl_tot_border']};"
                    f"font-weight:700;white-space:nowrap;background:{_T['tbl_tot_bg']};")
        _btd_tot_beh = (f"padding:10px 14px;text-align:left;font-size:13px;"
                        f"color:{_T['tbl_tot_text']};border-top:2px solid {_T['tbl_tot_border']};"
                        f"font-weight:700;white-space:nowrap;background:{_T['tbl_tot_bg']};")

        headers = ["Behavior", "Customers", "% Share",
                   f"{model_name} Orders", f"{model_name} Revenue",
                   f"{model_name} AOV",
                   "Other Orders", "Other Revenue", "Other AOV",
                   "Payout Amt", "Payout Ratio", "Pass Rate"]

        html = (f'<div style="overflow-x:auto;margin-bottom:16px;">'
                f'<table style="min-width:100%;border-collapse:collapse;'
                f'background:{_T["tbl_bg"]};border-radius:8px;overflow:hidden;white-space:nowrap;">')
        html += "<thead><tr>"
        for h in headers:
            al = "text-align:left;" if h == "Behavior" else ""
            html += f'<th style="{_bth}{al}">{h}</th>'
        html += "</tr></thead><tbody>"

        t_cust = t_same_o = t_other_o = 0
        t_same_r = t_other_r = t_pay = t_rev = 0.0
        t_p1b = t_p2c = t_p2b = t_rc = t_rt = 0

        for b in _behaviors:
            brow = seg_df[seg_df["behavior"] == b]
            cust = int(brow["customers"].iloc[0]) if not brow.empty else 0
            pct = cust / seg_total * 100 if seg_total else 0
            same_o = int(brow["same_orders"].iloc[0]) if not brow.empty else 0
            same_r = float(brow["same_revenue"].iloc[0]) if not brow.empty else 0
            other_o = int(brow["other_orders"].iloc[0]) if not brow.empty else 0
            other_r = float(brow["other_revenue"].iloc[0]) if not brow.empty else 0
            same_aov = same_r / same_o if same_o else 0
            other_aov = other_r / other_o if other_o else 0
            p1_b = int(brow["p1_violated"].iloc[0]) if not brow.empty else 0
            p2_c = int(brow["p2_count"].iloc[0]) if not brow.empty else 0
            p2_b = int(brow["p2_violated"].iloc[0]) if not brow.empty else 0
            real_c = int(brow["real_count"].iloc[0]) if not brow.empty else 0
            rt = int(brow["reset_topup"].iloc[0]) if not brow.empty else 0
            tot_rev = float(brow["total_revenue"].iloc[0]) if not brow.empty else 0
            pay_amt = float(brow["payout_amount"].iloc[0]) if not brow.empty else 0

            pr = _ncf_pass_rate(p1_b, p2_c, p2_b, real_c, rt)
            payout_ratio = pay_amt / tot_rev * 100 if tot_rev else 0

            t_cust += cust; t_same_o += same_o; t_same_r += same_r
            t_other_o += other_o; t_other_r += other_r
            t_pay += pay_amt; t_rev += tot_rev
            t_p1b += p1_b; t_p2c += p2_c; t_p2b += p2_b
            t_rc += real_c; t_rt += rt

            pr_str = f"{pr:.2f}%" if pr is not None else "N/A"
            html += "<tr>"
            html += f'<td style="{_btd_beh}">{b}</td>'
            html += f'<td style="{_btd}">{cust:,}</td>'
            html += f'<td style="{_btd}">{pct:.1f}%</td>'
            html += f'<td style="{_btd}">{same_o:,}</td>' if same_o else f'<td style="{_btd}">\u2014</td>'
            html += f'<td style="{_btd}">${same_r:,.0f}</td>' if same_o else f'<td style="{_btd}">\u2014</td>'
            html += f'<td style="{_btd}">${same_aov:,.0f}</td>' if same_o else f'<td style="{_btd}">\u2014</td>'
            html += f'<td style="{_btd}">{other_o:,}</td>' if other_o else f'<td style="{_btd}">\u2014</td>'
            html += f'<td style="{_btd}">${other_r:,.0f}</td>' if other_o else f'<td style="{_btd}">\u2014</td>'
            html += f'<td style="{_btd}">${other_aov:,.0f}</td>' if other_o else f'<td style="{_btd}">\u2014</td>'
            html += f'<td style="{_btd}">${pay_amt:,.0f}</td>' if pay_amt else f'<td style="{_btd}">\u2014</td>'
            html += f'<td style="{_btd}">{payout_ratio:.1f}%</td>' if tot_rev else f'<td style="{_btd}">\u2014</td>'
            html += f'<td style="{_btd}">{pr_str}</td>'
            html += "</tr>"

        t_same_aov = t_same_r / t_same_o if t_same_o else 0
        t_other_aov = t_other_r / t_other_o if t_other_o else 0
        t_pr = _ncf_pass_rate(t_p1b, t_p2c, t_p2b, t_rc, t_rt)
        t_payout_ratio = t_pay / t_rev * 100 if t_rev else 0

        t_pr_str = f"{t_pr:.2f}%" if t_pr is not None else "N/A"
        html += "<tr>"
        html += f'<td style="{_btd_tot_beh}">Total</td>'
        html += f'<td style="{_btd_tot}">{seg_total:,}</td>'
        html += f'<td style="{_btd_tot}">100.0%</td>'
        html += f'<td style="{_btd_tot}">{t_same_o:,}</td>'
        html += f'<td style="{_btd_tot}">${t_same_r:,.0f}</td>'
        html += f'<td style="{_btd_tot}">${t_same_aov:,.0f}</td>' if t_same_o else f'<td style="{_btd_tot}">\u2014</td>'
        html += f'<td style="{_btd_tot}">{t_other_o:,}</td>'
        html += f'<td style="{_btd_tot}">${t_other_r:,.0f}</td>'
        html += f'<td style="{_btd_tot}">${t_other_aov:,.0f}</td>' if t_other_o else f'<td style="{_btd_tot}">\u2014</td>'
        html += f'<td style="{_btd_tot}">${t_pay:,.0f}</td>' if t_pay else f'<td style="{_btd_tot}">\u2014</td>'
        html += f'<td style="{_btd_tot}">{t_payout_ratio:.1f}%</td>' if t_rev else f'<td style="{_btd_tot}">\u2014</td>'
        html += f'<td style="{_btd_tot}">{t_pr_str}</td>'
        html += "</tr>"

        html += "</tbody></table></div>"
        return html

    def _ncf_rep_html(seg_df, seg_total, model_name):
        _rth = (f"padding:10px 14px;text-align:right;font-size:12px;"
                f"color:{_T['tbl_hdr_text']};border-bottom:2px solid {_T['tbl_border']};"
                f"white-space:nowrap;background:{_T['tbl_hdr_bg']};"
                f"position:sticky;top:0;z-index:1;")
        _rtd = (f"padding:9px 14px;text-align:right;font-size:13px;"
                f"color:{_T['tbl_text']};border-bottom:1px solid {_T['tbl_row_border']};"
                f"white-space:nowrap;")
        _rtd_lab = (f"padding:9px 14px;text-align:left;font-size:13px;"
                    f"color:{_T['tbl_text']};border-bottom:1px solid {_T['tbl_row_border']};"
                    f"font-weight:500;white-space:nowrap;")
        _rtd_tot = (f"padding:10px 14px;text-align:right;font-size:13px;"
                    f"color:{_T['tbl_tot_text']};border-top:2px solid {_T['tbl_tot_border']};"
                    f"font-weight:700;white-space:nowrap;background:{_T['tbl_tot_bg']};")
        _rtd_tot_lab = (f"padding:10px 14px;text-align:left;font-size:13px;"
                        f"color:{_T['tbl_tot_text']};border-top:2px solid {_T['tbl_tot_border']};"
                        f"font-weight:700;white-space:nowrap;background:{_T['tbl_tot_bg']};")

        headers = [
            "Repurchases", "Customers", "% Share", "Cumul %",
            "Overall Payout Amt (Cumul)", "Overall Payout Ratio (Cumul)", "Overall Pass Rate (Cumul)",
            f"{model_name} Orders", f"{model_name} Revenue (Cumul)", f"{model_name} AOV",
            f"{model_name} Payout Ratio (Cumul)", f"{model_name} Payout Amt (Cumul)", f"{model_name} Pass Rate (Cumul)",
            "Other Models Orders", "Other Models Revenue (Cumul)", "Other Models AOV",
            "Other Models Payout Ratio (Cumul)", "Other Models Payout Amt (Cumul)", "Other Models Pass Rate (Cumul)",
        ]

        html = (f'<div style="overflow-x:auto;margin-bottom:16px;">'
                f'<table style="min-width:100%;border-collapse:collapse;'
                f'background:{_T["tbl_bg"]};border-radius:8px;overflow:hidden;white-space:nowrap;">')
        html += "<thead><tr>"
        for h in headers:
            al = "text-align:left;" if h == "Repurchases" else ""
            html += f'<th style="{_rth}{al}">{h}</th>'
        html += "</tr></thead><tbody>"

        # Cumulative accumulators for revenue, payout, pass rate stats
        cumul_pct = 0.0
        c_smr = c_omr = c_pa = c_ps = c_po = c_rev = 0.0
        c_s_p1b = c_s_p2c = c_s_p2b = c_s_rc = c_s_rt = 0
        c_o_p1b = c_o_p2c = c_o_p2b = c_o_rc = c_o_rt = 0

        def _pr_str(pr):
            return f'{pr:.2f}%' if pr is not None else 'N/A'

        for bkt in _REP_BUCKETS:
            brow = seg_df[seg_df["bucket"] == bkt]
            cust = int(brow["customers"].iloc[0]) if not brow.empty else 0
            if cust == 0:
                continue

            pct = cust / seg_total * 100 if seg_total else 0
            cumul_pct += pct

            smo = int(brow["same_orders"].iloc[0]) if not brow.empty else 0
            smr = float(brow["same_revenue"].iloc[0]) if not brow.empty else 0
            omo = int(brow["other_orders"].iloc[0]) if not brow.empty else 0
            omr = float(brow["other_revenue"].iloc[0]) if not brow.empty else 0
            tot_rev = float(brow["total_revenue"].iloc[0]) if not brow.empty else 0
            pa = float(brow["pay_all"].iloc[0]) if not brow.empty else 0
            ps_v = float(brow["pay_same"].iloc[0]) if not brow.empty else 0
            po_v = float(brow["pay_other"].iloc[0]) if not brow.empty else 0

            sp1b = int(brow["s_p1b"].iloc[0]) if not brow.empty else 0
            sp2c = int(brow["s_p2c"].iloc[0]) if not brow.empty else 0
            sp2b = int(brow["s_p2b"].iloc[0]) if not brow.empty else 0
            src = int(brow["s_rc"].iloc[0]) if not brow.empty else 0
            srt = int(brow["s_rt"].iloc[0]) if not brow.empty else 0
            op1b = int(brow["o_p1b"].iloc[0]) if not brow.empty else 0
            op2c = int(brow["o_p2c"].iloc[0]) if not brow.empty else 0
            op2b = int(brow["o_p2b"].iloc[0]) if not brow.empty else 0
            orc = int(brow["o_rc"].iloc[0]) if not brow.empty else 0
            ort = int(brow["o_rt"].iloc[0]) if not brow.empty else 0

            # Accumulate cumulative values
            c_smr += smr; c_omr += omr
            c_pa += pa; c_ps += ps_v; c_po += po_v; c_rev += tot_rev
            c_s_p1b += sp1b; c_s_p2c += sp2c; c_s_p2b += sp2b; c_s_rc += src; c_s_rt += srt
            c_o_p1b += op1b; c_o_p2c += op2c; c_o_p2b += op2b; c_o_rc += orc; c_o_rt += ort

            # AOV is per-row (not cumulative)
            sm_aov = smr / smo if smo else 0
            om_aov = omr / omo if omo else 0

            # Cumulative payout ratios
            cpay_ratio_all = c_pa / c_rev * 100 if c_rev else 0
            cpay_ratio_s = c_ps / c_smr * 100 if c_smr else 0
            cpay_ratio_o = c_po / c_omr * 100 if c_omr else 0

            # Cumulative pass rates
            cpr_all = _ncf_pass_rate(c_s_p1b + c_o_p1b, c_s_p2c + c_o_p2c, c_s_p2b + c_o_p2b, c_s_rc + c_o_rc, c_s_rt + c_o_rt)
            cpr_s = _ncf_pass_rate(c_s_p1b, c_s_p2c, c_s_p2b, c_s_rc, c_s_rt)
            cpr_o = _ncf_pass_rate(c_o_p1b, c_o_p2c, c_o_p2b, c_o_rc, c_o_rt)

            html += "<tr>"
            html += f'<td style="{_rtd_lab}">{bkt}</td>'
            html += f'<td style="{_rtd}">{cust:,}</td>'
            html += f'<td style="{_rtd}">{pct:.2f}%</td>'
            html += f'<td style="{_rtd}">{cumul_pct:.2f}%</td>'
            # Overall: cumulative payout, ratio, pass rate
            html += f'<td style="{_rtd}">${c_pa:,.0f}</td>' if c_pa else f'<td style="{_rtd}">\u2014</td>'
            html += f'<td style="{_rtd}">{cpay_ratio_all:.1f}%</td>' if c_rev else f'<td style="{_rtd}">\u2014</td>'
            html += f'<td style="{_rtd}">{_pr_str(cpr_all)}</td>'
            # Same model: orders (per-row), cumulative revenue, AOV (per-row)
            html += f'<td style="{_rtd}">{smo:,}</td>'
            html += f'<td style="{_rtd}">${c_smr:,.0f}</td>'
            html += f'<td style="{_rtd}">${sm_aov:,.0f}</td>' if smo else f'<td style="{_rtd}">\u2014</td>'
            # Same model: cumulative payout ratio, payout amt, pass rate
            html += f'<td style="{_rtd}">{cpay_ratio_s:.1f}%</td>' if c_smr else f'<td style="{_rtd}">\u2014</td>'
            html += f'<td style="{_rtd}">${c_ps:,.0f}</td>' if c_ps else f'<td style="{_rtd}">\u2014</td>'
            html += f'<td style="{_rtd}">{_pr_str(cpr_s)}</td>'
            # Other models: orders (per-row), cumulative revenue, AOV (per-row)
            html += f'<td style="{_rtd}">{omo:,}</td>' if omo else f'<td style="{_rtd}">\u2014</td>'
            html += f'<td style="{_rtd}">${c_omr:,.0f}</td>' if c_omr else f'<td style="{_rtd}">\u2014</td>'
            html += f'<td style="{_rtd}">${om_aov:,.0f}</td>' if omo else f'<td style="{_rtd}">\u2014</td>'
            # Other models: cumulative payout ratio, payout amt, pass rate
            html += f'<td style="{_rtd}">{cpay_ratio_o:.1f}%</td>' if c_omr else f'<td style="{_rtd}">\u2014</td>'
            html += f'<td style="{_rtd}">${c_po:,.0f}</td>' if c_po else f'<td style="{_rtd}">\u2014</td>'
            html += f'<td style="{_rtd}">{_pr_str(cpr_o)}</td>' if c_omr else f'<td style="{_rtd}">\u2014</td>'
            html += "</tr>"

        # Total row (same as final cumulative values)
        t_smo = int(seg_df["same_orders"].sum())
        t_omo = int(seg_df["other_orders"].sum())
        t_sm_aov = c_smr / t_smo if t_smo else 0
        t_om_aov = c_omr / t_omo if t_omo else 0
        t_pay_ratio_all = c_pa / c_rev * 100 if c_rev else 0
        t_pay_ratio_s = c_ps / c_smr * 100 if c_smr else 0
        t_pay_ratio_o = c_po / c_omr * 100 if c_omr else 0
        t_pr_all = _ncf_pass_rate(c_s_p1b + c_o_p1b, c_s_p2c + c_o_p2c, c_s_p2b + c_o_p2b, c_s_rc + c_o_rc, c_s_rt + c_o_rt)
        t_pr_s = _ncf_pass_rate(c_s_p1b, c_s_p2c, c_s_p2b, c_s_rc, c_s_rt)
        t_pr_o = _ncf_pass_rate(c_o_p1b, c_o_p2c, c_o_p2b, c_o_rc, c_o_rt)

        html += "<tr>"
        html += f'<td style="{_rtd_tot_lab}">Total</td>'
        html += f'<td style="{_rtd_tot}">{seg_total:,}</td>'
        html += f'<td style="{_rtd_tot}">100.00%</td>'
        html += f'<td style="{_rtd_tot}">\u2014</td>'
        html += f'<td style="{_rtd_tot}">${c_pa:,.0f}</td>' if c_pa else f'<td style="{_rtd_tot}">\u2014</td>'
        html += f'<td style="{_rtd_tot}">{t_pay_ratio_all:.1f}%</td>' if c_rev else f'<td style="{_rtd_tot}">\u2014</td>'
        html += f'<td style="{_rtd_tot}">{_pr_str(t_pr_all)}</td>'
        html += f'<td style="{_rtd_tot}">{t_smo:,}</td>'
        html += f'<td style="{_rtd_tot}">${c_smr:,.0f}</td>'
        html += f'<td style="{_rtd_tot}">${t_sm_aov:,.0f}</td>' if t_smo else f'<td style="{_rtd_tot}">\u2014</td>'
        html += f'<td style="{_rtd_tot}">{t_pay_ratio_s:.1f}%</td>' if c_smr else f'<td style="{_rtd_tot}">\u2014</td>'
        html += f'<td style="{_rtd_tot}">${c_ps:,.0f}</td>' if c_ps else f'<td style="{_rtd_tot}">\u2014</td>'
        html += f'<td style="{_rtd_tot}">{_pr_str(t_pr_s)}</td>'
        html += f'<td style="{_rtd_tot}">{t_omo:,}</td>' if t_omo else f'<td style="{_rtd_tot}">\u2014</td>'
        html += f'<td style="{_rtd_tot}">${c_omr:,.0f}</td>' if c_omr else f'<td style="{_rtd_tot}">\u2014</td>'
        html += f'<td style="{_rtd_tot}">${t_om_aov:,.0f}</td>' if t_omo else f'<td style="{_rtd_tot}">\u2014</td>'
        html += f'<td style="{_rtd_tot}">{t_pay_ratio_o:.1f}%</td>' if c_omr else f'<td style="{_rtd_tot}">\u2014</td>'
        html += f'<td style="{_rtd_tot}">${c_po:,.0f}</td>' if c_po else f'<td style="{_rtd_tot}">\u2014</td>'
        html += f'<td style="{_rtd_tot}">{_pr_str(t_pr_o)}</td>' if c_omr else f'<td style="{_rtd_tot}">\u2014</td>'
        html += "</tr>"

        html += "</tbody></table></div>"
        return html

    # ── Monthly New Customer Model Distribution ──────────────
    _ncf_show_dist = st.toggle("Monthly New Customer Model Distribution", value=True, key="ncf_tog_dist")
    _dist_raw = pd.DataFrame()
    _signups_raw = pd.DataFrame()
    if _ncf_show_dist:
        with st.spinner("Loading distribution..."):
            _dist_raw = _qc(_sql_ncf_dist(str(_ncf_start), str(_ncf_end)))
            _signups_raw = _qc(_sql_ncf_signups(str(_ncf_start), str(_ncf_end)))

    if _ncf_show_dist and not _dist_raw.empty:
        _dist_raw = _dist_raw.reset_index(drop=True)

        # Signups lookup
        _signup_map = {}
        if not _signups_raw.empty:
            _signup_map = dict(zip(_signups_raw['month'],
                                   _signups_raw['signups'].astype(int)))

        _clr_pos = "#2ecc71" if st.session_state.theme == "dark" else "#16a34a"
        _clr_neg = "#e74c3c" if st.session_state.theme == "dark" else "#dc2626"

        def _mom_html(cur, prv):
            if not prv:
                return ""
            pct = (cur - prv) / prv * 100
            clr = _clr_pos if pct >= 0 else _clr_neg
            return f' <span style="color:{clr};font-size:11px;">({pct:+.1f}%)</span>'

        def _pp_mom_html(cur_pct, prv_pct):
            if prv_pct is None:
                return ""
            diff = cur_pct - prv_pct
            clr = _clr_pos if diff >= 0 else _clr_neg
            return f' <span style="color:{clr};font-size:11px;">({diff:+.2f}pp)</span>'

        _hdr = ["Month", "Signups", "New Customer (Purchase)", "Same-Month Signup %",
                "Instant", "1-Step", "2-Step", "Lite", "Evaluation", "Express",
                "Instant %", "1-Step %", "2-Step %", "Lite %", "Evaluation %", "Express %"]
        _th_style = (f"padding:8px 12px;text-align:right;font-size:12px;"
                     f"color:{_T['tbl_hdr_text']};border-bottom:1px solid {_T['tbl_border']};"
                     f"white-space:nowrap;background:{_T['tbl_hdr_bg']};"
                     f"position:sticky;top:0;z-index:1;")
        _td_style = (f"padding:7px 12px;text-align:right;font-size:13px;"
                     f"color:{_T['tbl_text']};border-bottom:1px solid {_T['tbl_row_border']};"
                     f"white-space:nowrap;")
        _td_month = (f"padding:7px 12px;text-align:left;font-size:13px;"
                     f"font-weight:600;color:{_T['tbl_text']};"
                     f"border-bottom:1px solid {_T['tbl_row_border']};")

        _html = (f'<div style="overflow-x:auto;max-height:280px;overflow-y:auto;">'
                 f'<table style="min-width:100%;border-collapse:collapse;background:{_T["tbl_bg"]};'
                 f'border-radius:8px;white-space:nowrap;">')
        _html += "<thead><tr>"
        for h in _hdr:
            align = "text-align:left;" if h == "Month" else ""
            _html += f'<th style="{_th_style}{align}">{h}</th>'
        _html += "</tr></thead><tbody>"

        for idx in range(len(_dist_raw)):
            r = _dist_raw.iloc[idx]
            tot = int(r["total"])
            sms = int(r["same_month_signup"])
            inst = int(r["instant"])
            one = int(r["one_step"])
            two = int(r["two_step"])
            lite = int(r["lite"])
            evl = int(r["evaluation"])
            exp = int(r["express"])
            signups = _signup_map.get(r["month"], 0)
            conv = sms / tot * 100 if tot else 0

            ip = inst / tot * 100 if tot else 0
            op = one / tot * 100 if tot else 0
            tp = two / tot * 100 if tot else 0
            lp = lite / tot * 100 if tot else 0
            ep = evl / tot * 100 if tot else 0
            xp = exp / tot * 100 if tot else 0

            if idx > 0:
                p = _dist_raw.iloc[idx - 1]
                pt = int(p["total"])
                p_sms = int(p["same_month_signup"])
                p_conv = p_sms / pt * 100 if pt else None

                ms = _mom_html(signups, _signup_map.get(p["month"], 0))
                mt = _mom_html(tot, pt)
                m_conv = _pp_mom_html(conv, p_conv)
                mi = _mom_html(inst, int(p["instant"]))
                m1 = _mom_html(one, int(p["one_step"]))
                m2 = _mom_html(two, int(p["two_step"]))
                ml = _mom_html(lite, int(p["lite"]))
                me = _mom_html(evl, int(p["evaluation"]))
                mx = _mom_html(exp, int(p["express"]))

                pip = int(p["instant"]) / pt * 100 if pt else None
                pop = int(p["one_step"]) / pt * 100 if pt else None
                ptp = int(p["two_step"]) / pt * 100 if pt else None
                plp = int(p["lite"]) / pt * 100 if pt else None
                pep = int(p["evaluation"]) / pt * 100 if pt else None
                pxp = int(p["express"]) / pt * 100 if pt else None
                mip = _pp_mom_html(ip, pip)
                m1p = _pp_mom_html(op, pop)
                m2p = _pp_mom_html(tp, ptp)
                mlp = _pp_mom_html(lp, plp)
                mep = _pp_mom_html(ep, pep)
                mxp = _pp_mom_html(xp, pxp)
            else:
                ms = mt = m_conv = mi = m1 = m2 = ml = me = mx = ""
                mip = m1p = m2p = mlp = mep = mxp = ""

            _html += "<tr>"
            _html += f'<td style="{_td_month}">{r["month"]}</td>'
            _html += f'<td style="{_td_style}">{signups:,}{ms}</td>'
            _html += f'<td style="{_td_style}">{tot:,}{mt}</td>'
            _html += f'<td style="{_td_style}">{conv:.2f}%{m_conv}</td>'
            _html += f'<td style="{_td_style}">{inst:,}{mi}</td>'
            _html += f'<td style="{_td_style}">{one:,}{m1}</td>'
            _html += f'<td style="{_td_style}">{two:,}{m2}</td>'
            _html += f'<td style="{_td_style}">{lite:,}{ml}</td>'
            _html += f'<td style="{_td_style}">{evl:,}{me}</td>'
            _html += f'<td style="{_td_style}">{exp:,}{mx}</td>'
            _html += f'<td style="{_td_style}">{ip:.2f}%{mip}</td>'
            _html += f'<td style="{_td_style}">{op:.2f}%{m1p}</td>'
            _html += f'<td style="{_td_style}">{tp:.2f}%{m2p}</td>'
            _html += f'<td style="{_td_style}">{lp:.2f}%{mlp}</td>'
            _html += f'<td style="{_td_style}">{ep:.2f}%{mep}</td>'
            _html += f'<td style="{_td_style}">{xp:.2f}%{mxp}</td>'
            _html += "</tr>"

        # Total row
        _t_signups = sum(_signup_map.get(r["month"], 0) for _, r in _dist_raw.iterrows())
        _t_tot = int(_dist_raw["total"].sum())
        _t_sms = int(_dist_raw["same_month_signup"].sum())
        _t_inst = int(_dist_raw["instant"].sum())
        _t_one = int(_dist_raw["one_step"].sum())
        _t_two = int(_dist_raw["two_step"].sum())
        _t_lite = int(_dist_raw["lite"].sum())
        _t_evl = int(_dist_raw["evaluation"].sum())
        _t_exp = int(_dist_raw["express"].sum())
        _t_conv = _t_sms / _t_tot * 100 if _t_tot else 0
        _t_ip = _t_inst / _t_tot * 100 if _t_tot else 0
        _t_op = _t_one / _t_tot * 100 if _t_tot else 0
        _t_tp = _t_two / _t_tot * 100 if _t_tot else 0
        _t_lp = _t_lite / _t_tot * 100 if _t_tot else 0
        _t_ep = _t_evl / _t_tot * 100 if _t_tot else 0
        _t_xp = _t_exp / _t_tot * 100 if _t_tot else 0

        _td_tot = (f"padding:8px 12px;text-align:right;font-size:13px;font-weight:700;"
                   f"color:{_T['tbl_tot_text']};border-top:2px solid {_T['tbl_tot_border']};"
                   f"white-space:nowrap;background:{_T['tbl_tot_bg']};"
                   f"position:sticky;bottom:0;z-index:1;")
        _td_tot_l = (f"padding:8px 12px;text-align:left;font-size:13px;font-weight:700;"
                     f"color:{_T['tbl_tot_text']};border-top:2px solid {_T['tbl_tot_border']};"
                     f"white-space:nowrap;background:{_T['tbl_tot_bg']};"
                     f"position:sticky;bottom:0;z-index:1;")

        _html += "<tr>"
        _html += f'<td style="{_td_tot_l}">Total</td>'
        _html += f'<td style="{_td_tot}">{_t_signups:,}</td>'
        _html += f'<td style="{_td_tot}">{_t_tot:,}</td>'
        _html += f'<td style="{_td_tot}">{_t_conv:.2f}%</td>'
        _html += f'<td style="{_td_tot}">{_t_inst:,}</td>'
        _html += f'<td style="{_td_tot}">{_t_one:,}</td>'
        _html += f'<td style="{_td_tot}">{_t_two:,}</td>'
        _html += f'<td style="{_td_tot}">{_t_lite:,}</td>'
        _html += f'<td style="{_td_tot}">{_t_evl:,}</td>'
        _html += f'<td style="{_td_tot}">{_t_exp:,}</td>'
        _html += f'<td style="{_td_tot}">{_t_ip:.2f}%</td>'
        _html += f'<td style="{_td_tot}">{_t_op:.2f}%</td>'
        _html += f'<td style="{_td_tot}">{_t_tp:.2f}%</td>'
        _html += f'<td style="{_td_tot}">{_t_lp:.2f}%</td>'
        _html += f'<td style="{_td_tot}">{_t_ep:.2f}%</td>'
        _html += f'<td style="{_td_tot}">{_t_xp:.2f}%</td>'
        _html += "</tr>"

        _html += "</tbody></table></div>"
        st.markdown(_html, unsafe_allow_html=True)
    elif _ncf_show_dist:
        st.info("No data for the selected date range.")

    st.divider()

    # ── Monthly New vs Prior Model Breakdown ──────────────────
    _ncf_show_seg = st.toggle("Monthly New vs Prior Model Breakdown", value=False, key="ncf_tog_seg")
    _seg_monthly = pd.DataFrame()
    if _ncf_show_seg:
        with st.spinner("Loading segment breakdown..."):
            _seg_monthly = _qc(_sql_ncf_segment_monthly(str(_ncf_start), str(_ncf_end)))

    if _ncf_show_seg and not _seg_monthly.empty:
        _models_order = [m for m in _NCF_MODELS if m in _seg_monthly["model"].unique()]
        _months = sorted(_seg_monthly["month"].unique())

        # Pre-compute model totals for contribution %
        _total_amount = int(_seg_monthly["customers"].sum())
        _model_totals = {}
        for m in _models_order:
            _model_totals[m] = int(_seg_monthly[_seg_monthly["model"] == m]["customers"].sum())

        # MoM color helper
        _clr_p = "#2ecc71" if st.session_state.theme == "dark" else "#16a34a"
        _clr_n = "#e74c3c" if st.session_state.theme == "dark" else "#dc2626"
        def _mom_s(cur, prv):
            if not prv:
                return ""
            pct = (cur - prv) / prv * 100
            clr = _clr_p if pct >= 0 else _clr_n
            return f' <span style="color:{clr};font-size:10px;">({pct:+.1f}%)</span>'

        _sth = (f"padding:8px 12px;text-align:right;font-size:12px;"
                f"color:{_T['tbl_hdr_text']};border-bottom:1px solid {_T['tbl_border']};"
                f"white-space:nowrap;background:{_T['tbl_hdr_bg']};"
                f"position:sticky;top:0;z-index:1;")
        _sth_grp = (f"padding:8px 12px;text-align:center;font-size:12px;font-weight:700;"
                    f"color:{_T['tbl_hdr_text']};border-bottom:2px solid {_T['tbl_border']};"
                    f"white-space:nowrap;background:{_T['tbl_hdr_bg']};"
                    f"position:sticky;top:0;z-index:2;")
        _std = (f"padding:7px 12px;text-align:right;font-size:13px;"
                f"color:{_T['tbl_text']};border-bottom:1px solid {_T['tbl_row_border']};"
                f"white-space:nowrap;")
        _std_m = (f"padding:7px 12px;text-align:left;font-size:13px;"
                  f"font-weight:600;color:{_T['tbl_text']};"
                  f"border-bottom:1px solid {_T['tbl_row_border']};")
        _std_tot = (f"padding:8px 12px;text-align:right;font-size:13px;font-weight:700;"
                    f"color:{_T['tbl_tot_text']};border-top:2px solid {_T['tbl_tot_border']};"
                    f"white-space:nowrap;background:{_T['tbl_tot_bg']};"
                    f"position:sticky;bottom:0;z-index:1;")
        _std_tot_l = (f"padding:8px 12px;text-align:left;font-size:13px;font-weight:700;"
                      f"color:{_T['tbl_tot_text']};border-top:2px solid {_T['tbl_tot_border']};"
                      f"white-space:nowrap;background:{_T['tbl_tot_bg']};"
                      f"position:sticky;bottom:0;z-index:1;")

        _n_grps = 1 + len(_models_order)  # Overall + models
        _sh = (f'<div style="overflow-x:auto;max-height:280px;overflow-y:auto;margin:16px 0;">'
               f'<table style="min-width:100%;border-collapse:collapse;background:{_T["tbl_bg"]};'
               f'border-radius:8px;white-space:nowrap;">')

        # Group header row
        _sh += "<thead>"
        _sh += "<tr>"
        _sh += f'<th style="{_sth_grp}text-align:left;" rowspan="2">Month</th>'
        _sh += f'<th style="{_sth_grp}border-left:2px solid {_T["tbl_border"]};" colspan="3">Overall</th>'
        for m in _models_order:
            _m_contrib = f" ({_model_totals[m] / _total_amount * 100:.0f}%)" if _total_amount else ""
            _sh += f'<th style="{_sth_grp}border-left:2px solid {_T["tbl_border"]};" colspan="3">{m}{_m_contrib}</th>'
        _sh += "</tr>"

        # Sub-header row
        _sh += "<tr>"
        for _ in range(_n_grps):
            _sh += f'<th style="{_sth}border-left:2px solid {_T["tbl_border"]};">Total</th>'
            _sh += f'<th style="{_sth}">New</th>'
            _sh += f'<th style="{_sth}">Prior Model</th>'
        _sh += "</tr>"
        _sh += "</thead><tbody>"

        # Accumulators for total row + MoM tracking
        _t_overall = {"New": 0, "Prior Model": 0}
        _t_models = {m: {"New": 0, "Prior Model": 0} for m in _models_order}
        _prev = {}

        for mo in _months:
            mdf = _seg_monthly[_seg_monthly["month"] == mo]
            o_new = int(mdf[mdf["segment"] == "New"]["customers"].sum())
            o_prior = int(mdf[mdf["segment"] == "Prior Model"]["customers"].sum())
            o_total = o_new + o_prior
            _t_overall["New"] += o_new
            _t_overall["Prior Model"] += o_prior

            _sh += "<tr>"
            _sh += f'<td style="{_std_m}">{mo}</td>'
            o_new_pct = f" ({o_new / o_total * 100:.0f}%)" if o_total else ""
            o_pri_pct = f" ({o_prior / o_total * 100:.0f}%)" if o_total else ""
            _sh += f'<td style="{_std}border-left:2px solid {_T["tbl_row_border"]};">{o_total:,}{_mom_s(o_total, _prev.get("o_t", 0))}</td>'
            _sh += f'<td style="{_std}">{o_new:,}{o_new_pct}{_mom_s(o_new, _prev.get("o_n", 0))}</td>'
            _sh += f'<td style="{_std}">{o_prior:,}{o_pri_pct}{_mom_s(o_prior, _prev.get("o_p", 0))}</td>'
            _prev["o_t"], _prev["o_n"], _prev["o_p"] = o_total, o_new, o_prior

            for m in _models_order:
                mmdf = mdf[mdf["model"] == m]
                m_new = int(mmdf[mmdf["segment"] == "New"]["customers"].sum())
                m_prior = int(mmdf[mmdf["segment"] == "Prior Model"]["customers"].sum())
                m_total = m_new + m_prior
                _t_models[m]["New"] += m_new
                _t_models[m]["Prior Model"] += m_prior
                m_new_pct = f" ({m_new / m_total * 100:.0f}%)" if m_total else ""
                m_pri_pct = f" ({m_prior / m_total * 100:.0f}%)" if m_total else ""
                _mk = m.replace(" ", "_")
                _sh += f'<td style="{_std}border-left:2px solid {_T["tbl_row_border"]};">{m_total:,}{_mom_s(m_total, _prev.get(f"{_mk}_t", 0))}</td>'
                if m_total:
                    _sh += f'<td style="{_std}">{m_new:,}{m_new_pct}{_mom_s(m_new, _prev.get(f"{_mk}_n", 0))}</td>'
                    _sh += f'<td style="{_std}">{m_prior:,}{m_pri_pct}{_mom_s(m_prior, _prev.get(f"{_mk}_p", 0))}</td>'
                else:
                    _sh += f'<td style="{_std}">\u2014</td><td style="{_std}">\u2014</td>'
                _prev[f"{_mk}_t"], _prev[f"{_mk}_n"], _prev[f"{_mk}_p"] = m_total, m_new, m_prior
            _sh += "</tr>"

        # Total row
        _t_o_total = _t_overall["New"] + _t_overall["Prior Model"]
        _t_o_new_pct = f' ({_t_overall["New"] / _t_o_total * 100:.0f}%)' if _t_o_total else ""
        _t_o_pri_pct = f' ({_t_overall["Prior Model"] / _t_o_total * 100:.0f}%)' if _t_o_total else ""
        _sh += "<tr>"
        _sh += f'<td style="{_std_tot_l}">Total</td>'
        _sh += f'<td style="{_std_tot}border-left:2px solid {_T["tbl_tot_border"]};">{_t_o_total:,}</td>'
        _sh += f'<td style="{_std_tot}">{_t_overall["New"]:,}{_t_o_new_pct}</td>'
        _sh += f'<td style="{_std_tot}">{_t_overall["Prior Model"]:,}{_t_o_pri_pct}</td>'
        for m in _models_order:
            mt = _t_models[m]["New"] + _t_models[m]["Prior Model"]
            mn_pct = f' ({_t_models[m]["New"] / mt * 100:.0f}%)' if mt else ""
            mp_pct = f' ({_t_models[m]["Prior Model"] / mt * 100:.0f}%)' if mt else ""
            _sh += f'<td style="{_std_tot}border-left:2px solid {_T["tbl_tot_border"]};">{mt:,}</td>'
            _sh += f'<td style="{_std_tot}">{_t_models[m]["New"]:,}{mn_pct}</td>' if mt else f'<td style="{_std_tot}">\u2014</td>'
            _sh += f'<td style="{_std_tot}">{_t_models[m]["Prior Model"]:,}{mp_pct}</td>' if mt else f'<td style="{_std_tot}">\u2014</td>'
        _sh += "</tr>"

        _sh += "</tbody></table></div>"
        st.markdown(_sh, unsafe_allow_html=True)
    elif _ncf_show_seg:
        st.info("No data for the selected date range.")

    st.divider()

    # ── Prior period for comparison ──
    _period_len = (_ncf_end - _ncf_start).days + 1
    _prior_end = _ncf_start - timedelta(days=1)
    _prior_start = _ncf_start - timedelta(days=_period_len)

    # ── Per-Model Tabs (with Overall first) ────────────────────
    _ncf_tab_labels = ["Overall"] + _NCF_MODELS
    _ncf_tabs = st.tabs(_ncf_tab_labels)

    for _ncf_i, _ncf_tab in enumerate(_ncf_tabs):
        with _ncf_tab:
            if _ncf_i == 0:
                # ── Overall tab ──
                _ov_cur = _qc(_sql_ncf_overall(str(_ncf_start), str(_ncf_end)))
                _ov_prev = _qc(_sql_ncf_overall(str(_prior_start), str(_prior_end)))
                _ov_cur_total = int(_ov_cur["customers"].sum()) if not _ov_cur.empty else 0
                _ov_prev_total = int(_ov_prev["customers"].sum()) if not _ov_prev.empty else 0
                _ov_delta = _ov_cur_total - _ov_prev_total

                st.metric("Total New Customers", f"{_ov_cur_total:,}",
                          delta=f"{_ov_delta:+,} vs prior period")

                # Per-model breakdown (2 rows of 3)
                for _row_start in range(0, len(_NCF_MODELS), 3):
                    _row_models = _NCF_MODELS[_row_start:_row_start + 3]
                    _ov_cols = st.columns(3)
                    for _ci, _om in enumerate(_row_models):
                        _om_cur = int(_ov_cur[_ov_cur["model"] == _om]["customers"].sum()) if not _ov_cur.empty else 0
                        _om_prev = int(_ov_prev[_ov_prev["model"] == _om]["customers"].sum()) if not _ov_prev.empty else 0
                        _om_delta = _om_cur - _om_prev
                        _om_pct = f" ({_om_cur / _ov_cur_total * 100:.1f}%)" if _ov_cur_total else ""
                        _ov_cols[_ci].metric(_om, f"{_om_cur:,}{_om_pct}",
                                             delta=f"{_om_delta:+,}")
                continue

            # ── Model-specific tab ──
            _ncf_model = _NCF_MODELS[_ncf_i - 1]
            _ncf_pat = _NCF_PATTERNS[_ncf_model]

            # Current + prior period segment counts
            _seg_counts = _qc(_sql_ncf_seg_counts(_ncf_pat, str(_ncf_start), str(_ncf_end)))
            _seg_counts_prev = _qc(_sql_ncf_seg_counts(_ncf_pat, str(_prior_start), str(_prior_end)))

            def _parse_seg(df):
                d = p = 0
                if not df.empty:
                    dr = df[df["segment"] == "Direct"]
                    pr = df[df["segment"] == "Prior Model"]
                    d = int(dr["customers"].iloc[0]) if not dr.empty else 0
                    p = int(pr["customers"].iloc[0]) if not pr.empty else 0
                return d, p

            _seg_direct_n, _seg_prior_n = _parse_seg(_seg_counts)
            _seg_direct_p, _seg_prior_p = _parse_seg(_seg_counts_prev)
            _seg_total_n = _seg_direct_n + _seg_prior_n
            _seg_total_p = _seg_direct_p + _seg_prior_p
            _seg_direct_pct = _seg_direct_n / _seg_total_n * 100 if _seg_total_n else 0
            _seg_prior_pct = _seg_prior_n / _seg_total_n * 100 if _seg_total_n else 0

            _sm1, _sm2, _sm3 = st.columns(3)
            _sm1.metric("Total Customers", f"{_seg_total_n:,}",
                        delta=f"{_seg_total_n - _seg_total_p:+,} vs prior period")
            _sm2.metric(f"Direct {_ncf_model}", f"{_seg_direct_n:,} ({_seg_direct_pct:.1f}%)",
                        delta=f"{_seg_direct_n - _seg_direct_p:+,}")
            _sm3.metric("Prior Model", f"{_seg_prior_n:,} ({_seg_prior_pct:.1f}%)",
                        delta=f"{_seg_prior_n - _seg_prior_p:+,}")

            st.divider()

            # ── Direct [Model] ──
            _ncf_show_direct = st.toggle(
                f"Direct {_ncf_model}", value=False,
                key=f"ncf_tog_direct_{_ncf_i}")
            if _ncf_show_direct:
                st.caption(f"First-ever CFD purchase was {_ncf_model} \u2014 no prior orders on any model")
                with st.spinner("Loading Direct segment..."):
                    _ncf_df_d = _qc(_sql_ncf(_ncf_pat, str(_ncf_start), str(_ncf_end)))
                    _rep_df_d = _qc(_sql_ncf_repurchase(_ncf_pat, str(_ncf_start), str(_ncf_end)))

                if not _ncf_df_d.empty:
                    _d_seg = _ncf_df_d[_ncf_df_d["segment"] == "Direct Purchase"]
                    _d_cust = int(_d_seg["customers"].sum()) if not _d_seg.empty else 0
                    if _d_cust > 0:
                        st.markdown("**Post-Purchase Behavior**")
                        st.markdown(_ncf_build_html(_d_seg, _d_cust, _ncf_model),
                                    unsafe_allow_html=True)
                    else:
                        st.info("No behavior data for Direct segment.")
                else:
                    st.info("No data found for the selected filters.")

                if not _rep_df_d.empty:
                    _rd_seg = _rep_df_d[_rep_df_d["segment"] == "Direct"]
                    _rd_n = int(_rd_seg["customers"].sum()) if not _rd_seg.empty else 0
                    if _rd_n > 0:
                        st.markdown("**Repurchase Depth Analysis**")
                        st.markdown(_ncf_rep_html(_rd_seg, _rd_n, _ncf_model),
                                    unsafe_allow_html=True)

            st.divider()

            # ── Prior Model ──
            _ncf_show_prior = st.toggle(
                "Prior Model", value=False,
                key=f"ncf_tog_prior_{_ncf_i}")
            if _ncf_show_prior:
                st.caption(f"Had orders on other CFD models before buying {_ncf_model}")
                with st.spinner("Loading Prior Model segment..."):
                    _ncf_df_p = _qc(_sql_ncf(_ncf_pat, str(_ncf_start), str(_ncf_end)))
                    _rep_df_p = _qc(_sql_ncf_repurchase(_ncf_pat, str(_ncf_start), str(_ncf_end)))

                if not _ncf_df_p.empty:
                    _p_seg = _ncf_df_p[_ncf_df_p["segment"] == "Prior Model"]
                    _p_cust = int(_p_seg["customers"].sum()) if not _p_seg.empty else 0
                    if _p_cust > 0:
                        st.markdown("**Post-Purchase Behavior**")
                        st.markdown(_ncf_build_html(_p_seg, _p_cust, _ncf_model),
                                    unsafe_allow_html=True)
                    else:
                        st.info("No behavior data for Prior Model segment.")
                else:
                    st.info("No data found for the selected filters.")

                if not _rep_df_p.empty:
                    _rp_seg = _rep_df_p[_rep_df_p["segment"] == "Prior Model"]
                    _rp_n = int(_rp_seg["customers"].sum()) if not _rp_seg.empty else 0
                    if _rp_n > 0:
                        st.markdown("**Repurchase Depth Analysis**")
                        st.markdown(_ncf_rep_html(_rp_seg, _rp_n, _ncf_model),
                                    unsafe_allow_html=True)
