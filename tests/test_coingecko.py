import unittest

import httpx

from src.coingecko import add_market_caps


class CoinGeckoTests(unittest.IsolatedAsyncioTestCase):
    async def test_adds_market_cap_by_ticker_and_leaves_unlisted_market_empty(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.params["vs_currency"], "usd")
            self.assertEqual(request.url.params["include_tokens"], "top")
            self.assertEqual(set(request.url.params["symbols"].split(",")), {"btc", "missing"})
            return httpx.Response(200, json=[{"symbol": "btc", "market_cap": 2_000_000_000_000}])

        markets = {
            "main:BTC": {"name": "BTC"},
            "xyz:MISSING": {"name": "xyz:MISSING"},
        }
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await add_market_caps(client, markets)

        self.assertEqual(markets["main:BTC"]["market_cap_usd"], 2_000_000_000_000)
        self.assertIsNone(markets["xyz:MISSING"]["market_cap_usd"])


if __name__ == "__main__":
    unittest.main()
