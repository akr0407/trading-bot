"""
dashboard.py — Streamlit main entry point & home page.

Run with:
    streamlit run dashboard.py

This is the home page. Additional pages are in the pages/ folder
and automatically appear in the sidebar navigation.
"""

import streamlit as st
import database as db
from bot_loop import get_bot_manager

# ===================================================================
# Page config
# ===================================================================
st.set_page_config(
    page_title="Trading Bot — Hull + Supertrend",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===================================================================
# Init database on first run
# ===================================================================
db.init_db()

# ===================================================================
# Custom CSS for premium look
# ===================================================================
st.markdown("""
<style>
    /* Global font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* Metric cards */
    div[data-testid="metric-container"] {
        background: linear-gradient(135deg, #1a1f2e 0%, #252b3d 100%);
        border: 1px solid rgba(0, 212, 170, 0.2);
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
    div[data-testid="metric-container"] label {
        color: #8b95a5 !important;
        font-size: 0.85rem !important;
    }
    div[data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-size: 1.5rem !important;
        font-weight: 600 !important;
    }

    /* Status banner */
    .status-running {
        background: linear-gradient(90deg, rgba(0, 212, 170, 0.1) 0%, rgba(0, 212, 170, 0.05) 100%);
        border-left: 4px solid #00d4aa;
        padding: 12px 20px;
        border-radius: 0 8px 8px 0;
        margin-bottom: 1rem;
    }
    .status-stopped {
        background: linear-gradient(90deg, rgba(255, 76, 76, 0.1) 0%, rgba(255, 76, 76, 0.05) 100%);
        border-left: 4px solid #ff4c4c;
        padding: 12px 20px;
        border-radius: 0 8px 8px 0;
        margin-bottom: 1rem;
    }
    .status-error {
        background: linear-gradient(90deg, rgba(255, 170, 0, 0.1) 0%, rgba(255, 170, 0, 0.05) 100%);
        border-left: 4px solid #ffaa00;
        padding: 12px 20px;
        border-radius: 0 8px 8px 0;
        margin-bottom: 1rem;
    }

    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0e1117 0%, #151b28 100%);
    }

    /* Table styling */
    .stDataFrame { border-radius: 8px; overflow: hidden; }

    /* Button styling */
    .stButton > button {
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0, 212, 170, 0.3);
    }
</style>
""", unsafe_allow_html=True)

# ===================================================================
# Home Page Content
# ===================================================================

st.markdown("# 🤖 Trading Bot Dashboard")
st.markdown("**Hull Suite + Supertrend** — Self-hosted polling-based trading bot")

st.divider()

# ===================================================================
# Overview Section
# ===================================================================
accounts = db.get_accounts()
manager = get_bot_manager()

if not accounts:
    st.info(
        "👋 **Welcome!** No accounts configured yet.\n\n"
        "Go to **⚙️ Accounts** page to add your first broker account."
    )
else:
    # Summary metrics
    running_count = sum(1 for a in accounts if a.get("status") == "running")
    total_accounts = len(accounts)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Accounts", total_accounts)
    with col2:
        st.metric("Active Bots", running_count,
                   delta=f"{running_count}/{total_accounts}")
    with col3:
        # Count total trades today
        total_trades = 0
        for a in accounts:
            trades = db.get_trades(a["id"], limit=100)
            total_trades += len(trades)
        st.metric("Total Trades", total_trades)
    with col4:
        # Total PnL
        total_pnl = 0.0
        for a in accounts:
            stats = db.get_trade_stats(a["id"])
            total_pnl += stats.get("total_pnl", 0)
        delta_color = "normal" if total_pnl >= 0 else "inverse"
        st.metric("Total P&L", f"${total_pnl:,.2f}",
                   delta=f"{'▲' if total_pnl >= 0 else '▼'} ${abs(total_pnl):,.2f}",
                   delta_color=delta_color)

    st.divider()

    # Account cards
    st.subheader("Account Overview")

    for account in accounts:
        status = account.get("status", "stopped")
        status_emoji = {"running": "🟢", "stopped": "🔴", "error": "🟡"}.get(status, "⚪")
        status_class = f"status-{status}"

        st.markdown(
            f'<div class="{status_class}">'
            f'<strong>{status_emoji} {account["name"]}</strong> '
            f'— {account["broker_type"].upper()} | '
            f'{account.get("trading_pair", "N/A")} | '
            f'{account.get("timeframe", "N/A")} | '
            f'Status: <strong>{status.upper()}</strong>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Quick action buttons
        col_start, col_stop, col_kill, _ = st.columns([1, 1, 1, 3])
        with col_start:
            if st.button("▶ Start", key=f"home_start_{account['id']}",
                         disabled=(status == "running")):
                success, msg = manager.start_bot(account["id"])
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
                st.rerun()

        with col_stop:
            if st.button("⏹ Stop", key=f"home_stop_{account['id']}",
                         disabled=(status != "running")):
                success, msg = manager.stop_bot(account["id"])
                if success:
                    st.success(msg)
                else:
                    st.warning(msg)
                st.rerun()

        with col_kill:
            if st.button("🔴 KILL", key=f"home_kill_{account['id']}",
                         type="primary"):
                success, msg = manager.kill_bot(account["id"])
                st.warning(f"Kill switch activated: {msg}")
                st.rerun()

        st.markdown("---")

# ===================================================================
# Sidebar — Bot Info
# ===================================================================
with st.sidebar:
    st.markdown("### 🤖 Bot Info")
    st.markdown(
        "**Strategy:** Hull Suite + Supertrend\n\n"
        "**Mode:** Polling (no webhooks)\n\n"
        "**Brokers:** MT5, CCXT (Binance+)"
    )
    st.divider()
    st.markdown(
        "📖 [PineScript Source](feed/pinescript.md)\n\n"
        "Built with Streamlit + pandas_ta"
    )
