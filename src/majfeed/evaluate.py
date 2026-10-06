import argparse
import json
from collections import defaultdict
from datetime import datetime
from statistics import mean
from uuid import UUID

from .itemcf import InteractionPair, Neighbor, build_itemcf, load_pairs


def evaluate_recall(
    train_pairs: list[InteractionPair],
    validation_pairs: list[InteractionPair],
    topks: dict[UUID, list[Neighbor]],
    k: int = 20,
) -> dict:
    """Macro Recall@K for known users discovering training-catalog charts."""
    train_by_user = defaultdict(set)
    validation_by_user = defaultdict(set)
    for pair in train_pairs:
        train_by_user[pair["userId"]].add(pair["chartId"])
    for pair in validation_pairs:
        validation_by_user[pair["userId"]].add(pair["chartId"])
    train_items = {pair["chartId"] for pair in train_pairs}

    recalls = []
    hits = target_pairs = repeat_pairs = cold_users = cold_user_pairs = cold_item_pairs = 0
    for user, validation_items in validation_by_user.items():
        if user not in train_by_user:
            cold_users += 1
            cold_user_pairs += len(validation_items)
            continue

        history = train_by_user[user]
        repeat_pairs += len(validation_items & history)
        novel_items = validation_items - history
        cold_item_pairs += len(novel_items - train_items)
        targets = novel_items & train_items
        if not targets:
            continue

        scores = defaultdict(float)
        for chart in sorted(history):
            for neighbor in topks[chart]:
                if neighbor["guid"] not in history:
                    scores[neighbor["guid"]] += neighbor["score"]
        ranked = sorted(scores, key=lambda chart: (-scores[chart], chart.int))[:k]
        user_hits = len(set(ranked) & targets)
        recalls.append(user_hits / len(targets))
        hits += user_hits
        target_pairs += len(targets)

    return {
        "k": k,
        "recall_at_k": mean(recalls),
        "train_pairs": len(train_pairs),
        "train_users": len(train_by_user),
        "train_items": len(train_items),
        "validation_pairs": len(validation_pairs),
        "validation_users": len(validation_by_user),
        "evaluated_users": len(recalls),
        "target_pairs": target_pairs,
        "hits": hits,
        "excluded_repeat_pairs": repeat_pairs,
        "excluded_cold_users": cold_users,
        "excluded_cold_user_pairs": cold_user_pairs,
        "excluded_cold_item_pairs": cold_item_pairs,
    }


def run_time_split(
    uri: str,
    database_name: str,
    split: datetime,
    end: datetime,
    neighbor_k: int = 100,
    k: int = 20,
) -> dict:
    """Train before split; validate on [split, end), using actual play times."""
    train_pairs = load_pairs(uri, database_name, collection="PlayHistory", end=split)
    validation_pairs = load_pairs(
        uri, database_name, collection="PlayHistory", start=split, end=end
    )
    topks = build_itemcf(train_pairs, k=neighbor_k)
    return {
        "split": split.isoformat(),
        "validation_end": end.isoformat(),
        "neighbor_k": neighbor_k,
        **evaluate_recall(train_pairs, validation_pairs, topks, k=k),
    }


def main():
    parser = argparse.ArgumentParser(description="Time-split ItemCF Recall@K evaluation")
    parser.add_argument("--mongo-uri", default="mongodb://127.0.0.1:27018")
    parser.add_argument("--database", default="MajNetDb_local")
    parser.add_argument("--split", type=datetime.fromisoformat, required=True)
    parser.add_argument("--end", type=datetime.fromisoformat, required=True)
    parser.add_argument("--neighbor-k", type=int, default=100)
    parser.add_argument("--k", type=int, default=20)
    args = parser.parse_args()
    result = run_time_split(
        args.mongo_uri, args.database, args.split, args.end, args.neighbor_k, args.k
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
