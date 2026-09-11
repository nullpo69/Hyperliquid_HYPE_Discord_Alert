import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

from src.config import (COOLDOWN_SECONDS, DISCORD_WEBHOOK_URL, LIQ_15M_USD,
    LIQ_5M_USD, LIQ_DROP_PCT_15M, LIQ_DROP_PCT_5M, LIQ_ENABLED,
    LIQ_SINGLE_USD, MAX_ALERTS_PER_RUN, STATE_PATH, STATE_RETENTION_SECONDS,
    THRESHOLD_15M, THRESHOLD_5M, THRESHOLD_PREVDAY, TRIGGER_MODE)
from src.detector import Alert, detect, detect_liquidation
from src.hyperliquid import fetch_market_snapshots
from src.notifier import send_webhook_batches

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _empty_state() -> dict:
    return {"history": [], "oi_history": [], "last_alert": None, "last_liq_alert": None, "seen_at": 0}


def load_state(path: Path, now_ts: float) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError) as error:
        log.warning("Unable to load state: %s", error)
        data = {}
    entries = data.get("symbols", {}) if data.get("version") == 2 else {}
    if data and not entries:
        log.info("Resetting legacy state for dynamic DEX-qualified markets")
    cutoff = now_ts - STATE_RETENTION_SECONDS
    entries = {key: value for key, value in entries.items() if value.get("seen_at", 0) >= cutoff}
    return {"version": 2, "symbols": entries}


def save_state(path: Path, state: dict) -> None:
    for entry in state["symbols"].values():
        entry["history"] = entry.get("history", [])[-4:]
        entry["oi_history"] = entry.get("oi_history", [])[-4:]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _priority(item: tuple[str, Alert, dict, str]) -> tuple[float, float]:
    _, alert, _, kind = item
    return (1 if kind == "liquidation" else 0, (alert.oi_drop_usd or 0) if kind == "liquidation" else abs(alert.change))


async def run_once() -> bool:
    now_ts = time.time()
    state = load_state(STATE_PATH, now_ts)
    async with httpx.AsyncClient() as client:
        markets = await fetch_market_snapshots(client)
    log.info("Fetched %d eligible markets", len(markets))
    if not markets:
        log.warning("No market data returned; preserving state and skipping notifications")
        return False
    thresholds = {"5m": THRESHOLD_5M, "15m": THRESHOLD_15M, "prevDay": THRESHOLD_PREVDAY}
    candidates: list[tuple[str, Alert, dict, str]] = []
    for key, market in markets.items():
        entry = state["symbols"].setdefault(key, _empty_state())
        entry["seen_at"] = now_ts
        symbol = market["symbol"]
        if TRIGGER_MODE in ("price", "both"):
            alert = detect(entry["history"], market["price"], market["prev_day_price"], thresholds, entry["last_alert"], now_ts, COOLDOWN_SECONDS, symbol)
            if alert:
                candidates.append((key, alert, entry, "price"))
        entry["history"].append({"t": now_ts, "price": market["price"]})
        if LIQ_ENABLED:
            if TRIGGER_MODE in ("liquidation", "both"):
                alert = detect_liquidation(entry["oi_history"], market["oi_usd"], now_ts, COOLDOWN_SECONDS, entry["last_liq_alert"], symbol, LIQ_SINGLE_USD, LIQ_5M_USD, LIQ_15M_USD, LIQ_DROP_PCT_5M, LIQ_DROP_PCT_15M)
                if alert:
                    candidates.append((key, alert, entry, "liquidation"))
            entry["oi_history"].append({"t": now_ts, "oi": market["oi_usd"]})
    candidates.sort(key=_priority, reverse=True)
    chosen = candidates[:MAX_ALERTS_PER_RUN]
    suppressed = len(candidates) - len(chosen)
    if chosen and DISCORD_WEBHOOK_URL:
        await send_webhook_batches(DISCORD_WEBHOOK_URL, [alert for _, alert, _, _ in chosen], suppressed)
        for _, alert, entry, kind in chosen:
            record = {"time": now_ts, "direction": alert.direction, "kind": kind, "window": alert.window}
            if kind == "liquidation":
                entry["last_liq_alert"] = record
            else:
                entry["last_alert"] = record
        log.info("Sent %d alerts in %d webhook batch(es); suppressed %d", len(chosen), (len(chosen) + 9) // 10, suppressed)
    elif chosen:
        log.warning("DISCORD_WEBHOOK_URL not set; %d alerts not sent", len(chosen))
    else:
        log.info("No alerts")
    save_state(STATE_PATH, state)
    return bool(chosen and DISCORD_WEBHOOK_URL)


async def run_forever() -> None:
    from src.config import POLL_SECONDS
    while True:
        try:
            await run_once()
        except Exception:
            log.exception("run_once failed")
        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    import sys
    asyncio.run(run_forever() if "--loop" in sys.argv else run_once())
