"""股票池管理"""
from typing import List, Optional
from sqlalchemy.orm import Session
from database import Stock, get_db
from api.cninfo import search_stock


class StockPool:
    """股票池 CRUD"""

    @staticmethod
    def add_stock(code: str, db: Optional[Session] = None) -> Optional[Stock]:
        """添加股票到股票池（自动查询名称与 orgId）"""
        close_db = False
        if db is None:
            db = get_db()
            close_db = True

        try:
            # 去重检查
            existing = db.query(Stock).filter(Stock.code == code).first()
            if existing:
                print(f"[StockPool] 股票 {code} 已存在")
                return existing

            info = search_stock(code)
            if not info:
                print(f"[StockPool] 无法查询到股票 {code}")
                return None

            market = "sz"
            if info["orgId"].startswith("gssh"):
                market = "sh"
            elif info["orgId"].startswith("gsbj"):
                market = "bj"

            stock = Stock(
                code=info["code"],
                name=info["name"],
                market=market,
                org_id=info["orgId"],
            )
            db.add(stock)
            db.commit()
            db.refresh(stock)
            print(f"[StockPool] 添加股票: {info['code']} {info['name']}")
            return stock
        finally:
            if close_db:
                db.close()

    @staticmethod
    def remove_stock(code: str, db: Optional[Session] = None) -> bool:
        close_db = False
        if db is None:
            db = get_db()
            close_db = True
        try:
            stock = db.query(Stock).filter(Stock.code == code).first()
            if stock:
                db.delete(stock)
                db.commit()
                print(f"[StockPool] 移除股票: {code}")
                return True
            return False
        finally:
            if close_db:
                db.close()

    @staticmethod
    def list_stocks(db: Optional[Session] = None) -> List[Stock]:
        close_db = False
        if db is None:
            db = get_db()
            close_db = True
        try:
            return db.query(Stock).all()
        finally:
            if close_db:
                db.close()

    @staticmethod
    def get_stock(code: str, db: Optional[Session] = None) -> Optional[Stock]:
        close_db = False
        if db is None:
            db = get_db()
            close_db = True
        try:
            return db.query(Stock).filter(Stock.code == code).first()
        finally:
            if close_db:
                db.close()
