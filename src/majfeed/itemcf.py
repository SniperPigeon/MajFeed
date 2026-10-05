import numpy as np
from pymongo import MongoClient
import json
from scipy.sparse import coo_array, csr_array
import math
from uuid import UUID
uri = "mongodb://127.0.0.1:27018"

client = MongoClient(
    uri,
    uuidRepresentation="standard",
    tz_aware=True,
)

db = client["MajNetDb_local"]
scores = db['Scores']

# Filter out (user, chart) pairs, with chart with its hash that actually exists in MaiCharts,
# and deduplicate with same chart (ignore difficulty difference)
valid_chart_pipeline = [
    {
        "$lookup": {
            "from": "MaiCharts",
            "localField": "Hash",
            "foreignField": "Hash",
            "as": "chart",
        }
    },
    {
        "$unwind": "$chart"
    },
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
]

# uuid/objectid to incremental id projection
user_to_idx = {}
chart_to_idx = {}
rows = []
cols = []
with db["Scores"].aggregate(valid_chart_pipeline) as cursor:
    for record in cursor:
        user_id = record["userId"]
        chart_id = record["chartId"]

        if user_id not in user_to_idx:
            user_to_idx[user_id] = len(user_to_idx)

        if chart_id not in chart_to_idx:
            chart_to_idx[chart_id] = len(chart_to_idx)

        rows.append(user_to_idx[user_id])
        cols.append(chart_to_idx[chart_id])
        
vals = np.ones(len(rows), dtype=np.float32)
play_record_matrix = coo_array((vals, (rows, cols)), shape=(len(user_to_idx), len(chart_to_idx))).tocsr()

idx_to_user = {v: k for k, v in user_to_idx.items()}
idx_to_chart = {v: k for k, v in chart_to_idx.items()}


# ItemCF


user_counts = play_record_matrix.sum(axis=1).flatten()
item_counts = play_record_matrix.sum(axis=0).flatten()# get the number of users who played each chart

item_count_vector = 1 / np.sqrt(item_counts) # get the inverse of the sqrt of number of users who played each chart

user_iuf = 1.0 / np.log1p(user_counts)
user_iuf = user_iuf[:, None] # reshape to column vector
weighted_matrix = play_record_matrix.multiply(np.sqrt(user_iuf))

cocurrence_matrix = weighted_matrix.T @ weighted_matrix  # haven't clear diagonal and normalization yet. clear diagonal later.

similarity_matrix = cocurrence_matrix.multiply(item_count_vector).multiply(item_count_vector.reshape(-1, 1))  # normalize the cocurrence matrix to get similarity matrix

similarity_matrix.setdiag(0)  # set diagonal to 0
similarity_matrix = similarity_matrix / np.max(similarity_matrix) # normalization
similarity_matrix = similarity_matrix.tocsr()
similarity_matrix.eliminate_zeros()

# Obtain top K
topks = {}
K = 10
for i in range(similarity_matrix.shape[0]):
    key = idx_to_chart[i]
    start = similarity_matrix.indptr[i]
    end = similarity_matrix.indptr[i + 1]

    neighbor_indices = similarity_matrix.indices[start:end]
    neighbor_scores = similarity_matrix.data[start:end]
    top_k_index_indices = np.argsort(neighbor_scores)[::-1][:K]
    top_k_indicies = neighbor_indices[top_k_index_indices]
    
    topks[key] = [idx_to_chart[i] for i in top_k_indicies]


# Preview specified charts and their top-K neighbors.
requested_titles = ['卑弥呼', 'Breakfast is ham and eggs', 'Hotel Moonside', '']
sampled_charts = [
    chart["_id"]
    for chart in db["MaiCharts"].find(
        {"Title": {"$in": requested_titles}}, {"_id": 1}
    )
]
sampled_charts.append(UUID('88318323-3ef7-4b40-9eed-daba613207ee'))
sampled_charts.append(UUID('30110fd9-3030-4c51-bb0d-1bf36363903d'))
sampled_charts.append(UUID('38e4690c-c7bc-43de-82cb-14ec86ff4303'))
sampled_charts = list(dict.fromkeys(sampled_charts))
preview_ids = set(sampled_charts)
for chart_id in sampled_charts:
    preview_ids.update(topks.get(chart_id, []))
titles = {
    chart["_id"]: chart.get("Title", str(chart["_id"]))
    for chart in db["MaiCharts"].find(
        {"_id": {"$in": list(preview_ids)}}, {"_id": 1, "Title": 1}
    )
}

if not sampled_charts:
    print("没有可预览的谱面。")
for chart_id in sampled_charts:
    print(f"\n{titles.get(chart_id, str(chart_id))} [{chart_id}]")
    if not topks[chart_id]:
        print("  暂无相似谱面。")
    for rank, neighbor_id in enumerate(topks[chart_id], start=1):
        similarity = similarity_matrix[chart_to_idx[chart_id], chart_to_idx[neighbor_id]]
        print(f"  {rank:2}. {titles.get(neighbor_id, str(neighbor_id))} (相似度 {similarity:.4f})")
