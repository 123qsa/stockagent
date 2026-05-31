"""PDF 结构化提取（pymupdf4llm 版）

核心改进：
1. 用 pymupdf4llm（基于 PyMuPDF）替代 pdfplumber，PDF→Markdown 转换质量大幅提升
2. 表格以标准 Markdown 格式保留，LLM 理解效果远好于 pdfplumber 的原始提取
3. 支持图片占位、标题层级、阅读顺序恢复
4. 自动从 Markdown 中解析结构化表格数据

分块策略（确保100%完整入库）：
- chunk_type="full": 保存完整 Markdown 全文（不丢失任何内容）
- chunk_type="page": 按页面分块（需 page_chunks=True）
- chunk_type="table": 单独保存表格（结构化查询）
"""

import json
import os
import re
from typing import List, Dict, Optional

import pymupdf4llm
import fitz  # PyMuPDF


# 财务表格关键词映射（用于自动识别表格类型）
TABLE_TYPE_KEYWORDS = {
    "income": ["利润表", "损益表", "合并利润表", "合并损益表", "营业收入", "净利润", "营业成本", "利润总额", "营业利润"],
    "balance": ["资产负债表", "合并资产负债表", "资产总计", "负债总计", "所有者权益", "股东权益", "资产合计", "负债合计", "资产总额"],
    "cash": ["现金流量表", "合并现金流量表", "经营活动", "投资活动", "筹资活动", "现金及现金等价物"],
}


def _clean_cell(cell: str) -> str:
    """清理单元格内容"""
    if not cell:
        return ""
    text = cell.replace("\n", " ").replace("<br>", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _detect_table_type(table_lines: List[str], surrounding_text: str = "") -> str:
    """根据表头和周围文本判断表格类型"""
    all_text = surrounding_text + " " + " ".join(table_lines)
    scores = {}
    for ttype, keywords in TABLE_TYPE_KEYWORDS.items():
        scores[ttype] = sum(1 for kw in keywords if kw in all_text)
    if not scores or max(scores.values()) == 0:
        return "other"
    return max(scores, key=scores.get)


def _extract_markdown_tables(md_text: str) -> List[Dict]:
    """从 Markdown 文本中提取所有表格"""
    tables = []
    lines = md_text.split("\n")
    i = 0
    table_idx = 0

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and line.count("|") >= 2:
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1

            if len(table_lines) < 3:
                continue

            data_lines = []
            for tl in table_lines:
                if re.match(r"^\|[-\s|:]+\|$", tl) or re.match(r"^\|[-\s|:]+\|", tl):
                    continue
                data_lines.append(tl)

            if len(data_lines) < 2:
                continue

            header_line = data_lines[0]
            headers = [_clean_cell(h) for h in header_line.split("|")[1:-1]]

            rows = []
            for dl in data_lines[1:]:
                cells = [_clean_cell(c) for c in dl.split("|")[1:-1]]
                if any(c.strip() for c in cells):
                    rows.append(cells)

            if not rows:
                continue

            start_idx = max(0, i - len(table_lines) - 5)
            context_lines = [l.strip() for l in lines[start_idx:i - len(table_lines)] if l.strip() and not l.strip().startswith("|")]
            context = "\n".join(context_lines[-3:])

            md_table = "\n".join(table_lines)
            html = _table_to_html(headers, rows)
            ttype = _detect_table_type(table_lines, context)

            tables.append({
                "table_index": table_idx,
                "table_type": ttype,
                "markdown": md_table,
                "html": html,
                "context": context,
                "headers": json.dumps(headers, ensure_ascii=False),
                "rows": json.dumps(rows, ensure_ascii=False),
                "row_count": len(rows) + 1,
                "col_count": len(headers),
            })
            table_idx += 1
        else:
            i += 1

    return tables


def _table_to_html(headers: List[str], rows: List[List[str]]) -> str:
    """将表格数据转为 HTML"""
    lines = ["<table>"]
    lines.append("  <thead>")
    lines.append("    <tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>")
    lines.append("  </thead>")
    lines.append("  <tbody>")
    for row in rows:
        cells = []
        for ci, cell in enumerate(row):
            tag = "th" if ci == 0 and cell and not cell.replace(",", "").replace(".", "").replace("%", "").isdigit() else "td"
            cells.append(f"<{tag}>{cell}</{tag}>")
        lines.append("    <tr>" + "".join(cells) + "</tr>")
    lines.append("  </tbody>")
    lines.append("</table>")
    return "\n".join(lines)


def extract_structure_from_pdf(pdf_path: str, max_chars: Optional[int] = None) -> Dict:
    """从 PDF 提取结构化内容

    Returns:
        {
            "text": str,           # Markdown 全文
            "chunks": List[Dict],  # 分块结果
            "tables": List[Dict],  # 结构化表格
            "pages": int,
        }
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF 不存在: {pdf_path}")

    # 1. 提取完整 Markdown（page_chunks=True 按页分段，便于后续处理）
    md_text = pymupdf4llm.to_markdown(pdf_path)

    if not md_text or not md_text.strip():
        raise ValueError(f"无法从 PDF 提取内容: {pdf_path}")

    # 2. 获取页数
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    # 3. 提取结构化表格
    tables = _extract_markdown_tables(md_text)

    # 4. 构建 chunks（确保 100% 完整入库）
    chunks = []

    # chunk 0: 完整 Markdown 全文（不丢失任何内容）
    chunks.append({
        "index": 0,
        "type": "full",
        "content": md_text,
        "page_start": 1,
        "page_end": total_pages,
    })

    # chunk 1+: 每个表格作为一个独立 chunk
    for table in tables:
        chunks.append({
            "index": len(chunks),
            "type": "table",
            "content": table["markdown"],
            "table_data": table,
            "page_start": None,
            "page_end": None,
        })

    full_text = md_text
    if max_chars and len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "\n\n[...内容过长，已截断...]"

    return {
        "text": full_text,
        "chunks": chunks,
        "tables": tables,
        "pages": total_pages,
    }


def build_llm_context(structure: Dict, prefer_tables: bool = True, max_tables: int = 10) -> str:
    """将结构化内容组装成 LLM 友好的上下文"""
    parts = []

    # 1. 添加全文 Markdown
    parts.append("【公告正文】\n" + structure["text"])

    # 2. 添加结构化表格
    tables = structure.get("tables", [])
    if tables:
        priority_order = {"income": 0, "balance": 1, "cash": 2, "other": 3}
        tables_sorted = sorted(tables, key=lambda t: priority_order.get(t.get("table_type", "other"), 3))
        selected = tables_sorted[:max_tables]
        parts.append("\n\n【提取的财务表格】")
        for t in selected:
            ttype_label = {
                "income": "利润表",
                "balance": "资产负债表",
                "cash": "现金流量表",
                "other": "其他表格",
            }.get(t.get("table_type", "other"), "表格")
            parts.append(f"\n--- {ttype_label} ---")
            parts.append(t["markdown"])

    return "\n\n".join(parts)


# 兼容旧接口
def extract_text_from_pdf(pdf_path: str, max_chars: Optional[int] = None) -> str:
    """从 PDF 提取纯文本（兼容旧接口）"""
    structure = extract_structure_from_pdf(pdf_path, max_chars=max_chars)
    return structure["text"]
