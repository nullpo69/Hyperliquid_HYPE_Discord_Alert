"""
Liquidation proxy via OI drop.

Hyperliquidはグローバル清算のRESTを提供しないため、Actionsの5分pollで
取得可能な metaAndAssetCtxs.openInterest のドロップを清算推定として監視する。
OIはUSD建て想定 (openInterest * markPx ではなくAPIの openInterest自体がUSD)。
急落 = 強制決済によるポジション解消。

- 5m: 直前比 OIドロップ額 / ドロップ率
- 15m: 3回前比
WS常駐時は tradesの liquidationフラグを併用できるが、ActionsではOI方式が最も安定。
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from src.config import HL_API_URL, SYMBOL_TO_HL, SYMBOLS

log = logging.getLogger(__name__)


async def fetch_oi_snapshot(
    client: httpx.AsyncClient,
    symbols: list[str] | None = None,
) -> dict[str, dict]:
    """
    Returns: {display_symbol: {"oi": float, "markPx": float, "funding": str}}
    OIは APIの openInterest (文字列) をfloat化。欠損はスキップ。
    """
    if symbols is None:
        symbols = SYMBOLS

    # Group by dex like hyperliquid.fetch_all_prices
    dex_to_symbols: dict[str, list[str]] = {}
    for sym in symbols:
        if sym not in SYMBOL_TO_HL:
            continue
        dex, _ = SYMBOL_TO_HL[sym]
        dex_to_symbols.setdefault(dex, []).append(sym)

    dexes = list(dex_to_symbols.keys())

    async def fetch_dex(dex: str):
        payload: dict = {"type": "metaAndAssetCtxs"}
        if dex:
            payload["dex"] = dex
        resp = await client.post(HL_API_URL, json=payload, timeout=10)
        resp.raise_for_status()
        meta, ctxs = resp.json()
        # name -> ctx map
        m = {}
        for u, c in zip(meta.get("universe", []), ctxs):
            name = u.get("name")
            if name:
                m[name] = c
        return dex, m

    results = await asyncio.gather(*[fetch_dex(d) for d in dexes], return_exceptions=True)

    dex_to_map: dict[str, dict] = {}
    for r in results:
        if isinstance(r, Exception):
            log.warning(f"fetch_oi dex failed: {r}")
            continue
        dex, mp = r
        dex_to_map[dex] = mp

    out: dict[str, dict] = {}
    for sym in symbols:
        if sym not in SYMBOL_TO_HL:
            continue
        dex, hl_name = SYMBOL_TO_HL[sym]
        mp = dex_to_map.get(dex)
        if not mp:
            log.warning(f"{sym}: dex {dex} map missing")
            continue
        ctx = mp.get(hl_name)
        if not ctx:
            log.warning(f"{sym} ({hl_name}) not found in metaAndAssetCtxs dex={dex}")
            continue
        try:
            oi = float(ctx.get("openInterest", "0"))
            mark = float(ctx.get("markPx", "0") or ctx.get("oraclePx", "0") or 0)
            funding = ctx.get("funding", "")
            out[sym] = {"oi": oi, "markPx": mark, "funding": funding}
        except Exception as e:
            log.warning(f"{sym} parse OI failed: {e}")
            continue

    return out
