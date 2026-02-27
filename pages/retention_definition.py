"""Retention Definition page."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from shared import (
    get_retention_classified, get_retention_trend,
    RETENTION_ORDER, RETENTION_COLORS, ORDER_TYPE_NAMES,
    metric_delta,
)


def render():
    st.header("Retention Definition")

    # Info box with category definitions
    with st.expander("Category Definitions", expanded=False):
        st.markdown("""
| Category | Rule |
|---|---|
| First Purchase | Very first order ever |
| Acquisition Burst | Within 7 days of first purchase (not the first order itself) |
| Weekly Retention | 0–7 days since last purchase |
| Bi-weekly Retention | 8–14 days |
| Monthly Retention | 15–30 days |
| Quarterly Retention | 31–90 days |
| Bi-annual Retention | 91–180 days |
| Annual Retention | 181–365 days (actively trading) |
| Late Retention | 365+ days gap (actively trading) |
| Reacquisition | 181+ days gap, NOT actively trading (dormant won back) |

*CFD orders only (Futures excluded). Uses status=1 (completed) orders.*
        """)

    # ── Filters ───────────────────────────────────────────
    fc1, fc2 = st.columns([1, 3])
    with fc1:
        ret_date = st.date_input("Date", value=datetime.now().date() - timedelta(days=1), key="ret_date")
    with fc2:
        ret_compare = st.radio("Compare to", ["Previous Day", "Same Day Last Week", "Same Day Last Month"],
                               horizontal=True, key="ret_compare")

    ret_sel_str = str(ret_date)
    if ret_compare == "Previous Day":
        ret_comp_date = ret_date - timedelta(days=1)
    elif ret_compare == "Same Day Last Week":
        ret_comp_date = ret_date - timedelta(days=7)
    else:
        ret_comp_date = ret_date - timedelta(days=30)
    ret_comp_str = str(ret_comp_date)

    # ── Load data ─────────────────────────────────────────
    with st.spinner("Classifying orders..."):
        df_ret = get_retention_classified(ret_sel_str)
        df_ret_c = get_retention_classified(ret_comp_str)

    if df_ret.empty:
        st.warning("No data found for the selected date.")
        st.stop()

    # ── KPI Row 1 ─────────────────────────────────────────
    total_orders_r = len(df_ret)
    total_revenue_r = df_ret["total_amount"].sum()
    unique_customers_r = df_ret["user_id"].nunique()
    first_purchase_count = len(df_ret[df_ret["retention_category"] == "First Purchase"])
    returning_count = total_orders_r - first_purchase_count
    retention_rate = (returning_count / total_orders_r * 100) if total_orders_r > 0 else 0
    reacq_count = len(df_ret[df_ret["retention_category"] == "Reacquisition"])

    c_total_orders_r = len(df_ret_c) if not df_ret_c.empty else 0
    c_total_revenue_r = df_ret_c["total_amount"].sum() if not df_ret_c.empty else 0
    c_unique_customers_r = df_ret_c["user_id"].nunique() if not df_ret_c.empty else 0
    c_first_purchase = len(df_ret_c[df_ret_c["retention_category"] == "First Purchase"]) if not df_ret_c.empty else 0
    c_returning = c_total_orders_r - c_first_purchase
    c_retention_rate = (c_returning / c_total_orders_r * 100) if c_total_orders_r > 0 else 0
    c_reacq = len(df_ret_c[df_ret_c["retention_category"] == "Reacquisition"]) if not df_ret_c.empty else 0

    st.subheader(f"{ret_date.strftime('%B %d, %Y')}  vs  {ret_comp_date.strftime('%B %d, %Y')}")

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Orders", f"{total_orders_r:,}", metric_delta(total_orders_r, c_total_orders_r))
    k2.metric("Total Revenue", f"${total_revenue_r:,.0f}", metric_delta(total_revenue_r, c_total_revenue_r))
    k3.metric("Unique Customers", f"{unique_customers_r:,}", metric_delta(unique_customers_r, c_unique_customers_r))
    k4.metric("Retention Rate", f"{retention_rate:.1f}%", metric_delta(retention_rate, c_retention_rate))
    k5.metric("Reacquisitions", f"{reacq_count:,}", metric_delta(reacq_count, c_reacq))

    # ── KPI Row 2 ─────────────────────────────────────────
    fp_pct = (first_purchase_count / total_orders_r * 100) if total_orders_r > 0 else 0
    ret_pct = (returning_count / total_orders_r * 100) if total_orders_r > 0 else 0
    fp_orders = df_ret[df_ret["retention_category"] == "First Purchase"]
    ret_orders = df_ret[df_ret["retention_category"] != "First Purchase"]
    avg_new = fp_orders["total_amount"].mean() if len(fp_orders) > 0 else 0
    avg_returning = ret_orders["total_amount"].mean() if len(ret_orders) > 0 else 0

    c_fp_pct = (c_first_purchase / c_total_orders_r * 100) if c_total_orders_r > 0 else 0
    c_ret_pct = (c_returning / c_total_orders_r * 100) if c_total_orders_r > 0 else 0
    c_fp_orders = df_ret_c[df_ret_c["retention_category"] == "First Purchase"] if not df_ret_c.empty else pd.DataFrame(columns=["total_amount"])
    c_ret_orders = df_ret_c[df_ret_c["retention_category"] != "First Purchase"] if not df_ret_c.empty else pd.DataFrame(columns=["total_amount"])
    c_avg_new = c_fp_orders["total_amount"].mean() if len(c_fp_orders) > 0 else 0
    c_avg_returning = c_ret_orders["total_amount"].mean() if len(c_ret_orders) > 0 else 0

    k6, k7, k8, k9 = st.columns(4)
    k6.metric("First Purchase %", f"{fp_pct:.1f}%", metric_delta(fp_pct, c_fp_pct))
    k7.metric("Returning %", f"{ret_pct:.1f}%", metric_delta(ret_pct, c_ret_pct))
    k8.metric("Avg Order (New)", f"${avg_new:,.2f}", metric_delta(avg_new, c_avg_new))
    k9.metric("Avg Order (Returning)", f"${avg_returning:,.2f}", metric_delta(avg_returning, c_avg_returning))

    st.divider()

    # ── Tabs ──────────────────────────────────────────────
    tab_cat, tab_trend, tab_rev, tab_otype = st.tabs([
        "Category Breakdown", "Trend Over Time", "Revenue Analysis", "Order Type Split"
    ])

    # ── Tab 1: Category Breakdown ─────────────────────────
    with tab_cat:
        cat_agg = df_ret.groupby("retention_category").agg(
            orders=("order_id", "count"),
            revenue=("total_amount", "sum"),
            customers=("user_id", "nunique"),
            avg_order=("total_amount", "mean"),
        ).reset_index()
        cat_order_map = {c: i for i, c in enumerate(RETENTION_ORDER)}
        cat_agg["_sort"] = cat_agg["retention_category"].map(cat_order_map).fillna(99)
        cat_agg = cat_agg.sort_values("_sort").drop(columns="_sort")
        cat_agg["avg_order"] = cat_agg["avg_order"].round(2)
        cat_agg["order_pct"] = (cat_agg["orders"] / total_orders_r * 100).round(1)
        cat_agg["rev_pct"] = (cat_agg["revenue"] / total_revenue_r * 100).round(1) if total_revenue_r > 0 else 0

        if not df_ret_c.empty:
            c_cat_agg = df_ret_c.groupby("retention_category").agg(
                c_orders=("order_id", "count"), c_revenue=("total_amount", "sum")
            ).reset_index()
            cat_agg = cat_agg.merge(c_cat_agg, on="retention_category", how="left").fillna(0)
            cat_agg["order_change"] = ((cat_agg["orders"] - cat_agg["c_orders"]) / cat_agg["c_orders"].replace(0, pd.NA) * 100).round(1)
            cat_agg["rev_change"] = ((cat_agg["revenue"] - cat_agg["c_revenue"]) / cat_agg["c_revenue"].replace(0, pd.NA) * 100).round(1)

        st.dataframe(cat_agg, use_container_width=True, hide_index=True)

        c1, c2 = st.columns(2)
        with c1:
            fig = px.pie(cat_agg, values="orders", names="retention_category", title="Orders by Category",
                         color="retention_category", color_discrete_map=RETENTION_COLORS)
            fig.update_layout(height=400, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.pie(cat_agg, values="revenue", names="retention_category", title="Revenue by Category",
                         color="retention_category", color_discrete_map=RETENTION_COLORS)
            fig.update_layout(height=400, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

        fig = px.bar(cat_agg, x="retention_category", y="revenue", text="orders",
                     title="Revenue by Category",
                     color="retention_category", color_discrete_map=RETENTION_COLORS)
        fig.update_layout(height=400, margin=dict(t=40, b=20), showlegend=False, xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

    # ── Tab 2: Trend Over Time ────────────────────────────
    with tab_trend:
        gran = st.radio("Granularity", ["Last 14 Days", "Last 12 Weeks"], horizontal=True, key="ret_gran")
        if gran == "Last 14 Days":
            trend_start = str(ret_date - timedelta(days=13))
            trend_end = str(ret_date)
        else:
            trend_start = str(ret_date - timedelta(weeks=12) + timedelta(days=1))
            trend_end = str(ret_date)

        with st.spinner("Loading trend data..."):
            trend_df = get_retention_trend(trend_start, trend_end)

        if trend_df.empty:
            st.info("No trend data available.")
        else:
            if gran == "Last 12 Weeks":
                trend_df["order_date"] = pd.to_datetime(trend_df["order_date"])
                trend_df["period"] = trend_df["order_date"].dt.to_period("W").dt.start_time.dt.strftime("%Y-%m-%d")
                trend_agg = trend_df.groupby(["period", "retention_category"]).agg(
                    orders=("orders", "sum"), revenue=("revenue", "sum")
                ).reset_index()
                trend_agg = trend_agg.rename(columns={"period": "date"})
            else:
                trend_agg = trend_df.rename(columns={"order_date": "date"}).copy()
                trend_agg["date"] = trend_agg["date"].astype(str)

            fig = px.area(trend_agg, x="date", y="orders", color="retention_category",
                          title="Orders by Retention Category Over Time",
                          color_discrete_map=RETENTION_COLORS,
                          category_orders={"retention_category": RETENTION_ORDER})
            fig.update_layout(height=450, margin=dict(t=40, b=20), xaxis_title="",
                             legend=dict(orientation="h", yanchor="bottom", y=-0.35))
            st.plotly_chart(fig, use_container_width=True)

            fig = px.area(trend_agg, x="date", y="revenue", color="retention_category",
                          title="Revenue by Retention Category Over Time",
                          color_discrete_map=RETENTION_COLORS,
                          category_orders={"retention_category": RETENTION_ORDER})
            fig.update_layout(height=450, margin=dict(t=40, b=20), xaxis_title="",
                             legend=dict(orientation="h", yanchor="bottom", y=-0.35))
            st.plotly_chart(fig, use_container_width=True)

            st.caption("*Trend uses simplified classification: 181-365 day gaps shown as Annual Retention, "
                       "365+ as Late Retention (active trading check skipped for performance).*")

    # ── Tab 3: Revenue Analysis ───────────────────────────
    with tab_rev:
        rev_agg = df_ret.groupby("retention_category").agg(
            revenue=("total_amount", "sum"),
            orders=("order_id", "count"),
            avg_order=("total_amount", "mean"),
            median_order=("total_amount", "median"),
        ).reset_index()
        rev_order_map = {c: i for i, c in enumerate(RETENTION_ORDER)}
        rev_agg["_sort"] = rev_agg["retention_category"].map(rev_order_map).fillna(99)
        rev_agg = rev_agg.sort_values("_sort").drop(columns="_sort")
        rev_agg["avg_order"] = rev_agg["avg_order"].round(2)
        rev_agg["median_order"] = rev_agg["median_order"].round(2)
        rev_agg["rev_pct"] = (rev_agg["revenue"] / total_revenue_r * 100).round(1) if total_revenue_r > 0 else 0
        rev_agg["cum_rev_pct"] = rev_agg["rev_pct"].cumsum().round(1)

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=rev_agg["retention_category"], y=rev_agg["revenue"],
            name="Revenue",
            marker_color=[RETENTION_COLORS.get(c, "#888") for c in rev_agg["retention_category"]]))
        fig.add_trace(go.Scatter(
            x=rev_agg["retention_category"], y=rev_agg["avg_order"],
            name="Avg Order Value", yaxis="y2", mode="lines+markers",
            line=dict(color="#e76f51", width=2)))
        fig.update_layout(
            title="Revenue & AOV by Category",
            yaxis=dict(title="Revenue ($)"),
            yaxis2=dict(title="Avg Order ($)", overlaying="y", side="right"),
            height=420, margin=dict(t=40, b=20), xaxis_tickangle=-45,
        )
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(rev_agg[["retention_category", "revenue", "rev_pct", "cum_rev_pct",
                              "orders", "avg_order", "median_order"]],
                     use_container_width=True, hide_index=True)

        st.subheader("Revenue Concentration")
        rc1, rc2 = st.columns(2)
        with rc1:
            fig = px.bar(rev_agg, x="retention_category", y="cum_rev_pct",
                         title="Cumulative Revenue %", color_discrete_sequence=["#4361ee"])
            fig.add_hline(y=80, line_dash="dash", line_color="red", annotation_text="80%")
            fig.update_layout(height=350, margin=dict(t=40, b=20), xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        with rc2:
            top3 = rev_agg.nlargest(3, "revenue")
            fig = px.pie(top3, values="revenue", names="retention_category",
                         title="Top 3 Categories by Revenue",
                         color="retention_category", color_discrete_map=RETENTION_COLORS)
            fig.update_layout(height=350, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

    # ── Tab 4: Order Type Split ───────────────────────────
    with tab_otype:
        cross = df_ret.groupby(["retention_category", "order_type_name"]).agg(
            orders=("order_id", "count"), revenue=("total_amount", "sum")
        ).reset_index()

        pivot_orders = cross.pivot_table(index="retention_category", columns="order_type_name",
                                         values="orders", fill_value=0, aggfunc="sum")
        ot_order_map = {c: i for i, c in enumerate(RETENTION_ORDER)}
        pivot_orders["_sort"] = pivot_orders.index.map(ot_order_map).fillna(99)
        pivot_orders = pivot_orders.sort_values("_sort").drop(columns="_sort").astype(int)
        pivot_orders["Total"] = pivot_orders.sum(axis=1)

        pivot_rev = cross.pivot_table(index="retention_category", columns="order_type_name",
                                      values="revenue", fill_value=0, aggfunc="sum")
        pivot_rev["_sort"] = pivot_rev.index.map(ot_order_map).fillna(99)
        pivot_rev = pivot_rev.sort_values("_sort").drop(columns="_sort")
        pivot_rev["Total"] = pivot_rev.sum(axis=1)

        st.subheader("Orders by Retention Category x Order Type")
        st.dataframe(pivot_orders, use_container_width=True)

        fig = px.bar(cross, x="retention_category", y="orders", color="order_type_name",
                     title="Order Count by Category & Type", barmode="stack",
                     color_discrete_sequence=["#4361ee", "#e9c46a", "#2a9d8f", "#adb5bd"],
                     category_orders={"retention_category": RETENTION_ORDER})
        fig.update_layout(height=420, margin=dict(t=40, b=20), xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Revenue by Retention Category x Order Type")
        st.dataframe(pivot_rev.round(0), use_container_width=True)

        fig = px.bar(cross, x="retention_category", y="revenue", color="order_type_name",
                     title="Revenue by Category & Type", barmode="stack",
                     color_discrete_sequence=["#4361ee", "#e9c46a", "#2a9d8f", "#adb5bd"],
                     category_orders={"retention_category": RETENTION_ORDER})
        fig.update_layout(height=420, margin=dict(t=40, b=20), xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)
