"""
xhs发发发 — 静态 HTML 渲染器（SSG）
自包含 HTML（CSS/JS 内联），可直接部署到 GitHub Pages。
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import OUTPUT_DIR, STATE_DIR, now_cst, today_key, CST

logger = logging.getLogger("xhs.render")

# ═══════════════════════════════════════════════════════════════
# CSS（内联，仿 DailyBrief 自包含风格）
# ═══════════════════════════════════════════════════════════════

CSS = r"""
:root {
  --bg: #fffdf7; --card: #ffffff; --text: #2c2416; --text2: #6b5e4a;
  --accent: #ff6b35; --accent2: #ff8c5a; --border: #e8e0d5;
  --tag-bg: #f5efe4; --new-badge: #ff4444; --risk-high: #dc2626;
  --shadow: 0 1px 3px rgba(0,0,0,.06);
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #1a1814; --card: #24211b; --text: #e8e0d5; --text2: #a09682;
    --border: #3a3428; --tag-bg: #2a2620; --shadow: 0 1px 3px rgba(0,0,0,.3); }
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body { font: 15px/1.6 -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  background: var(--bg); color: var(--text); max-width: 960px; margin: 0 auto; padding: 20px; }

header { text-align: center; padding: 32px 0 20px; border-bottom: 2px solid var(--accent); margin-bottom: 24px; }
header h1 { font-size: 28px; color: var(--accent); }
header .date { font-size: 13px; color: var(--text2); margin-top: 4px; }

/* Tabs */
.tab-bar { display: flex; gap: 0; border-bottom: 2px solid var(--border); margin-bottom: 20px; overflow-x: auto; }
.tab-btn { padding: 10px 20px; border: none; background: none; cursor: pointer;
  font-size: 14px; color: var(--text2); border-bottom: 2px solid transparent; margin-bottom: -2px;
  white-space: nowrap; transition: .15s; }
.tab-btn:hover, .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab-panel { display: none; }
.tab-panel.active { display: block; }

/* Cards */
.card { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 18px 20px; margin-bottom: 14px; box-shadow: var(--shadow); position: relative; }
.card h3 { font-size: 16px; margin-bottom: 6px; }
.card h3 a { color: var(--text); text-decoration: none; }
.card h3 a:hover { color: var(--accent); }
.card .meta { font-size: 12px; color: var(--text2); margin-bottom: 8px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.card .summary { font-size: 14px; color: var(--text); line-height: 1.7; }
.card .facts { margin-top: 10px; padding: 10px 14px; background: var(--tag-bg); border-radius: 6px; font-size: 13px; }
.card .facts li { margin-left: 16px; margin-bottom: 4px; }

/* Badges */
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge-new { background: var(--new-badge); color: #fff; animation: blink 1.2s ease-in-out infinite; }
.badge-risk-high { background: var(--risk-high); color: #fff; }
.badge-risk-mid { background: #f59e0b; color: #fff; }
.badge-risk-low { background: #10b981; color: #fff; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:.4} }

/* Archive */
.pagination { display: flex; gap: 10px; justify-content: center; margin: 30px 0; flex-wrap: wrap; }
.pagination a, .pagination span { padding: 8px 16px; border: 1px solid var(--border); border-radius: 6px;
  text-decoration: none; color: var(--accent); font-size: 14px; }
.pagination a:hover { background: var(--accent); color: #fff; }
.pagination .current { background: var(--accent); color: #fff; }

footer { text-align: center; padding: 30px 0 20px; font-size: 12px; color: var(--text2); border-top: 1px solid var(--border); margin-top: 30px; }
.empty-state { text-align: center; padding: 40px; color: var(--text2); }
"""

# ═══════════════════════════════════════════════════════════════
# JS（内联）
# ═══════════════════════════════════════════════════════════════

JS = r"""
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.tab-bar').forEach(function(bar) {
    bar.addEventListener('click', function(e) {
      var btn = e.target.closest('.tab-btn');
      if (!btn) return;
      var tabId = btn.dataset.tab;
      bar.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      var container = bar.parentElement;
      container.querySelectorAll('.tab-panel').forEach(function(p) { p.classList.remove('active'); });
      var panel = container.querySelector('.tab-panel[data-tab="' + tabId + '"]');
      if (panel) panel.classList.add('active');
    });
  });
});
"""


class SSGRenderer:
    """静态网页生成器。"""

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.output_dir / "_state"

    # ── 数据读取 ──────────────────────────────────────

    def _load_articles(self, date_str: str = None) -> list[dict]:
        """加载指定日期的文章 JSON。"""
        if date_str is None:
            date_str = today_key()
        data_file = self.state_dir / f"{date_str}_articles.json"
        if not data_file.exists():
            logger.warning(f"数据文件不存在: {data_file}")
            return []
        try:
            return json.loads(data_file.read_text("utf-8"))
        except Exception as e:
            logger.error(f"读取数据失败: {e}")
            return []

    def _scan_available_dates(self) -> list[str]:
        """扫描所有可用日期。"""
        dates = []
        for f in sorted(self.state_dir.glob("*_articles.json"), reverse=True):
            name = f.stem.replace("_articles", "")
            if len(name) == 8 and name.isdigit():
                dates.append(name)
        return dates

    # ── HTML 构建 ─────────────────────────────────────

    def build_index(self, date_str: str = None) -> Path:
        """渲染首页 HTML。"""
        if date_str is None:
            date_str = today_key()
        articles = self._load_articles(date_str)
        html = self._render_page(articles, date_str, is_index=True)
        out = self.output_dir / "index.html"
        out.write_text(html, "utf-8")
        logger.info(f"首页已渲染: {out} ({len(articles)} 篇文章)")
        return out

    def build_archive(self) -> Path:
        """渲染历史归档页（按月分页，30天/页）。"""
        dates = self._scan_available_dates()
        out = self.output_dir / "archive.html"
        html = self._render_archive_page(dates)
        out.write_text(html, "utf-8")
        logger.info(f"归档页已渲染: {out} ({len(dates)} 天)")
        return out

    def build_all(self) -> tuple[Path, Path]:
        """重建首页 + 归档页。"""
        return self.build_index(), self.build_archive()

    # ── 页面组装 ──────────────────────────────────────

    def _render_page(self, articles: list[dict], date_str: str, is_index: bool = False) -> str:
        """组装完整 HTML 页面。"""
        # 按源分组
        tabs = self._group_by_source(articles)

        # 当前轮次 NEW 文章 URL 集合（从最新数据中标记）
        new_urls = set()
        if is_index:
            for art in articles:
                url = art.get("url", "")
                if url:
                    new_urls.add(url)

        # 渲染内容
        date_display = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        body = f'<header><h1>🍠 xhs发发发</h1><div class="date">{date_display} · 韩娱资讯速报</div></header>\n'
        body += self._render_tabs(tabs, new_urls)

        return self._wrap_html(f"xhs发发发 · {date_display}", body)

    def _render_archive_page(self, dates: list[str]) -> str:
        """渲染归档索引页。"""
        body = '<header><h1>📦 历史归档</h1></header>\n'

        # 按月份分组
        months: dict[str, list[str]] = {}
        for d in dates:
            month = d[:6]  # YYYYMM
            months.setdefault(month, []).append(d)

        for month in sorted(months, reverse=True):
            month_dates = months[month]
            y, m = month[:4], month[4:6]
            body += f'<h3 style="margin-top:24px;color:var(--accent)">{y}年{m}月</h3>\n'
            body += '<div style="display:flex;flex-wrap:wrap;gap:8px;margin:12px 0">\n'
            for d in sorted(month_dates, reverse=True):
                display = f"{d[4:6]}/{d[6:8]}"
                body += f'<a href="?date={d}" style="padding:8px 14px;border:1px solid var(--border);'
                body += f'border-radius:6px;text-decoration:none;color:var(--accent);font-size:13px">{display}</a>\n'
            body += '</div>\n'

        return self._wrap_html("xhs发发发 · 历史归档", body)

    def _group_by_source(self, articles: list[dict]) -> dict[str, list[dict]]:
        """按源分组，Soompi 排第一。"""
        tabs: dict[str, list[dict]] = {}
        for art in articles:
            sid = art.get("source_id", "other")
            tabs.setdefault(sid, []).append(art)

        # 排序：Soompi 第一，其余按字母
        def sort_key(item: tuple[str, list]) -> tuple:
            k = item[0]
            if k == "soompi":
                return (0, k)
            return (1, k)

        return dict(sorted(tabs.items(), key=sort_key))

    def _render_tabs(self, tabs: dict[str, list[dict]], new_urls: set) -> str:
        """渲染 Tab 切换区域。"""
        if not tabs:
            return '<div class="empty-state">📭 暂无内容，等待下一轮抓取...</div>'

        source_ids = list(tabs.keys())

        # Tab 按钮
        html = '<div class="tab-bar">\n'
        for i, sid in enumerate(source_ids):
            active = ' active' if i == 0 else ''
            name = tabs[sid][0].get("source_name", sid) if tabs[sid] else sid
            html += f'  <button class="tab-btn{active}" data-tab="{sid}">[{name}] ({len(tabs[sid])})</button>\n'
        html += '</div>\n'

        # Tab 面板
        for i, sid in enumerate(source_ids):
            active = ' active' if i == 0 else ''
            html += f'<div class="tab-panel{active}" data-tab="{sid}">\n'
            for art in tabs[sid]:
                html += self._render_card(art, art.get("url", "") in new_urls)
            html += '</div>\n'

        return html

    def _render_card(self, art: dict, is_new: bool) -> str:
        """渲染单篇文章卡片。"""
        title = art.get("title_zh") or art.get("title", "无标题")
        url = art.get("url", "#")
        summary = art.get("summary_zh", "")
        risk = art.get("risk_level", "低")
        source_type = art.get("source_type", "韩娱")
        facts = art.get("facts_list", [])

        # 风险徽章
        risk_class = {"高": "badge-risk-high", "中": "badge-risk-mid"}.get(risk, "badge-risk-low")

        html = '<div class="card">\n'
        html += f'  <h3><a href="{url}" target="_blank" rel="noopener">{title}</a></h3>\n'
        html += '  <div class="meta">\n'

        # NEW 标记
        if is_new:
            html += '    <span class="badge badge-new">NEW</span>\n'

        html += f'    <span class="badge {risk_class}">风险:{risk}</span>\n'
        html += f'    <span>{source_type}</span>\n'
        html += '  </div>\n'

        if summary:
            html += f'  <div class="summary">{summary}</div>\n'

        if facts:
            html += '  <ul class="facts">\n'
            for f in facts[:5]:
                html += f'    <li>{f}</li>\n'
            html += '  </ul>\n'

        html += '</div>\n'
        return html

    @staticmethod
    def _wrap_html(title: str, body: str) -> str:
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>
{body}
<footer>xhs发发发 · 韩娱资讯自动化 · 由 DeepSeek 驱动 · <a href="archive.html" style="color:var(--accent)">历史归档</a></footer>
<script>{JS}</script>
</body>
</html>"""
