# New Customer Flow Analysis

## The Question

When a company launches a new product model (e.g., Direct Start — a skip-the-evaluation instant account), the critical business question is:

**Is this new model attracting genuinely new customers, or is it just cannibalizing existing ones?**

If new customers are discovering the company *because of* this product, it's an acquisition driver. If existing customers are just switching from other models, the new product adds complexity without growing the pie.

## The Three-Layer Framework

### Layer 1: Monthly Distribution

The simplest view: for each month, count how many customers chose each model as their **first-ever purchase**.

```sql
WITH first_cfd_order AS (
    SELECT DISTINCT ON (o.user_id)
           o.user_id, o.created_at AS first_date,
           CASE WHEN a.type ILIKE '%standard 2-phase%' THEN 'Standard 2-Phase'
                WHEN a.type ILIKE '%standard 1-phase%' THEN 'Standard 1-Phase'
                WHEN a.type ILIKE '%basic lite%' THEN 'Basic Lite'
                WHEN a.type ILIKE '%direct start%' THEN 'Direct Start'
                ...
           END AS model
    FROM core.purchases o
    JOIN core.user_accounts a ON o.account_id = a.id
    WHERE o.status = 1
    ORDER BY o.user_id, o.created_at  -- First order per user
)
SELECT DATE_TRUNC('month', first_date) AS month, model, COUNT(*) AS customers
FROM first_cfd_order
GROUP BY 1, 2
```

`DISTINCT ON (user_id) ... ORDER BY created_at` efficiently picks each user's first-ever order. No window functions needed.

The output is a stacked bar chart showing model share over time. If a new model's share is *growing* MoM while total new customers also grow, it's genuinely expanding the market.

### Layer 2: New vs. Prior Model Segmentation

For each model, split the customers into:

- **New (Direct)**: This model was their very first CFD purchase ever
- **Prior Model**: They had purchased a different model before trying this one

```sql
CASE WHEN mf.first_model_date = cfc.first_ever_date
     THEN 'New' ELSE 'Prior Model' END AS segment
```

A simple equality check: if their first purchase of model X equals their first-ever purchase date, they are "New." Otherwise, they tried something else first.

**Why this matters**: If 80% of a model's customers are "New", it is an acquisition driver. If 80% are "Prior Model", it is not attracting new users — existing customers are just migrating.

### Layer 3: Post-Purchase Behavior

After a customer's first purchase of a model, what do they do next?

| Behavior | Definition |
|---|---|
| No Subsequent Purchase | Never bought again (churned) |
| Same Model Again Only | Repurchased the same model, never tried others |
| Other Models Only | Switched to different models, never repeated |
| Both Same + Other | Bought the same model again AND tried other models |

This is computed with a 7-CTE query:

```sql
-- Step 1: Find first-ever order per customer
-- Step 2: Find first order of the target model per customer
-- Step 3: Classify as New vs Prior
-- Step 4: Find all subsequent orders, using BOOL_OR to detect patterns
post_purchase AS (
    SELECT
        mc.user_id,
        BOOL_OR(sub_model = target_model) AS bought_same,
        BOOL_OR(sub_model != target_model) AS bought_other
    FROM ...
)
-- Step 5: Classify behavior
classified AS (
    SELECT user_id,
        CASE
            WHEN NOT bought_same AND NOT bought_other THEN 'No Subsequent Purchase'
            WHEN bought_same AND NOT bought_other THEN 'Same Model Again Only'
            WHEN NOT bought_same AND bought_other THEN 'Other Models Only'
            ELSE 'Both Same + Other'
        END AS behavior
    FROM post_purchase
)
```

Each behavior group gets revenue, AOV, payout ratio, and pass rate metrics.

### Pass Rate Calculation

The pass rate logic auto-detects 1-step vs. 2-step models:

```python
if p2_count > 0:  # 2-step model
    p1_pass_rate = p2_count / (p1_breaches + resets)
    p2_pass_rate = real_count / p2_breaches
    overall = p1_pass_rate * p2_pass_rate * 100
else:  # 1-step model
    overall = real_count / (p1_breaches + resets) * 100
```

Resets (repurchases of the same challenge after failure) are added to the denominator because each reset represents an additional attempt.

### Layer 4: Repurchase Depth

Customers are bucketed by how many times they've repurchased: 0 (one-and-done), 1, 2, 3, ... 6–10, 11+.

For each bucket, the table shows:
- Same-model revenue and orders
- Other-model revenue and orders
- Cumulative payout and pass rate

**Cumulative, not per-bucket**: The table reads "by the time a customer has repurchased 3 times, their cumulative pass rate is X% and cumulative payout is $Y." This is more actionable than per-bucket averages because it shows the full customer lifecycle value.

## Design Decisions

**Coupon filter**: The analysis can be filtered by promo code. This answers "did the Black Friday campaign bring in new customers or just give discounts to existing ones?"

**Toggle-gated queries**: Each layer is behind a toggle (`st.toggle`). The post-purchase behavior query is a 7-CTE monster that scans the entire orders table — it only runs when the user explicitly wants it.

**HTML tables over st.dataframe**: Custom HTML provides control over MoM change indicators (green/red arrows), percentage-point deltas, and sticky headers that Streamlit's built-in data frame doesn't support.

## What This Revealed

- **Direct Start attracted genuinely new customers** — ~70% of Direct Start's first-month customers had never purchased before, compared to ~45% for Standard 2-Phase. This validated the product team's hypothesis that a skip-the-evaluation option would expand the addressable market.

- **"Same Model Again Only" customers are the most profitable per-capita** — they have the highest pass rates and payout ratios, suggesting that model loyalty correlates with trading skill.

- **"Other Models Only" is a warning signal** — customers who immediately switch to a different model after their first purchase tend to have lower pass rates and higher churn, suggesting initial misalignment between customer expectations and product choice.

- **The revenue curve flattens after 4–5 repurchases** — cumulative revenue per customer grows steeply for the first 4 repurchases, then plateaus. This suggests that the highest-value intervention point is converting 1-time buyers into 3–4 time buyers.
