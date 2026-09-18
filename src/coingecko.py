"""CoinGecko market-cap lookup used to order Discord notifications."""
from __future__ import annotations

import logging

import httpx

from src.config import COINGECKO_API_KEY, COINGECKO_MARKETS_URL

log = logging.getLogger(__name__)


async def add_market_caps(client: httpx.AsyncClient, markets: dict[str, dict]) -> None:
    """Attach CoinGecko USD market caps where a perp ticker can be resolved.

    CoinGecko's ``include_tokens=top`` resolves duplicate ticker symbols to the
    largest market-cap asset, which is the least surprising choice for a
    ticker-only Hyperliquid market.  A lookup failure deliberately leaves the
    value as ``None`` so alerting itself is never blocked by this enrichment.
    """
    for market in markets.values():
        market["market_cap_usd"] = None

    symbols = sorted({market["name"].removeprefix("xyz:").lower() for market in markets.values()})
    if not symbols:
        return
    headers = {}
    if COINGECKO_API_KEY:
        header = "x-cg-pro-api-key" if "pro-api.coingecko.com" in COINGECKO_MARKETS_URL else "x-cg-demo-api-key"
        headers[header] = COINGECKO_API_KEY
    try:
        response = await client.get(
            COINGECKO_MARKETS_URL,
            headers=headers,
            params={
                "vs_currency": "usd",
                "symbols": ",".join(symbols),
                "include_tokens": "top",
                "sparkline": "false",
            },
            timeout=15,
        )
        response.raise_for_status()
        listings = response.json()
    except (httpx.HTTPError, ValueError) as error:
        log.warning("CoinGecko market-cap lookup failed; using volume fallback: %s", error)
        return

    if not isinstance(listings, list):
        log.warning("CoinGecko returned an unexpected market-cap response; using volume fallback")
        return
    caps_by_symbol: dict[str, float] = {}
    for listing in listings:
        if not isinstance(listing, dict):
            continue
        try:
            market_cap = float(listing["market_cap"])
        except (KeyError, TypeError, ValueError):
            continue
        if market_cap >= 0 and isinstance(listing.get("symbol"), str):
            caps_by_symbol[listing["symbol"].upper()] = market_cap
    for market in markets.values():
        market["market_cap_usd"] = caps_by_symbol.get(market["name"].removeprefix("xyz:").upper())
