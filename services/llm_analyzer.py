"""DeepSeek / LLM 公告分析服务"""
import json
import os
from typing import Optional, List
from openai import OpenAI

from database import get_db, AnalysisResult
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE, LLM_MAX_TEXT_LENGTH
from services.pdf_parser import PDFParserService


class LLMClient:
    """OpenAI 兼容 API 客户端"""

    def __init__(self):
        if not LLM_API_KEY:
            raise RuntimeError("未配置 LLM API Key，请设置环境变量 DEEPSEEK_API_KEY")
        self.client = OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
        )

    def chat(self, system_prompt: str, user_content: str) -> dict:
        """调用聊天接口，返回 {"content": str, "tokens": int}"""
        resp = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
        return {
            "content": resp.choices[0].message.content,
            "tokens": resp.usage.total_tokens if resp.usage else 0,
        }


# ==================== 分析提示词模板 ====================

PROMPT_SUMMARY = """你是一位专业的A股财报分析师。请仔细阅读以下上市公司公告，用中文给出精炼的摘要。

要求：
1. 用2-3句话概括公告核心内容
2. 指出公告类型（如：定期报告、重大资产重组、股权激励、关联交易等）
3. 语言简洁专业

请直接输出分析结果，不要加任何前缀说明。"""

PROMPT_KEY_INFO = """你是一位专业的A股财报分析师。请从以下公告中提取关键结构化信息，以 JSON 格式输出。

**重要提示**：公告正文下方附有【提取的财务表格】，其中的数字经过结构化提取，比正文中出现的数字更可靠。如涉及财务数据（营收、利润、资产等），请优先以表格中的数字为准，不要自行计算或估算。

需要提取的字段：
- 公告类型: string
- 涉及金额: string（如有，标注币种和单位；如无填"无"）
- 交易对手方/合作方: string（如有；如无填"无"）
- 关键日期: string（如股权登记日、实施日期等；如无填"无"）
- 涉及比例/数量: string（如持股比例、发行数量等；如无填"无"）
- 主要财务数据: object（如有表格，提取核心财务数字：营业收入、净利润、总资产等；如无填{}）
- 主要事项: string（一句话描述）

请只输出 JSON，不要加 markdown 代码块标记或其他说明。"""

PROMPT_RISK = """你是一位专业的A股投资分析师。请判断以下公告对股价的潜在影响，并给出理由。

**重要提示**：公告中的【提取的财务表格】部分已经过结构化处理，引用的财务数字请以表格为准，避免凭记忆复述数字。

请按以下格式输出：
- 影响判断: 利好 / 利空 / 中性
- 影响程度: 重大 / 中等 / 轻微
- 理由: （3-5句话说明判断依据，如涉及财务数据请明确引用）
- 关注点: （投资者后续应关注什么）

请直接输出分析结果。"""

PROMPT_IMPACT = """你是一位专业的行业研究员。请分析以下公告对公司业务和行业的长期影响。

**重要提示**：公告中的【提取的财务表格】已经过结构化提取，财务数字请以表格为准，避免产生数字幻觉。

请按以下格式输出：
- 业务影响: （对公司主营业务、竞争格局的影响）
- 财务影响: （对收入、利润、现金流等的潜在影响，引用具体数字时请核对表格）
- 战略意义: （是否符合公司长期战略方向）
- 行业对比: （与同行业其他公司类似操作的对比）

请直接输出分析结果。"""

ANALYSIS_TYPES = {
    "summary": ("摘要总结", PROMPT_SUMMARY),
    "key_info": ("关键信息", PROMPT_KEY_INFO),
    "risk": ("风险判断", PROMPT_RISK),
    "impact": ("业务影响", PROMPT_IMPACT),
}


