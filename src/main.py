import asyncio
import json
import time
import logging
from pathlib import Path

import httpx

from src.config import (
    DISCORD_WEBHOOK_URL,
    STATE_PATH,
    THRESHOLD_5M,
    THRESHOLD_15M,
    THRESHOLD_PREVDAY,
    COOLDOWN_SECONDS,
    SYMBOLS,
)
from src.detector import detect
from src.hyperliquid import fetch_all_prices
from src.notifier import send_webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _empty_symbol_state() -> dict:
    return {"history": [], "last_alert": None}


def load_state(path: Path) -> dict:
    """Load state, handling migration from old single-symbol format."""
    if not path.exists():
        return {"symbols": {sym: _empty_symbol_state() for sym in SYMBOLS}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # New format: has "symbols" key
        if "symbols" in data and isinstance(data["symbols"], dict):
            # Ensure all current SYMBOLS exist, and shape is valid
            for sym in SYMBOLS:
                if sym not in data["symbols"]:
                    data["symbols"][sym] = _empty_symbol_state()
                else:
                    entry = data["symbols"][sym]
                    if "history" not in entry:
                        entry["history"] = []
                    if "last_alert" not in entry:
                        entry["last_alert"] = None
            return data
        # Old format: top-level history/last_alert (HYPE only)
        if "history" in data:
            log.info("Migrating legacy state (single HYPE) to multi-symbol format")
            migrated = {"symbols": {}}
            # Preserve HYPE's history
            migrated["symbols"]["HYPE"] = {
                "history": data.get("history", []),
                "last_alert": data.get("last_alert"),
            }
            for sym in SYMBOLS:
                if sym not in migrated["symbols"]:
                    migrated["symbols"][sym] = _empty_symbol_state()
            return migrated
        # Unknown shape
        log.warning(f"Unknown state shape: {list(data.keys())}, resetting")
        return {"symbols": {sym: _empty_symbol_state() for sym in SYMBOLS}}
    except Exception as e:
        log.warning(f"Failed to load state: {e}, resetting")
        return {"symbols": {sym: _empty_symbol_state() for sym in SYMBOLS}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep history trimmed to last 4 entries (20 min) per symbol
    symbols = state.get("symbols", {})
    for sym, entry in symbols.items():
        history = entry.get("history", [])
        if len(history) > 4:
            entry["history"] = history[-4:]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


async def run_once() -> bool:
    """Fetch all symbols, detect alerts, notify. Returns True if any alert sent."""
    thresholds = {"5m": THRESHOLD_5M, "15m": THRESHOLD_15M, "prevDay": THRESHOLD_PREVDAY}
    state = load_state(STATE_PATH)
    now_ts = time.time()

    # Fetch prices for all symbols
    async with httpx.AsyncClient() as client:
        prices = await fetch_all_prices(client, symbols=SYMBOLS)

    log.info(f"Fetched {len(prices)}/{len(SYMBOLS)} symbols: " + ", ".join(f"{k}={v[0]:.2f}" for k, v in prices.items()))

    alerts_to_send: list = []
    # Process each symbol independently
    for symbol in SYMBOLS:
        if symbol not in prices:
            log.warning(f"{symbol}: no price data, skipping")
            continue
        price, prev_day = prices[symbol]
        entry = state["symbols"].setdefault(symbol, _empty_symbol_state())
        history: list[dict] = entry.get("history", [])
        last_alert = entry.get("last_alert")

        log.info(f"{symbol} price={price:.4f} prevDay={prev_day} history_len={len(history)}")

        alert = detect(
            history=history,
            current_price=price,
            prev_day_price=prev_day,
            thresholds=thresholds,
            last_alert=last_alert,
            now_ts=now_ts,
            cooldown=COOLDOWN_SECONDS,
            symbol=symbol,
        )

        # Always append to history
        history.append({"t": now_ts, "price": price})
        if len(history) > 4:
            history = history[-4:]
        entry["history"] = history

        if alert:
            log.info(f"ALERT {symbol} {alert.window} {alert.change*100:+.2f}% {alert.past_price}->{alert.current_price}")
            alerts_to_send.append((symbol, alert, entry))

    # Send webhooks sequentially (preserve history even if webhook fails)
    any_sent = False
    for symbol, alert, entry in alerts_to_send:
        if DISCORD_WEBHOOK_URL:
            try:
                await send_webhook(DISCORD_WEBHOOK_URL, alert)
                log.info(f"Webhook sent for {symbol}")
            except Exception as e:
                log.error(f"Webhook failed for {symbol}: {e}")
                # Save state without updating last_alert so it can retry next run
                save_state(STATE_PATH, state)
                raise
        else:
            log.warning(f"DISCORD_WEBHOOK_URL not set, skipping webhook for {symbol}")

        # Update last_alert on success (or when no webhook configured, still record to respect cooldown)
        entry["last_alert"] = {
            "time": now_ts,
            "direction": alert.direction,
            "change": alert.change,
            "window": alert.window,
            "price": alert.current_price,
            "symbol": symbol,
        }
        any_sent = True

    if not alerts_to_send:
        log.info("No alerts")

    save_state(STATE_PATH, state)
    return any_sent


async def run_forever():
    """For local continuous mode."""
    from src.config import POLL_SECONDS

    while True:
        try:
            await run_once()
        except Exception as e:
            log.error(f"run_once error: {e}")
        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    import sys

    if "--loop" in sys.argv:
        asyncio.run(run_forever())
    else:
        asyncio.run(run_once())
