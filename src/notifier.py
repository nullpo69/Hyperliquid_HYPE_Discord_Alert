import asyncio
import datetime

import httpx

from src.config import MAX_WEBHOOK_RETRIES
from src.detector import Alert

JST = datetime.timezone(datetime.timedelta(hours=9))


def _severity_emojis(value: float, thresholds: tuple[float, ...], emoji: str = "💥") -> str:
    """Return more emojis as a drop moves through the configured severity tiers."""
    level = sum(value >= threshold for threshold in thresholds)
    return emoji * max(1, min(level, len(thresholds)))


def _liquidation_emojis(drop_usd: float, drop_pct: float) -> tuple[str, str]:
    """Build independent visual severity indicators for USD and percentage drops."""
    amount = _severity_emojis(
        drop_usd,
        (50_000, 150_000, 300_000, 500_000, 1_000_000),
    )
    percentage = _severity_emojis(
        drop_pct,
        (0.04, 0.07, 0.10, 0.15, 0.25),
    )
    return amount, percentage


def build_embed(alert: Alert) -> dict:
    is_up = alert.direction == "up"
    is_liq = alert.kind == "liquidation"
    emoji = "💥" if is_liq else ("🚀" if is_up else "📉")
    color = 0xFF4500 if (is_liq or not is_up) else 0x00FF7F
    window_label = {"5m": "5分", "15m": "15分", "prevDay": "前日比", "liq5m": "清算5分", "liq15m": "清算15分"}.get(alert.window, alert.window)
    now_jst = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    if is_liq:
        drop = alert.oi_drop_usd or 0
        drop_pct = (alert.oi_drop_pct or 0) * 100
        amount_emojis, percentage_emojis = _liquidation_emojis(drop, drop_pct / 100)
        title = f"{percentage_emojis} {alert.symbol} 清算急増 -{drop_pct:.2f}% ({window_label})"
        description = (
            f"**OI現在:** `${alert.current_price:,.0f}`\n"
            f"**OIドロップ額:** `-${drop:,.0f}` {amount_emojis}\n"
            f"**OIドロップ率:** `-{drop_pct:.2f}%` {percentage_emojis}"
        )
        footer = f"Hyperliquid {alert.symbol} Liquidation • {now_jst}"
    else:
        pct = alert.change * 100
        sign = "+" if pct > 0 else ""
        title = f"{emoji} {alert.symbol}急{'騰' if is_up else '落'} {sign}{pct:.2f}% ({window_label})"
        description = f"**現在価格:** `${alert.current_price:,.4g}`\n**{window_label}前:** `${alert.past_price:,.4g}`\n**変化率:** `{sign}{pct:.2f}%`"
        footer = f"Hyperliquid {alert.symbol} • {now_jst}"
    return {"title": title, "description": description, "color": color, "footer": {"text": footer}, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}


async def send_webhook_batches(webhook_url: str, alerts: list[Alert], suppressed_count: int = 0) -> None:
    """Post alert embeds in groups of ten and honor Discord's dynamic 429 response."""
    if not webhook_url.startswith("https://"):
        raise ValueError("DISCORD_WEBHOOK_URL is not set or invalid")
    chunks = [alerts[index:index + 10] for index in range(0, len(alerts), 10)]
    async with httpx.AsyncClient() as client:
        for index, chunk in enumerate(chunks):
            suffix = f"（上限により {suppressed_count} 件は省略）" if index == 0 and suppressed_count else ""
            payload = {
                "username": "Hyperliquid Alert",
                "avatar_url": "https://hyperliquid.xyz/favicon.ico",
                "content": f"市場アラート {len(alerts)} 件 {suffix}",
                "embeds": [build_embed(alert) for alert in chunk],
                "allowed_mentions": {"parse": []},
            }
            for _ in range(MAX_WEBHOOK_RETRIES):
                response = await client.post(webhook_url, json=payload, timeout=15)
                if response.status_code != 429:
                    response.raise_for_status()
                    reset_after = response.headers.get("X-RateLimit-Reset-After")
                    if response.headers.get("X-RateLimit-Remaining") == "0" and reset_after:
                        await asyncio.sleep(float(reset_after))
                    break
                try:
                    retry_after = float(response.json().get("retry_after", response.headers.get("Retry-After", 1)))
                except (TypeError, ValueError):
                    retry_after = 1
                await asyncio.sleep(retry_after)
            else:
                raise RuntimeError("Discord webhook remained rate limited after retries")
