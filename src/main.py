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
    TRIGGER_MODE,
    LIQ_ENABLED,
    LIQ_DROP_PCT_5M,
    LIQ_DROP_PCT_15M,
    liq_threshold_single,
    liq_threshold_5m,
    liq_threshold_15m,
)
from src.detector import detect, detect_liquidation
from src.hyperliquid import fetch_all_prices
from src.liquidation import fetch_oi_snapshot
from src.notifier import send_webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _empty_symbol_state() -> dict:
    # price history + oi history + last alerts per kind
    return {"history": [], "oi_history": [], "last_alert": None, "last_liq_alert": None}


def load_state(path: Path) -> dict:
    """Load state, handling migration from old single-symbol and price-only formats."""
    if not path.exists():
        return {"symbols": {sym: _empty_symbol_state() for sym in SYMBOLS}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # New format: has "symbols" key
        if "symbols" in data and isinstance(data["symbols"], dict):
            for sym in SYMBOLS:
                if sym not in data["symbols"]:
                    data["symbols"][sym] = _empty_symbol_state()
                else:
                    entry = data["symbols"][sym]
                    if "history" not in entry:
                        entry["history"] = []
                    if "oi_history" not in entry:
                        entry["oi_history"] = []
                    if "last_alert" not in entry:
                        entry["last_alert"] = None
                    if "last_liq_alert" not in entry:
                        entry["last_liq_alert"] = None
                    # migrate old last_alert kind-less to include kind
                    if entry["last_alert"] and "kind" not in entry["last_alert"]:
                        entry["last_alert"]["kind"] = "price"
            return data
        # Old format: top-level history/last_alert (HYPE only)
        if "history" in data:
            log.info("Migrating legacy state (single HYPE) to multi-symbol format")
            migrated = {"symbols": {}}
            migrated["symbols"]["HYPE"] = {
                "history": data.get("history", []),
                "oi_history": [],
                "last_alert": data.get("last_alert"),
                "last_liq_alert": None,
            }
            for sym in SYMBOLS:
                if sym not in migrated["symbols"]:
                    migrated["symbols"][sym] = _empty_symbol_state()
            return migrated
        log.warning(f"Unknown state shape: {list(data.keys())}, resetting")
        return {"symbols": {sym: _empty_symbol_state() for sym in SYMBOLS}}
    except Exception as e:
        log.warning(f"Failed to load state: {e}, resetting")
        return {"symbols": {sym: _empty_symbol_state() for sym in SYMBOLS}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    symbols = state.get("symbols", {})
    for sym, entry in symbols.items():
        hist = entry.get("history", [])
        if len(hist) > 4:
            entry["history"] = hist[-4:]
        oi_hist = entry.get("oi_history", [])
        if len(oi_hist) > 4:
            entry["oi_history"] = oi_hist[-4:]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


async def run_once() -> bool:
    """Fetch all symbols, detect price and liquidation alerts, notify. Returns True if any alert sent."""
    thresholds = {"5m": THRESHOLD_5M, "15m": THRESHOLD_15M, "prevDay": THRESHOLD_PREVDAY}
    state = load_state(STATE_PATH)
    now_ts = time.time()

    # Fetch prices and OI in parallel
    async with httpx.AsyncClient() as client:
        prices_task = fetch_all_prices(client, symbols=SYMBOLS)
        oi_task = fetch_oi_snapshot(client, symbols=SYMBOLS) if LIQ_ENABLED else asyncio.sleep(0, result={})
        prices, oi_snapshot = await asyncio.gather(prices_task, oi_task)

    log.info(f"Fetched {len(prices)}/{len(SYMBOLS)} prices: " + ", ".join(f"{k}={v[0]:.2f}" for k, v in prices.items()))
    if LIQ_ENABLED:
        log.info(f"OI snapshot: " + ", ".join(f"{k}={v['oi']:.0f}" for k, v in oi_snapshot.items()))

    alerts_to_send: list = []

    for symbol in SYMBOLS:
        entry = state["symbols"].setdefault(symbol, _empty_symbol_state())
        history: list[dict] = entry.get("history", [])
        oi_history: list[dict] = entry.get("oi_history", [])
        last_alert = entry.get("last_alert")
        last_liq = entry.get("last_liq_alert")

        # --- Price path ---
        if symbol in prices:
            price, prev_day = prices[symbol]
            log.info(f"{symbol} price={price:.4f} prevDay={prev_day} history_len={len(history)}")
            if TRIGGER_MODE in ("price", "both"):
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
                if alert:
                    alert.kind = "price"
                    log.info(f"ALERT price {symbol} {alert.window} {alert.change*100:+.2f}% {alert.past_price}->{alert.current_price}")
                    alerts_to_send.append((symbol, alert, entry, "price"))
            # Always append to price history (even if liquidation also triggers)
            history.append({"t": now_ts, "price": price})
            if len(history) > 4:
                history = history[-4:]
            entry["history"] = history
        else:
            log.warning(f"{symbol}: no price data, skipping price check")

        # --- Liquidation path (OI drop) ---
        if LIQ_ENABLED and symbol in oi_snapshot and TRIGGER_MODE in ("liquidation", "both"):
            oi = oi_snapshot[symbol]["oi"]
            # Append after detection so history is past only for detect
            liq_alert = detect_liquidation(
                oi_history=oi_history,
                current_oi=oi,
                now_ts=now_ts,
                cooldown=COOLDOWN_SECONDS,
                last_alert=last_liq,
                symbol=symbol,
                thresh_single_usd=liq_threshold_single(symbol),
                thresh_5m_usd=liq_threshold_5m(symbol),
                thresh_15m_usd=liq_threshold_15m(symbol),
                drop_pct_5m=LIQ_DROP_PCT_5M,
                drop_pct_15m=LIQ_DROP_PCT_15M,
            )
            if liq_alert:
                log.info(f"ALERT liquidation {symbol} {liq_alert.window} drop ${liq_alert.oi_drop_usd:,.0f} ({liq_alert.oi_drop_pct*100:.2f}%) {liq_alert.oi_past:.0f}->{liq_alert.oi_current:.0f}")
                alerts_to_send.append((symbol, liq_alert, entry, "liquidation"))
            # Append to oi_history
            oi_history.append({"t": now_ts, "oi": oi})
            if len(oi_history) > 4:
                oi_history = oi_history[-4:]
            entry["oi_history"] = oi_history
        elif LIQ_ENABLED and symbol not in oi_snapshot:
            log.warning(f"{symbol}: no OI data, skipping liquidation check")
        elif LIQ_ENABLED:
            # Still need to record oi_history even if trigger_mode is price only? No, only if liquidation enabled and mode includes it
            # But we already handled both. If mode==price, skip recording to save state.
            pass

        # If LIQ_ENABLED but mode==price, we still want oi_history for future if mode switches? Record anyway
        if LIQ_ENABLED and symbol in oi_snapshot and TRIGGER_MODE == "price":
            # still maintain oi_history silently
            oi = oi_snapshot[symbol]["oi"]
            # avoid double append if already appended above (both case handled)
            # price-only case: append now
            if not oi_history or oi_history[-1]["t"] != now_ts:
                oi_history.append({"t": now_ts, "oi": oi})
                if len(oi_history) > 4:
                    oi_history = oi_history[-4:]
                entry["oi_history"] = oi_history

    # Send webhooks sequentially
    any_sent = False
    for symbol, alert, entry, kind in alerts_to_send:
        if DISCORD_WEBHOOK_URL:
            try:
                await send_webhook(DISCORD_WEBHOOK_URL, alert)
                log.info(f"Webhook sent for {symbol} kind={kind}")
            except Exception as e:
                log.error(f"Webhook failed for {symbol} kind={kind}: {e}")
                save_state(STATE_PATH, state)
                raise
        else:
            log.warning(f"DISCORD_WEBHOOK_URL not set, skipping webhook for {symbol} kind={kind}")

        if kind == "liquidation":
            entry["last_liq_alert"] = {
                "time": now_ts,
                "direction": alert.direction,
                "kind": "liquidation",
                "window": alert.window,
                "oi_drop_usd": alert.oi_drop_usd,
                "oi_drop_pct": alert.oi_drop_pct,
            }
        else:
            entry["last_alert"] = {
                "time": now_ts,
                "direction": alert.direction,
                "kind": "price",
                "change": alert.change,
                "window": alert.window,
                "price": alert.current_price,
                "symbol": symbol,
            }
        any_sent = True

    if not alerts_to_send:
        log.info("No alerts (price+liquidation)")

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
