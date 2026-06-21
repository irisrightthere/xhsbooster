"""
xhsbooster — 静态 HTML 渲染器（单层源胶囊 Tab）
卡片格式：标题 / 源,时间 / --- / 摘要
"""
import json
import logging
from pathlib import Path

from config import OUTPUT_DIR, STATE_DIR, today_key

logger = logging.getLogger("xhs.render")

# ═══════════════════════════════════════════════════════════════
# CSS
# ═══════════════════════════════════════════════════════════════

CSS = r"""
:root {
  --bg: #fffdf7; --card: #ffffff; --text: #2c2416; --text2: #6b5e4a;
  --accent: #ff6b35; --border: #e8e0d5; --tag-bg: #f5efe4;
  --new-badge: #dc2626; --shadow: 0 1px 3px rgba(0,0,0,.06);
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #1a1814; --card: #24211b; --text: #e8e0d5; --text2: #a09682;
    --border: #3a3428; --tag-bg: #2a2620; --shadow: 0 1px 3px rgba(0,0,0,.3); }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font: 15px/1.6 -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  background: var(--bg); color: var(--text); max-width: 720px; margin: 0 auto; padding: 20px; }
/* ── DailyBrief 风格 Header ── */
.report-header { margin-bottom: 1.25rem; }
.eyebrow { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.2em;
  color: var(--text2); font-weight: 500; }
.report-title { font-size: 2.2rem; font-weight: 700; margin: 0.4rem 0 0.6rem;
  letter-spacing: -0.02em; line-height: 1.1; color: var(--text); }
.archive-link { display: inline-block; margin-bottom: 1rem; font-size: 0.85rem;
  color: var(--text2); text-decoration: none; border-bottom: 1px dashed var(--border);
  padding-bottom: 1px; }
.archive-link:hover { color: var(--accent); border-bottom-style: solid; }

/* 源胶囊 Tab */
.tab-bar { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
.tab-btn { padding: 6px 16px; border: none; border-radius: 14px; cursor: pointer;
  font-size: 13px; color: var(--text2); background: var(--tag-bg); transition: .15s; }
.tab-btn:hover { background: var(--border); }
.tab-btn.active { background: var(--accent); color: #fff; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }

/* 卡片 */
.card { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 18px 20px; margin-bottom: 14px; box-shadow: var(--shadow); }
.card h3 { font-size: 16px; margin-bottom: 4px; }
.card h3 a { color: var(--text); text-decoration: none; }
.card h3 a:hover { color: var(--accent); }
.card .meta { font-size: 12px; color: var(--text2); margin-bottom: 6px; }
.card .separator { border: none; border-top: 1px solid var(--border); margin: 8px 0; }
.card .summary { font-size: 14px; color: var(--text); line-height: 1.7; }

/* NEW badge */
.badge-new { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px;
  font-weight: 600; background: var(--new-badge); color: #fff;
  animation: blink 1.2s ease-in-out infinite; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:.4} }

/* Archive */
.archive-list { list-style: none; }
.archive-list li { display: flex; justify-content: space-between; align-items: center;
  padding: 10px 0; border-bottom: 1px solid var(--border); }
.archive-list a { color: var(--accent); text-decoration: none; font-size: 15px; }
.archive-list .size { font-size: 13px; color: var(--text2); }
.archive-meta { font-size: 13px; color: var(--text2); margin-bottom: 20px; }

.empty-state { text-align: center; padding: 40px; color: var(--text2); }
footer { text-align: center; padding: 30px 0 20px; font-size: 12px; color: var(--text2);
  border-top: 1px solid var(--border); margin-top: 30px; }
footer a { color: var(--accent); text-decoration: none; }
"""

# ═══════════════════════════════════════════════════════════════
# JS
# ═══════════════════════════════════════════════════════════════

JS = r"""
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.tab-bar').forEach(function(bar) {
    bar.addEventListener('click', function(e) {
      var btn = e.target.closest('.tab-btn');
      if (!btn) return;
      var sid = btn.dataset.sid;
      bar.querySelectorAll('.tab-btn').forEach(function(b){ b.classList.remove('active'); });
      btn.classList.add('active');
      var container = bar.parentElement;
      container.querySelectorAll('.tab-panel').forEach(function(p){ p.classList.remove('active'); });
      var panel = container.querySelector('.tab-panel[data-sid="' + sid + '"]');
      if (panel) panel.classList.add('active');
    });
  });
});
"""


