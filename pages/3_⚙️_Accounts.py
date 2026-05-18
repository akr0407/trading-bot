"""
pages/3_⚙️_Accounts.py — Multi-account management page.

Add, edit, delete broker accounts. Test connections.
Each account has its own credentials, trading pair, and timeframe.
"""

import streamlit as st
import json

import database as db
from config import load_global_settings, ALLOWED_TIMEFRAMES
from utils.encryption import encrypt_credentials, decrypt_credentials

# ===================================================================
# Page config
# ===================================================================
st.set_page_config(page_title="Accounts", page_icon="⚙️", layout="wide")

st.markdown("# ⚙️ Account Management")
st.markdown("Add and manage broker accounts. Each account runs independently with its own trading pair and settings.")

settings = load_global_settings()

# ===================================================================
# Add New Account
# ===================================================================
st.subheader("➕ Add New Account")

with st.expander("Add a new broker account", expanded=False):
    with st.form("add_account_form"):
        col1, col2 = st.columns(2)

        with col1:
            acc_name = st.text_input("Account Name", placeholder="e.g., Finex Demo")
            broker_type = st.selectbox("Broker Type", ["mt5", "ccxt"])
            sandbox = st.checkbox("Sandbox / Demo Mode", value=True)

        with col2:
            trading_pair = st.text_input("Trading Pair", value="EURUSD",
                                          placeholder="e.g., EURUSD, GBPUSD, BTC/USDT")
            htf_timeframe = st.selectbox("Trend Timeframe (HTF)", ALLOWED_TIMEFRAMES,
                                          index=ALLOWED_TIMEFRAMES.index("15m"),
                                          help="Higher timeframe for trend direction")
            entry_timeframe = st.selectbox("Entry Timeframe (LTF)", ALLOWED_TIMEFRAMES,
                                            index=ALLOWED_TIMEFRAMES.index("5m"),
                                            help="Lower timeframe for trade entries")

        st.divider()

        # Dynamic credential fields based on broker type
        if broker_type == "mt5":
            st.markdown("**MetaTrader 5 Credentials**")
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                mt5_login = st.text_input("MT5 Account Number", placeholder="12345678")
            with col_b:
                mt5_password = st.text_input("MT5 Password", type="password")
            with col_c:
                mt5_server = st.text_input("MT5 Server", placeholder="Finex-Demo")

            mt5_path = st.text_input(
                "MT5 Terminal Path (optional)",
                placeholder=r"C:\Program Files\MetaTrader 5\terminal64.exe",
                help="Leave empty to use default MT5 installation",
            )
        else:
            st.markdown("**CCXT Exchange Credentials**")
            col_a, col_b = st.columns(2)
            with col_a:
                exchange_name = st.selectbox("Exchange", [
                    "binance", "bybit", "okx", "kucoin", "bitget",
                ])
                api_key = st.text_input("API Key")
            with col_b:
                api_secret = st.text_input("API Secret", type="password")
                api_password = st.text_input("API Password (if required)", type="password",
                                              help="Some exchanges like OKX require a passphrase")

        submitted = st.form_submit_button("💾 Save Account", use_container_width=True)

        if submitted:
            if not acc_name:
                st.error("Account name is required")
            elif not settings.master_key:
                st.error("MASTER_KEY not set in .env — cannot encrypt credentials")
            else:
                # Build credentials dict
                if broker_type == "mt5":
                    if not mt5_login or not mt5_password or not mt5_server:
                        st.error("MT5 login, password, and server are all required")
                        st.stop()
                    creds = {
                        "login": int(mt5_login),
                        "password": mt5_password,
                        "server": mt5_server,
                    }
                    if mt5_path:
                        creds["path"] = mt5_path
                else:
                    if not api_key or not api_secret:
                        st.error("API Key and Secret are required")
                        st.stop()
                    creds = {
                        "exchange": exchange_name,
                        "api_key": api_key,
                        "api_secret": api_secret,
                    }
                    if api_password:
                        creds["password"] = api_password

                # Encrypt and save
                try:
                    token = encrypt_credentials(creds, settings.master_key)
                    account_id = db.create_account(
                        name=acc_name,
                        broker_type=broker_type,
                        credentials_token=token,
                        sandbox=sandbox,
                    )
                    # Update trading pair and timeframe
                    db.update_account_settings(account_id,
                                                trading_pair=trading_pair,
                                                timeframe=entry_timeframe,
                                                htf_timeframe=htf_timeframe)
                    st.success(f"✅ Account '{acc_name}' created (ID: {account_id})")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error creating account: {e}")

st.divider()

# ===================================================================
# Existing Accounts
# ===================================================================
st.subheader("📋 Existing Accounts")

accounts = db.get_accounts()

if not accounts:
    st.info("No accounts yet. Use the form above to add one.")
