# xhsbooster 过滤策略文档

> **不可更改的硬性规则。** 任何后续修改都必须遵守本文档的三层过滤机制。

## 时间标准

- **时区**：北京时间 UTC+8（CST）
- **日期格式**：文件名 `YYYY-MMDD`，文章时间戳 `MMDDsource`（如 `0621soompi`）
- **当日边界**：CST 00:00:00 ~ 23:59:59

## 三层日期过滤（三重保障）

### 层1：爬虫层（crawler.py）

```python
# fetch_all() 中，去重之前执行
today_start = CST 当日 00:00:00 的 Unix 时间戳
today_end = today_start + 86400
articles = [a for a in articles if today_start <= a.published_ts < today_end]
```

### 层2：存储层（main.py）

```python
# 写入 JSON 前二次校验
today_mmdd = "0621"
validated = [a for a in enriched if a["published_at"][:4] == today_mmdd]
# 被拦截的打印 WARNING 日志
```

### 层3：渲染层（render.py）

```python
# _load_articles() 读取 JSON 后三次校验
today_mmdd = "0621"
filtered = [a for a in articles if a["published_at"][:4] == today_mmdd]
# 被拦截的打印 INFO 日志
```

## 排序规则

- **必须降序**：`articles.sort(key=lambda a: a.published_ts, reverse=True)`
- 最新文章排在最前，旧文章在后
- 排序在爬虫层去重之后执行

## 去重规则

- **存储**：SQLite，`dedup.db`
- **键**：MD5(url)
- **窗口**：72 小时滑动，自动清理过期记录
- **is_new 标记**：INSERT 成功 = True（新文章），冲突 = False（重复）

## 绝对禁止

- ❌ 展示非 CST 当日的文章
- ❌ 按任意非 `published_ts` 的字段排序
- ❌ 绕过三层过滤中的任何一层
- ❌ 在 HTML 页面中出现跨日期文章

## 参考

- DailyBrief 项目：`todayKey()` 时区感知日期键
- DailyBrief 项目：源级 `max_items` 控制量
- 本项目的 PRD：三重日期校验 + 72h 去重 + 降序展示
