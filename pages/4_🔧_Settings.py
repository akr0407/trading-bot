"""
pages/4_🔧_Settings.py — Strategy parameters, risk management, and bot configuration.
"""

import streamlit as st

import database as db
from config import load_global_settings, ALLOWED_TIMEFRAMES

# ===================================================================
# Page config
# ===================================================================
st.set_page_config(page_title="Settings", page_icon="🔧", layout="wide")

st.markdown("# 🔧 Settings")
st.markdown("Configure strategy parameters, risk management, and bot behavior per account.")

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
    key="settings_account_select",
)

settings = db.get_account_settings(selected_id)
if not settings:
    st.error("Settings not found for this account")
    st.stop()

global_settings = load_global_settings()

# ===================================================================
# Strategy Parameters
# ===================================================================
st.subheader("📐 Strategy Parameters — Hull Suite + Supertrend")

with st.form("strategy_params_form"):
    st.markdown("**Hull Suite**")
    col1, col2, col3 = st.columns(3)

    with col1:
        hull_mode = st.selectbox(
            "Hull Variation",
            ["Hma", "Ehma", "Thma"],
            index=["Hma", "Ehma", "Thma"].index(settings.get("hull_mode", "Hma")),
            help="HMA = standard, EHMA = exponential, THMA = triple",
        )
    with col2:
        hull_160 = st.number_input(
            "Hull Length 160", min_value=1, max_value=500,
            value=settings.get("hull_length_160", 160),
            help="Slow Hull MA period",
        )
    with col3:
        hull_80 = st.number_input(
            "Hull Length 80", min_value=1, max_value=500,
            value=settings.get("hull_length_80", 80),
            help="Fast Hull MA period",
        )

    st.markdown("**Supertrend**")
    col4, col5 = st.columns(2)

    with col4:
        atr_length = st.number_input(
            "ATR Length", min_value=1, max_value=50,
            value=settings.get("atr_length", 2),
            help="ATR period for Supertrend calculation",
        )
    with col5:
        st_factor = st.number_input(
            "Supertrend Factor", min_value=0.1, max_value=10.0,
            value=float(settings.get("supertrend_factor", 3.3)),
            step=0.1, format="%.1f",
            help="Multiplier for ATR bands",
        )

    if st.form_submit_button("💾 Save Strategy Parameters", use_container_width=True):
        db.update_account_settings(
            selected_id,
            hull_mode=hull_mode,
            hull_length_160=hull_160,
            hull_length_80=hull_80,
            atr_length=atr_length,
            supertrend_factor=st_factor,
        )
        st.success("Strategy parameters saved!")
        st.rerun()

st.divider()

# ===================================================================
# Risk Management
# ===================================================================
st.subheader("🛡️ Risk Management")

with st.form("risk_params_form"):
    col1, col2 = st.columns(2)

    with col1:
        lot_size = st.number_input(
            "Lot Size", min_value=0.01, max_value=100.0,
            value=float(settings.get("lot_size", 0.1)),
            step=0.01, format="%.2f",
            help="Volume per trade in lots",
        )
        max_positions = st.number_input(
            "Max Open Positions", min_value=1, max_value=50,
            value=settings.get("max_positions", 3),
            help="Maximum simultaneous open positions",
        )

    with col2:
        sl_pct = st.number_input(
            "Stop Loss (%)", min_value=0.0, max_value=50.0,
            value=float(settings.get("stop_loss_pct", 2.0)),
            step=0.1, format="%.1f",
            help="Stop loss as percentage from entry. Set 0 to disable.",
        )
        tp_pct = st.number_input(
            "Take Profit (%)", min_value=0.0, max_value=100.0,
            value=float(settings.get("take_profit_pct", 4.0)),
            step=0.1, format="%.1f",
            help="Take profit as percentage from entry. Set 0 to disable.",
        )

    if st.form_submit_button("💾 Save Risk Parameters", use_container_width=True):
        db.update_account_settings(
            selected_id,
            lot_size=lot_size,
            max_positions=max_positions,
            stop_loss_pct=sl_pct,
            take_profit_pct=tp_pct,
        )
        st.success("Risk parameters saved!")
        st.rerun()

