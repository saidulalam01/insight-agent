# SQL Patterns

A reference for the key SQL patterns used throughout the dashboard. Each pattern solves a specific analytical problem.

## 1. First-Event Detection with DISTINCT ON

**Problem**: Find the first order per customer without a subquery.

```sql
SELECT DISTINCT ON (o.user_id)
       o.user_id, o.created_at, o.total_amount
FROM core.purchases o
WHERE o.status = 1
ORDER BY o.user_id, o.created_at
```

`DISTINCT ON` is PostgreSQL-specific and significantly faster than the standard `ROW_NUMBER() ... WHERE rn = 1` pattern for large tables. The `ORDER BY` must start with the `DISTINCT ON` columns.

**Used in**: New Customer Flow (first-ever order per customer), Breach (first breach per customer per phase).

## 2. Window Functions for Inter-Event Gaps

**Problem**: Classify each purchase by the gap since the previous purchase by the same customer.

```sql
SELECT
    o.user_id,
    o.created_at,
    MIN(o.created_at) OVER (PARTITION BY o.user_id) AS first_order_at,
    LAG(o.created_at) OVER (
        PARTITION BY o.user_id ORDER BY o.created_at, o.id
    ) AS prev_order_at,
    ROW_NUMBER() OVER (
        PARTITION BY o.user_id ORDER BY o.created_at, o.id
    ) AS order_seq
FROM core.purchases o
```

Three window functions in one scan:
- `MIN(...) OVER (PARTITION BY user_id)` — the customer's very first order (used for Acquisition Burst check)
- `LAG(...) OVER (...)` — the previous order's timestamp (used for gap calculation)
- `ROW_NUMBER() OVER (...)` — sequential order number (used to identify first purchase)

**Tie-breaking**: `ORDER BY created_at, o.id` ensures deterministic results when two orders share the same timestamp.

**Used in**: Retention taxonomy (shared.py), Core Metrics retention.

## 3. Interval-to-Days Conversion

**Problem**: Calculate the number of days between two timestamps reliably.

```sql
EXTRACT(EPOCH FROM (created_at - prev_order_at)) / 86400.0 AS days_since_last
```

Why not `DATE_PART('day', interval)`? Because `DATE_PART` on an interval only returns the *days component*, ignoring months. A 2-month gap would return 0 days if using `DATE_PART('day', ...)`.

`EXTRACT(EPOCH FROM ...)` converts to total seconds, then dividing by 86400 gives fractional days. This is always correct regardless of month boundaries.

**Used in**: Every retention classification query.

## 4. Conditional Aggregates with FILTER

**Problem**: Compute per-model averages in a single table scan.

```sql
SELECT
    DATE_TRUNC('day', o.created_at) AS day,
    COUNT(*) AS total_orders,
    AVG(o.total_amount) AS overall_aov,
    COALESCE(AVG(o.total_amount) FILTER (
        WHERE a.type ILIKE '%standard 1-phase%'
    ), 0) AS aov_1step,
    COALESCE(AVG(o.total_amount) FILTER (
        WHERE a.type ILIKE '%standard 2-phase%'
    ), 0) AS aov_2step,
    COALESCE(AVG(o.total_amount) FILTER (
        WHERE a.type ILIKE '%basic lite%'
    ), 0) AS aov_lite
FROM core.purchases o
JOIN core.user_accounts a ON o.account_id = a.id
GROUP BY 1
```

`FILTER (WHERE ...)` is PostgreSQL's conditional aggregate syntax. It is cleaner than `CASE WHEN ... THEN value ELSE NULL END` inside `AVG()` and produces the same result. `COALESCE(..., 0)` handles models with no orders in a given period.

**Used in**: Core Metrics (AOV by model, payout by model).

## 5. Composable SQL Fragments

**Problem**: Apply geo, model, and size filters to multiple queries without duplicating filter logic.

```python
def _geo_join(alias="a", cid_col="user_id"):
    if not sel_regions and not sel_countries:
        return "", ""  # No filter needed
    joins = (f" JOIN core.users _gc ON {alias}.{cid_col} = _gc.id"
             f" JOIN core.regions _gco ON _gc.country_id = _gco.id"
             f" JOIN reporting.geo_regions _gr ON _gco.short_name = _gr.short_name")
    wheres = []
    if sel_regions:
        wheres.append(f"_gr.region IN ({sql_list(sel_regions)})")
    if sel_countries:
        wheres.append(f"_gr.name IN ({sql_list(sel_countries)})")
    return joins, " AND ".join(wheres)
```

