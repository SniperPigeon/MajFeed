import unittest
from uuid import UUID

from bson import ObjectId

from majfeed.evaluate import evaluate_recall


class RecallTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b, self.c, self.d = [UUID(int=i) for i in range(1, 5)]

    def pairs(self, *entries):
        return [
            {"userId": ObjectId(f"{user:024x}"), "chartId": chart, "weight": 1.0}
            for user, chart in entries
        ]

    def test_macro_recall_and_excluded_cohorts(self):
        a, b, c, d = self.a, self.b, self.c, self.d
        train = self.pairs((1, a), (2, b), (3, c))
        validation = self.pairs((1, a), (1, b), (1, c), (1, d), (4, b), (2, c), (3, c))
        topks = {
            a: [{"guid": b, "score": 0.9}, {"guid": c, "score": 0.1}],
            b: [{"guid": c, "score": 0.9}],
            c: [],
        }
        result = evaluate_recall(train, validation, topks, k=1)
        # User 1 recalls 1/2 and user 2 recalls 1/1: macro recall is 0.75.
        self.assertEqual(result["recall_at_k"], 0.75)
        self.assertEqual(result["evaluated_users"], 2)
        self.assertEqual(result["target_pairs"], 3)
        self.assertEqual(result["hits"], 2)
        self.assertEqual(result["excluded_repeat_pairs"], 2)
        self.assertEqual(result["excluded_cold_users"], 1)
        self.assertEqual(result["excluded_cold_user_pairs"], 1)
        self.assertEqual(result["excluded_cold_item_pairs"], 1)

    def test_combines_history_scores_and_filters_seen_items(self):
        a, b, c, d = self.a, self.b, self.c, self.d
        train = self.pairs((1, a), (1, b), (2, c), (3, d))
        validation = self.pairs((1, c))
        topks = {
            a: [
                {"guid": b, "score": 0.9},
                {"guid": d, "score": 0.6},
                {"guid": c, "score": 0.4},
            ],
            b: [{"guid": c, "score": 0.4}],
            c: [],
            d: [],
        }
        self.assertEqual(evaluate_recall(train, validation, topks, k=1)["recall_at_k"], 1.0)


if __name__ == "__main__":
    unittest.main()
