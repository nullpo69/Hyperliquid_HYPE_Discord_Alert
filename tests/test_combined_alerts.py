import unittest

from src.detector import Alert, CombinedAlert, detect_liquidation_candidates, detect_price_candidates
from src.main import _combine_same_window_alerts, _priority
from src.notifier import build_embed


NOW = 10_000.0
THRESHOLDS = {"5m": 0.05, "15m": 0.08, "prevDay": 0.10}


def price_alerts(history, current_price=110.0):
    return detect_price_candidates(history, current_price, None, THRESHOLDS, NOW, "ABC")


def oi_alerts(history, current_oi=900_000.0, current_price=110.0):
    return detect_liquidation_candidates(
        history, current_oi, current_price, NOW, "ABC", 50_000, 100_000, 0.04, 0.07,
    )


class CombinedAlertTests(unittest.TestCase):
    def test_same_five_minute_signals_become_one_combined_alert(self):
        price = price_alerts([{"t": NOW - 300, "price": 100.0}])
        liquidation = oi_alerts([{"t": NOW - 300, "oi": 1_000_000.0, "price": 100.0}])

        combined = _combine_same_window_alerts(price, liquidation, None, None, NOW)

        self.assertIsNotNone(combined)
        self.assertEqual(combined.window, "5m")
        self.assertEqual(combined.price.change, 0.10)
        self.assertEqual(combined.liquidation.oi_drop_usd, 100_000.0)

    def test_mismatched_windows_do_not_create_a_notification(self):
        price = [Alert("15m", 0.10, 100.0, 110.0, "up", "ABC")]
        liquidation = [
            Alert(
                "liq5m", -0.10, 1_000_000.0, 900_000.0, "down", "ABC", "liquidation",
                oi_drop_usd=100_000.0, oi_drop_pct=0.10,
            )
        ]

        combined = _combine_same_window_alerts(price, liquidation, None, None, NOW)

        self.assertIsNone(combined)

    def test_strongest_same_symbol_pair_is_retained(self):
        price = price_alerts([
            {"t": NOW - 900, "price": 80.0},
            {"t": NOW - 600, "price": 90.0},
            {"t": NOW - 300, "price": 100.0},
        ])
        liquidation = oi_alerts([
            {"t": NOW - 900, "oi": 1_500_000.0, "price": 80.0},
            {"t": NOW - 600, "oi": 1_400_000.0, "price": 90.0},
            {"t": NOW - 300, "oi": 1_000_000.0, "price": 100.0},
        ])

        combined = _combine_same_window_alerts(price, liquidation, None, None, NOW)

        self.assertIsNotNone(combined)
        self.assertEqual(combined.window, "15m")

    def test_cooldown_on_either_signal_suppresses_combined_alert(self):
        price = price_alerts([{"t": NOW - 300, "price": 100.0}])
        liquidation = oi_alerts([{"t": NOW - 300, "oi": 1_000_000.0, "price": 100.0}])

        combined = _combine_same_window_alerts(
            price,
            liquidation,
            {"time": NOW - 30, "direction": "up", "kind": "price"},
            None,
            NOW,
        )

        self.assertIsNone(combined)

    def test_volume_is_first_priority(self):
        low_volume = CombinedAlert(
            Alert("5m", 0.50, 100, 150, "up", "LOW"),
            Alert("liq5m", -0.50, 1_000_000, 500_000, "down", "LOW", "liquidation", oi_drop_usd=500_000, oi_drop_pct=.50),
        )
        high_volume = CombinedAlert(
            Alert("5m", 0.10, 100, 110, "up", "HIGH"),
            Alert("liq5m", -0.10, 1_000_000, 900_000, "down", "HIGH", "liquidation", oi_drop_usd=100_000, oi_drop_pct=.10),
        )

        self.assertGreater(
            _priority(("high", high_volume, {}, "combined", 2_000_000)),
            _priority(("low", low_volume, {}, "combined", 1_000_000)),
        )

    def test_combined_embed_includes_price_and_oi_metrics(self):
        combined = CombinedAlert(
            Alert("5m", -0.10, 100, 90, "down", "ABC"),
            Alert("liq5m", -0.10, 1_000_000, 900_000, "down", "ABC", "liquidation", oi_drop_usd=100_000, oi_drop_pct=.10),
        )

        embed = build_embed(combined)

        self.assertIn("価格変動率", embed["description"])
        self.assertIn("OIドロップ額", embed["description"])
        self.assertIn("ABC", embed["title"])


if __name__ == "__main__":
    unittest.main()
