#!/usr/bin/env python3
"""股票分析系统 - 入口"""
import sys
import argparse
from typing import Optional
from database import init_db, get_db, Announcement
from services.stock_pool import StockPool
from services.announcement import AnnouncementService
from services.llm_analyzer import AnnouncementAnalyzer, ANALYSIS_TYPES
from services.pdf_parser import PDFParserService
from scheduler.job import start_scheduler, stop_scheduler, trigger_once


def _download_recent(stock_code: str, limit: int = 10):
    """只下载最近 N 条未下载的公告 PDF"""
    db = get_db()
    try:
        pending = (
            db.query(Announcement)
            .filter(Announcement.stock_code == stock_code, Announcement.downloaded == False)
            .order_by(Announcement.announcement_time.desc())
            .limit(limit)
            .all()
        )
        for ann in pending:
            if not ann.adjunct_url:
                continue
            try:
                from api.cninfo import download_announcement_pdf
                from services.announcement import _safe_filename
                filename = _safe_filename(
                    ann.stock_code,
                    ann.announcement_time.strftime("%Y%m%d_%H%M%S") if ann.announcement_time else "unknown",
                    ann.title or "unnamed",
                    ann.announcement_id,
                )
                local_path = download_announcement_pdf(ann.adjunct_url, filename)
                ann.local_path = local_path
                ann.downloaded = True
            except Exception as e:
                print(f"[Main] 下载失败 {ann.announcement_id}: {e}")
        db.commit()
        print(f"[Main] 已下载 {stock_code} 最近 {len(pending)} 条公告 PDF")
    finally:
        db.close()


def init():
    """初始化数据库"""
    init_db()
    print("[Main] 数据库初始化完成")


def add_stock(code: str, start_date: Optional[str] = None, end_date: Optional[str] = None):
    """添加股票到股票池"""
    stock = StockPool.add_stock(code)
    if stock:
        # 同步公告元数据（支持日期范围，不自动下载全部PDF，避免超时）
        AnnouncementService.sync_stock_announcements(code, start_date=start_date, end_date=end_date)
        # 只下载最近10条公告的PDF
        _download_recent(code, limit=10)


def remove_stock(code: str):
    """从股票池移除股票"""
    StockPool.remove_stock(code)


def list_stocks():
    """列出股票池"""
    stocks = StockPool.list_stocks()
    if not stocks:
        print("股票池为空")
        return
    print("\n当前股票池:")
    print(f"{'代码':<10} {'名称':<12} {'市场':<6} {'最后公告时间':<20}")
    print("-" * 50)
    for s in stocks:
        last = s.last_announcement_time.strftime("%Y-%m-%d %H:%M") if s.last_announcement_time else "-"
        print(f"{s.code:<10} {s.name or '':<12} {s.market or '':<6} {last:<20}")
    print()


def sync_stock(code: str, start_date: Optional[str] = None, end_date: Optional[str] = None):
    """手动同步某只股票公告"""
    AnnouncementService.sync_stock_announcements(code, start_date=start_date, end_date=end_date)
    AnnouncementService.download_pending_announcements(code)


def sync_all():
    """手动同步所有股票公告"""
    trigger_once()


def analyze_stock(code: str, types: list, limit: int):
    """用 DeepSeek 分析某只股票最新公告"""
    analyzer = AnnouncementAnalyzer()
    results = analyzer.analyze_batch(code, analysis_types=types, limit=limit)
    total = sum(len(v) for v in results.values())
    print(f"\n[Main] 分析完成，共处理 {len(results)} 条公告，{total} 个分析结果")


def parse_stock(code: str, limit: int, all: bool = False):
    """解析某只股票的公告 PDF（结构化提取表格）"""
    if all:
        # 解析所有已下载但未解析的
        results = PDFParserService.parse_stock_announcements(code, limit=None)
    else:
        results = PDFParserService.parse_stock_announcements(code, limit=limit)
    print(f"\n[Main] 解析完成: 成功 {results['success']}, 失败 {results['failed']}")


def parse_all(limit: int = 10):
    """解析股票池中所有股票的最近公告"""
    stocks = StockPool.list_stocks()
    if not stocks:
        print("股票池为空")
        return
    for stock in stocks:
        try:
            print(f"\n[Main] ===== 解析 {stock.code} {stock.name or ''} =====")
            results = PDFParserService.parse_stock_announcements(stock.code, limit=limit)
            print(f"[Main] 成功 {results['success']}, 失败 {results['failed']}")
        except Exception as e:
            print(f"[Main] 解析 {stock.code} 失败: {e}")


