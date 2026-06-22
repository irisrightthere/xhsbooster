"""
xhsbooster — 静态 HTML 渲染器（v9 暗色主题 + 柔和紫调）
卡片格式：NEW点 + 标题 / 源,时间,风险 / --- / 摘要 / 按钮
"""
import json
import logging
from pathlib import Path

from config import OUTPUT_DIR, STATE_DIR, today_key

logger = logging.getLogger("xhs.render")

CSS = r"""
:root {
  --bg: #0B0F19; --surface: #161F30; --border: rgba(255,255,255,0.03);
  --text: #D1D9E6; --text2: #6C7D93;
  --accent: #B3C0FB; --accent-hover: #D6DFFF;
  --pulse-color: #bfa0ff;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font: 14px/1.6 -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  background: var(--bg); color: var(--text); overflow-x: hidden; }

/* Header */
.report-header { max-width: 720px; margin: 0 auto; padding: 24px 0 16px; }
.eyebrow { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.2em; color: var(--text2); font-weight: 500; }
.report-title { font-size: 2.2rem; font-weight: 700; margin: 0.4rem 0 0.6rem; letter-spacing: -0.02em; line-height: 1.1; }
.archive-link { display: inline-block; margin-bottom: 0.5rem; font-size: 0.85rem; color: var(--text2);
  text-decoration: none; border-bottom: 1px dashed rgba(179,192,251,0.2); padding-bottom: 1px; cursor: pointer; }
.archive-link:hover { color: var(--accent); border-bottom-style: solid; }

/* Tabs */
.tab-bar { max-width: 720px; margin: 0 auto; display: flex; gap: 0;
  border-bottom: 1px solid var(--border); overflow-x: auto; }
.tab-btn { padding: 12px 20px; border: none; background: none; cursor: pointer;
  font-size: 13px; color: var(--text2); border-bottom: 2px solid transparent;
  margin-bottom: -1px; white-space: nowrap; font-family: inherit; transition: .15s; }
.tab-btn:hover { color: var(--text); }
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab-count { font-size: 11px; color: var(--text2); margin-left: 4px; }
.tab-btn.active .tab-count { color: var(--accent); }

/* Content */
.content { max-width: 720px; margin: 0 auto; padding: 20px 0; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }

/* Card */
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 20px 24px; margin-bottom: 14px; transition: .15s; }
.card:hover { border-color: rgba(255,255,255,0.05); }

/* NEW 脉冲点 */
.card-head { display: flex; align-items: flex-start; gap: 8px; margin-bottom: 10px; }
.card-title { font-size: 17px; font-weight: 700; line-height: 1.5; flex: 1; }
.card-title a { color: var(--text); text-decoration: none; }
.card-title a:hover { color: var(--accent); }
.pulse-dot { display: inline-flex; align-items: center; gap: 5px; flex-shrink: 0; margin-top: 5px; }
.dot { width: 5px; height: 5px; background: var(--pulse-color); border-radius: 50%;
  box-shadow: 0 0 6px rgba(191,160,255,0.6);
  animation: muted-pulse-glow 3.5s infinite ease-in-out; }
@keyframes muted-pulse-glow {
  0%,100%{opacity:.4;transform:scale(.95);box-shadow:0 0 4px rgba(191,160,255,.3)}
  50%{opacity:1;transform:scale(1.1);box-shadow:0 0 10px rgba(191,160,255,.8)}
}
.new-label { font-size: 10px; font-weight: 700; color: var(--pulse-color); letter-spacing: .1em; }

/* Meta */
.card-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 13px; }
.meta-source { color: var(--text2); font-weight: 500; }
.meta-date { color: var(--text2); font-family: "SF Mono","Menlo",monospace; }

/* Risk tags */
.risk-tag { font-size: 10px; font-weight: 500; padding: 2px 8px; border-radius: 4px;
  border: 1px solid; letter-spacing: .05em; }
.risk-high { color:#92B594; background:rgba(146,181,148,.08); border-color:rgba(146,181,148,.2); }
.risk-mid { color:#BDB294; background:rgba(189,178,148,.08); border-color:rgba(189,178,148,.2); }
.risk-low { color:#6C7D93; background:rgba(255,255,255,.03); border-color:rgba(255,255,255,.08); }

/* Separator */
.card-sep { border: none; border-top: 1px solid var(--border); margin: 12px 0; }

/* Summary */
.card-summary { font-size: 14px; color: var(--text2); line-height: 1.75; }
.card-summary em { font-style: normal; font-weight: 500; color: var(--accent);
  background: rgba(179,192,251,.08); padding: 1px 5px; border-radius: 3px; }

/* Footer */
.card-footer { display: flex; gap: 14px; margin-top: 14px; align-items: center; }
.btn-view { color: var(--accent); text-decoration: none; font-size: 12px;
  border-bottom: 1px dashed rgba(179,192,251,.3); padding-bottom: 1px; transition: .15s; cursor: pointer; }
.btn-view:hover { color: var(--accent-hover); }
.btn-match { padding: 5px 16px; border: 1px solid rgba(179,192,251,.3); border-radius: 4px;
  background: rgba(179,192,251,.15); color: var(--accent); font-weight: 500;
  cursor: pointer; font-size: 11px; font-family: inherit; transition: .2s; }
.btn-match:hover { background: rgba(179,192,251,.25); color: #fff; }

/* Drawer */
.drawer-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.4);
  z-index: 99; opacity: 0; pointer-events: none; transition: opacity .25s; }
.drawer-overlay.open { opacity: 1; pointer-events: auto; }
.drawer { position: fixed; top: 0; left: 0; width: 300px; height: 100%;
  background: rgba(11,15,25,.9); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
  z-index: 100; transform: translateX(-100%); transition: transform .25s ease; overflow-y: auto;
  border-right: 1px solid rgba(179,192,251,.08); }
.drawer.open { transform: translateX(0); }
.drawer-header { padding: 20px; border-bottom: 1px solid rgba(255,255,255,.04);
  display: flex; justify-content: space-between; align-items: center; }
.drawer-header h2 { font-size: 16px; color: var(--text2); }
.drawer-close { background: none; border: none; color: var(--text2); cursor: pointer;
  font-size: 20px; padding: 4px 8px; border-radius: 4px; transition: .15s; }
.drawer-close:hover { color: var(--accent); }
.drawer-list { list-style: none; padding: 12px; }
.drawer-list li { margin-bottom: 2px; }
.drawer-list a { display: block; padding: 8px 12px; color: var(--text2); text-decoration: none;
  border-radius: 6px; font-size: 13px; transition: .15s; }
.drawer-list a:hover { background: rgba(179,192,251,.06); color: var(--accent); }

/* Toast */
.toast { position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%);
  background: rgba(179,192,251,.25); color: #fff; padding: 8px 20px;
  border-radius: 20px; font-size: 13px; z-index: 200;
  backdrop-filter: blur(10px); animation: toastAnim 2s ease; }
@keyframes toastAnim { 0%{opacity:0} 15%{opacity:1} 70%{opacity:1} 100%{opacity:0} }

/* Archive */
.archive-list { list-style: none; }
.archive-list li { display: flex; justify-content: space-between; align-items: center;
  padding: 10px 0; border-bottom: 1px solid var(--border); }
.archive-list a { color: var(--accent); text-decoration: none; font-size: 15px; }
.archive-list a:hover { color: var(--accent-hover); }
.archive-meta { font-size: 13px; color: var(--text2); margin-bottom: 20px; }
.empty-state { text-align: center; padding: 60px 20px; color: var(--text2); }
footer { text-align: center; padding: 30px 0 20px; font-size: 12px; color: var(--text2);
  border-top: 1px solid var(--border); margin-top: 30px; }
footer a { color: var(--accent); text-decoration: none; }
"""

