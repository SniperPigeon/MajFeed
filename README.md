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
