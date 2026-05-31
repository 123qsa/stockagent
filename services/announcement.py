"""公告获取与存储服务"""
import os
import re
from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy.orm import Session

from database import get_db, Stock, Announcement
from api.cninfo import fetch_all_announcements, download_announcement_pdf
from config import ANNOUNCEMENT_DIR


def _safe_filename(stock_code: str, announce_time: str, title: str, announcement_id: str) -> str:
    """生成安全的本地文件名"""
    # 清理非法字符
    clean_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:80]
    date_str = announce_time.replace("-", "").replace(" ", "_").replace(":", "")
    return f"{stock_code}_{date_str}_{announcement_id}_{clean_title}.pdf"


def _parse_time(time_val) -> Optional[datetime]:
    """解析巨潮时间（支持字符串和毫秒时间戳）"""
    if not time_val:
        return None
    if isinstance(time_val, (int, float)):
        # 毫秒时间戳
        return datetime.fromtimestamp(time_val / 1000)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(time_val, fmt)
        except ValueError:
            continue
    return None


class AnnouncementService:
    """公告业务服务"""

    @staticmethod
    def sync_stock_announcements(
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> int:
        """同步某只股票的公告，支持日期范围筛选，返回新增数量"""
        close_db = False
        if db is None:
            db = get_db()
            close_db = True

        added = 0
        try:
            stock = db.query(Stock).filter(Stock.code == stock_code).first()
            if not stock:
                print(f"[AnnouncementService] 股票 {stock_code} 不在股票池中")
                return 0

            date_range = ""
            if start_date and end_date:
                date_range = f"（{start_date} ~ {end_date}）"
            print(f"[AnnouncementService] 开始同步 {stock_code} {stock.name or ''} 的公告{date_range}...")
            items = fetch_all_announcements(stock_code, stock.org_id, start_date, end_date)
            print(f"[AnnouncementService] 获取到 {len(items)} 条公告")

            # 优化：检查该股票是否已有公告记录
            existing_ids = set()
            has_existing = db.query(Announcement).filter(Announcement.stock_code == stock_code).first() is not None
            if has_existing:
                rows = db.query(Announcement.announcement_id).filter(Announcement.stock_code == stock_code).all()
                existing_ids = {r[0] for r in rows}

            latest_time = stock.last_announcement_time
            batch = []
            seen_ids = set()  # 防止同一批 API 数据中有重复 ID

            for item in items:
                ann_id = str(item.get("announcementId", ""))
                if not ann_id:
                    continue
                if ann_id in existing_ids or ann_id in seen_ids:
                    continue
                seen_ids.add(ann_id)

                announce_time = _parse_time(item.get("announcementTime"))

                ann = Announcement(
                    stock_code=stock_code,
                    stock_name=stock.name,
                    announcement_id=ann_id,
                    title=item.get("announcementTitle", ""),
                    announcement_time=announce_time,
                    adjunct_url=item.get("adjunctUrl", ""),
                    category=item.get("announcementTypeName", ""),
                )
                batch.append(ann)
                added += 1

                if announce_time and (latest_time is None or announce_time > latest_time):
                    latest_time = announce_time

            if batch:
                db.add_all(batch)
            if latest_time:
                stock.last_announcement_time = latest_time
            db.commit()
            print(f"[AnnouncementService] {stock_code} 新增 {added} 条公告记录")
            return added
        except Exception as e:
            db.rollback()
            print(f"[AnnouncementService] 同步 {stock_code} 失败: {e}")
            raise
        finally:
            if close_db:
                db.close()

    @staticmethod
    def download_pending_announcements(stock_code: Optional[str] = None, db: Optional[Session] = None) -> int:
        """下载未下载的公告 PDF，返回下载成功数量"""
        close_db = False
        if db is None:
            db = get_db()
            close_db = True

        downloaded = 0
        try:
            query = db.query(Announcement).filter(Announcement.downloaded == False)
            if stock_code:
                query = query.filter(Announcement.stock_code == stock_code)

            pending = query.all()
            print(f"[AnnouncementService] 待下载公告: {len(pending)} 条")

            for ann in pending:
                if not ann.adjunct_url:
                    continue
                try:
                    filename = _safe_filename(
                        ann.stock_code,
                        ann.announcement_time.strftime("%Y%m%d_%H%M%S") if ann.announcement_time else "unknown",
                        ann.title or "unnamed",
                        ann.announcement_id,
                    )
                    local_path = download_announcement_pdf(ann.adjunct_url, filename)
                    ann.local_path = local_path
                    ann.downloaded = True
                    downloaded += 1
                except Exception as e:
                    print(f"[AnnouncementService] 下载失败 {ann.announcement_id}: {e}")

            db.commit()
            print(f"[AnnouncementService] 成功下载 {downloaded} 条公告")
            return downloaded
        except Exception as e:
            db.rollback()
            raise
        finally:
            if close_db:
                db.close()

    @staticmethod
    def check_new_announcements(stock_code: str, db: Optional[Session] = None) -> int:
        """检查并同步某只股票的最新公告，返回新增数量"""
        # 复用 sync，但可以通过 last_announcement_time 优化（TODO: 后续支持按日期增量）
        return AnnouncementService.sync_stock_announcements(stock_code, db)

    @staticmethod
    def poll_all_stocks(db: Optional[Session] = None) -> Dict[str, int]:
        """轮询股票池，检查所有股票的新公告"""
        from services.stock_pool import StockPool

        close_db = False
        if db is None:
            db = get_db()
            close_db = True

        results = {}
        try:
            stocks = StockPool.list_stocks(db)
            for stock in stocks:
                try:
                    new_count = AnnouncementService.check_new_announcements(stock.code, db)
                    results[stock.code] = new_count
                    if new_count > 0:
                        AnnouncementService.download_pending_announcements(stock.code, db)
                except Exception as e:
                    print(f"[AnnouncementService] 轮询 {stock.code} 出错: {e}")
                    results[stock.code] = -1
            return results
        finally:
            if close_db:
                db.close()


