import json
import httpx
from src.config import HL_API_URL


async def fetch_hype_price(client: httpx.AsyncClient) -> tuple[float, float | None]:
    """
    Fetch HYPE mid price.
    Returns: (price, prev_day_price)
    - price from allMids["HYPE"]
    - prev_day_price from metaAndAssetCtxs perp HYPE ctx (best effort)
    """
    # 1) allMids - lightest
    resp = await client.post(
        HL_API_URL,
        json={"type": "allMids"},
        timeout=10,
    )
    resp.raise_for_status()
    mids: dict = resp.json()
    price_str = mids.get("HYPE")
    if price_str is None:
        raise ValueError("HYPE not found in allMids")
    price = float(price_str)

    # 2) prevDayPx via metaAndAssetCtxs (fallback allowed)
    prev_day: float | None = None
    try:
        resp2 = await client.post(
            HL_API_URL,
            json={"type": "metaAndAssetCtxs"},
            timeout=10,
        )
        resp2.raise_for_status()
        meta, ctxs = resp2.json()
        universe = meta.get("universe", [])
        for u, c in zip(universe, ctxs):
            if u.get("name") == "HYPE":
                prev_day = float(c.get("prevDayPx")) if c.get("prevDayPx") else None
                break
    except Exception:
        # non-fatal
        pass

    return price, prev_day


def fetch_hype_price_sync() -> tuple[float, float | None]:
    """Sync wrapper for tests / simple usage."""
    import httpx as _httpx

    async def _run():
        async with _httpx.AsyncClient() as c:
            return await fetch_hype_price(c)

    import asyncio

    return asyncio.run(_run())
