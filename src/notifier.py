import datetime
import httpx

from src.detector import Alert

JST = datetime.timezone(datetime.timedelta(hours=9))


def build_embed(alert: Alert) -> dict:
    is_up = alert.direction == "up"
    # liquidationは常に down だが色は同じく赤
    is_liq = getattr(alert, "kind", "price") == "liquidation"
    emoji = "💥" if is_liq else ("🚀" if is_up else "📉")
    color = 0xFF4500 if (is_liq or not is_up) else 0x00FF7F
    pct = alert.change * 100
    sign = "+" if pct > 0 else ""

    window_map = {
        "5m": "5分",
        "15m": "15分",
        "prevDay": "前日比",
        "liq5m": "清算5分",
        "liq15m": "清算15分",
    }
    window_label = window_map.get(alert.window, alert.window)
    symbol = getattr(alert, "symbol", "HYPE")

    now_jst = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")

    if is_liq:
        drop_usd = getattr(alert, "oi_drop_usd", 0) or 0
        drop_pct = (getattr(alert, "oi_drop_pct", 0) or 0) * 100
        title = f"{emoji} {symbol} 清算急増 -{drop_pct:.2f}% ({window_label})"
        description = (
            f"**OI現在:** `${alert.current_price:,.0f}`\n"
            f"**{window_label}前:** `${alert.past_price:,.0f}`\n"
            f"**OIドロップ:** `-${drop_usd:,.0f}` (`-{drop_pct:.2f}%`)\n"
        )
        fields = [
            {"name": "Symbol", "value": symbol, "inline": True},
            {"name": "Window", "value": window_label, "inline": True},
            {"name": "Drop", "value": f"-${drop_usd:,.0f}", "inline": True},
        ]
        footer = f"Hyperliquid {symbol} Liquidation • {now_jst}"
    else:
        title = f"{emoji} {symbol}急{'騰' if is_up else '落'} {sign}{pct:.2f}% ({window_label})"
        description = (
            f"**現在価格:** `${alert.current_price:,.2f}`\n"
            f"**{window_label}前:** `${alert.past_price:,.2f}`\n"
            f"**変化率:** `{sign}{pct:.2f}%`\n"
        )
        fields = [
            {"name": "Symbol", "value": symbol, "inline": True},
            {"name": "Window", "value": window_label, "inline": True},
            {"name": "Direction", "value": alert.direction, "inline": True},
        ]
        footer = f"Hyperliquid {symbol} • {now_jst}"

    embed = {
        "title": title,
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {"text": footer},
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    return embed


async def send_webhook(webhook_url: str, alert: Alert) -> None:
    if not webhook_url or not webhook_url.startswith("https://"):
        raise ValueError("DISCORD_WEBHOOK_URL is not set or invalid")

    embed = build_embed(alert)
    symbol = getattr(alert, "symbol", "HYPE")
    kind = getattr(alert, "kind", "price")
    username = f"{symbol} {'Liq' if kind=='liquidation' else 'Alert'}"

    payload = {
        "username": username,
        "avatar_url": "https://hyperliquid.xyz/favicon.ico",
        "embeds": [embed],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(webhook_url, json=payload, timeout=10)
        # Handle Discord 429
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "5"))
            import asyncio

            await asyncio.sleep(retry_after)
            resp = await client.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
