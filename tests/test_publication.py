import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from majfeed.publication import make_model_version, save_neighbors


class PublicationTests(unittest.TestCase):
    def test_version_uses_fixed_width_utc_and_sorts_across_midnight(self):
        local = datetime(2026, 10, 12, 8, 0, 1, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(make_model_version("itemcf", local), "itemcf-20261012:000001")
        self.assertLess("itemcf-20261011:235959", make_model_version("itemcf", local))

    def test_invalid_version_or_neighbors_fail_before_opening_database(self):
        with patch("majfeed.publication.MongoClient") as client:
            for version in ("manual-v1", "itemcf-20261012:1", "other|bad-20261012:000001"):
                with self.subTest(version=version), self.assertRaises(ValueError):
                    save_neighbors("unused", "unused", {"a": []}, version)
            for neighbors in ([{"hash": "a", "score": 1}], [{"hash": "b", "score": float("nan")}],
                              [{"hash": "b", "score": 0}], [{"hash": "b", "score": 1}] * 2):
                with self.subTest(neighbors=neighbors), self.assertRaises(ValueError):
                    save_neighbors("unused", "unused", {"a": neighbors}, "itemcf-20261012:000001")
            client.assert_not_called()

    def test_version_requires_a_valid_model_name_and_timezone(self):
        with self.assertRaises(ValueError):
            make_model_version("itemcf|invalid")
        with self.assertRaises(ValueError):
            make_model_version(generated_at=datetime(2026, 10, 12))


if __name__ == "__main__":
    unittest.main()
