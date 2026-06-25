"""
xhsbooster — 多源爬虫（RSS + Web 双通道）
参考 DailyBrief 分发模式：sources.json → type 路由 → 专用解析器。
"""
import json
import re
import time
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
from pathlib import Path

import httpx
import feedparser

from config import (
    SOURCES_FILE, CRAWL_RETRY_COUNT, CRAWL_RETRY_INTERVAL,
    CRAWL_MAX_ITEMS_PER_SOURCE, now_cst, normalize_to_cst,
)
from dedup import DedupManager

logger = logging.getLogger("xhs.crawler")


@dataclass
class RawArticle:
    """标准化原始文章"""
    source_id: str
    source_name: str
    l1_tab: str = "韩娱"
    title: str = ""
    url: str = ""
    content: str = ""
    published_at: str = ""    # "0621soompi" 格式
    published_ts: float = 0   # Unix 时间戳（北京时间）
    category: str = "韩娱"
    source_lang: str = "en"   # ja / ko / en
    image_url: str = ""
    is_new: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


class Crawler:
    """多源爬虫，RSS + Web 双通道，单源失败不影响全局。"""

    def __init__(self, sources_path: Path = None):
        self.sources_path = sources_path or SOURCES_FILE
        self.sources = self._load_sources()
        self.dedup = DedupManager()
        enabled = sum(1 for s in self.sources if s.get("enabled", True))
        logger.info(f"加载 {len(self.sources)} 个源（启用 {enabled} 个）")

    def _load_sources(self) -> list:
        if not self.sources_path.exists():
            return []
        try:
            sources = json.loads(self.sources_path.read_text("utf-8"))
            return [s for s in sources if s.get("enabled", True)]
        except Exception as e:
            logger.error(f"解析源配置失败: {e}")
            return []

    # ── 主编排 ──────────────────────────────────────

    def _should_fetch_asianwiki(self) -> bool:
        """AsianWiki 仅在周一 CST 8:00-8:59 或手动强制时抓取"""
        import os
        if os.environ.get("FORCE_ASIANWIKI") == "true":
            return True
        now = now_cst()
        return now.weekday() == 0 and now.hour == 8  # 周一 8:00-8:59

    def fetch_all(self) -> list[RawArticle]:
        """遍历所有源，去重，返回新文章列表。"""
        self.dedup.prune()
        all_articles = []

        for source in self.sources:
            sid = source.get("id", "unknown")
            if sid == "asianwiki" and not self._should_fetch_asianwiki():
                logger.info(f"[{sid}] 跳过（非周一8点CST，非手动强制）")
                continue
            try:
                articles = self._fetch_source(source)
                all_articles.extend(articles)
                logger.info(f"[{sid}] 抓取 {len(articles)} 篇")
            except Exception as e:
                logger.error(f"[{sid}] 失败: {e}")

        # ── CST 当日过滤 ──
        from datetime import datetime, timezone as tz, timedelta
        cst = tz(timedelta(hours=8))
        today_start = datetime.now(cst).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        today_end = today_start + 86400

        filtered = []
        for art in all_articles:
            # AsianWiki 是戏剧排期目录，不按新闻日期过滤
            if art.source_id == 'asianwiki' or (today_start <= art.published_ts < today_end):
                filtered.append(art)
        skipped = len(all_articles) - len(filtered)
        if skipped:
            logger.info(f"日期过滤: 跳过 {skipped} 篇非当日文章")
        all_articles = filtered

        # 去重 + is_new 标记
        new_articles = []
        for art in all_articles:
            is_new = self.dedup.mark_seen(
                url=art.url,
                title=art.title,
                source_id=art.source_id,
                published_ts=art.published_ts,
                image_url=art.image_url,
            )
            if is_new:
                art.is_new = True
                new_articles.append(art)

        dup_count = len(all_articles) - len(new_articles)
        logger.info(f"去重后 {len(new_articles)} 新 · 过滤 {dup_count} 重复（缓存 {len(self.dedup)} 条）")

        # ── 按发布时间降序排列（新→旧）──
        new_articles.sort(key=lambda a: a.published_ts, reverse=True)
        return new_articles

    # ── 分发 ────────────────────────────────────────

    def _fetch_source(self, source: dict) -> list[RawArticle]:
        stype = source.get("type", "rss")
        max_items = source.get("max_items", CRAWL_MAX_ITEMS_PER_SOURCE)
        if stype == "rss":
            return self._fetch_rss(source, max_items)
        if stype == "web":
            return self._fetch_web(source, max_items)
        logger.warning(f"未知源类型 {stype}，跳过 {source.get('id')}")
        return []

    # ── RSS 通道 ────────────────────────────────────

    def _fetch_rss(self, source: dict, max_items: int) -> list[RawArticle]:
        url = source.get("url", "")
        if not url:
            return []

        feed = None
        for attempt in range(1, CRAWL_RETRY_COUNT + 1):
            try:
                feed = feedparser.parse(url)
                if feed.entries:
                    break
                if hasattr(feed, 'status') and feed.status >= 400:
                    raise Exception(f"HTTP {feed.status}")
            except Exception as e:
                logger.warning(f"RSS 重试 {attempt}/{CRAWL_RETRY_COUNT}: {url} - {e}")
                if attempt < CRAWL_RETRY_COUNT:
                    time.sleep(CRAWL_RETRY_INTERVAL)

        if not feed or not feed.entries:
            logger.error(f"RSS 彻底失败: {url}")
            return []

        articles = []
        for entry in feed.entries[:max_items]:
            try:
                art = self._parse_rss_entry(entry, source)
                if art:
                    articles.append(art)
            except Exception as e:
                logger.warning(f"解析条目失败: {e}")
        return articles

    def _parse_rss_entry(self, entry, source: dict) -> Optional[RawArticle]:
        title = getattr(entry, 'title', '').strip()
        url = getattr(entry, 'link', '').strip()
        if not title or not url:
            return None

        content = ""
        if hasattr(entry, 'content'):
            for c in entry.content:
                content += c.get('value', '')
        if not content and hasattr(entry, 'summary'):
            content = entry.summary
        if not content and hasattr(entry, 'description'):
            content = entry.description

        content = self._strip_html(content)

        # 优先用原始 published 字符串（保留时区信息），parse失败再降级
        published = ""
        if hasattr(entry, 'published') and entry.published:
            published = str(entry.published)
        elif hasattr(entry, 'published_parsed') and entry.published_parsed:
            try:
                dt = datetime(*entry.published_parsed[:6])
                published = dt.isoformat()
            except Exception:
                pass

        pub_display, pub_ts = normalize_to_cst(published, source.get("id", ""), source.get("source_lang", "en"))

        thumbnail = ""
        if hasattr(entry, 'media_thumbnail'):
            for mt in entry.media_thumbnail:
                thumbnail = mt.get('url', '')
                break

        return RawArticle(
            source_id=source.get("id", ""),
            source_name=source.get("name", ""),
            l1_tab=source.get("l1_tab", "韩娱"),
            title=title,
            url=url,
            content=content[:3000],
            published_at=pub_display,
            published_ts=pub_ts,
            category=source.get("category", "韩娱"),
            source_lang=source.get("source_lang", "en"),
            image_url=thumbnail,
        )

    # ── Web 通道 ────────────────────────────────────

    def _fetch_web(self, source: dict, max_items: int) -> list[RawArticle]:
        sid = source.get("id", "")
        url = source.get("url", "")
        if sid == "oricon":
            return self._fetch_oricon(source, max_items)
        if sid == "asianwiki":
            return self._fetch_asianwiki(source, max_items)
        logger.warning(f"Web 源无解析器: {sid}")
        return []

    # ── Oricon 解析器 ──────────────────────────────

    def _fetch_oricon(self, source: dict, max_items: int) -> list[RawArticle]:
        url = source.get("url", "")
        try:
            r = httpx.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept-Language": "ja-JP,ja;q=0.9",
            }, timeout=30)
        except Exception as e:
            logger.error(f"Oricon 请求失败: {e}")
            return []

        if r.status_code != 200:
            logger.error(f"Oricon HTTP {r.status_code}")
            return []

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "lxml")
        articles = []

        # Oricon: .cont-news 内 /news/ 链接（排除分页链接）
        news_section = soup.select_one(".cont-news")
        if not news_section:
            return articles

        seen = set()
        for link in news_section.select('a[href*="/news/"]'):
            href = link.get("href", "")
            if not href.startswith("/news/") or href.endswith("/p/"):
                continue
            title = link.get_text(strip=True)
            if len(title) < 5 or title in seen:
                continue
            seen.add(title)
            if len(articles) >= max_items:
                break

            full_url = "https://www.oricon.co.jp" + href
            pub_display, pub_ts = normalize_to_cst("", source.get("id", ""), source.get("source_lang", "en"))

            # 尝试找同卡片内的图片
            img_url = ""
            card = link.find_parent("article") or link.find_parent(class_="card")
            if card:
                img_el = card.select_one("img")
                img_url = img_el.get("src", "") if img_el else ""

            articles.append(RawArticle(
                source_id=source.get("id", ""),
                source_name=source.get("name", ""),
                l1_tab=source.get("l1_tab", "日娱"),
                title=title,
                url=full_url,
                content=title,
                published_at=pub_display,
                published_ts=pub_ts,
                category=source.get("category", "日剧"),
                source_lang=source.get("source_lang", "ja"),
                image_url=img_url,
            ))
        return articles

    # ── AsianWiki 解析器 ────────────────────────────

    def _fetch_asianwiki(self, source: dict, max_items: int) -> list[RawArticle]:
        # AsianWiki 必须用 curl_cffi（httpx 拿到的是简化版页面）
        try:
            from curl_cffi import requests as cffi_requests
        except ImportError:
            logger.error("curl_cffi 未安装，无法抓取 AsianWiki")
            return []

        html = ""
        try:
            r = cffi_requests.get("https://asianwiki.com/Main_Page", impersonate="chrome120", timeout=30)
            html = r.text
        except Exception as e:
            logger.error(f"AsianWiki 主页失败: {e}")
            return []
        if not html:
            return []

        month_map = {'January':1,'February':2,'March':3,'April':4,'May':5,'June':6,
                     'July':7,'August':8,'September':9,'October':10,'November':11,'December':12}
        current_year = 2026
        if r.status_code != 200:
            logger.error(f"AsianWiki HTTP {r.status_code}")
            return []

        start = r.text.find('id="Upcoming_Dramas"')
        end = r.text.find('<h2>', start + 100) if start > 0 else -1
        if start < 0 or end < 0:
            logger.error("AsianWiki 页面结构变化")
            return []
        section = r.text[start:end]

        # 解析月度排期: "Month Day" + <a>Title</a> (Station)
        pattern = r'"([A-Z][a-z]+(?:\s+\d+(?:-\d+)?)?)"\s*<br[^>]*>\s*\*\s*<a href="(https://asianwiki\.com/[^"]+)">([^<]+)</a>\s*\(?([^)<\n]*)'
        articles_data = []
        for d, u, t, s in re.findall(pattern, section):
            t = t.strip()
            if t:
                articles_data.append((d, t, u, s.strip().strip("()").strip()))

        articles = []
        for date_str, title, drama_url, station in articles_data:
            parts = date_str.split()
            month = month_map.get(parts[0], 0)
            if month in (11, 12):
                continue
            day = int(parts[1].split('-')[0]) if len(parts) > 1 else 1
            pub_ts = datetime(current_year, month, day, 12, 0, 0,
                              tzinfo=__import__('datetime').timezone(__import__('datetime').timedelta(hours=8))).timestamp()
            # 仅有月份无具体日期 → 标记为待定，不伪造日期
            if len(parts) == 1:
                # "August", "July" 等无具体日 → 标记为待定
                pub_ts = 0
                pub_display = f"{month:02d}00{source.get('id', 'asianwiki')}"
                date_str_final = f"{parts[0]} (待定)"
            else:
                pub_display = f"{month:02d}{day:02d}{source.get('id', 'asianwiki')}"
                date_str_final = date_str

            # 详情页抓取（快速模式：5s超时，失败不阻塞）
            cast = ""
            summary = ""
            try:
                dr = cffi_requests.get(drama_url, impersonate="chrome120", timeout=8)
                if dr.status_code == 200:
                    cidx = dr.text.find('id="Cast"')
                    if cidx > 0:
                        cchunk = dr.text[cidx:cidx+3000]
                        clinks = re.findall(r'<a\s+href="/[^"]+"[^>]*>([^<]+)</a>', cchunk)
                        seen = set()
                        casts = []
                        for c in clinks:
                            c = c.strip()
                            if c and c not in seen and len(c) > 1 and 'Cast' not in c and 'Plot' not in c:
                                seen.add(c)
                                casts.append(c)
                                if len(casts) >= 4:
                                    break
                        cast = " / ".join(casts)
                    sidx = dr.text.find('id="Plot_Synopsis')
                    if sidx > 0:
                        schunk = dr.text[sidx:sidx+4000]
                        pidx = schunk.find('<p>')
                        if pidx > 0:
                            para = schunk[pidx:pidx+1500]
                            summary = re.sub(r'<[^>]+>', ' ', para)
                            summary = re.sub(r'\s+', ' ', summary).strip()[:400]
            except Exception as e:
                logger.debug(f"AsianWiki 详情页跳过: {title[:30]} - {e}")

            # 暂不翻译，后续在 main pipeline 统一处理
            title_zh = ""
            cast_zh = cast
            summary_zh = summary

            articles.append(RawArticle(
                source_id=source.get("id", ""),
                source_name=source.get("name", ""),
                l1_tab=source.get("l1_tab", "韩娱"),
                title=title,
                url=drama_url,
                content=json.dumps({
                    "title_zh": title_zh,
                    "cast": cast_zh or cast,
                    "cast_en": cast,
                    "summary_zh": summary_zh or summary,
                    "summary_en": summary,
                    "platform": station,
                    "air_date": date_str_final,
                }, ensure_ascii=False),
                published_at=pub_display,
                published_ts=pub_ts,
                category="韩剧",
                source_lang=source.get("source_lang", "en"),
            ))

        # 也抓 "2026" 待定区块
        tbd_entries = self._fetch_asianwiki_tbd(html, source)
        articles.extend(tbd_entries)

        logger.info(f"AsianWiki: {len(articles)} 部 (含{len(tbd_entries)}部待定)")
        return articles

    def _fetch_asianwiki_tbd(self, html: str, source: dict) -> list[RawArticle]:
        """抓取 AsianWiki 2026 待定剧集"""
        import re as _re
        # 搜索 "2026" 后跟 drama 链接的区块（>2026< 已失效）
        pos = html.find('2026')
        while pos > 0:
            # 确认该位置附近有 asianwiki 链接
            if 'asianwiki.com' in html[pos:pos+500]:
                break
            pos = html.find('2026', pos + 1)
        if pos < 0 or 'asianwiki.com' not in html[pos:pos+500]:
            return []
        chunk = html[pos:pos+4000]
        titles = _re.findall(r'<a href="(https://asianwiki\.com/[^"]+)"[^>]*>([^<]+)</a>', chunk)
        seen = set()
        articles = []
        for url, title in titles:
            title = title.strip()
            if title in seen or len(title) < 2:
                continue
            seen.add(title)
            pub_ts = 0  # TBD 条目无具体时间戳，避免归入当月
            articles.append(RawArticle(
                source_id=source.get("id", ""),
                source_name=source.get("name", ""),
                l1_tab=source.get("l1_tab", "韩娱"),
                title=title,
                url=url,
                content=json.dumps({"platform": "", "air_date": "2026年待定"}, ensure_ascii=False),
                published_at="0000asianwiki",
                published_ts=pub_ts,
                category="韩剧",
                source_lang=source.get("source_lang", "en"),
            ))
        return articles

    # ── 工具 ────────────────────────────────────────

    @staticmethod
    def _strip_html(text: str) -> str:
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        return text.strip()
