"""Web 服务 - 股票公告分析对话界面"""

import os
import sys
import json
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# 确保能导入项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_db, Stock, Announcement, AnalysisResult
from services.pdf_parser import PDFParserService
from services.llm_analyzer import AnnouncementAnalyzer, ANALYSIS_TYPES

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/stocks")
def api_stocks():
    """获取股票池列表"""
    db = get_db()
    try:
        stocks = db.query(Stock).order_by(Stock.code).all()
        return jsonify([
            {
                "code": s.code,
                "name": s.name,
                "market": s.market,
                "last_announcement_time": s.last_announcement_time.strftime("%Y-%m-%d %H:%M") if s.last_announcement_time else None,
            }
            for s in stocks
        ])
    finally:
        db.close()


@app.route("/api/stocks/<code>/announcements")
def api_stock_announcements(code: str):
    """获取某只股票的公告列表"""
    db = get_db()
    try:
        limit = request.args.get("limit", 50, type=int)
        anns = (
            db.query(Announcement)
            .filter(Announcement.stock_code == code)
            .order_by(Announcement.announcement_time.desc())
            .limit(limit)
            .all()
        )
        return jsonify([
            {
                "id": a.announcement_id,
                "title": a.title,
                "time": a.announcement_time.strftime("%Y-%m-%d") if a.announcement_time else "",
                "category": a.category,
                "downloaded": a.downloaded,
                "parsed": a.parsed,
            }
            for a in anns
        ])
    finally:
        db.close()


