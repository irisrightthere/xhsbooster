#!/usr/bin/env python3
"""
merge_data.py — 爬虫数据 + 手动底库 → 生产数据

用法：python3 merge_data.py [spider_data.json] [manual_backup.md] [prod_data.json]

核心逻辑：
1. 解析 manual_backup.md 中的 Markdown 表格，提取所有剧集
2. 读取 spider_data.json（爬虫抓取结果）
3. 以 title（去空格、小写）为唯一键去重合并
4. 动态对齐：爬虫抓到具体日期 → 覆盖待定；爬虫漏抓 → 保留手动底库
5. 爬虫数据异常（< 手动底库 50%）→ 全额回滚手动底库
"""
import sys
import os
import re
import json


def parse_md_table(md_path: str) -> list[dict]:
    """解析 manual_backup.md，提取所有剧集为 dict 列表。"""
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    entries = []
    # 匹配 Markdown 表格行: | 日期 | [标题](url) | 平台 |
    # 跳过表头行（含 --- 的）
    row_pattern = re.compile(
        r'^\|\s*(.+?)\s*\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*(.+?)\s*\|',
        re.MULTILINE
    )

    for m in row_pattern.finditer(text):
        date_raw = m.group(1).strip()
        title = m.group(2).strip()
        url = m.group(3).strip()
        platform = m.group(4).strip()

        # 跳过表头/分割行
        if "---" in date_raw or not title:
            continue

        # 日期格式化
        if "待定" in date_raw or "暂无具体日期" in date_raw:
            date = "📌 待定"
        else:
            date = date_raw

        entries.append({
            "title": title,
            "url": url,
            "platform": platform,
            "date": date,
        })

    return entries


def load_spider_data(json_path: str) -> list[dict]:
    """加载爬虫 JSON 数据。"""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("spider_data.json 不是列表格式")
        return data
    except Exception as e:
        print(f"[WARNING] 爬虫数据读取失败: {e}", file=sys.stderr)
        return []


def normalize_title(t: str) -> str:
    """标题归一化：去空格、小写，用于唯一键比较。"""
    return re.sub(r'\s+', '', t).lower()


def merge(spider_data: list[dict], manual_data: list[dict]) -> list[dict]:
    """
    合并爬虫数据与手动底库。
    规则：
    - 以 title 为唯一键
    - 爬虫有具体日期 → 覆盖待定
    - 爬虫漏抓 → 保留手动底库
    - platform/url 冲突 → 信任手动底库
    """
    # 建立手动底库索引
    manual_index: dict[str, dict] = {}
    for entry in manual_data:
        key = normalize_title(entry["title"])
        manual_index[key] = entry

    # 建立爬虫数据索引
    spider_index: dict[str, dict] = {}
    for entry in spider_data:
        key = normalize_title(entry.get("title", ""))
        if key:
            spider_index[key] = entry

    # 合并
    all_keys = set(manual_index.keys()) | set(spider_index.keys())
    merged = []

    for key in all_keys:
        manual = manual_index.get(key)
        spider = spider_index.get(key)

        if manual and spider:
            # 两边都有：日期优先爬虫（如果爬虫有具体日期）
            spider_date = spider.get("date", "")
            is_tbd = "待定" in str(spider_date) or "📌" in str(spider_date)
            if not is_tbd and spider_date:
                final_date = spider_date  # 爬虫抓到了定档日期！
            else:
                final_date = manual["date"]  # 爬虫也是待定，用手动的

            entry = {
                "title": manual["title"],
                "url": manual["url"],        # url 信任手动
                "platform": manual["platform"],  # platform 信任手动
                "date": final_date,
            }
        elif manual:
            entry = dict(manual)  # 仅手动有
        else:
            # 仅爬虫有（手动底库缺失的剧）
            entry = {
                "title": spider.get("title", ""),
                "url": spider.get("url", ""),
                "platform": spider.get("platform", "TBA"),
                "date": spider.get("date", "📌 待定"),
            }

        merged.append(entry)

    # 按日期排序：待定放最后
    def sort_key(e):
        d = e.get("date", "")
        if "待定" in d:
            return (1, "")
        return (0, d)
    merged.sort(key=sort_key)

    return merged


def main():
    # 默认路径
    spider_path = sys.argv[1] if len(sys.argv) > 1 else "gh-pages/_state/spider_data.json"
    manual_path = sys.argv[2] if len(sys.argv) > 2 else "manual_backup.md"
    prod_path = sys.argv[3] if len(sys.argv) > 3 else "gh-pages/_state/prod_aw.json"

    # 1. 解析手动底库
    print(f"📖 解析手动底库: {manual_path}")
    try:
        manual_data = parse_md_table(manual_path)
        print(f"   解析到 {len(manual_data)} 条剧集")
    except Exception as e:
        print(f"[ERROR] 手动底库解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. 加载爬虫数据
    print(f"🕷️  加载爬虫数据: {spider_path}")
    spider_data = load_spider_data(spider_path)
    print(f"   加载到 {len(spider_data)} 条")

    # 3. 容错判定：爬虫数据太少 → 全额回滚
    if len(spider_data) < len(manual_data) * 0.5:
        print(f"[WARNING] 爬虫数据量异常（{len(spider_data)} < {len(manual_data) * 0.5}），已自动切换为手动底库全额保底！", file=sys.stderr)
        merged = list(manual_data)
    else:
        # 4. 合并
        merged = merge(spider_data, manual_data)

    # 5. 写入生产数据
    print(f"💾 写入生产数据: {prod_path} ({len(merged)} 条)")
    os.makedirs(os.path.dirname(prod_path) or ".", exist_ok=True)
    with open(prod_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    # 统计
    tbd = sum(1 for e in merged if "待定" in e.get("date", ""))
    print(f"   已定档: {len(merged) - tbd} 部")
    print(f"   待定: {tbd} 部")


if __name__ == "__main__":
    main()