class AnnouncementAnalyzer:
    """公告智能分析器"""

    def __init__(self):
        self.client = LLMClient()

    def analyze_single(
        self,
        announcement_id: str,
        stock_code: str,
        pdf_path: str,
        title: str,
        analysis_type: str = "summary",
    ) -> Optional[AnalysisResult]:
        """分析单条公告，返回数据库记录（已保存）"""
        if analysis_type not in ANALYSIS_TYPES:
            raise ValueError(f"不支持的 analysis_type: {analysis_type}，可选: {list(ANALYSIS_TYPES.keys())}")

        label, system_prompt = ANALYSIS_TYPES[analysis_type]

        # 获取结构化上下文（含表格）
        try:
            context = PDFParserService.get_announcement_context(announcement_id, max_tables=10)
            if not context:
                print(f"[Analyzer] 无法获取上下文 {announcement_id}")
                return None
        except Exception as e:
            print(f"[Analyzer] 上下文获取失败 {announcement_id}: {e}")
            return None

        # 截断保护
        if len(context) > LLM_MAX_TEXT_LENGTH:
            context = context[:LLM_MAX_TEXT_LENGTH] + "\n\n[...内容过长，已截断...]"

        # 组装 user content
        user_content = f"股票代码: {stock_code}\n公告标题: {title}\n\n{context}"

        # 调用 LLM
        print(f"[Analyzer] 正在分析 {stock_code} [{label}] {title[:40]}...")
        try:
            result = self.client.chat(system_prompt, user_content)
        except Exception as e:
            print(f"[Analyzer] LLM 调用失败: {e}")
            return None

        # 保存结果
        db = get_db()
        try:
            # 检查是否已存在
            existing = (
                db.query(AnalysisResult)
                .filter(
                    AnalysisResult.announcement_id == announcement_id,
                    AnalysisResult.analysis_type == analysis_type,
                )
                .first()
            )
            if existing:
                existing.result = result["content"]
                existing.model = LLM_MODEL
                existing.tokens_used = result["tokens"]
                db.commit()
                record = existing
            else:
                record = AnalysisResult(
                    announcement_id=announcement_id,
                    stock_code=stock_code,
                    analysis_type=analysis_type,
                    result=result["content"],
                    model=LLM_MODEL,
                    tokens_used=result["tokens"],
                )
                db.add(record)
                db.commit()
                db.refresh(record)

            print(f"[Analyzer] 完成 {label}，消耗 {result['tokens']} tokens")
            return record
        finally:
            db.close()

    def analyze_batch(
        self,
        stock_code: str,
        analysis_types: Optional[List[str]] = None,
        limit: int = 5,
        only_undownloaded: bool = False,
    ) -> dict:
        """批量分析某只股票的最新 N 条已下载公告
        
        返回: {announcement_id: {analysis_type: AnalysisResult}}
        """
        from database import Announcement

        if analysis_types is None:
            analysis_types = ["summary"]

        db = get_db()
        try:
            query = (
                db.query(Announcement)
                .filter(Announcement.stock_code == stock_code)
                .filter(Announcement.downloaded == True)
                .filter(Announcement.local_path.isnot(None))
            )
            if only_undownloaded:
                # 只分析还没有分析结果的公告
                analyzed_ids = (
                    db.query(AnalysisResult.announcement_id)
                    .filter(AnalysisResult.stock_code == stock_code)
                    .distinct()
                    .all()
                )
                analyzed_ids = {r[0] for r in analyzed_ids}
                if analyzed_ids:
                    query = query.filter(~Announcement.announcement_id.in_(analyzed_ids))

            announcements = query.order_by(Announcement.announcement_time.desc()).limit(limit).all()
        finally:
            db.close()

        results = {}
        for ann in announcements:
            results[ann.announcement_id] = {}
            for atype in analysis_types:
                try:
                    record = self.analyze_single(
                        ann.announcement_id,
                        stock_code,
                        ann.local_path,
                        ann.title,
                        analysis_type=atype,
                    )
                    if record:
                        results[ann.announcement_id][atype] = record
                except Exception as e:
                    print(f"[Analyzer] 分析 {ann.announcement_id} [{atype}] 失败: {e}")

        return results
