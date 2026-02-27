"""
Interactive Insight Dashboard
Run:   streamlit run app.py
Stop:  Ctrl+C (or kill the terminal)
Remove: rm -rf insight-agent/
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from datetime import datetime

st.set_page_config(
    page_title="Admin's Testing Ground",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── DB Connection ──────────────────────────────────────────
from db import get_engine, disconnect, is_connected

# ── Theme ──────────────────────────────────────────────────
if "theme" not in st.session_state:
    st.session_state.theme = "dark"

# Apply Streamlit's native theme based on toggle — this controls ALL widget colors
if st.session_state.theme == "light":
    st._config.set_option("theme.base", "light")
    st._config.set_option("theme.backgroundColor", "#f8f9fc")
    st._config.set_option("theme.secondaryBackgroundColor", "#eef1f6")
    st._config.set_option("theme.textColor", "#2c3e50")
    st._config.set_option("theme.primaryColor", "#4361ee")
else:
    st._config.set_option("theme.base", "dark")
    st._config.set_option("theme.backgroundColor", "")
    st._config.set_option("theme.secondaryBackgroundColor", "")
    st._config.set_option("theme.textColor", "")
    st._config.set_option("theme.primaryColor", "")

# Minimal CSS tweaks for light mode (native theme handles most things)
if st.session_state.theme == "light":
    st.markdown("""<style>
        /* Plotly transparent bg (so chart bg matches page) */
        .stApp .js-plotly-plot .plotly .main-svg { background: transparent !important; }

        /* Glide Data Editor (st.dataframe) light overrides */
        .stApp [data-testid="stDataFrame"] [data-testid="glideDataEditor"] {
            --gdg-bg-cell: #ffffff !important;
            --gdg-bg-header: #f5f6fa !important;
            --gdg-bg-header-has-focus: #eef1f6 !important;
            --gdg-text-dark: #2c3e50 !important;
            --gdg-text-medium: #4a5568 !important;
            --gdg-text-light: #6c7a8a !important;
            --gdg-border-color: #dfe3ea !important;
            --gdg-bg-cell-medium: #f8f9fc !important;
        }
    </style>""", unsafe_allow_html=True)

# Set plotly template based on theme
import plotly.io as pio
pio.templates.default = "plotly_dark" if st.session_state.theme == "dark" else "plotly_white"

# ── Sidebar ────────────────────────────────────────────────
with st.sidebar:
    st.title("🧪 Admin's Testing Ground")
    st.caption("Interactive database insights")

    _pages = ["Core Metrics", "Breach", "New Customer Flow", "Retention Definition", "Business Knowledge", "Product Updates & Offers"]
    _qp = st.query_params.get("page", "Core Metrics")
    _default_idx = _pages.index(_qp) if _qp in _pages else 0
    page = st.radio("Navigate", _pages, index=_default_idx, key="nav_page")
    st.query_params["page"] = page

    st.divider()
    st.caption("**Database**")
    _connected = is_connected()
    if _connected:
        st.success("Connected", icon="🟢")
        if st.button("Disconnect", use_container_width=True, key="db_disconnect"):
            disconnect()
            st.cache_data.clear()
            st.rerun()
    else:
        st.error("Disconnected", icon="🔴")
        if st.button("Connect", use_container_width=True, type="primary", key="db_connect"):
            try:
                get_engine()
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")

    st.divider()
    st.caption("**Quick actions**")
    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    _theme_label = "☀️ Light mode" if st.session_state.theme == "dark" else "🌙 Dark mode"
    if st.button(_theme_label, use_container_width=True):
        st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
        st.rerun()

    st.divider()
    st.caption(f"Last refreshed: {datetime.now().strftime('%H:%M:%S')}")
    st.caption("To stop: `Ctrl+C` in terminal")
    st.caption("To remove: `rm -rf insight-agent/`")

# ── Page Routing ───────────────────────────────────────────
if page == "Core Metrics":
    from pages.core_metrics import render
    render()
elif page == "Breach":
    from pages.breach import render
    render()
elif page == "New Customer Flow":
    from pages.new_customer_flow import render
    render()
elif page == "Retention Definition":
    from pages.retention_definition import render
    render()
elif page == "Business Knowledge":
    from pages.business_knowledge import render
    render()
elif page == "Product Updates & Offers":
    from pages.product_updates import render
    render()