@app.route("/api/announcements/<ann_id>/context")
def api_announcement_context(ann_id: str):
    """获取公告上下文（用于 LLM）"""
    max_chars = request.args.get("max_chars", 12000, type=int)
    try:
        ctx = PDFParserService.get_announcement_context(ann_id, max_tables=10)
        if len(ctx) > max_chars:
            ctx = ctx[:max_chars] + "\n\n[...内容过长，已截断...]"
        return jsonify({"context": ctx, "length": len(ctx)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/announcements/<ann_id>/analysis")
def api_announcement_analysis(ann_id: str):
    """获取已保存的分析结果"""
    db = get_db()
    try:
        results = (
            db.query(AnalysisResult)
            .filter(AnalysisResult.announcement_id == ann_id)
            .order_by(AnalysisResult.analysis_type)
            .all()
        )
        return jsonify([
            {
                "type": r.analysis_type,
                "type_name": ANALYSIS_TYPES.get(r.analysis_type, (r.analysis_type, ""))[0],
                "result": r.result,
                "model": r.model,
                "tokens": r.tokens_used,
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
            }
            for r in results
        ])
    finally:
        db.close()


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """LLM 对话接口

    Request:
    {
        "message": "用户问题",
        "stock_code": "000001",          // 可选
        "announcement_id": "...",        // 可选，如提供则带入公告上下文
        "analysis_type": "summary",      // 可选: summary/key_info/risk/impact
        "history": [{"role": "user"/"assistant", "content": "..."}]  // 可选
    }
    """
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    stock_code = data.get("stock_code", "")
    announcement_id = data.get("announcement_id", "")
    analysis_type = data.get("analysis_type", "summary")
    history = data.get("history", [])

    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    if analysis_type not in ANALYSIS_TYPES:
        analysis_type = "summary"

    try:
        # 构建系统提示词
        label, system_prompt = ANALYSIS_TYPES[analysis_type]

        # 如果有公告ID，获取上下文
        context = ""
        if announcement_id:
            try:
                ctx = PDFParserService.get_announcement_context(announcement_id, max_tables=10)
                if ctx:
                    max_len = 12000
                    if len(ctx) > max_len:
                        ctx = ctx[:max_len] + "\n\n[...内容过长，已截断...]"
                    context = ctx
            except Exception as e:
                print(f"[Web] 获取上下文失败: {e}")

        # 组装 user content
        if context:
            user_content = f"股票代码: {stock_code}\n\n{context}\n\n用户问题: {message}"
        else:
            user_content = f"股票代码: {stock_code}\n\n用户问题: {message}"

        # 调用 LLM
        from services.llm_analyzer import LLMClient, LLM_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE
        client = LLMClient()

        messages = [{"role": "system", "content": system_prompt}]

        # 添加历史记录（最多保留 6 轮）
        for h in history[-12:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})

        messages.append({"role": "user", "content": user_content})

        resp = client.client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )

        content = resp.choices[0].message.content
        tokens = resp.usage.total_tokens if resp.usage else 0

        return jsonify({
            "content": content,
            "tokens": tokens,
            "analysis_type": analysis_type,
            "analysis_name": label,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat/v2", methods=["POST"])
def api_chat_v2():
    """LLM 对话接口 V2 - 支持历史记录"""
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    stock_code = data.get("stock_code", "")
    announcement_id = data.get("announcement_id", "")
    analysis_type = data.get("analysis_type", "summary")
    history = data.get("history", [])

    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    if analysis_type not in ANALYSIS_TYPES:
        analysis_type = "summary"

    try:
        label, system_prompt = ANALYSIS_TYPES[analysis_type]

        # 获取公告上下文
        context = ""
        if announcement_id:
            try:
                ctx = PDFParserService.get_announcement_context(announcement_id, max_tables=10)
                if ctx:
                    max_len = 12000
                    if len(ctx) > max_len:
                        ctx = ctx[:max_len] + "\n\n[...内容过长，已截断...]"
                    context = ctx
            except Exception as e:
                print(f"[Web] 获取上下文失败: {e}")

        # 构建消息
        from services.llm_analyzer import LLMClient, LLM_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE
        client = LLMClient()

        messages = [{"role": "system", "content": system_prompt}]

        # 历史记录
        for h in history[-12:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})

        # 当前消息
        if context:
            user_content = f"股票代码: {stock_code}\n\n{context}\n\n用户问题: {message}"
        else:
            user_content = f"股票代码: {stock_code}\n\n用户问题: {message}"

        messages.append({"role": "user", "content": user_content})

        resp = client.client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )

        content = resp.choices[0].message.content
        tokens = resp.usage.total_tokens if resp.usage else 0

        return jsonify({
            "content": content,
            "tokens": tokens,
            "analysis_type": analysis_type,
            "analysis_name": label,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/ragflow/chat", methods=["POST"])
def api_ragflow_chat():
    """通过 RAGFlow 进行跨公告问答（需先部署 RAGFlow 服务并同步数据）

    Request:
    {
        "stock_code": "000001",
        "message": "2024年净利润是多少",
        "history": [...]
    }
    """
    data = request.get_json() or {}
    stock_code = data.get("stock_code", "").strip()
    message = data.get("message", "").strip()

    if not stock_code:
        return jsonify({"error": "股票代码不能为空"}), 400
    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    try:
        from rag import RAGFlowAdapter, check_ragflow_available

        if not check_ragflow_available():
            return jsonify({
                "error": "RAGFlow 服务未就绪",
                "hint": "请先部署 RAGFlow 服务并同步公告数据",
            }), 503

        adapter = RAGFlowAdapter()
        answer = adapter.chat(stock_code, message)

        return jsonify({
            "content": answer,
            "stock_code": stock_code,
            "source": "ragflow",
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/ragflow/retrieve", methods=["POST"])
def api_ragflow_retrieve():
    """通过 RAGFlow 检索公告片段（用于展示引用来源）

    Request:
    {
        "stock_code": "000001",
        "question": "2024年净利润",
        "top_k": 5
    }
    """
    data = request.get_json() or {}
    stock_code = data.get("stock_code", "").strip()
    question = data.get("question", "").strip()
    top_k = data.get("top_k", 5)

    if not stock_code or not question:
        return jsonify({"error": "股票代码和问题不能为空"}), 400

    try:
        from rag import RAGFlowAdapter, check_ragflow_available

        if not check_ragflow_available():
            return jsonify({"error": "RAGFlow 服务未就绪"}), 503

        adapter = RAGFlowAdapter()
        chunks = adapter.retrieve(stock_code, question, top_k=top_k)

        results = []
        for chunk in chunks:
            results.append({
                "content": getattr(chunk, "content", str(chunk))[:800],
                "doc_name": getattr(chunk, "document_name", ""),
                "score": getattr(chunk, "similarity", None),
            })

        return jsonify({
            "stock_code": stock_code,
            "question": question,
            "count": len(results),
            "chunks": results,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("[WebServer] 启动股票公告分析服务...")
    print("[WebServer] 访问 http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
