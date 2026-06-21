"""
xhs发发发 — RSS 多源爬虫
读取 sources.json，按类型分发抓取，返回标准化文章列表。
"""
import json
import time
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
from pathlib import Path

import httpx
import feedparser

from config import (
    SOURCES_FILE, CRAWL_TIMEOUT, CRAWL_RETRY_COUNT, CRAWL_RETRY_INTERVAL,
    CRAWL_MAX_ITEMS_PER_SOURCE, now_cst, url_hash,
)
from dedup import DedupManager

logger = logging.getLogger("xhs.crawler")


@dataclass
class RawArticle:
    """标准化原始文章"""
    source_id: str
    source_name: str
    title: str
    url: str
    content: str          # 正文/摘要合并
    published_at: str     # ISO 格式时间
    category: str = "韩娱"
    thumbnail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class Crawler:
    """多源 RSS 爬虫，单源失败不影响全局。"""

    def __init__(self, sources_path: Path = None):
        self.sources_path = sources_path or SOURCES_FILE
        self.sources = self._load_sources()
        self.dedup = DedupManager()
        logger.info(f"加载 {len(self.sources)} 个信息源（启用 {sum(1 for s in self.sources if s.get('enabled', True))} 个）")

    def _load_sources(self) -> list:
        if not self.sources_path.exists():
            logger.error(f"源配置文件不存在: {self.sources_path}")
            return []
        try:
            sources = json.loads(self.sources_path.read_text("utf-8"))
            return [s for s in sources if s.get("enabled", True)]
        except Exception as e:
            logger.error(f"解析源配置失败: {e}")
            return []

    # ── 抓取分发 ──────────────────────────────────────

    def fetch_all(self) -> list[RawArticle]:
        """遍历所有源，返回去重后的新文章列表。"""
        self.dedup.prune()
        all_articles = []

        for source in self.sources:
            sid = source.get("id", "unknown")
            try:
                articles = self._fetch_source(source)
                all_articles.extend(articles)
                logger.info(f"[{sid}] 抓取 {len(articles)} 篇")
            except Exception as e:
                logger.error(f"[{sid}] 抓取失败: {e}")

        # 去重
        new_articles = []
        for art in all_articles:
            if not self.dedup.is_duplicate(art.url, art.title):
                new_articles.append(art)
                self.dedup.mark_seen(art.url, art.title)

        dup_count = len(all_articles) - len(new_articles)
        logger.info(f"去重后: {len(new_articles)} 篇新文章（过滤 {dup_count} 篇重复）")
        return new_articles

    def _fetch_source(self, source: dict) -> list[RawArticle]:
        """按源类型分发。"""
        stype = source.get("type", "rss")
        max_items = source.get("max_items", CRAWL_MAX_ITEMS_PER_SOURCE)

        if stype == "rss":
            return self._fetch_rss(source, max_items)
        else:
            logger.warning(f"未知源类型: {stype}，跳过 {source.get('id')}")
            return []

    # ── RSS 抓取 ──────────────────────────────────────

    def _fetch_rss(self, source: dict, max_items: int) -> list[RawArticle]:
        """抓取 RSS/Atom feed，带重试。"""
        url = source.get("url", "")
        if not url:
            return []

        feed = None
        for attempt in range(1, CRAWL_RETRY_COUNT + 1):
            try:
                feed = feedparser.parse(url)
                if feed.entries:
                    break
                # feedparser 有时不抛异常但返回空
                if hasattr(feed, 'status') and feed.status >= 400:
                    raise Exception(f"HTTP {feed.status}")
            except Exception as e:
                logger.warning(f"RSS 抓取失败 (attempt {attempt}/{CRAWL_RETRY_COUNT}): {url} - {e}")
                if attempt < CRAWL_RETRY_COUNT:
                    time.sleep(CRAWL_RETRY_INTERVAL)

        if not feed or not feed.entries:
            logger.error(f"RSS 抓取彻底失败: {url}")
            return []

        articles = []
        for entry in feed.entries[:max_items]:
            try:
                art = self._parse_entry(entry, source)
                if art:
                    articles.append(art)
            except Exception as e:
                logger.warning(f"解析条目失败: {getattr(entry, 'link', '?')} - {e}")
        return articles

    def _parse_entry(self, entry, source: dict) -> Optional[RawArticle]:
        """将 feedparser entry 转为 RawArticle。"""
        title = getattr(entry, 'title', '').strip()
        url = getattr(entry, 'link', '').strip()
        if not title or not url:
            return None

        # 内容：优先 content:encoded > content > summary > description
        content = ""
        if hasattr(entry, 'content'):
            for c in entry.content:
                content += c.get('value', '')
        if not content and hasattr(entry, 'summary'):
            content = entry.summary
        if not content and hasattr(entry, 'description'):
            content = entry.description

        # 去除 HTML 标签（简单处理）
        content = self._strip_html(content)

        # 发布时间
        published = ""
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            try:
                dt = datetime(*entry.published_parsed[:6])
                published = dt.isoformat()
            except Exception:
                pass
        if not published and hasattr(entry, 'published'):
            published = str(entry.published)

        # 缩略图
        thumbnail = ""
        if hasattr(entry, 'media_thumbnail'):
            for mt in entry.media_thumbnail:
                thumbnail = mt.get('url', '')
                break

        return RawArticle(
            source_id=source.get("id", ""),
            source_name=source.get("name", ""),
            title=title,
            url=url,
            content=content[:3000],  # 限制长度
            published_at=published,
            category=source.get("category", "韩娱"),
            thumbnail=thumbnail,
        )

    @staticmethod
    def _strip_html(text: str) -> str:
        """去除 HTML 标签，保留文本。"""
        import re
        # 移除 script/style
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)
        # 替换 HTML 实体
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
        # 合并多余空白
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        return text.strip()