The function returns `(join_string, where_string)` that get injected into any SQL template:

```python
sql = f"""
    SELECT ...
    FROM core.user_accounts a
    {geo_join}
    WHERE a.violated = 1 {f'AND {geo_where}' if geo_where else ''}
"""
```

This pattern is used across Breach, Core Metrics, and New Customer Flow. The filter composition happens once; all queries consume the same fragments.

**Used in**: All interactive pages.

## 6. DISTINCT ON with Priority Ordering

**Problem**: Assign each breached customer to their *highest* phase (not their first breach).

```sql
SELECT DISTINCT ON (a.user_id)
       a.user_id, a.updated_at AS breach_at,
       CASE ... END AS phase
FROM core.user_accounts a
WHERE a.violated = 1
ORDER BY a.user_id,
         CASE phase
             WHEN 'Real' THEN 1
             WHEN 'Instant' THEN 2
             WHEN 'P2' THEN 3
             ELSE 4
         END
```

`DISTINCT ON` takes the first row per `user_id` after sorting. By sorting phases with Real first, a customer who breached in both P1 and Real gets assigned to Real. This prevents double-counting while preserving the most valuable information.

**Used in**: Breach repurchase tracking.

## 7. Year-Partitioned Table Routing

**Problem**: Trade data is split into year-partitioned tables (`reporting.user_trades_2025`, `reporting.user_trades_2026`). A query spanning December–January needs both.

```python
years = range(start_date.year, end_date.year + 1)
trade_unions = " UNION ALL ".join(
    f"SELECT * FROM reporting.user_trades_{y}" for y in years
)
sql = f"""
    WITH trades AS ({trade_unions})
    SELECT ... FROM trades t WHERE ...
"""
```

The code dynamically constructs a `UNION ALL` across the required year tables. For single-year queries, this reduces to a single table scan with no overhead.

**Used in**: Breach news impact analysis.

## 8. Two-Pass Classification (SQL + Python)

**Problem**: The retention classification needs an active-trading check for long-absence cases, but joining to the performance metrics table for every query is expensive.

**Solution**: Run the classification in SQL with a placeholder bucket (`_long_absence`), then resolve only those cases in Python with a targeted second query.

```python
# SQL returns orders with retention_category, some as '_long_absence'
df = run_query(classification_sql)

# Python: only query active-trading for the _long_absence subset
long_abs_users = df[df["retention_category"] == "_long_absence"]["user_id"].unique()
active_df = run_query(f"""
    SELECT DISTINCT a.user_id FROM ...
    WHERE a.user_id IN ({ids}) AND am."isActiveDay" = '1' ...
""")

# Resolve
df.loc[long_abs & is_active & (days <= 365), "retention_category"] = "Annual Retention"
df.loc[long_abs & is_active & (days > 365), "retention_category"] = "Late Retention"
df.loc[long_abs & ~is_active, "retention_category"] = "Reacquisition"
```

Tradeoff: Two queries instead of one, but the second query only runs for the small `_long_absence` subset (typically <5% of orders). The main SQL stays fast.

**Alternative considered**: A single SQL query with a LEFT JOIN to performance_metrics. Rejected because it would scan the metrics table for every order, not just the long-absence ones.

**Used in**: Retention (daily single-day view). The trend view skips the second pass entirely for speed, accepting slightly less accurate Annual/Late/Reacquisition classification.

## 9. Cache-by-SQL-Text

**Problem**: Streamlit re-runs the entire script on every interaction. Database queries should be cached, but the cache key must reflect the full query (including date ranges and filters).

```python
@st.cache_data(ttl=300)
def _qc(sql):
    """The SQL text IS the cache key."""
    return run_query(sql)
```

The function takes the complete SQL string as its only argument. Streamlit hashes the argument to produce a cache key. Identical SQL → cache hit. Different date range → different SQL → cache miss.

TTL of 300 seconds (5 minutes) balances freshness against query cost.

**Used in**: Every page via `shared._qc()` and `shared._qsc()`.
