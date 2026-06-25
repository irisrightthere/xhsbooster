#!/usr/bin/env python3
"""
xhsbooster — 云端主编排器
用法:
  python main.py run          # 全流程：抓取 → 提炼 → 存储 → 推送 → 渲染
  python main.py dry-run      # 仅抓取，不调 API（验证源可用性）
  python main.py render       # 从缓存 JSON 重建 HTML
  python main.py render --all # 重建全部历史 HTML
"""
import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime

from config import (
    STATE_DIR, OUTPUT_DIR, today_key, timestamp_key, now_cst,
    url_hash, safe_filename,
)
from crawler import Crawler, RawArticle
from dedup import DedupManager
from api_client import get_client
from notifier import FeishuNotifier
from render import SSGRenderer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("xhs.main")


# ═══════════════════════════════════════════════════════════════
# 核心管道
# ═══════════════════════════════════════════════════════════════

def run_pipeline(dry_run: bool = False) -> int:
    """
    全流程：
    1. 爬虫抓取 → 去重
    2. DeepSeek 提炼（JSON mode, temperature=0.1）
    3. 存储 JSON 到 _state/
    4. 飞书推送
    5. HTML 渲染
    """
    date_str = today_key()
    logger.info(f"═══ xhsbooster 管道启动 · {date_str} ═══")

    # ── Step 1: 抓取 ─────────────────────────────────
    crawler = Crawler()
    articles = crawler.fetch_all()
    logger.info(f"📰 抓取完成: {len(articles)} 篇新文章")

    if dry_run:
        logger.info("🏁 Dry-run 结束")
        for art in articles:
            logger.info(f"  [{art.source_name}] {art.title[:80]}")
        return 0

    if not articles:
        logger.info("✅ 无新文章")
        notifier = FeishuNotifier()
        notifier.notify_heartbeat(len(crawler.sources))
        # 仍然渲染（显示空状态）
        renderer = SSGRenderer()
        renderer.build_all()
        return 0

    # ── Step 2: DeepSeek 提炼 ─────────────────────────
    client = get_client()
    enriched = []
    failed = 0

    for art in articles:
        logger.info(f"🤖 提炼: [{art.source_name}] {art.title[:60]}")
        result = client.extract_and_classify(art.content, art.title, art.source_lang)
        if result:
            # 合并原始元数据
            enriched.append({
                **art.to_dict(),
                **result,
                "extracted_at": now_cst().isoformat(),
            })
        else:
            failed += 1
            # 即使失败也保留原文
            enriched.append({
                **art.to_dict(),
                "title_zh": art.title,
                "source_type": art.category,
                "risk_level": "低",
                "is_blurred": False,
                "facts_list": [],
                "summary_zh": art.content[:200] if art.content else "",
                "extracted_at": now_cst().isoformat(),
                "extraction_failed": True,
            })

    logger.info(f"🤖 提炼完成: {len(enriched)} 篇（失败 {failed} 篇）")

    # ── Step 3: 存储 JSON（含二次日期校验）────────────
    today_mmdd = now_cst().strftime("%m%d")
    validated = []
    storage_skipped = 0
    for art in enriched:
        pub_at = art.get("published_at", "")
        # AsianWiki 是排期目录，不按日期过滤
        if art.get("source_id") == "asianwiki" or pub_at[:4] == today_mmdd:
            validated.append(art)
        else:
            storage_skipped += 1
            logger.warning(f"存储层拦截非当日文章: {pub_at} | {art.get('title','')[:40]}")
    if storage_skipped:
        logger.info(f"存储层过滤: 拦截 {storage_skipped} 篇非当日文章")

    # ── AsianWiki 缓存持久化：如果今天没有 AW 数据，从最近旧文件复制 ──
    has_aw = any(a.get("source_id") == "asianwiki" for a in validated)
    if not has_aw:
        # 找到最近一个含 AsianWiki 的旧 state 文件
        old_files = sorted(STATE_DIR.glob("*_articles.json"), reverse=True)
        for old_f in old_files:
            if old_f.name == f"{date_str}_articles.json":
                continue
            try:
                old_data = json.loads(old_f.read_text("utf-8"))
                old_aw = [a for a in old_data if a.get("source_id") == "asianwiki"]
                # 验证旧数据格式：必须包含有效 JSON content（含 air_date + platform）
                valid_aw = []
                skipped_fmt = 0
                for a in old_aw:
                    try:
                        extra = json.loads(a.get("content", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        extra = {}
                    # 纯文本 content（非 JSON）或缺少关键字段 → 跳过
                    if not isinstance(extra, dict) or not extra.get("air_date"):
                        skipped_fmt += 1
                        continue
                    valid_aw.append(a)
                if valid_aw:
                    validated.extend(valid_aw)
                    logger.info(f"📦 AsianWiki 缓存: 从 {old_f.name} 复制 {len(valid_aw)} 篇（跳过 {skipped_fmt} 条旧格式）")
                elif skipped_fmt:
                    logger.warning(f"📦 AsianWiki 缓存: {old_f.name} 中 {skipped_fmt} 条均为旧格式，全部跳过")
                if valid_aw:
                    break
                # 如果旧文件全是旧格式，继续尝试更早的文件
            except Exception:
                continue

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"{date_str}_articles.json"
    state_file.write_text(
        json.dumps(validated, ensure_ascii=False, indent=2),
        "utf-8",
    )
    logger.info(f"💾 存储: {state_file} ({len(validated)} 篇)")

    # ── Step 4: 飞书推送 ─────────────────────────────
    notifier = FeishuNotifier()
    # 飞书仅推送新闻源，过滤 AsianWiki 排期
    news_articles = [a for a in enriched if a.get("source_id") != "asianwiki"]
    notifier.notify_new_articles(news_articles)
    logger.info("📨 飞书推送完成")

    # ── Step 5: HTML 渲染 ────────────────────────────
    renderer = SSGRenderer()
    renderer.build_all()
    logger.info("🌐 HTML 渲染完成")

    # 汇总
    high_risk = sum(1 for a in enriched if a.get("risk_level") == "高")
    logger.info(f"═══ 管道完成: {len(enriched)} 篇, 高风险 {high_risk} 篇 ═══")
    return 0


def render_command(rebuild_all: bool = False) -> int:
    """重建 HTML。"""
    renderer = SSGRenderer()
    renderer.build_all()
    logger.info("✅ HTML 重建完成")
    return 0


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="xhsbooster — 韩娱资讯自动化系统")
    sub = parser.add_subparsers(dest="command", help="子命令")

    # run
    p_run = sub.add_parser("run", help="全流程：抓取 → 提炼 → 通知 → 渲染")
    p_run.add_argument("--dry-run", "-n", action="store_true", help="仅抓取验证，不调 API")

    # render
    p_render = sub.add_parser("render", help="从缓存 JSON 重建 HTML")
    p_render.add_argument("--all", action="store_true", help="重建全部历史")

    args = parser.parse_args()

    if args.command == "run":
        sys.exit(run_pipeline(dry_run=args.dry_run))
    elif args.command == "render":
        sys.exit(render_command(rebuild_all=args.all))
    else:
        # 默认 run
        sys.exit(run_pipeline())

if __name__ == "__main__":
    main()
