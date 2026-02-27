import pandas as pd
from sqlalchemy import create_engine, text
from config import DB_CONFIG

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        cfg = DB_CONFIG
        url = f"postgresql+psycopg2://{cfg['user']}:{cfg['password']}@{cfg['host']}:{cfg['port']}/{cfg['dbname']}"
        _engine = create_engine(url, pool_pre_ping=True, pool_size=3)
    return _engine


def disconnect():
    """Dispose the engine and close all pooled connections."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def is_connected():
    """Check if the DB engine exists and can reach the database."""
    if _engine is None:
        return False
    try:
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def run_query(sql, params=None):
    """Execute a query and return results as a pandas DataFrame."""
    with get_engine().connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params)


def run_scalar(sql, params=None):
    """Execute a query and return a single scalar value."""
    with get_engine().connect() as conn:
        result = conn.execute(text(sql), params or {})
        row = result.fetchone()
        return row[0] if row else None
