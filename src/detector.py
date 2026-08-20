from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Alert:
    window: str  # "5m" | "15m" | "prevDay"
    change: float  # e.g. 0.052 = +5.2%
    past_price: float
    current_price: float
    direction: str  # "up" | "down"


def detect(
    history: list[dict],
    current_price: float,
    prev_day_price: float | None,
    thresholds: dict[str, float],
    last_alert: dict | None,
    now_ts: float,
    cooldown: int,
) -> Alert | None:
    """
    history: list of {"t": float, "price": float} sorted ascending (oldest first).
             Caller should have already appended current? No - history is past only.
    """
    candidates: list[Alert] = []

    # 5m check: need at least 1 past entry (5 min ago)
    if len(history) >= 1:
        past = history[-1]
        # Only use if timestamp is within 4-6 min window? For Actions cron 5m, allow any last entry
        # But ensure at least 4 min has passed to avoid false 5m on first run
        if now_ts - past["t"] >= 240:  # 4 min
            change = (current_price - past["price"]) / past["price"]
            if abs(change) >= thresholds["5m"]:
                candidates.append(
                    Alert("5m", change, past["price"], current_price, "up" if change > 0 else "down")
                )

    # 15m check: need 3 entries ago
    if len(history) >= 3:
        past = history[-3]
        if now_ts - past["t"] >= 780:  # 13 min tolerance
            change = (current_price - past["price"]) / past["price"]
            if abs(change) >= thresholds["15m"]:
                candidates.append(
                    Alert("15m", change, past["price"], current_price, "up" if change > 0 else "down")
                )

    # prevDay check
    if prev_day_price is not None and prev_day_price > 0:
        change = (current_price - prev_day_price) / prev_day_price
        if abs(change) >= thresholds["prevDay"]:
            candidates.append(
                Alert("prevDay", change, prev_day_price, current_price, "up" if change > 0 else "down")
            )

    if not candidates:
        return None

    # Pick largest absolute change
    candidates.sort(key=lambda a: abs(a.change), reverse=True)
    best = candidates[0]

    # Cooldown check
    if last_alert is not None:
        last_t = last_alert.get("time", 0)
        last_dir = last_alert.get("direction")
        # Same direction within cooldown -> suppress
        if now_ts - last_t < cooldown and last_dir == best.direction:
            return None
        # Also suppress if any alert within cooldown? No - allow opposite direction immediately
        # e.g. up then down should notify even within cooldown

    return best
