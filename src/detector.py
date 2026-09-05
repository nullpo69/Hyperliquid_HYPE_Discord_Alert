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
                    Alert("5m", change, past["price"], current_price, "up" if change > 0 else "down", symbol)
                )

    # 15m check: need 3 entries ago
    if len(history) >= 3:
        past = history[-3]
        if now_ts - past["t"] >= 780:  # 13 min tolerance
            change = (current_price - past["price"]) / past["price"]
            if abs(change) >= thresholds["15m"]:
                candidates.append(
                    Alert("15m", change, past["price"], current_price, "up" if change > 0 else "down", symbol)
                )

    # prevDay check
    if prev_day_price is not None and prev_day_price > 0:
        change = (current_price - prev_day_price) / prev_day_price
        if abs(change) >= thresholds["prevDay"]:
            candidates.append(
                Alert("prevDay", change, prev_day_price, current_price, "up" if change > 0 else "down", symbol)
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


def detect_liquidation(
    oi_history: list[dict],
    current_oi: float,
    now_ts: float,
    cooldown: int,
    last_alert: dict | None,
    symbol: str,
    thresh_single_usd: float,
    thresh_5m_usd: float,
    thresh_15m_usd: float,
    drop_pct_5m: float,
    drop_pct_15m: float,
) -> Alert | None:
    """
    OIドロップを清算推定として検知。
    oi_history: list of {"t": float, "oi": float}  (past only, oldest first)
    発火条件 (OR):
      - 5m OIドロップ額 >= thresh_5m_usd または ドロップ率 >= drop_pct_5m
      - 15m 同上 (3回前)
    単発 thresh_single_usd は 5mドロップ額がそれを超えた場合にwindow=liqSingleとしても扱うが、
    現行は5mと同じ判定に統合（単発は5mの厳しい方）。
    価格と異なり清算は常に down方向のみ。クールダウンは liquidation同士で判定。
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
                if drop_usd >= thresh_5m_usd or drop_pct >= drop_pct_5m:
                    # single閾値も参考に: 5mドロップがsingle超えでなければ抑制（誤検知防止）
                    # ただし thresh_single_usd が 5mより小さい場合はsingleで十分なのでORで既に発火
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
                        )
                    )
                elif drop_usd >= thresh_single_usd and drop_usd >= thresh_single_usd:
                    # フォールバック: single閾値のみで発火したい場合（5m閾値が高すぎる銘柄）
                    # ただし上記で既に OR なのでここは実質同じ。念のため単独判定も残す
                    pass

            # 単発的ドロップが大きくても5m閾値未満でもsingleで拾う
            if past_oi > 0 and current_oi < past_oi:
                drop_usd = past_oi - current_oi
                drop_pct = drop_usd / past_oi
                # single閾値が5mより小さい場合、singleだけで発火させる
                if thresh_single_usd < thresh_5m_usd and drop_usd >= thresh_single_usd and drop_usd < thresh_5m_usd and drop_pct < drop_pct_5m:
                    # まだ候補が無ければsingleとして追加
                    if not candidates:
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
                if drop_usd >= thresh_15m_usd or drop_pct >= drop_pct_15m:
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
                        )
                    )

    if not candidates:
        return None

    # 最大ドロップ額で選択
    candidates.sort(key=lambda a: (a.oi_drop_usd or 0), reverse=True)
    best = candidates[0]

    # クールダウン: liquidationは downのみなので same direction = 常に抑制対象
    # ただし priceとkindが異なる場合は別枠にしたいので last_alert.kind も見る
    if last_alert is not None:
        last_t = last_alert.get("time", 0)
        last_kind = last_alert.get("kind", "price")
        last_dir = last_alert.get("direction")
        # 同じkindの同じ方向のみクールダウン
        if last_kind == "liquidation" and last_dir == best.direction and now_ts - last_t < cooldown:
            return None

    return best
