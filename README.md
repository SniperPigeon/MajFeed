## Summary

为MajdataNet设计的推荐推流数据处理部分，并持久化到MongoDB。Feed的拼接和构成API由MajdataNet后端负责。

## Notes

`load_pairs(uri, database_name)` 默认读取 `Scores`，按 Hash 关联当前
`MaiCharts`，返回去重后的 `userId/chartId` 对。可用 `collection` 切换集合，
并通过 `start`、`end` 在去重前筛选 `[start, end)` 时间范围。

`build_itemcf(pairs, k=100)` 保留二值交互、IUF、原始谱面用户数归一化和
Top-K 排序。输入应是去重后的 pair；返回值为
`dict[UUID, list[{"guid": UUID, "score": float}]]`，函数不访问数据库或打印结果。

在项目根目录调用：

```bash
PYTHONPATH=src uv run --locked python - <<'PYTHON'
from majfeed.itemcf import build_itemcf, load_pairs

pairs = load_pairs("mongodb://127.0.0.1:27018", "MajNetDb_local")
topks = build_itemcf(pairs, k=100)
PYTHON
```

运行测试：

```bash
PYTHONPATH=src uv run --locked python -m unittest discover -s tests -v
```
