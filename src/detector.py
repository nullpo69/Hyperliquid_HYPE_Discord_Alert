from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Alert:
    window: str  # "5m" | "15m" | "prevDay" | "liq5m" | "liq15m"
    change: float  # e.g. 0.052 = +5.2%  (liquidationでは drop率, 負数)
    past_price: float
    current_price: float
    direction: str  # "up" | "down"
    symbol: str = "HYPE"  # display symbol, e.g. HYPE / NVDA / SKHYNIX
    kind: str = "price"  # "price" | "liquidation"
    # liquidation only
    oi_current: float | None = None
    oi_past: float | None = None
    oi_drop_usd: float | None = None  # pastOi - currentOi (>0 が清算推定)
    oi_drop_pct: float | None = None
    price_change_pct: float | None = None  # 清算判定期間中の価格変動率


@dataclass
class CombinedAlert:
    """A same-window price move and OI drop for one market."""

    price: Alert
    liquidation: Alert

    @property
    def symbol(self) -> str:
        return self.price.symbol

    @property
    def window(self) -> str:
        return self.price.window


def is_same_direction_cooldown(alert: Alert, last_alert: dict | None, now_ts: float, cooldown: int) -> bool:
    if last_alert is None:
        return False
    return now_ts - last_alert.get("time", 0) < cooldown and last_alert.get("direction") == alert.direction


def detect_price_candidates(
    history: list[dict],
    current_price: float,
    prev_day_price: float | None,
    thresholds: dict[str, float],
    now_ts: float,
    symbol: str = "HYPE",
) -> list[Alert]:
    """Return every price threshold crossed, without applying a cooldown."""
    candidates: list[Alert] = []

    if len(history) >= 1 and now_ts - history[-1]["t"] >= 240:
        past = history[-1]
        if past["price"] > 0:
            change = (current_price - past["price"]) / past["price"]
            if abs(change) >= thresholds["5m"]:
                candidates.append(Alert("5m", change, past["price"], current_price, "up" if change > 0 else "down", symbol))

    if len(history) >= 3 and now_ts - history[-3]["t"] >= 780:
        past = history[-3]
        if past["price"] > 0:
            change = (current_price - past["price"]) / past["price"]
            if abs(change) >= thresholds["15m"]:
                candidates.append(Alert("15m", change, past["price"], current_price, "up" if change > 0 else "down", symbol))

    if prev_day_price is not None and prev_day_price > 0:
        change = (current_price - prev_day_price) / prev_day_price
        if abs(change) >= thresholds["prevDay"]:
            candidates.append(Alert("prevDay", change, prev_day_price, current_price, "up" if change > 0 else "down", symbol))

    return candidates


def detect(
    history: list[dict],
    current_price: float,
    prev_day_price: float | None,
    thresholds: dict[str, float],
    last_alert: dict | None,
    now_ts: float,
    cooldown: int,
    symbol: str = "HYPE",
) -> Alert | None:
    """
    history: list of {"t": float, "price": float} sorted ascending (oldest first).
             Caller should have already appended current? No - history is past only.
    """
    candidates = detect_price_candidates(
        history,
        current_price,
        prev_day_price,
        thresholds,
        now_ts,
        symbol,
    )

    if not candidates:
        return None

    # Pick largest absolute change
    candidates.sort(key=lambda a: abs(a.change), reverse=True)
    best = candidates[0]

    # Cooldown check
    if is_same_direction_cooldown(best, last_alert, now_ts, cooldown):
        return None

    return best


def detect_liquidation_candidates(
    oi_history: list[dict],
    current_oi: float,
    current_market_price: float,
    now_ts: float,
    symbol: str,
    thresh_5m_usd: float,
    thresh_15m_usd: float,
    drop_pct_5m: float,
    drop_pct_15m: float,
) -> list[Alert]:
    """
    OIドロップを清算推定として検知。
    oi_history: list of {"t": float, "oi": float, "price": float}  (past only, oldest first)
    発火条件 (AND):
      - 5m OIドロップ額 >= thresh_5m_usd かつ ドロップ率 >= drop_pct_5m
      - 15m 同上 (3回前)
    価格と異なり清算は常に down方向のみ。クールダウンは呼び出し側で判定する。
    """
    candidates: list[Alert] = []

    # 5m OI drop
    if len(oi_history) >= 1:
        past = oi_history[-1]
        if now_ts - past["t"] >= 240:
            past_oi = past["oi"]
            if past_oi > 0 and current_oi < past_oi:
                drop_usd = past_oi - current_oi
                drop_pct = drop_usd / past_oi
                past_market_price = past.get("price")
                price_change_pct = (
                    (current_market_price - past_market_price) / past_market_price
                    if isinstance(past_market_price, (int, float)) and past_market_price > 0
                    else None
                )
                if drop_usd >= thresh_5m_usd and drop_pct >= drop_pct_5m:
                    candidates.append(
                        Alert(
                            window="liq5m",
                            change=-drop_pct,
                            past_price=past_oi,
                            current_price=current_oi,
                            direction="down",
                            symbol=symbol,
                            kind="liquidation",
                            oi_current=current_oi,
                            oi_past=past_oi,
                            oi_drop_usd=drop_usd,
                            oi_drop_pct=drop_pct,
                            price_change_pct=price_change_pct,
                        )
                    )
    # 15m OI drop
    if len(oi_history) >= 3:
        past = oi_history[-3]
        if now_ts - past["t"] >= 780:
            past_oi = past["oi"]
            if past_oi > 0 and current_oi < past_oi:
                drop_usd = past_oi - current_oi
                drop_pct = drop_usd / past_oi
                past_market_price = past.get("price")
                price_change_pct = (
                    (current_market_price - past_market_price) / past_market_price
                    if isinstance(past_market_price, (int, float)) and past_market_price > 0
                    else None
                )
                if drop_usd >= thresh_15m_usd and drop_pct >= drop_pct_15m:
                    candidates.append(
                        Alert(
                            window="liq15m",
                            change=-drop_pct,
                            past_price=past_oi,
                            current_price=current_oi,
                            direction="down",
                            symbol=symbol,
                            kind="liquidation",
                            oi_current=current_oi,
                            oi_past=past_oi,
                            oi_drop_usd=drop_usd,
                            oi_drop_pct=drop_pct,
                            price_change_pct=price_change_pct,
                        )
                    )

    return candidates


def detect_liquidation(
    oi_history: list[dict],
    current_oi: float,
    current_market_price: float,
    now_ts: float,
    cooldown: int,
    last_alert: dict | None,
    symbol: str,
    thresh_5m_usd: float,
    thresh_15m_usd: float,
    drop_pct_5m: float,
    drop_pct_15m: float,
) -> Alert | None:
    candidates = detect_liquidation_candidates(
        oi_history, current_oi, current_market_price, now_ts, symbol,
        thresh_5m_usd, thresh_15m_usd, drop_pct_5m, drop_pct_15m,
    )
    if not candidates:
        return None
    candidates.sort(key=lambda alert: (alert.oi_drop_usd or 0), reverse=True)
    best = candidates[0]
    if last_alert is not None and last_alert.get("kind", "price") == "liquidation":
        if is_same_direction_cooldown(best, last_alert, now_ts, cooldown):
            return None
    return best
