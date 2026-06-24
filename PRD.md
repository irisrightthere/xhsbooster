# xhsbooster 产品需求文档 v2.0

> 最后更新：2026-06-24
> 本文档记录当前已实现的所有功能。任何后续修改必须先 plan、确认、再更新本文档。

---

## 一、架构

### 双层架构（参考 DailyBrief）

```
Layer 1: GitHub Actions（云端，永远在线）
  每 4 小时 cron → crawler → DeepSeek 提炼 → 飞书推送 → HTML 渲染 → gh-pages 部署

Layer 2: 本地 Mac（按需运行，深度加工）
  puller → Obsidian 存储 → draft_generator → 人工审核 → 发布
  （Layer 2 代码已编写，待接入）
```

---

## 二、信息源（当前启用 3 个）

| # | id | 名称 | 类型 | Tab | 语言 | 状态 |
|---|-----|------|------|-----|------|------|
| 1 | soompi | Soompi | RSS | 第一位 | en | ✅ |
| 2 | google-kpop | Google News | RSS | 第二位 | en | ✅ |
| 3 | asianwiki | AsianWiki | 网页 | 第三位 | en | ✅ |
| — | google-jdrama | Google News 日娱 | RSS | — | en | ⏸️ 蛀掉 |
| — | oricon | Oricon News | 网页 | — | ja | ⏸️ 蛀掉 |

---

## 三、数据管道

```
sources.json → crawler.py → 日期过滤 → SQLite 去重 → DeepSeek 提炼 → 飞书推送 → HTML 渲染
```

### 爬虫层
- RSS 源：feedparser，重试 3 次，间隔 30s
- AsianWiki：httpx 抓主页 + 详情页，提取日期/平台/Cast/摘要
- 单源失败不影响全局

### 日期过滤（三层）
1. **爬虫层**：`published_ts` 在 CST 当天范围内（AsianWiki 跳过此过滤）
2. **存储层**：写入 JSON 前二次校验 `published_at` 前缀
3. **渲染层**：读取 JSON 后三次校验

### 去重
- SQLite，MD5(url) 主键
- 72h 滑动窗口，自动清理过期
- `is_new` 标记：INSERT 成功=新文章

### DeepSeek 提炼
- 模型：deepseek-v4
- temperature：0.1
- JSON mode：title_zh / source_type / risk_level / is_blurred / facts_list / summary_zh
- 系统 prompt：资深日韩娱主编，禁止笼统词汇，数字逐一列举
- AsianWiki：仅爬取英文原文，暂未接翻译

### 飞书推送
- 有新文章：文本消息 + 网站链接（仅推送 Soompi + Google News，AsianWiki 不推送）
- 无更新：心跳 `[巡检报告]`
- 无风险标记，无源标签
- 重试 3 次 → 死信队列

---

## 四、网站 UI（v9 暗色主题）

### Header（DailyBrief 风格）
```
🍠 xhsbooster
2026-06-24
← 往期回顾（左侧滑入抽屉）
```

### Tab
```
[Soompi 15] [Google News 10] [AsianWiki 58]
```

### 新闻卡片（Soompi / Google News）
```
标题（链接原文）
NEW Soompi · 2026-06-24
─────────────────
摘要
─────────────────
查看原文 ↗  匹配模板（复制到剪贴板）
```

### AsianWiki 戏剧卡片
```
🗓️ 3月 2日
Siren's Kiss | 海妖之吻
Cast: 金宣虎 / 高允贞 / 福士苍汰 / 李伊丹
─────────────────
摘要
─────────────────
[tvN] [韩剧]
```

### AsianWiki 三层筛选
- 地区：全部 / 韩国 / 日本
- 平台：动态生成
- 月份：1-8月 + 📌待定

### 配色方案
- 背景 `#0B0F19`，卡片 `#161F30`
- 主色 `#B3C0FB`（明薰衣草紫）
- NEW 脉冲 `#bfa0ff`（柔和紫调，3.5s 慢呼吸）
- 风险标签：低对比度灰调
- 高亮文字：淡紫灰 `#B3C0FB`，极淡底色

### 往期回顾

**入口：** Header `← 往期回顾` 链接，点击从左侧滑入抽屉。

**数据来源：** `gh-pages/_state/` 目录下所有 `YYYY-MMDD_articles.json` 文件。

**展示格式（DailyBrief 风格）：**
```
📦 往期回顾                    ✕
─────────────────────────────
2026-06-24
2026-06-23
2026-06-22
2026-06-21
...
```
- 纯列表，按日期倒序（最新在前）
- 每行一个日期链接，点击跳转对应日期的首页
- 页脚也有 `往期回顾` 链接，指向 `archive.html` 独立归档页

**持久化机制：** 每次 Actions 运行前，通过 curl 从已部署的网站下载近 7 天的 `_state/*.json` 文件到本地，与新生成的文件合并后再整体部署，保证历史数据不丢失。

---

## 五、数据字段

### RawArticle
| 字段 | 说明 |
|------|------|
| source_id | 源标识 |
| source_name | 源名称 |
| l1_tab | 韩娱（已弃用 L1 层级，仅保留兼容） |
| title | 原标题 |
| url | 原文链接 |
| content | 正文/JSON（AsianWiki 存储结构化数据） |
| published_at | MMDDsource 格式 |
| published_ts | CST Unix 时间戳 |
| category | 韩娱/韩剧/日剧 |
| source_lang | en/ja/ko |
| image_url | 图片链接 |
| is_new | 本轮新文章 |

---

## 六、与原始 PRD 的主要差异

| 原始 PRD | 当前实现 | 原因 |
|---------|---------|------|
| 本地 APScheduler 定时 | GitHub Actions cron | 电脑关机也能跑 |
| 仅 Soompi 源 | Soompi + Google News + AsianWiki | 扩展覆盖 |
| L1+L2 双层 Tab | 单层胶囊（韩娱/日娱已合并） | 简化，日娱暂蛀 |
| 浅色主题 | 暗色 v9 主题 | 用户选择 |
| 卡片含风险+事实 | 仅标题+摘要 | 精简，事实留给内部卡片 |
| JSON 去重 | SQLite 去重 | 更可靠 |
| 飞书富文本卡片+@all | 纯文本+链接 | 用户选择简化 |
| Obsidian 7 目录 | 6 目录（Layer 2 待接入） | 渐进 |
| APScheduler 定时 | GitHub Actions 2h | 云端永续 |
| 日娱 2 源 | 蛀掉，后续再开 | 先跑通韩娱 |
| 没有 AsianWiki | AsianWiki 戏剧排期目录 | 新增需求 |

---

## 七、待实现

- [ ] AsianWiki Cast/摘要接 DeepSeek 翻译
- [ ] Layer 2（本地 Obsidian 同步 + 草稿生成）接入
- [ ] 日娱源重新启用
- [ ] 归档页分页（30天/页）
- [ ] AsianWiki Movies 部分