def analyze_all(types: list, limit: int):
    """分析股票池中所有股票的最新公告"""
    stocks = StockPool.list_stocks()
    if not stocks:
        print("股票池为空")
        return
    analyzer = AnnouncementAnalyzer()
    for stock in stocks:
        try:
            print(f"\n[Main] ===== 分析 {stock.code} {stock.name or ''} =====")
            analyzer.analyze_batch(stock.code, analysis_types=types, limit=limit)
        except Exception as e:
            print(f"[Main] 分析 {stock.code} 失败: {e}")


def start_poll(interval: int = 5):
    """启动定时轮询"""
    start_scheduler(interval)
    print("按 Ctrl+C 停止...")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_scheduler()


def main():
    parser = argparse.ArgumentParser(description="股票分析系统")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="初始化数据库")

    p_add = sub.add_parser("add", help="添加股票到股票池")
    p_add.add_argument("code", help="股票代码，如 000001")
    p_add.add_argument("--start-date", help="起始日期，如 2025-12-01")
    p_add.add_argument("--end-date", help="结束日期，如 2026-05-30")

    p_remove = sub.add_parser("remove", help="从股票池移除股票")
    p_remove.add_argument("code", help="股票代码")

    sub.add_parser("list", help="列出股票池")

    p_sync = sub.add_parser("sync", help="手动同步某只股票公告")
    p_sync.add_argument("code", help="股票代码")
    p_sync.add_argument("--start-date", help="起始日期，如 2025-12-01")
    p_sync.add_argument("--end-date", help="结束日期，如 2026-05-30")

    sub.add_parser("sync-all", help="手动同步所有股票公告")

    p_poll = sub.add_parser("poll", help="启动定时轮询")
    p_poll.add_argument("--interval", type=int, default=5, help="轮询间隔（分钟），默认 5")

    p_analyze = sub.add_parser("analyze", help="用 DeepSeek 分析股票公告")
    p_analyze.add_argument("code", help="股票代码")
    p_analyze.add_argument("--type", dest="analysis_types", action="append", choices=list(ANALYSIS_TYPES.keys()), help="分析类型，可多次指定，默认 summary")
    p_analyze.add_argument("--limit", type=int, default=3, help="分析最近 N 条公告，默认 3")

    p_analyze_all = sub.add_parser("analyze-all", help="分析股票池所有股票")
    p_analyze_all.add_argument("--type", dest="analysis_types", action="append", choices=list(ANALYSIS_TYPES.keys()), help="分析类型，可多次指定，默认 summary")
    p_analyze_all.add_argument("--limit", type=int, default=3, help="每只分析最近 N 条，默认 3")

    p_parse = sub.add_parser("parse", help="解析公告 PDF（结构化提取表格）")
    p_parse.add_argument("code", help="股票代码")
    p_parse.add_argument("--limit", type=int, default=10, help="解析最近 N 条，默认 10")
    p_parse.add_argument("--all", action="store_true", help="解析该股票所有未解析的公告")

    p_parse_all = sub.add_parser("parse-all", help="解析股票池所有股票的公告")
    p_parse_all.add_argument("--limit", type=int, default=5, help="每只解析最近 N 条，默认 5")

    args = parser.parse_args()

    if args.command == "init":
        init()
    elif args.command == "add":
        init()
        add_stock(args.code, start_date=args.start_date, end_date=args.end_date)
    elif args.command == "remove":
        remove_stock(args.code)
    elif args.command == "list":
        list_stocks()
    elif args.command == "sync":
        sync_stock(args.code, start_date=args.start_date, end_date=args.end_date)
    elif args.command == "sync-all":
        init()
        sync_all()
    elif args.command == "poll":
        init()
        start_poll(args.interval)
    elif args.command == "analyze":
        types = args.analysis_types or ["summary"]
        analyze_stock(args.code, types, args.limit)
    elif args.command == "analyze-all":
        types = args.analysis_types or ["summary"]
        analyze_all(types, args.limit)
    elif args.command == "parse":
        parse_stock(args.code, args.limit, all=args.all)
    elif args.command == "parse-all":
        parse_all(args.limit)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
