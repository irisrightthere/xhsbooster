"""
xhsbooster — DeepSeek API 客户端
封装 deepseek-v4（提取/分类）和 deepseek-v4-pro（深度改写）调用。
"""
import json
import re
import time
import logging
from typing import Optional

import httpx

from config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL,
    DEEPSEEK_V4, DEEPSEEK_V4_PRO,
    TEMPERATURE_EXTRACT, TEMPERATURE_SUMMARY, TEMPERATURE_REWRITE,
)

logger = logging.getLogger("xhs.api")

# ═══════════════════════════════════════════════════════════════
# System Prompts
# ═══════════════════════════════════════════════════════════════

SYSTEM_EXTRACT = """你是一位资深日韩娱乐主编，精通 K-pop、韩剧、日娱译名体系，拥有 15 年编辑部经验。

你的核心职责：将输入的英文韩娱/日娱资讯，精确翻译并提炼为结构化中文 JSON。

## 你的工作准则

### 1. 角色定位
你是一个冷静、仔细的阅读和分析工具，不是创意写手。你逐字忠于原文，绝不添加原文没有的信息，绝不编造细节。

### 2. 翻译规范
- 艺人名/组合名/歌曲名/剧名：使用业界通用中文译名。若不确定，保留英文原名并在括号内标注"（暂译）"
- 所属社/平台名：使用官方中文名或业界通用称呼
- 专业术语：使用饭圈/剧粉通行的中文表达

### 3. 硬性反向约束（绝对禁止）
标题和摘要中绝对禁止使用以下笼统词汇：
- 引发争议、引起关注、引发热议、掀起讨论、备受瞩目
- 行为不妥、不当行为、争议行为
- 一切没有具体物理事实支撑的概括性表述

若原文涉及争议/塌房事件，必须精准提取出最具体的：
- 物理行为（如：违规开闪光灯、酒驾、特定言论原文）
- 硬核数据（如：收视率数字、销量数字、罚款金额、刑期）
- 官方回应原文（如：所属社声明具体内容）

### 4. 标题数字解析（强制性）
若原文标题包含"Achieves #1 in multiple countries / tops charts in X regions"等笼统统计：
- 必须通读全文
- 在 facts_list 中逐一列举每一项具体的国家、地区或奖项名称
- 示例：不能说"拿下多国第一"，必须写"iTunes 美国第1、日本第1、巴西第1"
- 缺一不可——原文提到几个就必须列出几个

### 5. 模糊水文兜底
若原文确实极度模糊、毫无具体事实（无时间、无地点、无数据、无具名来源）：
- 将 is_blurred 设为 true
- summary_zh 输出固定格式：[原文未提及具体行为，仅称：{原文最核心的一句话翻译}]

### 6. 风险评估
- 低：普通资讯（回归、综艺、榜单、预告、画报、采访）
- 中：恋情/绯闻/未确认爆料/解约传闻
- 高：重大负面（法律问题、警方介入、死亡、严重塌房、酒驾/毒品等刑事指控）

## 输出格式
你必须严格返回以下 JSON 结构，不得包含任何额外字段或文字：

{
  "title_zh": "中文精炼标题（20-40字，精确概括核心事件）",
  "source_type": "韩娱",
  "risk_level": "低",
  "is_blurred": false,
  "facts_list": [
    "事实点1：时间+地点+主体+具体动作",
    "事实点2：数据/声明/后续进展"
  ],
  "summary_zh": "中文内容核心摘要（80-200字，仅包含原文可确认信息）"
}

source_type 取值：韩娱 / 韩剧 / 日剧"""

