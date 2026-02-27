# Insight Agent

An interactive data analytics dashboard built with Streamlit and PostgreSQL. Features retention analysis, breach tracking, customer flow modeling, and a knowledge base with FAQ search.

## Quick Start

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/insight-agent.git
cd insight-agent

# Install dependencies
pip install -r requirements.txt

# Run with sample data (no database needed)
streamlit run app.py

# Or connect your own database
cp .env.example .env
# Edit .env with your database credentials
streamlit run app.py
```

## Pages

- **Core Metrics** — Revenue, signups, payouts, AOV, and weekly trends
- **Breach** — Account violation analysis with repurchase tracking
- **New Customer Flow** — First-purchase behavior and model adoption trends
- **Retention Definition** — Custom retention taxonomy with daily/trend views
- **Business Knowledge** — FAQ search engine + rotating "Did You Know?" cards
- **Product Updates & Offers** — Historical promotions and announcements

## Project Structure

```
insight-agent/
├── app.py                    # Main Streamlit entrypoint + routing
├── config.py                 # DB & email config from .env
├── db.py                     # SQLAlchemy engine + query runners
├── shared.py                 # Theme, helpers, retention SQL
├── insights.py               # Automated insight generation
├── report.py                 # HTML report builder
├── run.py                    # Scheduled report runner
├── mailer.py                 # SMTP email sender
├── pages/
│   ├── core_metrics.py       # Revenue & signup dashboards
│   ├── breach.py             # Breach & repurchase analysis
│   ├── new_customer_flow.py  # Customer acquisition flow
│   ├── retention_definition.py
│   ├── business_knowledge.py # FAQ search + DYK cards
│   └── product_updates.py    # Offers timeline
├── data/
│   ├── faq_files/            # FAQ markdown files (CFD, Futures)
│   └── seed.py               # Sample data generator
├── context/
│   ├── learnings.md          # Business context notes
│   └── notes.jsonl           # Structured context log
├── offers_data.json          # Product updates & offers data
├── start.sh / stop.sh        # Launch/stop scripts
└── .env.example              # Environment template
```

## Configuration

Copy `.env.example` to `.env` and update with your values.

The app expects a PostgreSQL database with the schemas and tables referenced in the SQL queries. Use `data/seed.py` as a starting point to create sample tables.

## Sample Data

Run `python data/seed.py` to generate sample tables in your local database. The FAQ search and product updates pages work without a database connection.
