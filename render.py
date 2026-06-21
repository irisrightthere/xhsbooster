"""
xhsbooster — 静态 HTML 渲染器（两层 Tab：L1 大类 + L2 源胶囊）
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

/* ── L1 大类标签（大字 + 底线高亮）── */
.l1-bar { display: flex; gap: 24px; border-bottom: 2px solid var(--border); margin-bottom: 12px; }
.l1-btn { padding: 10px 24px; border: none; background: none; cursor: pointer;
  font-size: 15px; font-weight: 700; color: var(--text2);
  border-bottom: 3px solid transparent; margin-bottom: -2px; transition: .15s; }
.l1-btn:hover, .l1-btn.active { color: var(--accent); border-bottom-color: var(--accent); }

/* ── L2 源胶囊（小字 + 圆角背景）── */
.l2-bar { display: flex; gap: 8px; margin: 12px 0 20px; padding-left: 8px; flex-wrap: wrap; }
.l2-btn { padding: 5px 14px; border: none; border-radius: 14px; cursor: pointer;
  font-size: 12px; color: var(--text2); background: var(--tag-bg); transition: .15s; }
.l2-btn:hover { background: var(--border); }
.l2-btn.active { background: var(--accent); color: #fff; }

/* ── 面板 ── */
.l1-panel { display: none; }
.l1-panel.active { display: block; }
.l2-panel { display: none; }
.l2-panel.active { display: block; }

/* ── 卡片 ── */
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
# JS
# ═══════════════════════════════════════════════════════════════

JS = r"""
document.addEventListener('DOMContentLoaded', function() {
  // ── L1 切换 → L2 整行替换 ──
  document.querySelectorAll('.l1-bar').forEach(function(bar) {
    bar.addEventListener('click', function(e) {
      var btn = e.target.closest('.l1-btn');
      if (!btn) return;
      var l1Id = btn.dataset.l1;

      // L1 active
      bar.querySelectorAll('.l1-btn').forEach(function(b){ b.classList.remove('active'); });
      btn.classList.add('active');

      // 显示对应 L1 面板
      document.querySelectorAll('.l1-panel').forEach(function(p){ p.classList.remove('active'); });
      var panel = document.querySelector('.l1-panel[data-l1="' + l1Id + '"]');
      if (panel) {
        panel.classList.add('active');
        // 自动选中第一个 L2
        var firstL2 = panel.querySelector('.l2-btn');
        if (firstL2) firstL2.click();
      }
    });
  });

  // ── L2 切换 ──
  document.querySelectorAll('.l2-bar').forEach(function(bar) {
    bar.addEventListener('click', function(e) {
      var btn = e.target.closest('.l2-btn');
      if (!btn) return;
      var sid = btn.dataset.sid;

      bar.querySelectorAll('.l2-btn').forEach(function(b){ b.classList.remove('active'); });
      btn.classList.add('active');

      // 在同一个 L1 panel 内切换 L2
      var l1Panel = btn.closest('.l1-panel');
      l1Panel.querySelectorAll('.l2-panel').forEach(function(p){ p.classList.remove('active'); });
      var l2Panel = l1Panel.querySelector('.l2-panel[data-sid="' + sid + '"]');
      if (l2Panel) l2Panel.classList.add('active');
    });
  });
});
"""


class SSGRenderer:
    """两层 Tab 静态网页生成器。"""

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
            return json.loads(data_file.read_text("utf-8"))
        except Exception as e:
            logger.error(f"读取数据失败: {e}")
            return []

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
        html = self._render_page(articles, date_str)
        out = self.output_dir / "index.html"
        out.write_text(html, "utf-8")
        logger.info(f"首页渲染: {out} ({len(articles)} 篇)")
        return out

    def build_archive(self) -> Path:
        dates = self._scan_dates()
        out = self.output_dir / "archive.html"
        html = self._render_archive_page(dates)
        out.write_text(html, "utf-8")
        logger.info(f"归档渲染: {out} ({len(dates)} 天)")
        return out

    def build_all(self) -> tuple[Path, Path]:
        return self.build_index(), self.build_archive()

    # ── 页面组装 ──────────────────────────────────────

    def _render_page(self, articles: list[dict], date_str: str) -> str:
        grouped = self._group_by_l1(articles)
        l1_ids = list(grouped.keys())

        date_display = f"{date_str[:4]}-{date_str[5:7]}-{date_str[7:9]}"
        body = f'<header><h1>🍠 xhsbooster</h1><div class="date">{date_display} · 韩日娱资讯</div></header>\n'

        if not grouped:
            body += '<div class="empty-state">📭 暂无内容</div>'
            return self._wrap_html(f"xhsbooster · {date_display}", body)

        # L1 按钮
        body += '<div class="l1-bar">\n'
        for i, l1 in enumerate(l1_ids):
            active = ' active' if i == 0 else ''
            count = sum(len(v) for v in grouped[l1].values())
            body += f'  <button class="l1-btn{active}" data-l1="{l1}">{l1} ({count})</button>\n'
        body += '</div>\n'

        # L1 面板
        for i, l1 in enumerate(l1_ids):
            active = ' active' if i == 0 else ''
            body += f'<div class="l1-panel{active}" data-l1="{l1}">\n'
            body += self._render_l2_tabs(grouped[l1], l1)
            body += '</div>\n'

        return self._wrap_html(f"xhsbooster · {date_display}", body)

    def _render_l2_tabs(self, sources: dict[str, list[dict]], l1_id: str) -> str:
        """渲染 L2 源胶囊 + 卡片。"""
        # 排序：Soompi → AsianWiki → Google News → Oricon
        order = {"soompi": 0, "asianwiki": 1, "google-kpop": 2, "google-jdrama": 3, "oricon": 4}
        sorted_sids = sorted(sources.keys(), key=lambda k: order.get(k, 99))

        html = '<div class="l2-bar">\n'
        for i, sid in enumerate(sorted_sids):
            active = ' active' if i == 0 else ''
            src_name = sources[sid][0].get("source_name", sid) if sources[sid] else sid
            html += f'  <button class="l2-btn{active}" data-sid="{sid}">{src_name} ({len(sources[sid])})</button>\n'
        html += '</div>\n'

        # 卡片
        for i, sid in enumerate(sorted_sids):
            active = ' active' if i == 0 else ''
            html += f'<div class="l2-panel{active}" data-sid="{sid}">\n'
            for art in sources[sid]:
                html += self._render_card(art)
            html += '</div>\n'

        return html

    def _group_by_l1(self, articles: list[dict]) -> dict[str, dict[str, list[dict]]]:
        """按 L1 → source_id 两层分组。"""
        grouped: dict[str, dict[str, list[dict]]] = {}
        for art in articles:
            l1 = art.get("l1_tab", "韩娱")
            sid = art.get("source_id", "other")
            grouped.setdefault(l1, {}).setdefault(sid, []).append(art)
        return grouped

    def _render_card(self, art: dict) -> str:
        title = art.get("title_zh") or art.get("title", "无标题")
        url = art.get("url", "#")
        summary = art.get("summary_zh", "")
        risk = art.get("risk_level", "低")
        source_type = art.get("source_type", art.get("category", "韩娱"))
        facts = art.get("facts_list", [])
        is_new = art.get("is_new", False)
        image_url = art.get("image_url", "")
        published_at = art.get("published_at", "")

        risk_class = {"高": "badge-risk-high", "中": "badge-risk-mid"}.get(risk, "badge-risk-low")
        source_name = art.get("source_name", "")

        html = '<div class="card">\n'

        # 图片缩略图
        if image_url:
            html += f'  <img src="{image_url}" style="float:right;width:80px;height:80px;object-fit:cover;border-radius:6px;margin-left:12px;" loading="lazy" alt="">\n'

        html += f'  <h3><a href="{url}" target="_blank" rel="noopener">{title}</a></h3>\n'
        html += '  <div class="meta">\n'
        if is_new:
            html += '    <span class="badge badge-new">NEW</span>\n'
        html += f'    <span class="badge {risk_class}">风险:{risk}</span>\n'
        html += f'    <span>{source_type}</span>\n'
        if source_name:
            html += f'    <span>· {source_name}</span>\n'
        if published_at:
            html += f'    <span>· {published_at}</span>\n'
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

    def _render_archive_page(self, dates: list[str]) -> str:
        body = '<header><h1>📦 历史归档</h1></header>\n'
        months: dict[str, list[str]] = {}
        for d in dates:
            month = d[:4] + d[5:7]
            months.setdefault(month, []).append(d)
        for month in sorted(months, reverse=True):
            y, m = month[:4], month[4:6]
            body += f'<h3 style="margin-top:24px;color:var(--accent)">{y}年{m}月</h3>\n'
            body += '<div style="display:flex;flex-wrap:wrap;gap:8px;margin:12px 0">\n'
            for d in sorted(months[month], reverse=True):
                display = f"{d[5:7]}/{d[7:9]}"
                body += f'<a href="?date={d}" style="padding:8px 14px;border:1px solid var(--border);'
                body += f'border-radius:6px;text-decoration:none;color:var(--accent);font-size:13px">{display}</a>\n'
            body += '</div>\n'
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
<footer>xhsbooster · 韩日娱资讯自动化 · DeepSeek 驱动 · <a href="archive.html" style="color:var(--accent)">历史归档</a></footer>
<script>{JS}</script>
</body>
</html>"""
