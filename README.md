## Summary

为MajdataNet设计的推荐推流数据处理部分，并持久化到MongoDB。Feed的拼接和构成API由MajdataNet后端负责。

## Notes

推荐算法：`ItemCF + 用户活跃度IUF降权`，同时权重部分采用户游玩记录为1.0，点赞记录为1.5，在合并时加总。IUF依然靠`log1p(uniquePlayCount)`作为降权。

分母类似普通ItemCF，不过由于我们引入权重，这里靠`sigma sqrt(R^2)`作为Normalization范数。公式：

\[
S_{ij}
=
\frac{\sum_u IUF_u\,R_{ui}R_{uj}}
{\sqrt{\sum_u R_{ui}^{2}}\sqrt{\sum_u R_{uj}^{2}}}
\]

## 谱面标识与回写

训练、评估和近邻回写统一使用 `MaiCharts.Hash`，区分大小写。游玩仍从
`Scores.Hash` / `PlayHistory.Hash` 读取，点赞从 `ChartInteracts.ChartHash` 读取；
仅保留能关联到当前谱面的交互，并按用户与 Hash 去重。
输入为 `userId/chartHash/weight`，Top-K 返回 `dict[str, list[{"hash": str, "score": float}]]`。
IUF、交互权重和归一化公式保持不变。

`ChartNeighbors` 以源谱面的 Hash 字符串作为 `_id`，内嵌
`Neighbors[{ChartHash, Score}]`，另外保留 `ModelVersion` 和 UTC `GeneratedAt`。
同 Hash 的谱面更换 UUID 后，后端按 Hash 读取近邻并解析当前的谱面对象。

旧的 UUID 文档不会被新版后端读取。部署时先运行新版 majfeed 生成 Hash 文档，
再部署匹配的 mmfcapi；无需先删除旧文档，也不会自动修改历史成绩。
Hash 本身变化的谱面仍按新标识处理。

## 主入口

在项目根目录准备 `.env` 后运行

```bash
cp .env.example .env
uv run --locked --env-file .env python src/main.py
```

配置中的 `MONGO_URI`、`MONGO_DATABASE` 和 `MODEL_VERSION` 必填，`TOP_K` 默认为 100。
执行后会更新配置数据库内的 `ChartNeighbors`，完成后输出一条 JSON 统计并退出。


运行测试：

```bash
PYTHONPATH=src uv run --locked python -m unittest discover -s tests -v
```

MongoDB 回写集成检查（自动创建并清理独立测试库）：

```bash
MONGO_TEST_URI='mongodb://127.0.0.1:27018' PYTHONPATH=src \
  uv run --locked python tests/check_mongo_write.py -v
```
