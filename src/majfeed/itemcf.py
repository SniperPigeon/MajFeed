from collections.abc import Iterable
from datetime import datetime, timezone
from typing import TypedDict
from uuid import UUID

import numpy as np
from bson import ObjectId
from pymongo import MongoClient, ReplaceOne
from scipy.sparse import coo_array


class InteractionPair(TypedDict):
    userId: ObjectId
    chartId: UUID
    weight: float


class Neighbor(TypedDict):
    guid: UUID
    score: float


def load_pairs(
    uri: str,
    database_name: str,
    *,
    collection: str = "Scores",
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[InteractionPair]:
    """提取 [start, end) 内去重后的用户—谱面对，游玩权重为 1.0。"""
    pipeline = []
    # 先按时间筛选再去重，分别保留训练期和验证期实际出现的交互。
    time_filter = {}
    if start is not None:
        time_filter["$gte"] = start
    if end is not None:
        time_filter["$lt"] = end
    if time_filter:
        pipeline.append({"$match": {"Timestamp": time_filter}})

    # 按 Hash 关联当前谱面，$unwind 会排除找不到谱面的成绩记录。
    pipeline.extend([
        {
            "$lookup": {
                "from": "MaiCharts",
                "localField": "Hash",
                "foreignField": "Hash",
                "as": "chart",
            }
        },
        {"$unwind": "$chart"},
        # 忽略难度差异，同一用户和同一谱面只保留一条游玩关系。
        {
            "$group": {
                "_id": {
                    "userId": "$PlayerId",
                    "chartId": "$chart._id",
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "userId": "$_id.userId",
                "chartId": "$_id.chartId",
                "weight": {"$literal": 1.0},  # 用 $literal 返回常量，而不是保留同名字段。
            }
        },
    ])

    with MongoClient(uri, uuidRepresentation="standard", tz_aware=True) as client:
        with client[database_name][collection].aggregate(pipeline) as cursor:
            return list(cursor)


def load_like_pairs(uri: str, database_name: str) -> list[InteractionPair]:
    """提取当前有效的点赞关系，点赞权重为 1.5。"""
    # Likes 只有当前用户列表，没有个人点赞时间，因此不用于历史时间切分。
    pipeline = [
        {
            "$lookup": {
                "from": "MaiCharts",
                "localField": "ChartHash",
                "foreignField": "Hash",
                "as": "chart",
            }
        },
        {"$unwind": "$chart"},
        {"$unwind": "$Likes"},  # 将点赞用户数组展开成单个用户—谱面对。
        # 只保留仍然存在的账号，避免将已删除账号的点赞加入训练。
        {
            "$lookup": {
                "from": "NetUsers",
                "localField": "Likes",
                "foreignField": "_id",
                "as": "user",
            }
        },
        {"$unwind": "$user"},
        {
            "$group": {
                "_id": {
                    "userId": "$Likes",
                    "chartId": "$chart._id",
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "userId": "$_id.userId",
                "chartId": "$_id.chartId",
                "weight": {"$literal": 1.5},
            }
        },
    ]

    with MongoClient(uri, uuidRepresentation="standard", tz_aware=True) as client:
        with client[database_name]["ChartInteracts"].aggregate(pipeline) as cursor:
            return list(cursor)


def build_itemcf(
    pairs: Iterable[InteractionPair], k: int = 100
) -> dict[UUID, list[Neighbor]]:
    """计算带交互权重的 IUF ItemCF，按谱面返回 Top-K 的 guid/score 列表。"""
    # UUID/ObjectId 映射到连续整数索引：用户对应行，谱面对应列。
    user_to_idx = {}
    chart_to_idx = {}
    rows = []
    cols = []
    vals = []
    for record in pairs:
        user_id = record["userId"]
        chart_id = record["chartId"]
        if user_id not in user_to_idx:
            user_to_idx[user_id] = len(user_to_idx)
        if chart_id not in chart_to_idx:
            chart_to_idx[chart_id] = len(chart_to_idx)
        rows.append(user_to_idx[user_id])
        cols.append(chart_to_idx[chart_id])
        vals.append(record["weight"])

    # COO 转 CSR 时会合并重复坐标，游玩 1.0 加点赞 1.5 就得到权重 2.5。
    vals = np.asarray(vals, dtype=np.float32)
    play_record_matrix = coo_array(
        (vals, (rows, cols)), shape=(len(user_to_idx), len(chart_to_idx))
    ).tocsr()
    idx_to_chart = {v: key for key, v in chart_to_idx.items()}

    # IUF 按用户接触过的不同谱面数量计算，不能把交互权重的行和当成数量。
    user_counts = play_record_matrix.count_nonzero(axis=1).astype(np.float32)
    # 分母使用原始权重列的 L2 范数；全为 1 时，等价于谱面用户数的平方根。
    item_square_sums = (
        play_record_matrix.multiply(play_record_matrix).sum(axis=0).flatten()
    )
    item_norm_vector = 1 / np.sqrt(item_square_sums)
    # 转为 (用户数, 1) 的列向量，让每个用户的 IUF 权重广播到其整行。
    user_iuf = (1.0 / np.log1p(user_counts))[:, None]
    # 两侧先乘 sqrt(IUF)，转置相乘后，共同用户的贡献恰好乘一次 IUF。
    weighted_matrix = play_record_matrix.multiply(np.sqrt(user_iuf))
    cocurrence_matrix = weighted_matrix.T @ weighted_matrix
    # 分别按列、按行乘范数的倒数，相当于除以两张谱面各自的范数。
    similarity_matrix = (
        cocurrence_matrix.multiply(item_norm_vector)
        .multiply(item_norm_vector.reshape(-1, 1))
    )
    similarity_matrix.setdiag(0)  # 清除自身相似度，不把谱面自己作为推荐。
    similarity_matrix = similarity_matrix.tocsr()
    similarity_matrix.eliminate_zeros()  # 删除 setdiag 留下的显式零。

    # 每行对应一张谱面，从非零邻居中按相似度降序选 Top-K。
    topks = {}
    for i in range(similarity_matrix.shape[0]):
        # indptr 给出该行在 indices/data 两个一维数组中的起止位置。
        start = similarity_matrix.indptr[i]
        end = similarity_matrix.indptr[i + 1]
        neighbor_indices = similarity_matrix.indices[start:end]
        neighbor_scores = similarity_matrix.data[start:end]
        positions = np.argsort(neighbor_scores)[::-1][:k]
        # positions 是邻居数组内的位置，还需经过列索引映射回谱面 UUID。
        topks[idx_to_chart[i]] = [
            {
                "guid": idx_to_chart[int(neighbor_indices[pos])],
                "score": float(neighbor_scores[pos]),
            }
            for pos in positions
        ]
    return topks


def save_neighbors(
    uri: str,
    database_name: str,
    topks: dict[UUID, list[Neighbor]],
    model_version: str,
) -> int:
    """按 C# ChartNeighborList 的结构更新 ChartNeighbors，返回写入谱面数。"""
    generated_at = datetime.now(timezone.utc)
    operations = []
    written = 0
    with MongoClient(uri, uuidRepresentation="standard", tz_aware=True) as client:
        collection = client[database_name]["ChartNeighbors"]
        for chart_id, neighbors in topks.items():
            # _id 复用原谱面 UUID；字段大小写和 UUID Standard 格式与 C# 模型一致。
            document = {
                "_id": chart_id,
                "ModelVersion": model_version,
                "GeneratedAt": generated_at,
                "Neighbors": [
                    {"ChartId": neighbor["guid"], "Score": float(neighbor["score"])}
                    for neighbor in sorted(neighbors, key=lambda item: item["score"], reverse=True)
                ],
            }
            # 同一谱面直接替换当前近邻列表，不存在时插入；本轮所有文档共用生成时间。
            operations.append(ReplaceOne({"_id": chart_id}, document, upsert=True))
            if len(operations) == 500:
                collection.bulk_write(operations, ordered=False)
                written += len(operations)
                operations.clear()

        # 写入最后不足一批的结果，空结果不会发出写入操作。
        if operations:
            collection.bulk_write(operations, ordered=False)
            written += len(operations)
    return written
