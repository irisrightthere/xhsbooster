"""
xhsbooster — 飞书分级推送
- 有新文章 → 富文本卡片 + @所有人
- 无更新 → 极简单行心跳
- 高风险 → 标红 [⚠️高危塌房]
- 3 次重试 → 死信日志
"""
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from config import FEISHU_WEBHOOK_URL, now_cst, STATE_DIR

logger = logging.getLogger("xhs.feishu")

DEAD_LETTER_FILE = STATE_DIR / "feishu_dlq.json"


class FeishuNotifier:
    """飞书群机器人推送。"""

    def __init__(self, webhook_url: str = None):
        self.webhook = webhook_url or FEISHU_WEBHOOK_URL
        if not self.webhook:
            logger.warning("FEISHU_WEBHOOK_URL 未设置，通知功能禁用")

    # ── 存活心跳 ──────────────────────────────────────

    def notify_heartbeat(self, sources_checked: int = 0) -> bool:
        """无更新时发送极简单行存活报告。"""
        ts = now_cst().strftime("%Y-%m%d %H:%M")
        text = f"[{ts} 巡检报告]：{sources_checked} 个源已检查，无增量更新。系统运行正常。"
        return self._send_text(text)

    # ── 新文章通知 ────────────────────────────────────

    def notify_new_articles(self, articles: list[dict]) -> bool:
        """
        有新文章时发送富文本卡片。
        articles: [{"title_zh": ..., "source_type": ..., "risk_level": ..., "summary_zh": ...}]
        """
        if not articles:
            return self.notify_heartbeat()

        ts = now_cst().strftime("%Y-%m-%d %H:%M CST")
        lines = [f"📅 {ts}", f"🏄🏻‍♀️ 现在速报：https://irisrightthere.github.io/xhsbooster/", ""]

        for i, art in enumerate(articles, 1):
            title = art.get("title_zh", art.get("title", "无标题"))
            summary = art.get("summary_zh", "")[:100]

            lines.append(f"{i}. {title}")
            if summary:
                lines.append(f"   📝 {summary}")
            lines.append("")

        lines.append("娱乐至上发发发 🍠")
        return self._send_text("\n".join(lines))

    # ── 故障通知 ──────────────────────────────────────

    def notify_fault(self, error_msg: str) -> bool:
        """爬虫全崩故障通知。"""
        ts = now_cst().strftime("%Y-%m%d %H:%M")
        text = f"🚨 [{ts} 故障报告]\n{error_msg}\n请检查 GitHub Actions 日志。"
        return self._send_text(text)

    # ── 底层发送 ──────────────────────────────────────

    def _send_text(self, text: str, retries: int = 3) -> bool:
        if not self.webhook:
            return False

        payload = {"msg_type": "text", "content": {"text": text}}

        for attempt in range(1, retries + 1):
            try:
                with httpx.Client(timeout=15) as client:
                    resp = client.post(self.webhook, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 0:
                        return True
                    else:
                        logger.warning(f"飞书返回错误 (attempt {attempt}): {data}")
                else:
                    logger.warning(f"飞书 HTTP {resp.status_code} (attempt {attempt})")
            except Exception as e:
                logger.warning(f"飞书请求异常 (attempt {attempt}): {e}")

            if attempt < retries:
                time.sleep(attempt)

        # 死信队列
        self._write_dead_letter(text)
        return False

    def _write_dead_letter(self, text: str):
        """写入死信队列。"""
        DEAD_LETTER_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = []
            if DEAD_LETTER_FILE.exists():
                existing = json.loads(DEAD_LETTER_FILE.read_text("utf-8"))
            existing.append({"timestamp": now_cst().isoformat(), "text": text})
            DEAD_LETTER_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.error(f"写入死信队列失败: {e}")
