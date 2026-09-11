"""Dynamic Hyperliquid perpetual-market discovery and snapshots."""
from __future__ import annotations

import asyncio
import logging

import httpx

from src.config import HL_API_URL, MIN_DAY_VOLUME_USD, MIN_OPEN_INTEREST_USD, MONITORED_DEXES, SYMBOLS

log = logging.getLogger(__name__)


def market_key(dex: str, name: str) -> str:
    """A stable key; ticker names can overlap across HIP-3 DEXes."""
    return f"{dex or 'main'}:{name}"


def display_name(dex: str, name: str) -> str:
    ticker = name.removeprefix("xyz:")
    return ticker if not dex else f"{dex}/{ticker}"


async def fetch_market_snapshots(client: httpx.AsyncClient) -> dict[str, dict]:
    """Fetch every eligible perp from main and trade.xyz in four batched requests.

    `openInterest` is coin-denominated in the API, so it is converted to USD with
    `markPx`; this keeps the OI thresholds meaningful across markets.
    """
    async def fetch_dex(dex: str):
        base = {"dex": dex} if dex else {}
        mids_request = client.post(HL_API_URL, json={"type": "allMids", **base}, timeout=15)
        meta_request = client.post(HL_API_URL, json={"type": "metaAndAssetCtxs", **base}, timeout=15)
        mids_response, meta_response = await asyncio.gather(mids_request, meta_request)
        mids_response.raise_for_status()
        meta_response.raise_for_status()
        meta, contexts = meta_response.json()
        return dex, mids_response.json(), meta.get("universe", []), contexts

    results = await asyncio.gather(*(fetch_dex(dex) for dex in MONITORED_DEXES), return_exceptions=True)
    markets: dict[str, dict] = {}
    for result in results:
        if isinstance(result, Exception):
            log.warning("Market discovery failed: %s", result)
            continue
        dex, mids, universe, contexts = result
        for asset, context in zip(universe, contexts):
            name = asset.get("name")
            if not name:
                continue
            ticker = name.removeprefix("xyz:").upper()
            if SYMBOLS and ticker not in SYMBOLS and name.upper() not in SYMBOLS:
                continue
            try:
                price = float(mids.get(name) or context.get("markPx") or 0)
                open_interest = float(context.get("openInterest") or 0)
                day_volume = float(context.get("dayNtlVlm") or 0)
            except (TypeError, ValueError):
                continue
            oi_usd = open_interest * price
            if price <= 0 or oi_usd < MIN_OPEN_INTEREST_USD or day_volume < MIN_DAY_VOLUME_USD:
                continue
            key = market_key(dex, name)
            markets[key] = {
                "dex": dex,
                "name": name,
                "symbol": display_name(dex, name),
                "price": price,
                "prev_day_price": _float_or_none(context.get("prevDayPx")),
                "oi_usd": oi_usd,
                "day_volume_usd": day_volume,
            }
    return markets


def _float_or_none(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
