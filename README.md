## Summary

为MajdataNet设计的推荐推流数据处理部分，并持久化到MongoDB。Feed的拼接和构成API由MajdataNet后端负责。

## Notes

`load_pairs(uri, database_name)` 默认读取 `Scores`，按 Hash 关联当前
`MaiCharts`，返回去重后的 `userId/chartId` 对，每条带有 `weight: 1.0`。可用 `collection` 切换集合，
并通过 `start`、`end` 在去重前筛选 `[start, end)` 时间范围。

`load_like_pairs(uri, database_name)` 展开 `ChartInteracts.Likes`，关联当前谱面
和现存账号，返回去重后的 `userId/chartId` 对，每条带有 `weight: 1.5`。
点赞只有当前状态，没有个人操作时间，因此该函数不参与历史时间切分评估。

`build_itemcf(pairs, k=100)` 按每条记录的 `weight` 构建交互数组，同一用户—谱面的
多条记录在转为 CSR 时相加。例如游玩 1.0 加点赞 1.5，最终权重为 2.5。
IUF 使用每行非零项数量（不同谱面数）；分母使用未乘 IUF 的交互权重列的 L2 范数。
全为 1.0 且没有重复 pair 时，与原二值 IUF 公式一致。返回值为
`dict[UUID, list[{"guid": UUID, "score": float}]]`，函数不访问数据库或打印结果。

在项目根目录调用：

```bash
PYTHONPATH=src uv run --locked python - <<'PYTHON'
from itertools import chain
from majfeed.itemcf import build_itemcf, load_like_pairs, load_pairs

pairs = load_pairs("mongodb://127.0.0.1:27018", "MajNetDb_local")
like_pairs = load_like_pairs("mongodb://127.0.0.1:27018", "MajNetDb_local")
topks = build_itemcf(chain(pairs, like_pairs), k=100)
PYTHON
```

运行测试：

```bash
PYTHONPATH=src uv run --locked python -m unittest discover -s tests -v
```

## 时间切分召回评估

评估使用 `PlayHistory.Timestamp`：训练集为 `< split`，验证集为
`[split, end)`。先筛选时间再对用户—谱面对去重，不使用 `Scores` 的最后更新时间
代替真实游玩时间。IUF 和相似度只用训练集计算。
当前点赞没有历史时间戳，不加入该评估；每条去重游玩 pair 的权重仍为 1.0。

```bash
PYTHONPATH=src uv run --locked python -m majfeed.evaluate \
  --split '2026-09-01T00:00:00+08:00' \
  --end '2026-10-01T00:00:00+08:00' \
  --neighbor-k 100 --k 20
```

时间参数使用带时区的 ISO 8601 格式。默认读取本机
`mongodb://127.0.0.1:27018/MajNetDb_local`，可用 `--mongo-uri` 和 `--database` 修改。

对每个有训练历史的验证用户，累加其历史谱面邻居的相似度，排除已经玩过的谱面，
按分数取前 K 项；同分时按谱面 UUID 排序。没有候选命中时记零，不补热门或随机结果。
验证目标为该用户在验证期首次接触、且训练期其他用户已经接触过的谱面。
`recall_at_k` 是每个可评估用户的 `命中数 / 目标数` 的算术平均。

输出还包含训练/验证规模、可评估用户数、命中数，以及被排除的冷用户、
冷用户交互、老用户的新谱交互和重复游玩数量。没有有效验证目标的用户不参与平均。
这是基于当前 `MaiCharts` 的历史回测，已删除或变更 Hash 且无法关联的谱面不在结果中。
