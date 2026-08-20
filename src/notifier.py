import datetime
import httpx

from src.detector import Alert

JST = datetime.timezone(datetime.timedelta(hours=9))


def build_embed(alert: Alert) -> dict:
    is_up = alert.direction == "up"
    emoji = "🚀" if is_up else "📉"
    color = 0x00FF7F if is_up else 0xFF4500  # green / red
    pct = alert.change * 100
    sign = "+" if pct > 0 else ""

    window_label = {"5m": "5分", "15m": "15分", "prevDay": "前日比"}[alert.window]

    title = f"{emoji} HYPE急{'騰' if is_up else '落'} {sign}{pct:.2f}% ({window_label})"

    now_jst = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")

    description = (
        f"**現在価格:** `${alert.current_price:,.2f}`\n"
        f"**{window_label}前:** `${alert.past_price:,.2f}`\n"
        f"**変化率:** `{sign}{pct:.2f}%`\n"
    )

    embed = {
        "title": title,
        "description": description,
        "color": color,
        "fields": [
            {"name": "Window", "value": window_label, "inline": True},
            {"name": "Direction", "value": alert.direction, "inline": True},
            {"name": "Threshold", "value": f"{window_label} 閾値超過", "inline": True},
        ],
        "footer": {"text": f"Hyperliquid HYPE • {now_jst}"},
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    return embed


async def send_webhook(webhook_url: str, alert: Alert) -> None:
    if not webhook_url or not webhook_url.startswith("https://"):
        raise ValueError("DISCORD_WEBHOOK_URL is not set or invalid")

    embed = build_embed(alert)

    payload = {
        "username": "HYPE Alert",
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
