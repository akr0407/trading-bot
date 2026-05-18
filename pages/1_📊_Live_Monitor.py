"""
pages/1_📊_Live_Monitor.py — Real-time monitoring page.

Shows: account selector, kill switch, balance metrics, indicator panel,
signal log, and a live price chart with Hull + Supertrend overlay.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

import database as db
from bot_loop import get_bot_manager

# ===================================================================
# Page config
# ===================================================================
st.set_page_config(page_title="Live Monitor", page_icon="📊", layout="wide")

# Auto-refresh every 5 seconds
st_autorefresh(interval=5000, limit=None, key="monitor_refresh")

st.markdown("# 📊 Live Monitor")

# ===================================================================
# Account selector
# ===================================================================
accounts = db.get_accounts()

if not accounts:
    st.info("No accounts configured. Go to **⚙️ Accounts** to add one.")
    st.stop()

account_names = {a["id"]: f"{a['name']} ({a['broker_type'].upper()})" for a in accounts}
selected_id = st.selectbox(
    "Select Account",
    options=list(account_names.keys()),
    format_func=lambda x: account_names[x],
    key="monitor_account_select",
)

account = next((a for a in accounts if a["id"] == selected_id), None)
if not account:
    st.error("Account not found")
    st.stop()

settings = db.get_account_settings(selected_id)
state = db.get_bot_state(selected_id)
manager = get_bot_manager()

# ===================================================================
# Status & Kill Switch
# ===================================================================
status = state.get("status", "stopped") if state else "stopped"
kill_active = state.get("kill_switch", 0) if state else 0

col_status, col_kill = st.columns([3, 1])

with col_status:
    status_emoji = {"running": "🟢", "stopped": "🔴", "error": "🟡"}.get(status, "⚪")
    pair = settings.get("trading_pair", "N/A") if settings else "N/A"
    tf = settings.get("timeframe", "N/A") if settings else "N/A"

    st.markdown(
        f"### {status_emoji} {status.upper()} — {pair} · {tf}",
    )

    if status == "error" and state and state.get("last_error"):
        st.error(f"Last error: {state['last_error']}")

with col_kill:
    st.markdown("### 🚨 Kill Switch")
    if kill_active:
        st.error("⚠️ KILL SWITCH IS ACTIVE")
        if st.button("🔓 Deactivate Kill Switch", key="deactivate_kill"):
            db.set_kill_switch(selected_id, False)
            st.rerun()
    else:
        if st.button("🔴 ACTIVATE KILL SWITCH", key="activate_kill", type="primary"):
            success, msg = manager.kill_bot(selected_id)
            st.warning(f"Kill switch activated! {msg}")
            st.rerun()

st.divider()

# ===================================================================
# Bot Controls
# ===================================================================
col_start, col_stop, _ = st.columns([1, 1, 4])
with col_start:
    if st.button("▶ Start Bot", key="monitor_start",
                 disabled=(status == "running"), use_container_width=True):
        success, msg = manager.start_bot(selected_id)
        if success:
            st.success(msg)
        else:
            st.error(msg)
        st.rerun()

with col_stop:
    if st.button("⏹ Stop Bot", key="monitor_stop",
                 disabled=(status != "running"), use_container_width=True):
        success, msg = manager.stop_bot(selected_id)
        st.info(msg)
        st.rerun()

st.divider()

# ===================================================================
# Indicator Panel — latest signal
# ===================================================================
st.subheader("📈 Indicator Values")

signals = db.get_signals(selected_id, limit=1)

if signals:
    sig = signals[0]
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        h160 = sig.get("hull_160")
        h160_trend = sig.get("hull_160_trend", "N/A")
        trend_icon = "🟢" if h160_trend == "bullish" else "🔴"
        st.metric(
            f"Hull 160 {trend_icon}",
            f"{h160:.5f}" if h160 else "N/A",
            delta=h160_trend.capitalize(),
            delta_color="normal" if h160_trend == "bullish" else "inverse",
        )

    with col2:
        h80 = sig.get("hull_80")
        h80_trend = sig.get("hull_80_trend", "N/A")
        trend_icon = "🟢" if h80_trend == "bullish" else "🔴"
        st.metric(
            f"Hull 80 {trend_icon}",
            f"{h80:.5f}" if h80 else "N/A",
            delta=h80_trend.capitalize(),
            delta_color="normal" if h80_trend == "bullish" else "inverse",
        )

    with col3:
        st_val = sig.get("supertrend")
        direction = sig.get("direction")
        dir_text = "Uptrend ↑" if direction == 1 else "Downtrend ↓" if direction == -1 else "N/A"
        st.metric(
            "Supertrend",
            f"{st_val:.5f}" if st_val else "N/A",
            delta=dir_text,
            delta_color="normal" if direction == 1 else "inverse",
        )

    with col4:
        signal_val = sig.get("signal", "HOLD")
        signal_colors = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}
        st.metric(
            f"Signal {signal_colors.get(signal_val, '')}",
            signal_val,
            delta=f"Dir: {sig.get('prev_direction', '?')} → {sig.get('direction', '?')}",
        )
else:
    st.info("No indicator data yet — waiting for first calculation...")

st.divider()

# ===================================================================
# Signal Log — recent calculations
# ===================================================================
st.subheader("📋 Signal Log")

signals_all = db.get_signals(selected_id, limit=30)

if signals_all:
    df_signals = pd.DataFrame(signals_all)
    display_cols = [
        "created_at", "signal", "hull_160", "hull_160_trend",
        "hull_80", "hull_80_trend", "supertrend", "direction", "prev_direction",
    ]
    available_cols = [c for c in display_cols if c in df_signals.columns]
    df_display = df_signals[available_cols]

    # Color-code signals
    def highlight_signal(val):
        if val == "BUY":
            return "background-color: rgba(0, 212, 170, 0.2); color: #00d4aa; font-weight: bold"
        elif val == "SELL":
            return "background-color: rgba(255, 76, 76, 0.2); color: #ff4c4c; font-weight: bold"
        return ""

    styled = df_display.style.map(highlight_signal, subset=["signal"] if "signal" in available_cols else [])
    st.dataframe(styled, use_container_width=True, height=400)
else:
    st.info("No signals recorded yet.")