class SSGRenderer:
    """单层源胶囊 Tab 静态网页生成器。"""

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.output_dir / "_state"

    def _load_articles(self, date_str: str = None) -> list[dict]:
        if date_str is None:
            date_str = today_key()
        data_file = self.state_dir / f"{date_str}_articles.json"
        if not data_file.exists():
            return []
        try:
            articles = json.loads(data_file.read_text("utf-8"))
        except Exception as e:
            logger.error(f"读取数据失败: {e}")
            return []

        today_mmdd = today_key()[5:7] + today_key()[7:9]
        filtered = [a for a in articles if a.get("published_at", "")[:4] == today_mmdd]
        skipped = len(articles) - len(filtered)
        if skipped:
            logger.info(f"渲染层拦截 {skipped} 篇非当日文章")
        return filtered

    def _scan_dates(self) -> list[str]:
        dates = []
        for f in sorted(self.state_dir.glob("*_articles.json"), reverse=True):
            name = f.stem.replace("_articles", "")
            if len(name) == 8 and name.isdigit():
                dates.append(name)
        return dates

    def build_index(self, date_str: str = None) -> Path:
        if date_str is None:
            date_str = today_key()
        articles = self._load_articles(date_str)
        html = self._render_index(articles, date_str)
        out = self.output_dir / "index.html"
        out.write_text(html, "utf-8")
        logger.info(f"首页渲染: {out} ({len(articles)} 篇)")
        return out

    def build_archive(self) -> Path:
        dates = self._scan_dates()
        out = self.output_dir / "archive.html"
        html = self._render_archive(dates)
        out.write_text(html, "utf-8")
        logger.info(f"归档渲染: {out} ({len(dates)} 天)")
        return out

    def build_all(self) -> tuple[Path, Path]:
        return self.build_index(), self.build_archive()

    # ── 首页 ──────────────────────────────────────

    def _render_index(self, articles: list[dict], date_str: str) -> str:
        grouped = self._group_by_source(articles)
        sids = list(grouped.keys())

        date_display = f"{date_str[:4]}-{date_str[5:7]}-{date_str[7:9]}"
        body = f'<header class="report-header"><span class="eyebrow">🍠 xhsbooster</span><h1 class="report-title">{date_display}</h1><a class="archive-link" href="archive.html">← 往期回顾</a></header>\n'

        if not grouped:
            body += '<div class="empty-state">📭 暂无内容</div>'
            return self._wrap_html(f"xhsbooster · {date_display}", body)

        # 源胶囊 Tab
        body += '<div class="tab-bar">\n'
        for i, sid in enumerate(sids):
            active = ' active' if i == 0 else ''
            name = grouped[sid][0].get("source_name", sid) if grouped[sid] else sid
            body += f'  <button class="tab-btn{active}" data-sid="{sid}">{name} ({len(grouped[sid])})</button>\n'
        body += '</div>\n'

        # Tab 面板
        for i, sid in enumerate(sids):
            active = ' active' if i == 0 else ''
            body += f'<div class="tab-panel{active}" data-sid="{sid}">\n'
            for art in grouped[sid]:
                body += self._render_card(art)
            body += '</div>\n'

        return self._wrap_html(f"xhsbooster · {date_display}", body)

    def _render_card(self, art: dict) -> str:
        title = art.get("title_zh") or art.get("title", "无标题")
        url = art.get("url", "#")
        summary = art.get("summary_zh", "")
        source_name = art.get("source_name", "")
        published_at = art.get("published_at", "")
        is_new = art.get("is_new", False)

        html = '<div class="card">\n'
        # 标题
        html += f'  <h3><a href="{url}" target="_blank" rel="noopener">{title}</a></h3>\n'
        # 源, 时间
        html += '  <div class="meta">\n'
        if is_new:
            html += '    <span class="badge-new">NEW</span>\n'
        html += f'    <span>{source_name}</span>\n'
        if published_at:
            html += f'    <span>· {published_at}</span>\n'
        html += '  </div>\n'
        # 分隔 + 摘要
        if summary:
            html += '  <hr class="separator">\n'
            html += f'  <div class="summary">{summary}</div>\n'
        html += '</div>\n'
        return html

    def _group_by_source(self, articles: list[dict]) -> dict[str, list[dict]]:
        order = {"soompi": 0, "asianwiki": 1, "google-kpop": 2, "google-jdrama": 3, "oricon": 4}
        grouped: dict[str, list[dict]] = {}
        for art in articles:
            sid = art.get("source_id", "other")
            grouped.setdefault(sid, []).append(art)
        return dict(sorted(grouped.items(), key=lambda kv: order.get(kv[0], 99)))

    # ── 归档（DailyBrief 风格）───────────────────

    def _render_archive(self, dates: list[str]) -> str:
        body = '<header class="report-header"><span class="eyebrow">📦 往期回顾</span><h1 class="report-title">Archive</h1><a class="archive-link" href="index.html">← 返回首页</a></header>\n'
        body += f'<p class="archive-meta">{len(dates)} 份报告 · 最新在前 · 生成于 {today_key()}</p>\n'

        if not dates:
            body += '<div class="empty-state">暂无历史报告</div>'
            return self._wrap_html("xhsbooster · 历史归档", body)

        body += '<ul class="archive-list">\n'
        for d in dates:
            display = f"{d[:4]}-{d[5:7]}-{d[7:9]}"
            body += f'  <li><a href="?date={d}">{display}</a><span class="size"></span></li>\n'
        body += '</ul>\n'

        return self._wrap_html("xhsbooster · 历史归档", body)

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
<footer>xhsbooster · 韩娱资讯自动化 · DeepSeek 驱动 · <a href="archive.html">往期回顾</a></footer>
<script>{JS}</script>
</body>
</html>"""
