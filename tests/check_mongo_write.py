import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from bson import ObjectId
from pymongo import MongoClient

from majfeed.itemcf import load_like_pairs, load_pairs, save_neighbors


class MongoWriteChecks(unittest.TestCase):
    def setUp(self):
        self.uri = os.environ["MONGO_TEST_URI"]
        self.client = MongoClient(self.uri, uuidRepresentation="standard", tz_aware=True)
        # 只在本次创建的独立数据库中验证回写，结束后删除该测试库。
        self.database_name = f"majfeed_write_check_{uuid4().hex}"
        self.db = self.client[self.database_name]

    def tearDown(self):
        self.client.drop_database(self.database_name)
        self.client.close()

    def test_bson_contract_batching_and_upsert(self):
        low, high = "hash-low+/=", "hash-high+/="
        topks = {
            f"hash-{i}": [{"hash": low, "score": 0.25}, {"hash": high, "score": 0.75}]
            for i in range(1, 502)
        }
        written = save_neighbors(self.uri, self.database_name, topks, "itemcf-test-v1")
        self.assertEqual(written, 501)
        self.assertEqual(self.db.ChartNeighbors.count_documents({}), 501)
        docs = list(self.db.ChartNeighbors.find())
        self.assertEqual(len({doc["GeneratedAt"] for doc in docs}), 1)
        for doc in docs:
            self.assertEqual(set(doc), {"_id", "ModelVersion", "GeneratedAt", "Neighbors"})
            self.assertIsInstance(doc["_id"], str)
            self.assertEqual(doc["ModelVersion"], "itemcf-test-v1")
            self.assertIsInstance(doc["GeneratedAt"], datetime)
            self.assertEqual(doc["GeneratedAt"].utcoffset(), timedelta(0))
            self.assertEqual(doc["Neighbors"], [
                {"ChartHash": high, "Score": 0.75},
                {"ChartHash": low, "Score": 0.25},
            ])
            self.assertIsInstance(doc["Neighbors"][0]["ChartHash"], str)
            self.assertIsInstance(doc["Neighbors"][0]["Score"], float)

        self.assertEqual(save_neighbors(
            self.uri, self.database_name, {"hash-1": []}, "itemcf-test-v2"
        ), 1)
        self.assertEqual(self.db.ChartNeighbors.count_documents({}), 501)
        updated = self.db.ChartNeighbors.find_one({"_id": "hash-1"})
        self.assertEqual(updated["ModelVersion"], "itemcf-test-v2")
        self.assertEqual(updated["Neighbors"], [])
        self.assertEqual(self.db.ChartNeighbors.find_one({"_id": "hash-2"})["ModelVersion"], "itemcf-test-v1")

    def test_empty_result_does_not_write_documents(self):
        self.assertEqual(save_neighbors(self.uri, self.database_name, {}, "empty"), 0)
        self.assertEqual(self.db.ChartNeighbors.count_documents({}), 0)

    def test_main_reads_configuration_and_writes_weighted_neighbors(self):
        a, b, c = [UUID(int=i) for i in range(1, 4)]
        u1, u2 = [ObjectId(f"{i:024x}") for i in range(1, 3)]
        self.db.MaiCharts.insert_many([
            {"_id": a, "Hash": "a"},
            {"_id": b, "Hash": "b"},
            {"_id": c, "Hash": "c"},
        ])
        self.db.NetUsers.insert_many([{"_id": u1}, {"_id": u2}])
        self.db.Scores.insert_many([
            {"PlayerId": u1, "Hash": "a"},
            {"PlayerId": u1, "Hash": "b"},
            {"PlayerId": u2, "Hash": "a"},
            {"PlayerId": u2, "Hash": "c"},
        ])
        self.db.ChartInteracts.insert_many([
            {"ChartHash": "a", "Likes": [u1]},
            {"ChartHash": "b", "Likes": [u2]},
        ])

        root = Path(__file__).resolve().parents[1]
        process = subprocess.run(
            [sys.executable, str(root / "src/main.py")],
            cwd=root,
            env={
                **os.environ,
                "MONGO_URI": self.uri,
                "MONGO_DATABASE": self.database_name,
                "MODEL_VERSION": "configured-v1",
                "TOP_K": "1",
            },
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        self.assertEqual(json.loads(process.stdout), {
            "model_version": "configured-v1",
            "k": 1,
            "play_pairs": 4,
            "like_pairs": 2,
            "written_charts": 3,
        })

        # A 的权重为 [2.5, 1]，B 为 [1, 1.5]，两位用户分别接触 2、3 张谱面。
        expected_ab = (2.5 / math.log(3) + 1.5 / math.log(4)) / math.sqrt(7.25 * 3.25)
        docs = {doc["_id"]: doc for doc in self.db.ChartNeighbors.find()}
        self.assertEqual(set(docs), {"a", "b", "c"})
        self.assertEqual(docs["a"]["ModelVersion"], "configured-v1")
        self.assertEqual(docs["a"]["Neighbors"][0]["ChartHash"], "b")
        self.assertAlmostEqual(docs["a"]["Neighbors"][0]["Score"], expected_ab, places=6)
        self.assertEqual(docs["b"]["Neighbors"][0]["ChartHash"], "a")
        self.assertEqual(docs["c"]["Neighbors"][0]["ChartHash"], "b")
        self.assertTrue(all(len(doc["Neighbors"]) == 1 for doc in docs.values()))

        # 同 Hash 的谱面换成新 UUID 后，历史交互和已存近邻依然用同一标识关联。
        plays_before = load_pairs(self.uri, self.database_name)
        likes_before = load_like_pairs(self.uri, self.database_name)
        self.assertTrue(all(set(pair) == {"userId", "chartHash", "weight"} for pair in plays_before + likes_before))
        self.db.MaiCharts.delete_many({"_id": {"$in": [a, b, c]}})
        self.db.MaiCharts.insert_many([
            {"_id": uuid4(), "Hash": chart_hash} for chart_hash in ["a", "b", "c"]
        ])
        to_keys = lambda pairs: {(p["userId"], p["chartHash"], p["weight"]) for p in pairs}
        self.assertEqual(to_keys(plays_before), to_keys(load_pairs(self.uri, self.database_name)))
        self.assertEqual(to_keys(likes_before), to_keys(load_like_pairs(self.uri, self.database_name)))
        self.assertEqual(self.db.ChartNeighbors.find_one({"_id": "a"})["Neighbors"], docs["a"]["Neighbors"])
        self.assertEqual(self.db.ChartNeighbors.count_documents({}), 3)


if __name__ == "__main__":
    unittest.main()
