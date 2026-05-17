# README & DEVELOPER AGENT SOP: PINESCRIPT-TO-PYTHON TRADING BOT

This document serves as your strict operational blueprint, architectural guide, and code style specification for this project. Read and adhere to these guidelines during every step of development.

---

## 1. PROJECT OVERVIEW & CONSTRAINTS
You are building a **Self-Hosted Automated Trading Bot**. 
*   **CRITICAL CONSTRAINT:** The user is on a FREE TradingView tier. This system **MUST NOT** use webhooks, Flask/FastAPI servers, or external internet listeners.
*   **CORE MECHANISM:** The bot operates on a **Polling Loop**. It pulls OHLCV (candle) data from the exchange/broker API, calculates the technical indicators locally using Python libraries, and executes trades based on those local calculations.

---

## 2. REPOSITORY & FILE STRUCTURE
You must organize the project according to the following modular structure. Do not write monolithic code.

```text
├── config.py          # Environment variables, API Keys, Risk parameters
├── database.py        # SQLite setup and functions for logging trades
├── exchange_bridge.py # CCXT / MetaTrader5 integration and order execution
├── strategy.py        # Converted Pine Script logic (Pure Math/DataFrames)
├── bot_loop.py        # The main timed loop (Polling mechanism)
├── dashboard.py       # Streamlit Web GUI interface
└── requirements.txt   # Python dependencies
