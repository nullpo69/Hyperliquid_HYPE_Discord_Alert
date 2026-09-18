"""Market-cap enrichment for trade.xyz HIP-3 equity perpetuals."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from src.config import HIP3_MARKET_CAP_CACHE_SECONDS, NASDAQ_QUOTE_SUMMARY_URL

log = logging.getLogger(__name__)

# These trade.xyz tickers represent indices, ETFs, commodities, or FX. They do
# not have a company's market cap; a same-named listed company would be wrong.
NON_EQUITY_XYZ_SYMBOLS = frozenset({
    "ALUMINIUM", "BRENTOIL", "CBRS", "CL", "COPPER", "CORN", "DRAM", "DXY",
    "EUR", "EWJ", "EWY", "EWZ", "EWT", "GBP", "GOLD", "H100", "IBOV", "JP225",
    "JPY", "KR200", "KRW", "MAGS", "NATGAS", "NIFTY", "PALLADIUM", "PLATINUM",
    "SILVER", "SMH", "SOXL", "SP500", "SPCX", "TLT", "TTF", "URANIUM", "URNM",
    "VIX", "VOL", "WHEAT", "XBI", "XLE", "XYZ100",
})


def _cached_value(cache: dict[str, dict[str, Any]], key: str, now_ts: float) -> tuple[bool, float | None]:
    value = cache.get(key)
    if not isinstance(value, dict) or now_ts - value.get("fetched_at", 0) >= HIP3_MARKET_CAP_CACHE_SECONDS:
        return False, None
    market_cap = value.get("market_cap_usd")
    return True, float(market_cap) if isinstance(market_cap, (int, float)) else None


def _parse_market_cap(payload: object) -> float | None:
    try:
        value = payload["data"]["summaryData"]["MarketCap"]["value"]
        return float(str(value).replace(",", ""))
    except (KeyError, TypeError, ValueError):
        return None


async def add_hip3_market_caps(
    client: httpx.AsyncClient,
    markets: dict[str, dict],
    cache: dict[str, dict[str, Any]],
    now_ts: float,
) -> None:
    """Override trade.xyz priorities with public-equity market caps."""
    unresolved: list[tuple[str, dict, str]] = []
    for key, market in markets.items():
        if market["dex"] != "xyz":
            continue
        ticker = market["name"].removeprefix("xyz:").upper()
        is_cached, market_cap = _cached_value(cache, key, now_ts)
        if is_cached:
            market["market_cap_usd"] = market_cap
        elif ticker in NON_EQUITY_XYZ_SYMBOLS:
            market["market_cap_usd"] = None
            cache[key] = {"market_cap_usd": None, "fetched_at": now_ts}
        else:
            unresolved.append((key, market, ticker))

    semaphore = asyncio.Semaphore(8)

    async def fetch_one(key: str, market: dict, ticker: str) -> None:
        try:
            async with semaphore:
                response = await client.get(
                    NASDAQ_QUOTE_SUMMARY_URL.format(symbol=ticker),
                    headers={"Accept": "application/json", "User-Agent": "Hyperliquid-HYPE-Discord-Alert/1.0"},
                    timeout=15,
                )
                response.raise_for_status()
            market_cap = _parse_market_cap(response.json())
        except (httpx.HTTPError, ValueError) as error:
            log.warning("Nasdaq market-cap lookup failed for xyz:%s: %s", ticker, error)
            market_cap = None
        market["market_cap_usd"] = market_cap
        cache[key] = {"market_cap_usd": market_cap, "fetched_at": now_ts}

    await asyncio.gather(*(fetch_one(key, market, ticker) for key, market, ticker in unresolved))
