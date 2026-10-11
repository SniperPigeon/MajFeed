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

## 谱面标识与版本发布

训练、评估和近邻回写统一使用 `MaiCharts.Hash`，区分大小写。游玩从
`Scores.Hash` / `PlayHistory.Hash` 读取，点赞从 `ChartInteracts.ChartHash` 读取；
仅保留能关联到当前谱面的交互，并按用户与 Hash 去重。
输入为 `userId/chartHash/weight`，Top-K 返回 `dict[str, list[{"hash": str, "score": float}]]`。

每轮开始自动生成 `{model}-yyyyMMdd:HHmmss`（UTC），例如 `itemcf-20261012:000001`。
模型名当前由 `src/main.py` 的 `MODEL_NAME` 常量指定为 `itemcf`，不再手填 `MODEL_VERSION`。
同一模型内版本号可按字符串排序；同秒冲突直接失败，不覆盖或复用版本。

`ChartNeighbors` 文档包含 `_id = ModelVersion + "|" + ChartHash`、独立的源
`ChartHash`、`ModelVersion`、UTC `GeneratedAt` 和 `Neighbors[{ChartHash, Score}]`。
同 Hash 更换 UUID 不影响关联。新旧版本同时存在，已发布版本不可修改。

发布流程在 `src/majfeed/publication.py`：

1. 在 `RecommendationModels` 插入版本占位：`_id`、`Model`、`GeneratedAt`、`ChartCount` 和空 `PublishedAt`。
2. 每批 500 条插入近邻；回读整版，逐条验证内容和总数。
3. 校验成功后原子设置 `PublishedAt`。mmfcapi 只在当前模型已发布记录中排序选最新版，一次推荐固定一个版本。

写入/验证失败不会发布，也不会触碰旧版。失败占位保留供排查，重跑使用新版本号；
只有确认原写入进程已停止后才可手动清理该失败版本。空训练结果不发布新版本。
清理由 `src/main.py` 的 `run` 在本轮发布成功后执行，发布失败或空结果不会触发清理。

## 主入口

在项目根目录准备 `.env` 后运行：

```bash
cp .env.example .env
uv run --locked --env-file .env python src/main.py
```

`MONGO_URI`、`MONGO_DATABASE` 必填，`TOP_K` 默认 100。
成功后输出 JSON，包含本轮自动生成的 `model_version`、训练交互数、写入谱面数及 `deleted_versions`。

## 夜间运行与清理

训练、发布和旧版本清理集成在同一个 `run` 里，mmfcapi 不负责清理。
建议让部署机器的调度器在低负载时段（例如当地时间 03:00）运行上面的主入口，
无需单独配置清理任务。

- 本轮完整发布成功后，才执行旧版本回收。
- 保留版本号最大的两版。
- 更旧版本自首次被更高版本取代满一小时后，才删除其近邻及发布记录。
- 只删除已确定的旧版本，不使用 `ModelVersion != current` 这种广泛条件。
- 未发布占位、其他模型及旧格式遗留数据不自动删除。

版本生成时间和发布时间分开记录，因此训练完成顺序不同也不会提早清理仍需保留的版本。
部署机器的定时任务需按实际路径和时区配置；此项目不会修改系统调度器。

## 迁移与测试

先运行新版 majfeed，确认出现 `PublishedAt` 非空的版本，再部署匹配的 mmfcapi。
旧的 `_id = Hash` / UUID 数据不会被新版读取或自动清理，确认迁移稳定后可单独处理。

```bash
PYTHONPATH=src uv run --locked python -m unittest discover -s tests -v
```

MongoDB 发布/失败恢复/夜间清理集成检查（只创建和清理独立测试库）：

```bash
MONGO_TEST_URI='mongodb://127.0.0.1:27018' PYTHONPATH=src \
  uv run --locked python tests/check_mongo_write.py -v
```
