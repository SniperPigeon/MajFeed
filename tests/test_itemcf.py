import math
import unittest
from uuid import UUID

from bson import ObjectId

from majfeed.itemcf import build_itemcf


class ItemCFTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b, self.c, self.d = [UUID(int=i) for i in range(1, 5)]
        # User activity: 3, 2, 1, 1. Item support: 3, 2, 1, 1.
        histories = [(self.a, self.b, self.c), (self.a, self.b), (self.a,), (self.d,)]
        self.pairs = [
            {"userId": ObjectId(f"{u:024x}"), "chartId": chart}
            for u, history in enumerate(histories, start=1)
            for chart in history
        ]

    def test_iuf_scores_and_neighbor_contract(self):
        neighbors = build_itemcf(self.pairs)
        expected_ab = (1 / math.log(4) + 1 / math.log(3)) / math.sqrt(6)
        expected_ac = (1 / math.log(4)) / math.sqrt(3)
        self.assertEqual([n["guid"] for n in neighbors[self.a]], [self.b, self.c])
        self.assertAlmostEqual(neighbors[self.a][0]["score"], expected_ab, places=6)
        self.assertAlmostEqual(neighbors[self.a][1]["score"], expected_ac, places=6)
        self.assertEqual(neighbors[self.d], [])
        for chart, items in neighbors.items():
            for neighbor in items:
                self.assertEqual(set(neighbor), {"guid", "score"})
                self.assertIsInstance(neighbor["guid"], UUID)
                self.assertIsInstance(neighbor["score"], float)
                self.assertNotEqual(chart, neighbor["guid"])

    def test_top_k_limits_each_chart(self):
        neighbors = build_itemcf(self.pairs, k=1)
        self.assertEqual([n["guid"] for n in neighbors[self.a]], [self.b])
        self.assertTrue(all(len(items) <= 1 for items in neighbors.values()))


if __name__ == "__main__":
    unittest.main()
