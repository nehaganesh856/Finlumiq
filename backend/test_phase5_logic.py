"""Unit tests for Phase 5 split calculations; no MySQL server required."""
import sys
import types
import unittest

# Flask is an existing project dependency, but the pure calculation helper can
# be tested in a minimal environment without installing Flask.
if "flask" not in sys.modules:
    fake_flask = types.ModuleType("flask")
    fake_flask.jsonify = lambda *a, **k: None
    fake_flask.request = object()
    fake_flask.session = {}
    sys.modules["flask"] = fake_flask

from decimal import Decimal
from phase5 import _split_amounts, register_phase5_routes


class SplitCalculationTests(unittest.TestCase):
    def assert_total(self, rows, expected):
        self.assertEqual(sum((Decimal(str(value)) for _, value in rows), Decimal("0.00")), Decimal(expected))

    def test_equal_split_distributes_remaining_paise(self):
        rows = _split_amounts("100.00", [3, 1, 2], "equal", [])
        self.assertEqual(rows, [(1, Decimal("33.34")), (2, Decimal("33.33")), (3, Decimal("33.33"))])
        self.assert_total(rows, "100.00")

    def test_custom_split_requires_exact_total(self):
        valid = [{"user_id": 1, "amount": "20"}, {"user_id": 2, "amount": "30"}, {"user_id": 3, "amount": "50"}]
        rows = _split_amounts("100.00", [1, 2, 3], "custom", valid)
        self.assert_total(rows, "100.00")
        invalid = [{"user_id": 1, "amount": "20"}, {"user_id": 2, "amount": "30"}, {"user_id": 3, "amount": "49.99"}]
        with self.assertRaises(ValueError):
            _split_amounts("100.00", [1, 2, 3], "custom", invalid)

    def test_percentage_split_requires_100_percent_and_rounds_exactly(self):
        valid = [{"user_id": 1, "percentage": "33.33"}, {"user_id": 2, "percentage": "33.33"}, {"user_id": 3, "percentage": "33.34"}]
        rows = _split_amounts("100.00", [1, 2, 3], "percentage", valid)
        self.assert_total(rows, "100.00")
        invalid = [{"user_id": 1, "percentage": 60}, {"user_id": 2, "percentage": 30}]
        with self.assertRaises(ValueError):
            _split_amounts("100.00", [1, 2], "percentage", invalid)

    def test_duplicate_participants_are_rejected(self):
        with self.assertRaises(ValueError):
            _split_amounts("10.00", [1, 1], "equal", [])

    def test_zero_total_is_rejected(self):
        with self.assertRaises(ValueError):
            _split_amounts("0", [1], "equal", [])

    def test_phase5_routes_register_without_duplicate_paths(self):
        class FakeApp:
            def __init__(self): self.routes = []
            def route(self, path, methods=None):
                def decorate(fn):
                    self.routes.append((path, tuple(methods or ["GET"]), fn.__name__))
                    return fn
                return decorate
        app = FakeApp()
        def identity(view): return view
        register_phase5_routes(app, lambda: None, identity)
        self.assertGreaterEqual(len(app.routes), 15)
        paths = [r[0] for r in app.routes]
        self.assertEqual(len(paths), len(set(paths)), "Duplicate Phase 5 route paths")
        self.assertIn("/api/expense-groups", paths)
        self.assertIn("/api/user-reminders", paths)
        self.assertIn("/api/notifications", paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