SYSTEM_REWRITE = """你是一位资深小红书韩娱博主，拥有 50 万粉丝。你擅长将韩娱资讯改写成小红书风格的爆款文案。

## 写作原则
1. 以朋友分享的口吻推荐，不是官方通稿
2. 信息密度高，但阅读轻松
3. 可以适当用 emoji 和网络热词，但不能过度
4. 所有事实必须来自输入的事实卡片，不得编造
5. 不确定的信息用"目前公开信息显示"开头

## 禁止
- 虚构网友反应、热搜排名、评论态度
- 使用"全网炸了""不看后悔""神仙"等夸张词
- 加入主观情绪化的价值观判断

## 输出格式
返回标准 JSON：
{
  "title1": "备选标题1",
  "title2": "备选标题2",
  "title3": "备选标题3",
  "title4": "备选标题4",
  "title5": "备选标题5",
  "body": "正文（小红书风格，300-800字）",
  "tags": "#tag1 #tag2 #tag3 #tag4 #tag5 #tag6 #tag7 #tag8"
}"""

SYSTEM_HIGH_RISK_PATCH = """
## ⚠️ 高风险安全补丁
当前事件被判定为高风险负面事件。请在执行以上写作任务时，追加以下约束：
1. 采用完全客观中立的陈述视角叙述，严禁带有情绪偏见
2. 自动替换极易被小红书平台封禁的敏感词
3. 以事实陈述为主，不做价值判断
4. 引导读者理性讨论，不煽动对立情绪"""


# ═══════════════════════════════════════════════════════════════
# DeepSeek Client
# ═══════════════════════════════════════════════════════════════

