import os
import unittest
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from bson.binary import Binary, UUID_SUBTYPE, UuidRepresentation
from bson.codec_options import CodecOptions
from pymongo import MongoClient

from majfeed.itemcf import save_neighbors


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
        low, high = UUID(int=1001), UUID(int=1002)
        topks = {
            UUID(int=i): [{"guid": low, "score": 0.25}, {"guid": high, "score": 0.75}]
            for i in range(1, 502)
        }
        written = save_neighbors(self.uri, self.database_name, topks, "itemcf-test-v1")
        self.assertEqual(written, 501)
        self.assertEqual(self.db.ChartNeighbors.count_documents({}), 501)
        docs = list(self.db.ChartNeighbors.find())
        self.assertEqual(len({doc["GeneratedAt"] for doc in docs}), 1)
        for doc in docs:
            self.assertEqual(set(doc), {"_id", "ModelVersion", "GeneratedAt", "Neighbors"})
            self.assertIsInstance(doc["_id"], UUID)
            self.assertEqual(doc["ModelVersion"], "itemcf-test-v1")
            self.assertIsInstance(doc["GeneratedAt"], datetime)
            self.assertEqual(doc["GeneratedAt"].utcoffset(), timedelta(0))
            self.assertEqual(doc["Neighbors"], [
                {"ChartId": high, "Score": 0.75},
                {"ChartId": low, "Score": 0.25},
            ])

        raw = self.db.get_collection(
            "ChartNeighbors",
            codec_options=CodecOptions(uuid_representation=UuidRepresentation.UNSPECIFIED),
        ).find_one({"ModelVersion": "itemcf-test-v1"})
        self.assertIsInstance(raw["_id"], Binary)
        self.assertEqual(raw["_id"].subtype, UUID_SUBTYPE)
        self.assertEqual(raw["Neighbors"][0]["ChartId"].subtype, UUID_SUBTYPE)
        self.assertIsInstance(raw["Neighbors"][0]["Score"], float)

        self.assertEqual(save_neighbors(
            self.uri, self.database_name, {UUID(int=1): []}, "itemcf-test-v2"
        ), 1)
        self.assertEqual(self.db.ChartNeighbors.count_documents({}), 501)
        updated = self.db.ChartNeighbors.find_one({"_id": UUID(int=1)})
        self.assertEqual(updated["ModelVersion"], "itemcf-test-v2")
        self.assertEqual(updated["Neighbors"], [])
        self.assertEqual(self.db.ChartNeighbors.find_one({"_id": UUID(int=2)})["ModelVersion"], "itemcf-test-v1")

    def test_empty_result_does_not_write_documents(self):
        self.assertEqual(save_neighbors(self.uri, self.database_name, {}, "empty"), 0)
        self.assertEqual(self.db.ChartNeighbors.count_documents({}), 0)


if __name__ == "__main__":
    unittest.main()
