"""
webhook_server.py — Dormant FastAPI webhook endpoint.

DISABLED by default. Enable when you upgrade to TradingView Pro by
setting WEBHOOK_ENABLED=true in your .env file.

When enabled, this server receives TradingView alert webhooks and
triggers trade execution directly (bypassing the polling loop).

Run separately:
    uvicorn webhook_server:app --host 0.0.0.0 --port 8080
"""

import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

from config import load_global_settings
import database as db

logger = logging.getLogger(__name__)

# ===================================================================
# App setup
# ===================================================================
app = FastAPI(
    title="Trading Bot Webhook",
    description="Receives TradingView alerts and triggers trade execution",
    version="1.0.0",
)

settings = load_global_settings()


# ===================================================================
# Models
# ===================================================================
class WebhookPayload(BaseModel):
    """
    Expected TradingView alert payload.

    Configure alert message in TradingView as:
        {"action": "BUY", "pair": "EURUSD", "source": "tradingview"}
    """
    action: str           # BUY or SELL
    pair: str             # Trading pair / symbol
    source: str = "tradingview"
    account_id: int | None = None  # Optional: target specific account


# ===================================================================
# Endpoints
# ===================================================================
@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "webhook_enabled": settings.webhook_enabled}


@app.post("/webhook")
async def receive_webhook(
    payload: WebhookPayload,
    x_webhook_secret: str = Header(None, alias="X-Webhook-Secret"),
):
    """
    Receive a TradingView alert webhook.

    Headers:
        X-Webhook-Secret: Must match WEBHOOK_SECRET from .env

    Body:
        {"action": "BUY"|"SELL", "pair": "EURUSD", "account_id": 1}
    """
    if not settings.webhook_enabled:
        raise HTTPException(status_code=503, detail="Webhook server is disabled")

    # Validate secret
    if settings.webhook_secret and x_webhook_secret != settings.webhook_secret:
        logger.warning("Invalid webhook secret received")
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # Validate action
    action = payload.action.upper()
    if action not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    logger.info("Webhook received: %s %s (account: %s)",
                action, payload.pair, payload.account_id)

    # Find target account(s)
    accounts = db.get_accounts()
    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts configured")

    target_accounts = accounts
    if payload.account_id:
        target_accounts = [a for a in accounts if a["id"] == payload.account_id]
        if not target_accounts:
            raise HTTPException(status_code=404,
                                detail=f"Account {payload.account_id} not found")

    # Execute on matching accounts
    results = []
    for account in target_accounts:
        acc_id = account["id"]

        # Check kill switch
        if db.get_kill_switch(acc_id):
            results.append({
                "account_id": acc_id,
                "success": False,
                "message": "Kill switch is active",
            })
            continue

        # Create bridge and execute
        try:
            from bot_loop import create_bridge
            acc_settings = db.get_account_settings(acc_id)
            bridge = create_bridge(account, settings.master_key)

            if not bridge.connect():
                results.append({
                    "account_id": acc_id,
                    "success": False,
                    "message": "Failed to connect to broker",
                })
                continue

            lot_size = acc_settings.get("lot_size", 0.1) if acc_settings else 0.1
            result = bridge.place_order(
                pair=payload.pair,
                side=action,
                volume=lot_size,
            )

            if result.get("success"):
                db.log_trade(
                    account_id=acc_id,
                    pair=payload.pair,
                    side=action,
                    price=result.get("price", 0),
                    quantity=lot_size,
                    order_id=result.get("order_id"),
                    source="webhook",
                )

            bridge.disconnect()
            results.append({
                "account_id": acc_id,
                **result,
            })

        except Exception as e:
            logger.exception("Webhook execution error for account %d: %s", acc_id, e)
            results.append({
                "account_id": acc_id,
                "success": False,
                "message": str(e),
            })

    return {
        "status": "processed",
        "action": action,
        "pair": payload.pair,
        "results": results,
    }


# ===================================================================
# Startup / Runner
# ===================================================================
def run_webhook_server():
    """Start the webhook server (call from main bot if enabled)."""
    if not settings.webhook_enabled:
        logger.info("Webhook server is disabled (WEBHOOK_ENABLED=false)")
        return

    import uvicorn
    logger.info("Starting webhook server on port %d", settings.webhook_port)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.webhook_port,
        log_level="info",
    )


if __name__ == "__main__":
    run_webhook_server()
