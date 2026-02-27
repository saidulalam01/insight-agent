# Insight Agent

A self-service analytics dashboard built for a prop trading firm's data team. Replaces ad-hoc SQL queries and manual spreadsheets with an interactive tool that answers recurring business questions in real time.

## The Problem

The data team was fielding the same questions repeatedly:
- "What's our revenue today vs last week?"
- "Why did breach rates spike?"
- "Are new customers sticking with their first product or switching?"
- "What's our retention actually look like — not just 30/60/90 day buckets?"

Each answer required writing SQL against a production PostgreSQL warehouse, formatting it, and sharing it over Slack. The same queries ran dozens of times with slightly different date ranges. No one outside the data team could self-serve.

## The Solution

A Streamlit dashboard connected directly to the warehouse (read-only) with six purpose-built pages, each solving a specific analytical question. Every page has filters, comparisons to prior periods, and visual breakdowns — no SQL knowledge required.

### What Each Page Does

**Core Metrics** — The daily operating view. Revenue, signups, payouts, and average order value with week-over-week deltas. Model-level AOV breakdown shows which products drive revenue. Weekly trend charts catch anomalies before they become problems.

**Breach Analysis** — Accounts that violate risk rules (daily/monthly loss limits) are "breached." This page breaks down breach volume by reason, model, account size, and geography. The key insight: it tracks what happens *after* a breach — do users repurchase the same product, switch models, or churn? This drives product and pricing decisions.

**New Customer Flow** — Answers "what does a new customer's first week look like?" Tracks first-purchase model choice, whether they buy additional accounts, and how quickly. The contribution analysis shows whether newer products (like Direct Start) are attracting genuinely new customers or just cannibalizing existing ones.

**Retention Definition** — A custom retention taxonomy that goes beyond simple "30/60/90 day" buckets. Classifies every repeat purchase into categories like Acquisition Burst (within 7 days), Weekly/Bi-weekly/Monthly/Quarterly Retention, and Reacquisition (returned after 6+ months of inactivity). Uses an active-trading check to distinguish "Annual Retention" (still trading, just buying slowly) from "Reacquisition" (went dormant and came back). Daily and trend views show how the retention mix evolves over time.

**Business Knowledge** — A searchable FAQ engine that parses markdown knowledge base files at runtime. Keyword search with title-boosting ranks results. "Did You Know?" cards surface random business rules on each page load — useful for onboarding new team members who need to learn product nuances quickly.

**Product Updates & Offers** — A timeline of historical promotions, pricing changes, and platform announcements. Searchable and filterable by date range, type, and keywords. Provides context when analyzing metric changes ("revenue spiked on Nov 25 — oh, that was the Black Friday campaign").

## Key Design Decisions

**No API key required.** The dashboard works entirely through pre-built SQL queries with parameterized filters. An optional Claude integration adds natural-language querying ("Ask Anything"), but the core experience needs zero external APIs.

**URL-based navigation.** Page selection is stored in `st.query_params`, so bookmarking and sharing specific views works across browser refreshes — a common pain point with Streamlit apps.

**5-minute query cache.** All database queries are cached with `@st.cache_data(ttl=300)`. Heavy pages like New Customer Flow (which runs multi-CTE queries with window functions) load instantly on revisit.

**Dark/light theme toggle.** Full theme support including Plotly chart backgrounds and Streamlit's native data editor colors. Controlled via a single session state variable.

**Automated email reports.** A scheduled runner (`run.py`) generates HTML reports with alerts (revenue drops, payout spikes, breach rate anomalies) and emails them via SMTP. The alerting thresholds are configurable in `config.py`.

**Learnings system.** Business context is stored in `context/learnings.md` and `context/notes.jsonl`. As the team feeds in domain knowledge ("we ran a promo in October"), the insight engine incorporates it. The system improves over time without code changes.

## Outcomes

- Reduced recurring analytics requests by ~80% — stakeholders self-serve through the dashboard
- Retention taxonomy adopted as the standard definition across the analytics team
- Breach-to-repurchase tracking identified that users who breach via Monthly Loss Limit repurchase at 2x the rate of Daily Loss Limit breaches — directly informed the pricing team's reset fee strategy
- New Customer Flow analysis revealed that the newest product model was attracting genuinely new customers (not cannibalization), validating the product team's launch hypothesis

## Documentation

Detailed write-ups on the analytical frameworks, SQL patterns, and design decisions:

- **[Retention Taxonomy](docs/retention-taxonomy.md)** — The custom 10-category retention system, the active-trading check, and why standard 30/60/90 day buckets aren't enough
- **[Breach & Repurchase Framework](docs/breach-repurchase.md)** — Connecting violation events to subsequent purchase behavior, news impact correlation
- **[Customer Flow Analysis](docs/customer-flow-analysis.md)** — Contribution vs. cannibalization framework for new product launches
- **[SQL Patterns](docs/sql-patterns.md)** — Key PostgreSQL patterns: DISTINCT ON, window functions, FILTER aggregates, composable fragments, year-partitioned routing
- **[Alert System](docs/alert-system.md)** — Threshold-based anomaly detection, HTML email reports, SVG sparklines, scheduling

## Tech Stack

- **Frontend**: Streamlit (Python)
- **Database**: PostgreSQL (read-only connection)
- **Charts**: Plotly Express
- **Scheduling**: Python `schedule` library
- **Email**: SMTP via `smtplib`
- **Caching**: Streamlit's built-in `@st.cache_data`

## Project Structure

```
insight-agent/
├── app.py                    # Entrypoint — routing, theme, sidebar
├── config.py                 # DB, email, and alert threshold config
├── db.py                     # SQLAlchemy engine + query helpers
├── shared.py                 # Theme system, formatters, retention SQL
├── insights.py               # Automated insight generation engine
├── report.py                 # HTML report builder (daily/weekly)
├── run.py                    # Scheduled report runner
├── mailer.py                 # SMTP email sender
├── pages/
│   ├── core_metrics.py       # Revenue, signups, payouts, AOV
│   ├── breach.py             # Breach analysis + repurchase tracking
│   ├── new_customer_flow.py  # First-purchase behavior + model adoption
│   ├── retention_definition.py  # Custom retention taxonomy
│   ├── business_knowledge.py # FAQ search + Did You Know cards
│   └── product_updates.py    # Promotions & announcements timeline
├── data/
│   ├── faq_files/            # Markdown knowledge base (CFD, Futures)
│   └── seed.py               # Sample data generator
├── context/                  # Business context (learnings + notes)
├── offers_data.json          # Product updates data
├── start.sh / stop.sh        # Launch scripts
└── .env.example              # Environment template
```

## Running Locally

```bash
pip install -r requirements.txt
cp .env.example .env          # Edit with your DB credentials
streamlit run app.py
```

The FAQ search and product updates pages work without a database. Core Metrics, Breach, New Customer Flow, and Retention require a PostgreSQL connection with the expected schema (see SQL queries in each page file for table definitions).

## Note

This is an anonymized version of an internal tool. Company names, product names, database schemas, and business-specific details have been replaced with generic equivalents. The code, architecture, and analytical logic are real.
