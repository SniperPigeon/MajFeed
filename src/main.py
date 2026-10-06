import json
import os
from itertools import chain

from majfeed.itemcf import build_itemcf, load_like_pairs, load_pairs, save_neighbors


def run(uri: str, database_name: str, model_version: str, k: int = 100) -> dict:
    """读取游玩与点赞，计算 Top-K，并回写当前谱面的近邻列表。"""
    play_pairs = load_pairs(uri, database_name)
    like_pairs = load_like_pairs(uri, database_name)
    # 保留两种行为的权重，同一用户—谱面对在 ItemCF 内累计为 2.5。
    topks = build_itemcf(chain(play_pairs, like_pairs), k=k)
    written = save_neighbors(uri, database_name, topks, model_version)
    return {
        "model_version": model_version,
        "k": k,
        "play_pairs": len(play_pairs),
        "like_pairs": len(like_pairs),
        "written_charts": written,
    }


def main():
    # 本地由 uv --env-file 加载配置，容器中由 Docker 注入同名环境变量。
    result = run(
        os.environ["MONGO_URI"],
        os.environ["MONGO_DATABASE"],
        os.environ["MODEL_VERSION"],
        k=int(os.environ.get("TOP_K", "100")),
    )
    # 只在整轮写入完成后输出统计，异常直接交给调用脚本或定时任务处理。
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
