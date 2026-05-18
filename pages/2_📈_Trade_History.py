"""
pages/2_📈_Trade_History.py — Trade log, equity curve, and performance stats.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import database as db

# ===================================================================
# Page config
# ===================================================================
st.set_page_config(page_title="Trade History", page_icon="📈", layout="wide")

st.markdown("# 📈 Trade History")

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
    key="history_account_select",
)

# ===================================================================
# Performance Stats
# ===================================================================
st.subheader("📊 Performance Summary")

stats = db.get_trade_stats(selected_id)

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Total Trades", stats["total_trades"])
with col2:
    wr = stats["win_rate"]
    st.metric("Win Rate", f"{wr:.1f}%",
              delta_color="normal" if wr >= 50 else "inverse")
with col3:
    pnl = stats["total_pnl"]
    st.metric("Total P&L", f"${pnl:,.2f}",
              delta=f"{'▲' if pnl >= 0 else '▼'} ${abs(pnl):,.2f}",
              delta_color="normal" if pnl >= 0 else "inverse")
with col4:
    pf = stats["profit_factor"]
    pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
    st.metric("Profit Factor", pf_str)
with col5:
    st.metric("Max Drawdown", f"${stats['max_drawdown']:,.2f}")

# Second row
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Wins", stats["wins"])
with col2:
    st.metric("Losses", stats["losses"])
with col3:
    st.metric("Avg Win", f"${stats['avg_win']:,.2f}")
with col4:
    st.metric("Avg Loss", f"${stats['avg_loss']:,.2f}")

st.divider()

# ===================================================================
# Equity Curve
# ===================================================================
st.subheader("📉 Equity Curve")

trades = db.get_trades(selected_id, limit=500)

if trades:
    df_trades = pd.DataFrame(trades)

    # Only closed trades with PnL for equity curve
    closed = df_trades[df_trades["status"] == "closed"].copy()

    if not closed.empty and "pnl" in closed.columns:
        closed = closed.sort_values("created_at")
        closed["cumulative_pnl"] = closed["pnl"].cumsum()

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=closed["created_at"],
            y=closed["cumulative_pnl"],
            mode="lines+markers",
            name="Cumulative P&L",
            line=dict(
                color="#00d4aa",
                width=2,
            ),
            marker=dict(size=4),
            fill="tozeroy",
            fillcolor="rgba(0, 212, 170, 0.1)",
        ))

        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis_title="Date",
            yaxis_title="Cumulative P&L ($)",
            height=400,
            margin=dict(l=0, r=0, t=20, b=0),
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No closed trades with P&L data yet.")

    st.divider()

    # ===================================================================
    # Trade Table
    # ===================================================================
    st.subheader("📋 Trade Log")

    # Filters
    col_filter1, col_filter2, col_filter3 = st.columns(3)
    with col_filter1:
        side_filter = st.selectbox("Side", ["All", "BUY", "SELL"], key="side_filter")
    with col_filter2:
        status_filter = st.selectbox("Status", ["All", "open", "closed", "cancelled"],
                                      key="status_filter")
    with col_filter3:
        source_filter = st.selectbox("Source", ["All", "polling", "webhook"],
                                      key="source_filter")

    df_display = df_trades.copy()
    if side_filter != "All":
        df_display = df_display[df_display["side"] == side_filter]
    if status_filter != "All":
        df_display = df_display[df_display["status"] == status_filter]
    if source_filter != "All":
        df_display = df_display[df_display["source"] == source_filter]

    display_cols = ["created_at", "pair", "side", "price", "quantity",
                    "pnl", "status", "source", "order_id"]
    available = [c for c in display_cols if c in df_display.columns]

    def color_side(val):
        if val == "BUY":
            return "color: #00d4aa; font-weight: bold"
        elif val == "SELL":
            return "color: #ff4c4c; font-weight: bold"
        return ""

    def color_pnl(val):
        try:
            v = float(val)
            if v > 0:
                return "color: #00d4aa"
            elif v < 0:
                return "color: #ff4c4c"
        except (TypeError, ValueError):
            pass
        return ""

    styled = df_display[available].style
    if "side" in available:
        styled = styled.map(color_side, subset=["side"])
    if "pnl" in available:
        styled = styled.map(color_pnl, subset=["pnl"])

    st.dataframe(styled, use_container_width=True, height=500)

else:
    st.info("No trades recorded yet. The bot will log trades once signals are triggered.")
