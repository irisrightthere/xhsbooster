"""
xhsbooster — 全局配置（云端 + 本地共享）
"""
import os
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

# 自动加载 .env 文件（本地测试用，GitHub Actions 用 secrets）
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

# ═══ 时区 ═══
CST = timezone(timedelta(hours=8))  # 北京时间

def now_cst() -> datetime:
    return datetime.now(CST)

def today_key() -> str:
    """返回今日日期字符串，如 '2026-0621'"""
    return now_cst().strftime("%Y-%m%d")

def datetime_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m%d")

def timestamp_key() -> str:
    """返回 HHMM 格式时间戳，用于文件命名前缀"""
    return now_cst().strftime("%H%M")

# ═══ 路径 ═══
CLOUD_ROOT = Path(__file__).resolve().parent
STATE_DIR = CLOUD_ROOT / "gh-pages" / "_state"
OUTPUT_DIR = CLOUD_ROOT / "gh-pages"
SOURCES_FILE = CLOUD_ROOT / "sources.json"

# 本地 Obsidian 路径（仅 Layer 2 使用）
OBSIDIAN_VAULT = Path(os.environ.get("OBSIDIAN_VAULT_PATH", os.path.expanduser("~/iris")))
LOCAL_PROJECT = OBSIDIAN_VAULT / "🚀-项目" / "xhsbooster"
DIR_WORKBENCH = LOCAL_PROJECT / "00_工作台"
DIR_NEWS = LOCAL_PROJECT / "01_📰资讯源"
DIR_CARDS = LOCAL_PROJECT / "02_🧩事实卡片"
DIR_REFERENCE = LOCAL_PROJECT / "03_参考文本"
DIR_TEMPLATES = LOCAL_PROJECT / "04_文法模板"
DIR_DRAFTS = LOCAL_PROJECT / "05_✍️草稿文件"
DIR_PUBLISHED = LOCAL_PROJECT / "06_✅发布稿"

# ═══ DeepSeek API ═══
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_V4 = os.environ.get("DEEPSEEK_V4_MODEL", "deepseek-chat")      # deepseek-v4
DEEPSEEK_V4_PRO = os.environ.get("DEEPSEEK_V4_PRO_MODEL", "deepseek-reasoner")  # deepseek-v4-pro

# ═══ 模型温度分层 ═══
TEMPERATURE_EXTRACT = 0.1    # 翻译+分类+事实提取：极低，零容忍幻觉
TEMPERATURE_SUMMARY = 0.3    # 飞书摘要：略增可读性
TEMPERATURE_REWRITE = 0.5    # 深度文案改写：需要文采但不能虚构

# ═══ 去重 ═══
DEDUP_WINDOW_HOURS = 72                     # 滑动窗口
DEDUP_TITLE_SIMILARITY_THRESHOLD = 0.85     # 标题相似度阈值
DEDUP_DB_PATH = STATE_DIR / "dedup.db"      # SQLite 去重数据库

# ═══ 爬虫 ═══
CRAWL_TIMEOUT = 30          # 单次请求超时（秒）
CRAWL_RETRY_COUNT = 3       # 重试次数
CRAWL_RETRY_INTERVAL = 30   # 重试间隔（秒）
CRAWL_MAX_ITEMS_PER_SOURCE = 30  # 每源每次最多抓取条数

# ═══ 飞书 ═══
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")

# ═══ 归档 ═══
ARCHIVE_DAYS = 90  # 超过此天数自动打包

# ═══ 工具函数 ═══
def url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().lower().encode()).hexdigest()[:16]

def title_hash(title: str) -> str:
    """标题归一化后哈希"""
    import re
    cleaned = re.sub(r'\s+', ' ', title.strip().lower())
    return hashlib.sha256(cleaned.encode()).hexdigest()[:16]

def md5_hash(text: str) -> str:
    """MD5 哈希（用于去重）"""
    return hashlib.md5(text.strip().lower().encode()).hexdigest()

def normalize_to_cst(published_str: str, source_id: str = "") -> tuple[str, float]:
    """
    将任意时间字符串 → 北京时间。
    返回: (display_str, unix_ts)
      display_str: "0621soompi" 格式
      unix_ts: Unix 时间戳
    """
    from dateutil import parser as dateparser
    try:
        dt_utc = dateparser.parse(published_str, ignoretz=True)
        # 假设输入为 UTC，转为 CST
        from datetime import timezone as tz
        dt_utc = dt_utc.replace(tzinfo=tz.utc)
        dt_cst = dt_utc.astimezone(CST)
        display = f"{dt_cst.strftime('%m%d')}{source_id}"
        return display, dt_cst.timestamp()
    except Exception:
        ts = now_cst().timestamp()
        display = f"{now_cst().strftime('%m%d')}{source_id}"
        return display, ts

def safe_filename(title: str, max_len: int = 60) -> str:
    """将标题转为安全文件名"""
    import re
    # 保留中英日韩文字、数字、空格、常用符号
    cleaned = re.sub(r'[^\w\s一-鿿぀-ゟ゠-ヿ가-힯-]', '', title)
    cleaned = re.sub(r'\s+', '_', cleaned.strip())
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned
