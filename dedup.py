"""
xhs发发发 — SQLite 去重管理器
MD5(url) 主键，自动 is_new 标记，72h 自动清理。
"""
import sqlite3
import time
import logging
from pathlib import Path

from config import DEDUP_DB_PATH, DEDUP_WINDOW_HOURS, md5_hash

logger = logging.getLogger("xhs.dedup")


class DedupManager:
    """SQLite 去重：MD5(url) 做主键，记录首次抓取时间、图片 URL。"""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or DEDUP_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_table()

    def _init_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS dedup (
                url_hash TEXT PRIMARY KEY,
                title TEXT,
                published_ts REAL,
                source_id TEXT,
                first_seen REAL,
                image_url TEXT
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_published ON dedup(published_ts)
        """)
        self._conn.commit()

    # ── 清理过期 ──────────────────────────────────────

    def prune(self):
        """清理超过 72h 的旧记录。"""
        cutoff = time.time() - DEDUP_WINDOW_HOURS * 3600
        cur = self._conn.execute("DELETE FROM dedup WHERE first_seen < ?", (cutoff,))
        self._conn.commit()
        if cur.rowcount:
            logger.info(f"清理 {cur.rowcount} 条过期去重记录")

    # ── 是否重复 ──────────────────────────────────────

    def is_duplicate(self, url: str) -> bool:
        """检查 URL 是否已存在。"""
        uhash = md5_hash(url)
        cur = self._conn.execute("SELECT 1 FROM dedup WHERE url_hash = ?", (uhash,))
        return cur.fetchone() is not None

    # ── 标记已见，返回 is_new ────────────────────────

    def mark_seen(self, url: str, title: str = "", source_id: str = "",
                   published_ts: float = 0, image_url: str = "") -> bool:
        """
        尝试插入新记录。成功 → True（新文章）；冲突 → False（重复）。
        """
        uhash = md5_hash(url)
        try:
            self._conn.execute(
                "INSERT INTO dedup VALUES (?, ?, ?, ?, ?, ?)",
                (uhash, title, published_ts, source_id, time.time(), image_url),
            )
            self._conn.commit()
            return True  # 新文章
        except sqlite3.IntegrityError:
            return False  # 重复

    def __len__(self):
        cur = self._conn.execute("SELECT COUNT(*) FROM dedup")
        return cur.fetchone()[0]

    def close(self):
        self._conn.close()