class DeepSeekClient:
    """DeepSeek API 客户端，支持 v4 和 v4-pro 模型。"""

    def __init__(self, api_key: str = None, base_url: str = None):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.base_url = (base_url or DEEPSEEK_BASE_URL).rstrip("/")
        if not self.api_key:
            logger.warning("DEEPSEEK_API_KEY 未设置！")

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ── 底层 HTTP 调用 ─────────────────────────────────

    def _call(
        self,
        system_prompt: str,
        user_content: str,
        model: str = None,
        temperature: float = TEMPERATURE_EXTRACT,
        max_tokens: int = 4096,
        response_format: Optional[dict] = None,
        retries: int = 3,
    ) -> Optional[str]:
        """底层 API 调用，带重试和指数退避。"""
        model = model or DEEPSEEK_V4
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        last_error = None
        for attempt in range(1, retries + 1):
            try:
                with httpx.Client(timeout=120) as client:
                    resp = client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._headers,
                        json=payload,
                    )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    logger.warning(f"API 调用失败 (attempt {attempt}/{retries}): {last_error}")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"API 异常 (attempt {attempt}/{retries}): {e}")

            if attempt < retries:
                wait = 2 ** (attempt - 1)  # 1s, 2s, 4s
                time.sleep(wait)

        logger.error(f"API 调用彻底失败: {last_error}")
        return None

    # ── JSON 解析与修复 ─────────────────────────────────

    @staticmethod
    def _parse_json(raw: str) -> Optional[dict]:
        """多层 JSON 解析降级：直接解析 → jsonrepair → 正则提取。"""
        if not raw:
            return None

        strategies = [
            # 策略 1：直接解析
            lambda s: json.loads(s),
            # 策略 2：去掉 markdown 代码块后解析
            lambda s: json.loads(re.search(r'```(?:json)?\s*\n?(.*?)\n?```', s, re.DOTALL).group(1)),
            # 策略 3：提取第一个 JSON 对象
            lambda s: json.loads(re.search(r'\{.*\}', s, re.DOTALL).group(0)),
        ]

        for i, strategy in enumerate(strategies):
            try:
                result = strategy(raw)
                if isinstance(result, dict):
                    if i > 0:
                        logger.info(f"JSON 解析成功（策略 {i+1}）")
                    return result
            except Exception:
                continue

        # 策略 4：jsonrepair 修复
        try:
            from jsonrepair import repair_json
            repaired = repair_json(raw)
            # 找修复后的第一个 JSON 对象
            m = re.search(r'\{.*\}', repaired, re.DOTALL)
            if m:
                return json.loads(m.group(0))
        except Exception:
            pass

        logger.error(f"JSON 解析彻底失败，原始输出前 500 字符:\n{raw[:500]}")
        return None

    # ── 业务方法 ───────────────────────────────────────

    def extract_and_classify(self, text: str, title: str = "", source_lang: str = "en") -> Optional[dict]:
        """
        Module 1 核心：翻译 + 分类 + 事实提取。
        使用 deepseek-v4，JSON mode，temperature=0.1。
        source_lang: 源语言 (ja/ko/en)，动态注入 System Prompt。
        """
        if not self.api_key:
            logger.error("无法调用 API：DEEPSEEK_API_KEY 未设置")
            return None

        # 源语言名称映射
        lang_names = {"ja": "日语", "ko": "韩语", "en": "英语"}
        lang_hint = lang_names.get(source_lang, "外语")

        # 动态注入源语言
        dynamic_prompt = SYSTEM_EXTRACT + f"\n\n## 当前任务\n你正在处理一篇源语言为 {lang_hint} 的资讯。请特别注意该语言的专有名词、日期格式和文化语境，精确翻译为中文。"

        user = f"标题：{title}\n\n原文内容：\n{text[:3000]}"
        raw = self._call(
            system_prompt=dynamic_prompt,
            user_content=user,
            model=DEEPSEEK_V4,
            temperature=TEMPERATURE_EXTRACT,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        result = self._parse_json(raw)

        # 兜底：确保必要字段存在
        if result:
            result.setdefault("title_zh", title or "无标题")
            result.setdefault("source_type", "韩娱")
            result.setdefault("risk_level", "低")
            result.setdefault("is_blurred", False)
            result.setdefault("facts_list", [])
            result.setdefault("summary_zh", "")
        return result

    def summarize_for_feishu(self, extracted: dict) -> str:
        """
        生成飞书推送用的短摘要。
        使用 deepseek-v4，temperature=0.3。
        """
        if not self.api_key:
            return extracted.get("summary_zh", "")[:120]

        prompt = "将以下结构化资讯压缩为一条 60 字以内、适合即时通讯推送的中文摘要。只返回摘要文本，不要 JSON。"
        user = json.dumps(extracted, ensure_ascii=False)
        raw = self._call(
            system_prompt=prompt,
            user_content=user,
            model=DEEPSEEK_V4,
            temperature=TEMPERATURE_SUMMARY,
            max_tokens=200,
        )
        return raw.strip() if raw else extracted.get("summary_zh", "")[:120]

    def rewrite_draft(
        self,
        fact_card: dict,
        template_text: str,
        risk_level: str = "低",
    ) -> Optional[dict]:
        """
        Module 5 核心：深度文案改写。
        使用 deepseek-v4-pro，temperature=0.5。
        高风险文章自动注入安全补丁。
        """
        if not self.api_key:
            logger.error("无法调用 API：DEEPSEEK_API_KEY 未设置")
            return None

        system = SYSTEM_REWRITE
        if risk_level == "高":
            system += "\n" + SYSTEM_HIGH_RISK_PATCH

        # 合并事实卡片和文法模板
        user_parts = [
            "## 事实卡片",
            json.dumps(fact_card, ensure_ascii=False, indent=2),
            "",
            "## 文法模板参考",
            template_text,
        ]
        user = "\n".join(user_parts)

        raw = self._call(
            system_prompt=system,
            user_content=user,
            model=DEEPSEEK_V4_PRO,
            temperature=TEMPERATURE_REWRITE,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        return self._parse_json(raw)


# ═══════════════════════════════════════════════════════════════
# 便捷工厂
# ═══════════════════════════════════════════════════════════════

_client: Optional[DeepSeekClient] = None

def get_client() -> DeepSeekClient:
    global _client
    if _client is None:
        _client = DeepSeekClient()
    return _client