else:
    for account in accounts:
        acc_id = account["id"]
        status = account.get("status", "stopped")
        status_emoji = {"running": "🟢", "stopped": "🔴", "error": "🟡"}.get(status, "⚪")
        sandbox_badge = "🧪 DEMO" if account.get("sandbox") else "🔴 LIVE"

        with st.expander(
            f"{status_emoji} **{account['name']}** — "
            f"{account['broker_type'].upper()} | "
            f"{account.get('trading_pair', 'N/A')} | "
            f"{account.get('timeframe', 'N/A')} | "
            f"{sandbox_badge}"
        ):
            acc_settings = db.get_account_settings(acc_id)

            # -------------------------------------------------------
            # Edit Account Info
            # -------------------------------------------------------
            tab_info, tab_creds, tab_danger = st.tabs([
                "📝 Edit Info", "🔑 Update Credentials", "⚠️ Danger Zone"
            ])

            with tab_info:
                with st.form(f"edit_account_{acc_id}"):
                    new_name = st.text_input("Account Name", value=account["name"],
                                              key=f"edit_name_{acc_id}")
                    new_pair = st.text_input("Trading Pair",
                                              value=acc_settings.get("trading_pair", "EURUSD") if acc_settings else "EURUSD",
                                              key=f"edit_pair_{acc_id}")
                    new_tf = st.selectbox(
                        "Timeframe", ALLOWED_TIMEFRAMES,
                        index=ALLOWED_TIMEFRAMES.index(
                            acc_settings.get("timeframe", "1h") if acc_settings else "1h"
                        ),
                        key=f"edit_tf_{acc_id}",
                    )
                    new_sandbox = st.checkbox("Sandbox / Demo Mode",
                                              value=bool(account.get("sandbox", 1)),
                                              key=f"edit_sandbox_{acc_id}")

                    if st.form_submit_button("💾 Save Changes", use_container_width=True):
                        db.update_account(acc_id, name=new_name, sandbox=int(new_sandbox))
                        db.update_account_settings(acc_id,
                                                    trading_pair=new_pair,
                                                    timeframe=new_tf)
                        st.success("Account updated!")
                        st.rerun()

            with tab_creds:
                st.warning("⚠️ Updating credentials will require restarting the bot.")

                with st.form(f"update_creds_{acc_id}"):
                    if account["broker_type"] == "mt5":
                        new_login = st.text_input("MT5 Account Number",
                                                   key=f"cred_login_{acc_id}")
                        new_password = st.text_input("MT5 Password", type="password",
                                                      key=f"cred_pass_{acc_id}")
                        new_server = st.text_input("MT5 Server",
                                                    key=f"cred_server_{acc_id}")
                        new_path = st.text_input("MT5 Terminal Path (optional)",
                                                  key=f"cred_path_{acc_id}")
                    else:
                        new_exchange = st.text_input("Exchange Name",
                                                      key=f"cred_exchange_{acc_id}")
                        new_api_key = st.text_input("API Key",
                                                     key=f"cred_apikey_{acc_id}")
                        new_api_secret = st.text_input("API Secret", type="password",
                                                        key=f"cred_secret_{acc_id}")
                        new_api_pass = st.text_input("API Password", type="password",
                                                      key=f"cred_apipass_{acc_id}")

                    if st.form_submit_button("🔐 Update Credentials", use_container_width=True):
                        if not settings.master_key:
                            st.error("MASTER_KEY not set")
                        else:
                            if account["broker_type"] == "mt5":
                                if not new_login or not new_password or not new_server:
                                    st.error("All MT5 fields are required")
                                else:
                                    creds = {
                                        "login": int(new_login),
                                        "password": new_password,
                                        "server": new_server,
                                    }
                                    if new_path:
                                        creds["path"] = new_path
                                    token = encrypt_credentials(creds, settings.master_key)
                                    db.update_account(acc_id, credentials=token)
                                    st.success("Credentials updated!")
                            else:
                                if not new_api_key or not new_api_secret:
                                    st.error("API Key and Secret are required")
                                else:
                                    creds = {
                                        "exchange": new_exchange or "binance",
                                        "api_key": new_api_key,
                                        "api_secret": new_api_secret,
                                    }
                                    if new_api_pass:
                                        creds["password"] = new_api_pass
                                    token = encrypt_credentials(creds, settings.master_key)
                                    db.update_account(acc_id, credentials=token)
                                    st.success("Credentials updated!")

            with tab_danger:
                st.error("⚠️ This action is irreversible!")
                col_del, _ = st.columns([1, 3])
                with col_del:
                    if st.button(f"🗑️ Delete Account", key=f"delete_{acc_id}",
                                  type="primary"):
                        db.delete_account(acc_id)
                        st.success(f"Account '{account['name']}' deleted")
                        st.rerun()

            # -------------------------------------------------------
            # Test Connection
            # -------------------------------------------------------
            st.divider()
            if st.button("🔌 Test Connection", key=f"test_conn_{acc_id}"):
                with st.spinner("Connecting... (this may take a few seconds)"):
                    try:
                        from bot_loop import create_bridge
                        bridge = create_bridge(account, settings.master_key)
                        connected = bridge.connect()
                        if connected:
                            bal = bridge.get_balance()
                            st.success(
                                f"✅ Connected! Balance: {bal.get('balance', 'N/A')} "
                                f"{bal.get('currency', '')}"
                            )
                            bridge.disconnect()
                        else:
                            # Try to get the actual MT5 error
                            error_msg = "Unknown error"
                            try:
                                import MetaTrader5 as mt5
                                error_msg = str(mt5.last_error())
                            except Exception:
                                pass
                            st.error(
                                f"❌ Connection failed — {error_msg}\n\n"
                                "Check: MT5 terminal is running, credentials are correct, "
                                "and the server name matches what's shown in MT5's "
                                "File > Open an Account."
                            )
                    except Exception as e:
                        st.error(f"❌ Connection error: {e}")
