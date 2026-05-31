"""PDF 结构化解析服务

将公告 PDF 解析为结构化数据（文本块 + 表格），存入数据库。
解决 LLM 直接读 PDF 导致的"数字幻觉"问题。
"""

import json
from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Session

from database import get_db, Announcement, AnnouncementChunk, FinancialTable
from services.pdf_reader import extract_structure_from_pdf


class PDFParserService:
    """PDF 结构化解析器"""

    @staticmethod
    def parse_announcement(announcement_id: str, db: Optional[Session] = None) -> dict:
        """解析单条公告 PDF，返回统计信息

        Returns:
            {"chunks": int, "tables": int, "pages": int}
        """
        close_db = False
        if db is None:
            db = get_db()
            close_db = True

        try:
            ann = db.query(Announcement).filter(Announcement.announcement_id == announcement_id).first()
            if not ann:
                raise ValueError(f"公告不存在: {announcement_id}")

            if not ann.local_path or not ann.downloaded:
                raise ValueError(f"公告 PDF 未下载: {announcement_id}")

            print(f"[PDFParser] 开始解析 {ann.stock_code} {ann.title[:40]}...")

            # 1. 提取结构化内容
            structure = extract_structure_from_pdf(ann.local_path)

            # 2. 清空旧数据（幂等）
            db.query(AnnouncementChunk).filter(
                AnnouncementChunk.announcement_id == announcement_id
            ).delete(synchronize_session=False)
            db.query(FinancialTable).filter(
                FinancialTable.announcement_id == announcement_id
            ).delete(synchronize_session=False)

            # 3. 保存文本块
            chunk_records = []
            for chunk in structure["chunks"]:
                table_data = None
                if chunk["type"] == "table" and "table_data" in chunk:
                    td = chunk["table_data"]
                    table_data = json.dumps({
                        "headers": td.get("headers"),
                        "rows": td.get("rows"),
                        "html": td.get("html"),
                        "context": td.get("context"),
                        "row_count": td.get("row_count"),
                        "col_count": td.get("col_count"),
                    }, ensure_ascii=False)

                chunk_records.append(AnnouncementChunk(
                    announcement_id=announcement_id,
                    stock_code=ann.stock_code,
                    chunk_index=chunk["index"],
                    chunk_type=chunk["type"],
                    content=chunk["content"],
                    table_data=table_data,
                    page_start=chunk.get("page_start"),
                    page_end=chunk.get("page_end"),
                ))

            if chunk_records:
                db.add_all(chunk_records)

            # 4. 保存财务表格（独立表，方便 SQL 查询）
            table_records = []
            for ti, table in enumerate(structure["tables"]):
                table_records.append(FinancialTable(
                    announcement_id=announcement_id,
                    stock_code=ann.stock_code,
                    table_index=ti,
                    table_title=table.get("table_title") or "",
                    table_type=table.get("table_type", "other"),
                    page_number=table.get("page_number"),
                    headers=table.get("headers"),
                    rows=table.get("rows"),
                    html=table.get("html"),
                    context=table.get("context"),
                    row_count=table.get("row_count"),
                    col_count=table.get("col_count"),
                ))

            if table_records:
                db.add_all(table_records)

            # 5. 更新公告状态
            ann.parsed = True
            ann.parsed_at = datetime.now()

            db.commit()

            stats = {
                "chunks": len(chunk_records),
                "tables": len(table_records),
                "pages": structure["pages"],
            }
            print(f"[PDFParser] 完成: {stats['pages']}页, {stats['chunks']}块, {stats['tables']}表")
            return stats

        except Exception as e:
            db.rollback()
            print(f"[PDFParser] 解析失败 {announcement_id}: {e}")
            raise
        finally:
            if close_db:
                db.close()

    @staticmethod
    def parse_stock_announcements(stock_code: str, limit: Optional[int] = None, db: Optional[Session] = None) -> dict:
        """批量解析某只股票的所有未解析公告"""
        close_db = False
        if db is None:
            db = get_db()
            close_db = True

        results = {"success": 0, "failed": 0, "skipped": 0, "details": []}
        try:
            query = db.query(Announcement).filter(
                Announcement.stock_code == stock_code,
                Announcement.downloaded == True,
                Announcement.local_path.isnot(None),
            )
            # 默认只解析未解析的
            query = query.filter(Announcement.parsed == False)

            if limit:
                query = query.order_by(Announcement.announcement_time.desc()).limit(limit)

            announcements = query.all()
            print(f"[PDFParser] {stock_code} 待解析公告: {len(announcements)} 条")

            for ann in announcements:
                try:
                    stats = PDFParserService.parse_announcement(ann.announcement_id, db)
                    results["success"] += 1
                    results["details"].append({"id": ann.announcement_id, "status": "ok", **stats})
                except Exception as e:
                    results["failed"] += 1
                    results["details"].append({"id": ann.announcement_id, "status": "failed", "error": str(e)})

            return results
        finally:
            if close_db:
                db.close()

    @staticmethod
    def get_announcement_context(
        announcement_id: str,
        max_tables: int = 10,
        table_format: str = "markdown",
        db: Optional[Session] = None,
    ) -> str:
        """获取某条公告的 LLM 友好上下文（优先使用结构化表格）

        Args:
            table_format: "markdown" 或 "html"，控制表格输出格式
        """
        close_db = False
        if db is None:
            db = get_db()
            close_db = True

        try:
            ann = db.query(Announcement).filter(Announcement.announcement_id == announcement_id).first()
            if not ann:
                return ""

            # 如果已解析，从数据库组装
            if ann.parsed:
                chunks = db.query(AnnouncementChunk).filter(
                    AnnouncementChunk.announcement_id == announcement_id
                ).order_by(AnnouncementChunk.chunk_index).all()

                tables = db.query(FinancialTable).filter(
                    FinancialTable.announcement_id == announcement_id
                ).order_by(FinancialTable.table_index).all()

                parts = []

                # 1. 优先使用完整 Markdown 全文（chunk_type="full"）
                full_chunk = db.query(AnnouncementChunk).filter(
                    AnnouncementChunk.announcement_id == announcement_id,
                    AnnouncementChunk.chunk_type == "full",
                ).first()

                if full_chunk and full_chunk.content:
                    parts.append("【公告正文】\n" + full_chunk.content)
                else:
                    # 兼容旧数据：拼接所有文本块
                    text_parts = [c.content for c in chunks if c.chunk_type in ("text", "page")]
                    if text_parts:
                        parts.append("【公告正文】\n" + "\n\n".join(text_parts))

                # 2. 附加结构化表格
                if tables:
                    priority = {"income": 0, "balance": 1, "cash": 2, "other": 3}
                    sorted_tables = sorted(tables, key=lambda t: priority.get(t.table_type, 3))
                    selected = sorted_tables[:max_tables]

                    parts.append("\n\n【提取的财务表格】")
                    for t in selected:
                        ttype_label = {
                            "income": "利润表",
                            "balance": "资产负债表",
                            "cash": "现金流量表",
                            "other": "其他表格",
                        }.get(t.table_type, "表格")

                        if table_format == "html" and t.html:
                            parts.append(f"\n--- {ttype_label} [HTML] ---")
                            parts.append(t.html)
                        else:
                            headers = json.loads(t.headers) if t.headers else []
                            rows = json.loads(t.rows) if t.rows else []

                            md_lines = []
                            md_lines.append(f"\n--- {ttype_label} ---")
                            if headers:
                                md_lines.append("| " + " | ".join(str(h or "") for h in headers) + " |")
                                md_lines.append("|" + "|".join([" --- " for _ in headers]) + "|")
                            for row in rows[:50]:
                                md_lines.append("| " + " | ".join(str(c or "") for c in row) + " |")

                            parts.append("\n".join(md_lines))

                return "\n\n".join(parts)

            # 未解析则实时解析
            from services.pdf_reader import build_llm_context
            structure = extract_structure_from_pdf(ann.local_path)
            return build_llm_context(structure, max_tables=max_tables)

        finally:
            if close_db:
                db.close()