st.divider()

# ===================================================================
# Trading Configuration
# ===================================================================
st.subheader("📡 Trading Configuration")

with st.form("trading_config_form"):
    col1, col2, col3 = st.columns(3)

    with col1:
        trading_pair = st.text_input(
            "Trading Pair",
            value=settings.get("trading_pair", "EURUSD"),
            help="Symbol name (MT5: EURUSD, GBPUSD | CCXT: BTC/USDT)",
        )
    with col2:
        htf_timeframe = st.selectbox(
            "Trend Timeframe (HTF)",
            ALLOWED_TIMEFRAMES,
            index=ALLOWED_TIMEFRAMES.index(
                settings.get("htf_timeframe", "15m")
            ),
            help="Higher timeframe for trend direction (Supertrend)",
        )
    with col3:
        entry_timeframe = st.selectbox(
            "Entry Timeframe (LTF)",
            ALLOWED_TIMEFRAMES,
            index=ALLOWED_TIMEFRAMES.index(
                settings.get("timeframe", "5m")
            ),
            help="Lower timeframe for trade entries (Supertrend signal)",
        )

    st.caption(
        "📐 **Multi-TF logic:** The bot checks the Supertrend trend on the HTF, "
        "then looks for entry signals on the LTF. Trades are only executed when "
        "the LTF signal matches the HTF trend direction."
    )

    if st.form_submit_button("💾 Save Trading Config", use_container_width=True):
        # Validate: HTF must be larger than LTF
        from config import TIMEFRAME_SECONDS
        htf_sec = TIMEFRAME_SECONDS.get(htf_timeframe, 0)
        ltf_sec = TIMEFRAME_SECONDS.get(entry_timeframe, 0)
        if htf_sec <= ltf_sec:
            st.error("⚠️ Trend Timeframe must be larger than Entry Timeframe!")
        else:
            db.update_account_settings(
                selected_id,
                trading_pair=trading_pair,
                timeframe=entry_timeframe,
                htf_timeframe=htf_timeframe,
            )
            st.success("Trading configuration saved!")
            st.rerun()

st.divider()

# ===================================================================
# Webhook Configuration (Future — TradingView Pro)
# ===================================================================
st.subheader("🌐 Webhook Configuration")

webhook_enabled = global_settings.webhook_enabled

if webhook_enabled:
    st.success("✅ Webhook server is **ENABLED**")
    st.code(f"Webhook URL: http://your-server:{global_settings.webhook_port}/webhook")
    st.markdown(
        "Configure this URL in TradingView alert settings.\n\n"
        "**Alert message format:**\n"
        "```json\n"
        '{"action": "{{strategy.order.action}}", "pair": "{{ticker}}", '
        '"source": "tradingview"}\n'
        "```"
    )
else:
    st.info(
        "🔒 Webhook server is **DISABLED** (polling mode active)\n\n"
        "To enable webhooks for TradingView Pro, set `WEBHOOK_ENABLED=true` in your `.env` file "
        "and restart the application."
    )

st.divider()

# ===================================================================
# Current Settings Summary
# ===================================================================
st.subheader("📋 Current Settings Summary")

import pandas as pd

settings_data = {
    "Parameter": [
        "Trading Pair", "Trend Timeframe (HTF)", "Entry Timeframe (LTF)",
        "Hull Mode", "Hull Length 160", "Hull Length 80",
        "ATR Length", "Supertrend Factor",
        "Lot Size", "Max Positions",
        "Stop Loss %", "Take Profit %",
    ],
    "Value": [
        settings.get("trading_pair"),
        settings.get("htf_timeframe", "15m"),
        settings.get("timeframe"),
        settings.get("hull_mode"),
        settings.get("hull_length_160"),
        settings.get("hull_length_80"),
        settings.get("atr_length"),
        settings.get("supertrend_factor"),
        settings.get("lot_size"),
        settings.get("max_positions"),
        settings.get("stop_loss_pct"),
        settings.get("take_profit_pct"),
    ],
}

st.dataframe(
    pd.DataFrame(settings_data),
    use_container_width=True,
    hide_index=True,
)
