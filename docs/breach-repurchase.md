# Breach & Repurchase Framework

## The Question

When a trading account violates a risk rule (daily loss limit, monthly loss limit, etc.), the account is "breached" and deactivated. The obvious metric is breach rate — but the more important business question is: **what happens after the breach?**

- Does the customer come back and buy a new account?
- Does repurchase behavior differ by breach reason?
- Does it differ by evaluation phase (P1, P2, funded)?
- How much of the breach volume is news-driven (and therefore somewhat uncontrollable)?

## The Framework

### 1. Breach Volume by Phase

Every breached account is classified into a phase:

```sql
CASE
    WHEN a.type ILIKE '%Demo P1%' THEN 'P1 (Demo)'
    WHEN a.type ILIKE '%Demo P2%' THEN 'P2'
    WHEN a.type ILIKE '%Real%' THEN 'Real'
    WHEN a.type ILIKE '%Instant%' THEN 'Instant'
    WHEN a.type ILIKE '%Demo%' THEN 'P1 (Demo)'
    ELSE 'Other'
END AS phase
```

**Important ordering**: `Demo P1` is checked before generic `Demo` to prevent mis-classification. The `ILIKE` patterns are carefully ordered from most specific to least specific.

The output: breach count and unique customer count per phase, compared to a prior period. This immediately shows where breaches are concentrating — early in the funnel (P1) or on funded accounts (Real/Instant).

### 2. Breach Reason Breakdown

Breach reasons fall into distinct categories:

| Reason | What It Means |
|---|---|
| Daily Loss Limit (DLL) | Lost too much in a single day |
| Monthly Loss Limit (MLL) | Cumulative losses exceeded the threshold |
| Profit Target Reached | **This is actually a pass**, not a failure |
| Inactivity | No trades for 30 consecutive days |
| Admin | Manual intervention |
| Platform Switch / Account Migrated | Operational, not trading-related |

The reason pie chart is deliberately **unfiltered by the reason filter** — even when a user filters to see only DLL breaches, the pie chart shows the full distribution. This prevents the filter from hiding context.

### 3. Repurchase Tracking

The core analytical contribution: connecting breach events to subsequent purchase behavior.

```sql
-- Step 1: Find all breached customers, deduplicated by highest phase
WITH violated AS (
    SELECT DISTINCT ON (a.user_id)
           a.user_id, a.violated AS breach_at, phase
    FROM core.user_accounts a
    WHERE a.violated = 1 AND a.updated_at BETWEEN ...
    ORDER BY a.user_id, phase_priority DESC
),
-- Step 2: Check for subsequent purchases
repurchased AS (
    SELECT DISTINCT b.user_id
    FROM violated b
    JOIN core.purchases o ON o.user_id = b.user_id
    WHERE o.status = 1
      AND o.created_at > b.breach_at  -- Must be AFTER the breach
)
```

Key design: **`DISTINCT ON (user_id)` with phase priority ordering**. A customer who breached in both P1 and P2 during the period is assigned to their highest phase. This prevents double-counting and gives a cleaner picture of where the most valuable breaches happen.

The repurchase rate is: `repurchased customers / total breached customers × 100%`

### 4. News Impact Correlation

Trading around high-impact news events (NFP, CPI, rate decisions) carries additional risk. This section quantifies how much of the breach volume is news-driven.

The analysis joins three data sources:
- **Breached accounts** — the pool of violated accounts
- **News calendar** — events where `is_blocked = 1` (restricted high-impact events)
- **Trade data** — the actual trades placed by these accounts

The match condition checks for temporal overlap:

```sql
WHERE t.open_time <= news_event.date + INTERVAL '5 minutes'
  AND t.close_time >= news_event.date - INTERVAL '5 minutes'
```

If a trade was open during the 5-minute window around a restricted news event AND the account was subsequently breached, it's counted as a news-related breach.

**Year-partitioned trade tables**: Trade data is split by calendar year (`reporting.user_trades_2025`, `reporting.user_trades_2026`). If the analysis date range spans December–January, the query dynamically constructs a `UNION ALL` across both year tables.

### 5. Dynamic Filter Composition

All panels share a common filter system:

```python
def _br_geo_join(alias="a", cid_col="user_id"):
    """Build geographic filter JOINs and WHERE clauses."""
    joins = " JOIN core.users _gc ON {alias}.{cid_col} = _gc.id"
            " JOIN core.regions _gco ON _gc.country_id = _gco.id"
            " JOIN reporting.geo_regions _gr ON _gco.short_name = _gr.short_name"
    wheres = []
    if sel_regions:
        wheres.append(f"_gr.region IN (...)")
    if sel_countries:
        wheres.append(f"_gr.name IN (...)")
    return joins, " AND ".join(wheres)
```

Filters (region, country, model, account size, breach reason) are composed as SQL fragments and injected into every query. One set of filter-building functions feeds all SQL templates, eliminating duplication.

## What This Revealed

- **MLL breaches repurchase at ~2x the rate of DLL breaches.** Customers who hit the monthly loss limit (gradual drawdown) are more likely to try again than those who hit the daily loss limit (sudden blow-up). This is intuitive — MLL feels like bad luck over time; DLL feels like a catastrophic mistake.

- **Real/funded account breaches have the lowest repurchase rate.** Once a customer loses a funded account, they are significantly less likely to restart the process compared to someone who breached during Phase 1.

- **News-related breaches account for a meaningful portion of funded account violations.** This is somewhat uncontrollable — the company can restrict news trading but cannot eliminate the risk entirely. Quantifying this helps separate "customer skill issue" from "market event issue."

- **Inactivity breaches are nearly invisible to users.** They account for a small but consistent share and have near-zero repurchase rates — these are customers who forgot they had an account.
