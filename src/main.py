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
)
from src.detector import detect
from src.hyperliquid import fetch_hype_price
from src.notifier import send_webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"history": [], "last_alert": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Validate shape
        if "history" not in data:
            data["history"] = []
        if "last_alert" not in data:
            data["last_alert"] = None
        return data
    except Exception as e:
        log.warning(f"Failed to load state: {e}, resetting")
        return {"history": [], "last_alert": None}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep history trimmed to last 4 entries (20 min)
    history = state.get("history", [])
    if len(history) > 4:
        history = history[-4:]
        state["history"] = history
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


async def run_once() -> bool:
    """Returns True if alert sent."""
    thresholds = {"5m": THRESHOLD_5M, "15m": THRESHOLD_15M, "prevDay": THRESHOLD_PREVDAY}
    state = load_state(STATE_PATH)
    history: list[dict] = state.get("history", [])
    last_alert = state.get("last_alert")

    now_ts = time.time()

    # Fetch price
    async with httpx.AsyncClient() as client:
        price, prev_day = await fetch_hype_price(client)

    log.info(f"HYPE price={price:.4f} prevDay={prev_day} history_len={len(history)}")

    alert = detect(
        history=history,
        current_price=price,
        prev_day_price=prev_day,
        thresholds=thresholds,
        last_alert=last_alert,
        now_ts=now_ts,
        cooldown=COOLDOWN_SECONDS,
    )

    # Always append to history
    history.append({"t": now_ts, "price": price})
    if len(history) > 4:
        history = history[-4:]

    if alert:
        log.info(f"ALERT {alert.window} {alert.change*100:+.2f}% {alert.past_price}->{alert.current_price}")
        if DISCORD_WEBHOOK_URL:
            try:
                await send_webhook(DISCORD_WEBHOOK_URL, alert)
                log.info("Webhook sent")
            except Exception as e:
                log.error(f"Webhook failed: {e}")
                # Still update state to avoid spam, but don't set last_alert?
                # Save last_alert only on success to retry next run
                state["history"] = history
                save_state(STATE_PATH, state)
                raise
        else:
            log.warning("DISCORD_WEBHOOK_URL not set, skipping webhook")

        state["history"] = history
        state["last_alert"] = {
            "time": now_ts,
            "direction": alert.direction,
            "change": alert.change,
            "window": alert.window,
            "price": price,
        }
        save_state(STATE_PATH, state)
        return True
    else:
        log.info("No alert")
        state["history"] = history
        save_state(STATE_PATH, state)
        return False


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
