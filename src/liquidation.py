"""Compatibility helper for callers that only need the dynamic OI snapshot."""
from __future__ import annotations

import httpx

from src.hyperliquid import fetch_market_snapshots


async def fetch_oi_snapshot(client: httpx.AsyncClient, symbols: list[str] | None = None) -> dict[str, dict]:
    """Return USD-denominated OI keyed by dynamic DEX-qualified market key."""
    markets = await fetch_market_snapshots(client)
    requested = {symbol.upper() for symbol in symbols} if symbols else None
    return {
        key: {"oi": market["oi_usd"], "markPx": market["price"], "dayNtlVlm": market["day_volume_usd"]}
        for key, market in markets.items()
        if not requested or market["symbol"].upper() in requested or market["name"].upper() in requested
    }
