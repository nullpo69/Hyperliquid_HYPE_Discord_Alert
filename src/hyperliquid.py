import asyncio
import httpx
from src.config import HL_API_URL, SYMBOL_TO_HL, SYMBOLS


async def fetch_all_prices(
    client: httpx.AsyncClient,
    symbols: list[str] | None = None,
) -> dict[str, tuple[float, float | None]]:
    """
    Fetch mid price and prevDayPx for multiple symbols.
    Returns: {display_symbol: (price, prev_day_price)}
    Internally batches into dex-grouped calls (allMids + metaAndAssetCtxs per dex).
    """
    if symbols is None:
        symbols = SYMBOLS

    # Group by dex
    dex_to_hl_names: dict[str, list[tuple[str, str]]] = {}  # dex -> [(display, hl_name)]
    for sym in symbols:
        if sym not in SYMBOL_TO_HL:
            raise ValueError(f"Unknown symbol '{sym}' — no mapping in SYMBOL_TO_HL")
        dex, hl_name = SYMBOL_TO_HL[sym]
        dex_to_hl_names.setdefault(dex, []).append((sym, hl_name))

    dexes = list(dex_to_hl_names.keys())

    # Prepare concurrent fetches: allMids + metaAndAssetCtxs per dex
    async def fetch_dex(dex: str):
        # allMids
        payload_mids: dict = {"type": "allMids"}
        if dex:
            payload_mids["dex"] = dex
        resp = await client.post(HL_API_URL, json=payload_mids, timeout=10)
        resp.raise_for_status()
        mids: dict = resp.json()

        # prevDayPx via metaAndAssetCtxs (best effort)
        prev_map: dict[str, float | None] = {}
        try:
            payload_meta: dict = {"type": "metaAndAssetCtxs"}
            if dex:
                payload_meta["dex"] = dex
            resp2 = await client.post(HL_API_URL, json=payload_meta, timeout=10)
            resp2.raise_for_status()
            meta, ctxs = resp2.json()
            universe = meta.get("universe", [])
            for u, c in zip(universe, ctxs):
                name = u.get("name")
                if name:
                    try:
                        v = c.get("prevDayPx")
                        prev_map[name] = float(v) if v else None
                    except (TypeError, ValueError):
                        prev_map[name] = None
        except Exception:
            pass
        return mids, prev_map

    # Run dex fetches concurrently — isolate failures per dex
    dex_to_mids: dict[str, dict] = {}
    dex_to_prev: dict[str, dict] = {}

    async def safe_fetch_dex(dex: str):
        try:
            mids, prev_map = await fetch_dex(dex)
            return dex, mids, prev_map, None
        except Exception as e:
            return dex, {}, {}, e

    results = await asyncio.gather(*[safe_fetch_dex(d) for d in dexes])
    for dex, mids, prev_map, err in results:
        if err is not None:
            import logging
            logging.getLogger(__name__).warning(f"Failed to fetch dex '{dex}': {err}")
            continue
        dex_to_mids[dex] = mids
        dex_to_prev[dex] = prev_map

    # Build output per requested symbol — skip missing with warning instead of crashing all
    out: dict[str, tuple[float, float | None]] = {}
    for sym in symbols:
        dex, hl_name = SYMBOL_TO_HL[sym]
        mids = dex_to_mids.get(dex)
        if mids is None:
            import logging
            logging.getLogger(__name__).warning(f"{sym} ({hl_name}) skipped: dex '{dex}' fetch failed")
            continue
        prev_map = dex_to_prev.get(dex, {})
        price_str = mids.get(hl_name)
        if price_str is None:
            import logging
            logging.getLogger(__name__).warning(f"{sym} ({hl_name}) not found in allMids (dex='{dex}'), skipping")
            continue
        try:
            price = float(price_str)
        except (TypeError, ValueError):
            import logging
            logging.getLogger(__name__).warning(f"{sym} ({hl_name}) invalid price '{price_str}', skipping")
            continue
        prev_day = prev_map.get(hl_name)
        out[sym] = (price, prev_day)

    return out


async def fetch_hype_price(client: httpx.AsyncClient) -> tuple[float, float | None]:
    """
    Fetch HYPE mid price. Kept for backward compatibility.
    Returns: (price, prev_day_price)
    """
    result = await fetch_all_prices(client, symbols=["HYPE"])
    return result["HYPE"]


def fetch_hype_price_sync() -> tuple[float, float | None]:
    """Sync wrapper for tests / simple usage."""
    import httpx as _httpx

    async def _run():
        async with _httpx.AsyncClient() as c:
            return await fetch_hype_price(c)

    import asyncio

    return asyncio.run(_run())


async def fetch_all_prices_sync_wrapper(symbols: list[str] | None = None) -> dict[str, tuple[float, float | None]]:
    """Sync wrapper for fetch_all_prices."""
    import httpx as _httpx

    async def _run():
        async with _httpx.AsyncClient() as c:
            return await fetch_all_prices(c, symbols=symbols)

    import asyncio

    return asyncio.run(_run())
