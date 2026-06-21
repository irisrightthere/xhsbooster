"""
xhs发发发 — 72h 滑动窗口去重管理器
"""
import json
import time
import logging
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from config import (
    SEEN_URLS_FILE, DEDUP_WINDOW_HOURS, DEDUP_TITLE_SIMILARITY_THRESHOLD,
    url_hash, title_hash, now_cst,
)

logger = logging.getLogger("xhs.dedup")


class DedupManager:
    """72h 滑动窗口去重：URL 完全匹配 + 标题相似度。"""

    def __init__(self, cache_path: Path = None):
        self.cache_path = cache_path or SEEN_URLS_FILE
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: dict = {}  # {url_hash: {title, timestamp, title_hash}}
        self._load()

    # ── 持久化 ────────────────────────────────────────

    def _load(self):
        if self.cache_path.exists():
            try:
                self._entries = json.loads(self.cache_path.read_text("utf-8"))
                logger.info(f"加载去重缓存: {len(self._entries)} 条")
            except Exception as e:
                logger.warning(f"去重缓存损坏，重建: {e}")
                self._entries = {}
        else:
            self._entries = {}

    def _save(self):
        self.cache_path.write_text(
            json.dumps(self._entries, ensure_ascii=False, indent=2),
            "utf-8",
        )

    # ── 清理过期 ──────────────────────────────────────

    def prune(self):
        """清理超过 72h 的条目。"""
        cutoff = time.time() - DEDUP_WINDOW_HOURS * 3600
        stale = [h for h, e in self._entries.items() if e.get("timestamp", 0) < cutoff]
        for h in stale:
            del self._entries[h]
        if stale:
            self._save()
            logger.info(f"清理 {len(stale)} 条过期去重记录")

    # ── 去重判断 ──────────────────────────────────────

    def is_duplicate(self, url: str, title: str = "") -> bool:
        """
        两阶段去重：
        1. URL 哈希完全匹配
        2. 标题文本相似度 > 阈值
        """
        uhash = url_hash(url)
        thash = title_hash(title) if title else ""

        # 阶段 1：URL 完全匹配
        if uhash in self._entries:
            logger.debug(f"URL 重复: {title[:50]}")
            return True

        # 阶段 2：标题相似度匹配
        if thash:
            for existing in self._entries.values():
                existing_title = existing.get("title", "")
                if not existing_title:
                    continue
                similarity = SequenceMatcher(None, title.lower(), existing_title.lower()).ratio()
                if similarity >= DEDUP_TITLE_SIMILARITY_THRESHOLD:
                    logger.info(f"标题相似 ({similarity:.2f}): '{title[:60]}' ≈ '{existing_title[:60]}'")
                    return True

        return False

    # ── 标记已见 ──────────────────────────────────────

    def mark_seen(self, url: str, title: str = ""):
        """将文章标记为已抓取。"""
        uhash = url_hash(url)
        self._entries[uhash] = {
            "title": title,
            "timestamp": time.time(),
            "title_hash": title_hash(title) if title else "",
        }
        # 控制缓存大小：最多保留 50000 条
        if len(self._entries) > 50000:
            sorted_entries = sorted(self._entries.items(), key=lambda x: x[1].get("timestamp", 0))
            self._entries = dict(sorted_entries[-40000:])

        self._save()

    def __len__(self):
        return len(self._entries)