JS = r"""
function copyDraft(btn) {
  navigator.clipboard.writeText(btn.dataset.copy).then(function() {
    var toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = '✅ 已复制，粘贴到 Obsidian 提炼助手';
    document.body.appendChild(toast);
    setTimeout(function(){ toast.remove(); }, 2000);
  });
}
function toggleDrawer() {
  document.getElementById('drawer').classList.toggle('open');
  document.getElementById('overlay').classList.toggle('open');
}
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
    """暗色主题静态网页生成器。"""

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

    def _render_index(self, articles: list[dict], date_str: str) -> str:
        grouped = self._group_by_source(articles)
        sids = list(grouped.keys())
        date_display = f"{date_str[:4]}-{date_str[5:7]}-{date_str[7:9]}"

        body = '<div class="drawer-overlay" id="overlay" onclick="toggleDrawer()"></div>\n'
        body += '<div class="drawer" id="drawer">\n'
        body += '  <div class="drawer-header"><h2>📅 往期回顾</h2><button class="drawer-close" onclick="toggleDrawer()">✕</button></div>\n'
        body += '  <ul class="drawer-list">\n'
        for d in self._scan_dates():
            display = f"{d[:4]}-{d[5:7]}-{d[7:9]}"
            body += f'    <li><a href="?date={d}">{display}</a></li>\n'
        body += '  </ul>\n</div>\n'

        body += f'<header class="report-header"><span class="eyebrow">🍠 xhsbooster</span><h1 class="report-title">{date_display}</h1><a class="archive-link" onclick="toggleDrawer()">← 往期回顾</a></header>\n'

        if not grouped:
            body += '<div class="empty-state">📭 暂无内容</div>'
            return self._wrap_html(f"xhsbooster · {date_display}", body)

        body += '<div class="tab-bar">\n'
        for i, sid in enumerate(sids):
            active = ' active' if i == 0 else ''
            name = grouped[sid][0].get("source_name", sid) if grouped[sid] else sid
            body += f'  <button class="tab-btn{active}" data-sid="{sid}">[{name}]<span class="tab-count">{len(grouped[sid])}</span></button>\n'
        body += '</div>\n'

        body += '<div class="content">\n'
        for i, sid in enumerate(sids):
            active = ' active' if i == 0 else ''
            body += f'<div class="tab-panel{active}" data-sid="{sid}">\n'
            for art in grouped[sid]:
                body += self._render_card(art)
            body += '</div>\n'
        body += '</div>\n'

        return self._wrap_html(f"xhsbooster · {date_display}", body)

    def _render_card(self, art: dict) -> str:
        title = art.get("title_zh") or art.get("title", "无标题")
        url = art.get("url", "#")
        summary = art.get("summary_zh", "")
        source_name = art.get("source_name", "")
        published_ts = art.get("published_ts", 0)
        is_new = art.get("is_new", False)
        risk = art.get("risk_level", "低")
        risk_type = art.get("source_type", "")

        from datetime import datetime, timezone, timedelta
        cst = timezone(timedelta(hours=8))
        date_display = datetime.fromtimestamp(published_ts, tz=cst).strftime("%Y-%m-%d") if published_ts else ""

        risk_label = {"高": "争议·高", "中": "舆论·中"}.get(risk, f"{risk_type}·低") if risk_type else {"高": "争议·高", "中": "舆论·中"}.get(risk, "资讯·低")
        risk_class = {"高": "risk-high", "中": "risk-mid"}.get(risk, "risk-low")

        import html as _html
        copy_text = _html.escape(f"{title}\\n来源：{source_name}\\n日期：{date_display}\\n摘要：{summary}", quote=True)

        h = '<div class="card">\n'
        h += '  <div class="card-head">\n'
        if is_new:
            h += '    <span class="pulse-dot"><span class="dot"></span><span class="new-label">NEW</span></span>\n'
        h += f'    <div class="card-title"><a href="{url}" target="_blank" rel="noopener">{title}</a></div>\n'
        h += '  </div>\n'
        h += '  <div class="card-meta">\n'
        h += f'    <span class="meta-source">{source_name}</span>\n'
        if date_display:
            h += f'    <span class="meta-date">· {date_display}</span>\n'
        h += f'    <span class="risk-tag {risk_class}">{risk_label}</span>\n'
        h += '  </div>\n'
        if summary:
            h += '  <hr class="card-sep">\n'
            h += f'  <div class="card-summary">{summary}</div>\n'
        h += '  <div class="card-footer">\n'
        h += f'    <a href="{url}" target="_blank" rel="noopener" class="btn-view">查看原文 ↗</a>\n'
        h += f'    <button class="btn-match" onclick="copyDraft(this)" data-copy="{copy_text}">匹配模板</button>\n'
        h += '  </div>\n'
        h += '</div>\n'
        return h

    def _group_by_source(self, articles: list[dict]) -> dict[str, list[dict]]:
        order = {"soompi": 0, "google-kpop": 1, "asianwiki": 2, "google-jdrama": 3, "oricon": 4}
        grouped: dict[str, list[dict]] = {}
        for art in articles:
            sid = art.get("source_id", "other")
            grouped.setdefault(sid, []).append(art)
        return dict(sorted(grouped.items(), key=lambda kv: order.get(kv[0], 99)))

    def _render_archive(self, dates: list[str]) -> str:
        body = '<header class="report-header"><span class="eyebrow">📦 往期回顾</span><h1 class="report-title">Archive</h1><a class="archive-link" href="index.html">← 返回首页</a></header>\n'
        body += f'<p class="archive-meta">{len(dates)} 份报告 · 最新在前 · 生成于 {today_key()}</p>\n'
        if not dates:
            body += '<div class="empty-state">暂无历史报告</div>'
            return self._wrap_html("xhsbooster · 往期回顾", body)
        body += '<ul class="archive-list">\n'
        for d in dates:
            display = f"{d[:4]}-{d[5:7]}-{d[7:9]}"
            body += f'  <li><a href="?date={d}">{display}</a></li>\n'
        body += '</ul>\n'
        return self._wrap_html("xhsbooster · 往期回顾", body)

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
