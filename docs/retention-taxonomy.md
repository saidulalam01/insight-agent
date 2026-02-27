# Retention Taxonomy

## The Problem with Standard Retention Buckets

Most analytics teams define retention as "did the user come back within 30/60/90 days?" This is a blunt instrument. It tells you *if* someone returned, but not *how* they returned:

- A customer who buys every week is very different from one who buys every 3 months
- A customer who disappeared for 8 months but was actively trading the whole time is different from one who went completely dormant
- Lumping "returned within 90 days" into one bucket hides whether your revenue comes from habitual buyers or sporadic ones

We needed a taxonomy that captures **purchase rhythm**, not just recency.

## The 10-Category System

Every order in the system is classified into exactly one retention category based on two signals: the gap since the customer's previous order, and whether they were actively trading during that gap.

| Category | Rule | What It Means |
|---|---|---|
| **First Purchase** | `order_seq = 1` | Brand new customer |
| **Acquisition Burst** | First order ≤7 days ago | Bought again within a week of their first purchase — high initial engagement |
| **Weekly Retention** | Last order ≤7 days ago | Habitual, high-frequency buyer |
| **Bi-weekly Retention** | Last order 8–14 days ago | Regular cadence |
| **Monthly Retention** | Last order 15–30 days ago | Standard monthly buyer |
| **Quarterly Retention** | Last order 31–90 days ago | Buys roughly once per quarter |
| **Bi-annual Retention** | Last order 91–180 days ago | Seasonal or occasional buyer |
| **Annual Retention** | Last order >180 days, actively trading, gap ≤365 days | Long gap but still engaged — likely just didn't need a new account |
| **Late Retention** | Last order >180 days, actively trading, gap >365 days | Very long dormancy but still on the platform |
| **Reacquisition** | Last order >180 days, NOT actively trading | Genuinely lapsed customer who came back |

## The Active-Trading Check

The critical distinction is between Annual Retention and Reacquisition. Both have 180+ day purchase gaps, but they represent fundamentally different customer states:

- **Annual Retention**: The customer hadn't *bought* anything for months, but they were still *trading* on existing accounts. They were engaged — just didn't need a new purchase. When they finally buy again, it's a natural extension of ongoing activity.

- **Reacquisition**: The customer stopped buying AND stopped trading. They were truly gone. Their return is a win-back event, possibly triggered by a promo or life change.

### How the check works

For any order classified as `_long_absence` (>180 day gap), we query the `performance_metrics` table:

```sql
SELECT DISTINCT a.user_id
FROM core.user_accounts a
JOIN core.performance_metrics am ON am.account_id = a.id
WHERE a.user_id IN (...)
  AND am."isActiveDay" = '1'
  AND am."reportDate" >= reference_date - 180 days
  AND am."reportDate" < reference_date
```

If the customer had at least one active trading day in the 180 days before their new purchase, they are classified as Annual/Late Retention. If not, they are Reacquisition.

### Why two passes?

The main retention SQL classifies everything in one query using window functions. But the active-trading check requires joining to a large metrics table. Rather than making every query pay that cost, we:

1. **SQL pass**: Classify all orders, using `_long_absence` as a placeholder for the >180 day cases
2. **Python pass**: For only the `_long_absence` subset (typically <5% of orders), run the active-trading query and resolve into Annual/Late/Reacquisition

This keeps the main query fast while still getting the nuanced classification where it matters.

## SQL Implementation

The classification uses window functions on the orders table:

```sql
WITH customer_orders AS (
    SELECT
        o.user_id,
        o.id AS order_id,
        o.total_amount,
        o.created_at,
        MIN(o.created_at) OVER (PARTITION BY o.user_id) AS first_order_at,
        LAG(o.created_at) OVER (
            PARTITION BY o.user_id ORDER BY o.created_at, o.id
        ) AS prev_order_at,
        ROW_NUMBER() OVER (
            PARTITION BY o.user_id ORDER BY o.created_at, o.id
        ) AS order_seq
    FROM core.purchases o
    ...
)
SELECT *,
    CASE
        WHEN order_seq = 1 THEN 'First Purchase'
        WHEN days_since_first <= 7 THEN 'Acquisition Burst'
        WHEN days_since_last <= 7 THEN 'Weekly Retention'
        WHEN days_since_last <= 14 THEN 'Bi-weekly Retention'
        WHEN days_since_last <= 30 THEN 'Monthly Retention'
        WHEN days_since_last <= 90 THEN 'Quarterly Retention'
        WHEN days_since_last <= 180 THEN 'Bi-annual Retention'
        ELSE '_long_absence'
    END AS retention_category
FROM customer_orders
```

Key details:
- **`ORDER BY created_at, o.id`** — tie-breaking by ID ensures deterministic ordering when two orders share the same timestamp
- **`EXTRACT(EPOCH FROM ...) / 86400.0`** — converts intervals to days without relying on PostgreSQL's interval arithmetic, which can behave unexpectedly at month boundaries
- **Acquisition Burst uses `days_since_first`** (not `days_since_last`) — it captures the initial buying spree relative to the customer's first-ever order

## How It's Used

### Daily view (Retention Definition page)
For a single day, every order is classified and displayed as a stacked bar and summary table. This shows the revenue composition: what percentage came from new customers vs. returning ones, and at what frequency.

### Trend view (Core Metrics page)
Aggregated by date over a range. Shows how the retention mix evolves — e.g., is the "First Purchase" share growing (healthy acquisition) or is revenue increasingly dependent on "Quarterly Retention" (slowing growth)?

### Automated reports (insights.py)
The weekly report includes the retention breakdown, surfacing shifts that might not be visible day-to-day.

## What This Revealed

- **Acquisition Burst is a leading indicator.** When the Acquisition Burst share drops, it predicts a revenue decline 2–3 weeks later — these are the most engaged new customers, and if fewer of them are buying a second account within a week, something changed.
- **Reacquisition spikes correlate with promotions.** Campaign periods show a clear bump in Reacquisition (dormant customers returning), validating that promos are reaching lapsed users, not just feeding existing ones.
- **Monthly Retention is the largest returning bucket.** Most repeat customers buy roughly monthly, which aligns with the typical trading cycle of evaluating results, adjusting, and purchasing a new account.
