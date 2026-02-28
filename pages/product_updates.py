"""Product Updates & Offers page."""

import os
import json
import re
import html as html_mod
import streamlit as st
from datetime import datetime

from shared import get_theme


OFFERS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "offers_data.json")


def _load_offers_file():
    if not os.path.exists(OFFERS_PATH):
        return None
    with open(OFFERS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _parse_date(s):
    if not s or not s.strip():
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def _calc_duration(start_str, end_str):
    s, e = _parse_date(start_str), _parse_date(end_str)
    if s and e:
        d = (e - s).days
        return max(d, 1)
    return None


def _score_offer(o, query):
    q = query.lower().strip()
    q_words = set(re.findall(r'\w+', q))
    if not q_words:
        return 0
    _all_text = " ".join(str(v) for v in o.values()).lower()
    score = 0
    if q in _all_text:
        score += 10
    for cp in o.get("Code", "").lower().split("\n"):
        if q == cp.strip():
            score += 20
    matched = sum(1 for w in q_words if w in _all_text)
    if matched == 0:
        return 0
    score += matched * 3
    if matched == len(q_words):
        score += 5
    if any(w in o.get("Code", "").lower() for w in q_words):
        score += 5
    pcts = re.findall(r'\d+%', q)
    for p in pcts:
        if p in _all_text:
            score += 10
    return score


def render():
    _T = get_theme()

    _offers_file = _load_offers_file()
    _offers = _offers_file.get("data", []) if _offers_file else []
    _last_synced = _offers_file.get("last_synced", "") if _offers_file else ""

    # ── Header with last synced ─────────────────────────────
    _hdr_col, _sync_col = st.columns([4, 1])
    with _hdr_col:
        st.header("Product Updates & Offers")
    with _sync_col:
        if _last_synced:
            try:
                _sync_dt = datetime.fromisoformat(_last_synced)
                _sync_str = _sync_dt.strftime("%b %d, %I:%M %p")
            except Exception:
                _sync_str = "Unknown"
            st.caption(f"Last synced: {_sync_str}")
        else:
            st.caption("Not synced yet")

    if not _offers:
        st.warning("No offers data found. Sync the data source to load offers.")
        return

    # ── Filters row 1: dropdowns ───────────────────────
    _fc1, _fc2, _fc3, _fc4 = st.columns(4)
    _all_years = sorted(set(o.get("Year", "") for o in _offers if o.get("Year")), reverse=True)
    _all_types = sorted(set(o.get("Notice Type", "") for o in _offers if o.get("Notice Type")))
    _all_products = sorted(set(o.get("Product Type", "") for o in _offers if o.get("Product Type")))
    _all_offer_types = sorted(set(o.get("Offer Type", "") for o in _offers
                                  if o.get("Offer Type") and o.get("Offer Type") != "None"))
    with _fc1:
        _sel_year = st.selectbox("Year", ["All"] + _all_years, key="pu_year")
    with _fc2:
        _sel_type = st.selectbox("Type", ["All"] + _all_types, key="pu_ntype")
    with _fc3:
        _sel_product = st.selectbox("Product", ["All"] + _all_products, key="pu_product")
    with _fc4:
        _sel_offer = st.selectbox("Offer Type", ["All"] + _all_offer_types, key="pu_otype")

    # ── Extract all unique coupon codes ───────────────────
    _all_codes_set = set()
    for _o in _offers:
        for _c in _o.get("Code", "").split("\n"):
            for _tok in re.findall(r'[A-Za-z][A-Za-z0-9]{2,}', _c):
                if _tok.upper() == _tok or any(ch.isdigit() for ch in _tok):
                    _all_codes_set.add(_tok)
        for _tok in re.findall(r'(?:Code|Coupon)[:\s]+([A-Z][A-Z0-9]{2,})', _o.get("Announcement", "")):
            _all_codes_set.add(_tok)
    _all_codes = sorted(_all_codes_set)

    # ── Filters row 2: date range, coupon code, search ──
    _fr1, _fr2, _fr3 = st.columns([2, 1, 2])
    _all_dates = [_parse_date(o.get("Starting Date", "")) for o in _offers]
    _all_dates = [d for d in _all_dates if d]
    _min_date = min(_all_dates).date() if _all_dates else datetime(2022, 1, 1).date()
    _max_date = max(_all_dates).date() if _all_dates else datetime.now().date()
    with _fr1:
        _date_range = st.date_input("Date range", value=(_min_date, _max_date),
                                    min_value=_min_date, max_value=_max_date, key="pu_dates")
    with _fr2:
        _sel_code = st.selectbox("Coupon Code", ["All"] + _all_codes, key="pu_code_filter")
    with _fr3:
        _search = st.text_input("Search", placeholder="e.g. 'black friday', 'BUNDLE', '25%'...", key="pu_search")

    # ── Apply filters ──────────────────────────────────
    _filtered = _offers
    if _sel_year != "All":
        _filtered = [o for o in _filtered if o.get("Year") == _sel_year]
    if _sel_type != "All":
        _filtered = [o for o in _filtered if o.get("Notice Type") == _sel_type]
    if _sel_product != "All":
        _filtered = [o for o in _filtered if o.get("Product Type") == _sel_product]
    if _sel_offer != "All":
        _filtered = [o for o in _filtered if o.get("Offer Type") == _sel_offer]
    # Coupon code filter
    if _sel_code != "All":
        _code_lower = _sel_code.lower()
        _filtered = [o for o in _filtered
                     if _code_lower in o.get("Code", "").lower()
                     or _code_lower in o.get("Announcement", "").lower()]
    # Date range filter
    if isinstance(_date_range, tuple) and len(_date_range) == 2:
        _dr_start, _dr_end = _date_range
        _date_filtered = []
        for o in _filtered:
            od = _parse_date(o.get("Starting Date", ""))
            if od and _dr_start <= od.date() <= _dr_end:
                _date_filtered.append(o)
        _filtered = _date_filtered
    if _search.strip():
        _scored = [(o, _score_offer(o, _search)) for o in _filtered]
        _scored = [(o, s) for o, s in _scored if s > 0]
        _scored.sort(key=lambda x: -x[1])
        _filtered = [o for o, s in _scored]
    else:
        _filtered.sort(key=lambda o: _parse_date(o.get("Starting Date", "")) or datetime.min, reverse=True)

    # ── Summary metrics ────────────────────────────────
    _m1, _m2, _m3, _m4 = st.columns(4)
    _m1.metric("Offers", sum(1 for o in _filtered if o.get("Notice Type") == "Offer"))
    _m2.metric("Product Changes", sum(1 for o in _filtered if o.get("Notice Type") == "Product Modification"))
    _m3.metric("Launches", sum(1 for o in _filtered if o.get("Notice Type") == "Product Launch"))
    _m4.metric("With Coupon", sum(1 for o in _filtered if o.get("Code", "").strip()))
    st.caption(f"Showing **{len(_filtered)}** of {len(_offers)} entries")

    _type_colors = {"Offer": "#4361ee", "Product Modification": "#e67e22", "Product Launch": "#2ecc71"}
    _otype_colors = {"Discount": "#3498db", "Reward": "#9b59b6", "BUNDLE": "#e74c3c", "Combo": "#1abc9c"}

    def _highlight_ann(text):
        """Highlight key info in announcement text for quick scanning."""
        safe = html_mod.escape(text).replace("\r", "")
        safe = re.sub(
            r'(\d+%)',
            rf'<span style="color:{_T["hl_pct"]};font-weight:700;">\1</span>',
            safe,
        )
        safe = re.sub(
            r'(\$[\d,]+(?:\.\d{2})?)',
            rf'<span style="color:{_T["hl_dollar"]};font-weight:600;">\1</span>',
            safe,
        )
        for _model in ["Standard 1-Phase", "Standard 2-Phase", "Basic Lite", "Direct Start",
                       "Rapid", "Legacy", "Bolt"]:
            _model_esc = html_mod.escape(_model)
            safe = safe.replace(
                _model_esc,
                f'<span style="color:{_T["hl_model"]};font-weight:600;">{_model_esc}</span>',
            )
        for _term in ["BUNDLE", "Free", "New Users", "Existing Users", "New User",
                      "Recurring", "Old User"]:
            _term_esc = html_mod.escape(_term)
            safe = re.sub(
                f'(?i)({re.escape(_term_esc)})',
                rf'<span style="color:{_T["hl_term"]};font-weight:600;">\1</span>',
                safe,
            )
        safe = safe.replace("\n", "<br>")
        return safe

    for _o in _filtered:
        _ntype = _o.get("Notice Type", "")
        _border_clr = _type_colors.get(_ntype, "#555")
        _product = _o.get("Product Type", "")
        _otype = _o.get("Offer Type", "")
        _code = _o.get("Code", "").strip()
        _start = _o.get("Starting Date", "")
        _end = _o.get("Ending Date", "")
        _ann = _o.get("Announcement", "").strip()
        _dur = _calc_duration(_start, _end)

        # Split first line as title if it's short enough
        _ann_lines = _ann.replace("\r", "").split("\n", 1)
        _title_raw = _ann_lines[0].strip().rstrip(":").rstrip("-").strip()
        _body_raw = _ann_lines[1].strip() if len(_ann_lines) > 1 else ""
        if len(_title_raw) > 80 or not _body_raw:
            _title_raw = ""
            _body_raw = _ann

        _title_html = html_mod.escape(_title_raw) if _title_raw else ""
        _body_html = _highlight_ann(_body_raw)

        # Badges
        _badges = f'<span style="background:{_border_clr};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;margin-right:6px;">{html_mod.escape(_ntype)}</span>'
        if _product:
            _badges += f'<span style="background:{_T["badge_neutral_bg"]};color:{_T["badge_neutral_text"]};padding:2px 8px;border-radius:4px;font-size:11px;margin-right:6px;">{html_mod.escape(_product)}</span>'
        if _otype and _otype != "None":
            _badges += f'<span style="background:{_otype_colors.get(_otype, "#555")};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;">{html_mod.escape(_otype)}</span>'

        # Date + duration
        _is_offer = _ntype == "Offer"
        _date_html = html_mod.escape(_start)
        if _is_offer and _end:
            _date_html += f' &rarr; {html_mod.escape(_end)}'
            if _dur is not None:
                _date_html += f' <span style="background:{_T["dur_bg"]};color:{_T["dur_text"]};padding:1px 6px;border-radius:3px;font-size:10px;margin-left:6px;">{_dur} day{"s" if _dur != 1 else ""}</span>'
            elif _start:
                _date_html += f' <span style="background:{_T["dur_bg"]};color:{_T["dur_text"]};padding:1px 6px;border-radius:3px;font-size:10px;margin-left:6px;">Ongoing</span>'

        # Codes
        _code_html = ""
        if _code:
            _codes = [c.strip() for c in _code.split("\n") if c.strip()]
            _code_spans = "".join(
                f'<span style="background:{_T["code_bg"]};border:1px solid {_T["code_border"]};color:{_T["code_text"]};'
                f'padding:5px 14px;border-radius:6px;font-family:monospace;font-size:13px;'
                f'letter-spacing:1.5px;font-weight:600;">{html_mod.escape(c)}</span>'
                for c in _codes
            )
            _code_html = f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;">{_code_spans}</div>'

        # Title
        _title_block = ""
        if _title_html:
            _title_block = (f'<div style="color:{_T["title_text"]};font-size:16px;font-weight:700;'
                            f'margin-bottom:8px;">{_title_html}</div>')

        st.markdown(
            f'<div style="background:{_T["card_bg"]};'
            f'border-radius:12px;padding:20px 24px;border-left:4px solid {_border_clr};'
            f'margin-bottom:14px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;flex-wrap:wrap;gap:6px;">'
            f'<div>{_badges}</div>'
            f'<div style="color:{_T["date_text"]};font-size:12px;white-space:nowrap;">{_date_html}</div>'
            f'</div>'
            f'{_code_html}'
            f'{_title_block}'
            f'<div style="color:{_T["body_text"]};font-size:13px;line-height:1.7;">{_body_html}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
