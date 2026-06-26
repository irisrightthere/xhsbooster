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
        if "暂无具体日期" in date_raw:
            # "7月 (暂无具体日期)" → 保留原样，后续渲染时归入对应月份
            date = date_raw
        elif "待定" in date_raw:
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


def is_concrete_date(d: str) -> bool:
    """
    日期是否具体到「月+日」（非 TBA/待定/纯年份/空）。
    - 接受: "1月22日", "6月11日", "June 22" 等
    - 拒绝: "TBA", "2026", "2026年待定", "待定", "", "6月"（无日）
    """
    if not d or not str(d).strip():
        return False
    s = str(d).strip()
    # 拒绝 TBA / 待定 / 纯年份 / 未知
    if re.search(r'TBA|待定|📌|unknown|undecided', s, re.IGNORECASE):
        return False
    # 拒绝纯 "2026" 或 "2026年"（无具体月日）
    if re.fullmatch(r'2026\s*(年\s*)?', s):
        return False
    # 必须包含 X月Y日 或 Month Day 模式
    if re.search(r'\d{1,2}月\s*\d{1,2}日', s):
        return True
    if re.search(r'[A-Z][a-z]+\s+\d+', s):
        return True
    return False


def merge(spider_data: list[dict], manual_data: list[dict]) -> list[dict]:
    """
    合并爬虫数据与手动底库。
    规则：
    - 手动底库逐条处理，允许同标题多条目（如 8月定档 + 待定 同时保留）
    - 爬虫有具体日期 → 覆盖手动对应条目
    - 爬虫漏抓 → 保留手动底库
    - platform/url 冲突 → 信任手动底库
    """
    # 建立爬虫数据索引（仅用于增强手动条目）
    spider_index: dict[str, dict] = {}
    for entry in spider_data:
        key = normalize_title(entry.get("title", ""))
        if key:
            spider_index[key] = entry

    merged = []
    matched_spider_keys: set = set()

    # 逐条处理手动底库（不去重，允许同标题多条）
    for manual in manual_data:
        key = normalize_title(manual["title"])
        spider = spider_index.get(key)

        if spider:
            # 爬虫有具体日期 → 覆盖手动
            spider_date = spider.get("date", "")
            if is_concrete_date(spider_date):
                # 如果手动是待定，且同标题已有其他定档条目 → 保留待定（不去重）
                if not is_concrete_date(manual["date"]):
                    has_dated_sibling = any(
                        normalize_title(m["title"]) == key and is_concrete_date(m["date"])
                        for m in manual_data if m is not manual
                    )
                    if has_dated_sibling:
                        final_date = manual["date"]  # 保留待定，另有一条已定档
                    else:
                        final_date = spider_date
                else:
                    final_date = spider_date  # 手动也是定档 → 蜘蛛覆盖
            else:
                final_date = manual["date"]
            matched_spider_keys.add(key)
            entry = {
                "title": manual["title"],
                "url": manual["url"],
                "platform": manual["platform"],
                "date": final_date,
            }
        else:
            entry = dict(manual)

        merged.append(entry)

    # 仅爬虫有的条目（手动底库缺失）
    for key, spider in spider_index.items():
        if key not in matched_spider_keys:
            spider_date_raw = spider.get("date", "")
            spider_platform = spider.get("platform", "")
            date_final = spider_date_raw if is_concrete_date(spider_date_raw) else "📌 待定"
            platform_final = spider_platform if spider_platform and str(spider_platform).strip().upper() != "TBA" else "TBA"
            merged.append({
                "title": spider.get("title", ""),
                "url": spider.get("url", ""),
                "platform": platform_final,
                "date": date_final,
            })

    # 按日期排序：具体日期 → 月份待定 → 完全待定
    def sort_key(e):
        d = e.get("date", "")
        if "待定" in d and "暂无具体日期" not in d:
            return (2, "")  # 纯待定放最后
        if "暂无具体日期" in d:
            # 月份待定：排在对应月份的最后
            import re as _re
            m = _re.search(r'(\d{1,2})月', d)
            month = int(m.group(1)) if m else 13
            return (1, f"{month:02d}")  # 月份待定排在具体日期之后
        return (0, d)  # 具体日期排最前
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
