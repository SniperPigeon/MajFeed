from collections.abc import Iterable
from datetime import datetime
from typing import TypedDict
from uuid import UUID

import numpy as np
from bson import ObjectId
from pymongo import MongoClient
from scipy.sparse import coo_array


class InteractionPair(TypedDict):
    userId: ObjectId
    chartId: UUID


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
    """Load distinct user/chart pairs with a current Hash in [start, end)."""
    pipeline = []
    time_filter = {}
    if start is not None:
        time_filter["$gte"] = start
    if end is not None:
        time_filter["$lt"] = end
    if time_filter:
        pipeline.append({"$match": {"Timestamp": time_filter}})

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
            }
        },
    ])

    with MongoClient(uri, uuidRepresentation="standard", tz_aware=True) as client:
        with client[database_name][collection].aggregate(pipeline) as cursor:
            return list(cursor)


def build_itemcf(
    pairs: Iterable[InteractionPair], k: int = 100
) -> dict[UUID, list[Neighbor]]:
    """Compute the existing IUF ItemCF formula from deduplicated binary pairs."""
    user_to_idx = {}
    chart_to_idx = {}
    rows = []
    cols = []
    for record in pairs:
        user_id = record["userId"]
        chart_id = record["chartId"]
        if user_id not in user_to_idx:
            user_to_idx[user_id] = len(user_to_idx)
        if chart_id not in chart_to_idx:
            chart_to_idx[chart_id] = len(chart_to_idx)
        rows.append(user_to_idx[user_id])
        cols.append(chart_to_idx[chart_id])

    vals = np.ones(len(rows), dtype=np.float32)
    play_record_matrix = coo_array(
        (vals, (rows, cols)), shape=(len(user_to_idx), len(chart_to_idx))
    ).tocsr()
    idx_to_chart = {v: key for key, v in chart_to_idx.items()}

    user_counts = play_record_matrix.sum(axis=1).flatten()
    item_counts = play_record_matrix.sum(axis=0).flatten()
    item_count_vector = 1 / np.sqrt(item_counts)
    user_iuf = (1.0 / np.log1p(user_counts))[:, None]
    weighted_matrix = play_record_matrix.multiply(np.sqrt(user_iuf))
    cocurrence_matrix = weighted_matrix.T @ weighted_matrix
    similarity_matrix = (
        cocurrence_matrix.multiply(item_count_vector)
        .multiply(item_count_vector.reshape(-1, 1))
    )
    similarity_matrix.setdiag(0)
    similarity_matrix = similarity_matrix.tocsr()
    similarity_matrix.eliminate_zeros()

    topks = {}
    for i in range(similarity_matrix.shape[0]):
        start = similarity_matrix.indptr[i]
        end = similarity_matrix.indptr[i + 1]
        neighbor_indices = similarity_matrix.indices[start:end]
        neighbor_scores = similarity_matrix.data[start:end]
        positions = np.argsort(neighbor_scores)[::-1][:k]
        topks[idx_to_chart[i]] = [
            {
                "guid": idx_to_chart[int(neighbor_indices[pos])],
                "score": float(neighbor_scores[pos]),
            }
            for pos in positions
        ]
    return topks
