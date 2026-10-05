import numpy as np
from pymongo import MongoClient
import json
from scipy.sparse import coo_array, csr_array
import math
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

cocurrence_matrix = play_record_matrix.T @ play_record_matrix  # haven't clear diagonal and normalization yet.
item_counts = cocurrence_matrix.diagonal() # get the number of users who played each chart
item_count_vector = 1 / (item_counts ** 0.5) # get the inverse of the sqrt of number of users who played each chart

similarity_matrix = cocurrence_matrix.multiply(item_count_vector).multiply(item_count_vector.reshape(-1, 1))  # normalize the cocurrence matrix to get similarity matrix

similarity_matrix.setdiag(0)  # set diagonal to 0
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

first = next(iter(topks))
print(f"First Pair: {first} : {topks[first]}")
    
    


