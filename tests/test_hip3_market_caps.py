import unittest

import httpx

from src.hip3_market_caps import add_hip3_market_caps


class Hip3MarketCapTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_nasdaq_for_equities_and_skips_non_equity_tickers(self):
        requested_symbols = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_symbols.append(request.url.path.split("/")[-2])
            return httpx.Response(200, json={
                "data": {"summaryData": {"MarketCap": {"value": "3,000,000,000,000"}}},
            })

        markets = {
            "xyz:TSLA": {"dex": "xyz", "name": "xyz:TSLA"},
            "xyz:GOLD": {"dex": "xyz", "name": "xyz:GOLD"},
        }
        cache = {}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await add_hip3_market_caps(client, markets, cache, 10_000)

        self.assertEqual(requested_symbols, ["TSLA"])
        self.assertEqual(markets["xyz:TSLA"]["market_cap_usd"], 3_000_000_000_000)
        self.assertIsNone(markets["xyz:GOLD"]["market_cap_usd"])

    async def test_reuses_the_cache_before_expiry(self):
        def handler(_: httpx.Request) -> httpx.Response:
            self.fail("cached market cap must not make a request")

        markets = {"xyz:TSLA": {"dex": "xyz", "name": "xyz:TSLA"}}
        cache = {"xyz:TSLA": {"market_cap_usd": 1_000_000, "fetched_at": 10_000}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await add_hip3_market_caps(client, markets, cache, 10_001)

        self.assertEqual(markets["xyz:TSLA"]["market_cap_usd"], 1_000_000)


if __name__ == "__main__":
    unittest.main()
