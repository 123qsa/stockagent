"""数据库模型与连接"""
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from datetime import datetime
from config import DATABASE_URL

Base = declarative_base()
engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


class Stock(Base):
    """股票池"""
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, unique=True, index=True, comment="股票代码")
    name = Column(String(100), comment="股票名称")
    market = Column(String(10), comment="市场 sz/sh/bj")
    org_id = Column(String(50), comment="巨潮资讯 orgId")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_announcement_time = Column(DateTime, comment="最后一条公告时间")


class Announcement(Base):
    """公告记录"""
    __tablename__ = "announcements"
    __table_args__ = (UniqueConstraint("stock_code", "announcement_id", name="uq_stock_announcement"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(20), nullable=False, index=True)
    stock_name = Column(String(100))
    announcement_id = Column(String(50), nullable=False, index=True, comment="巨潮公告ID")
    title = Column(Text, comment="公告标题")
    announcement_time = Column(DateTime, index=True, comment="公告时间")
    adjunct_url = Column(Text, comment="公告PDF相对路径")
    local_path = Column(Text, comment="本地保存路径")
    category = Column(String(50), comment="公告类别")
    downloaded = Column(Boolean, default=False)
    parsed = Column(Boolean, default=False, comment="是否已完成结构化解析")
    parsed_at = Column(DateTime, comment="解析完成时间")
    created_at = Column(DateTime, default=datetime.now)


class AnalysisResult(Base):
    """公告 AI 分析结果"""
    __tablename__ = "analysis_results"
    __table_args__ = (UniqueConstraint("announcement_id", "analysis_type", name="uq_ann_analysis"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    announcement_id = Column(String(50), nullable=False, index=True)
    stock_code = Column(String(20), nullable=False, index=True)
    analysis_type = Column(String(50), nullable=False, comment="分析类型: summary/risk/key_info")
    result = Column(Text, comment="分析结果 JSON 或文本")
    model = Column(String(50), comment="使用的模型")
    tokens_used = Column(Integer, comment="消耗的 token 数")
    created_at = Column(DateTime, default=datetime.now)


class AnnouncementChunk(Base):
    """公告文本块（用于结构化分析）"""
    __tablename__ = "announcement_chunks"
    __table_args__ = (
        UniqueConstraint("announcement_id", "chunk_index", name="uq_ann_chunk"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    announcement_id = Column(String(50), nullable=False, index=True)
    stock_code = Column(String(20), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False, comment="块序号")
    chunk_type = Column(String(20), default="text", comment="text/table/title")
    content = Column(Text, comment="文本内容")
    table_data = Column(Text, comment="JSON格式的表格数据（当chunk_type=table时）")
    page_start = Column(Integer, comment="起始页码")
    page_end = Column(Integer, comment="结束页码")
    created_at = Column(DateTime, default=datetime.now)


class FinancialTable(Base):
    """公告中的财务表格（结构化存储，防数字幻觉）"""
    __tablename__ = "financial_tables"
    __table_args__ = (
        UniqueConstraint("announcement_id", "table_index", name="uq_ann_table"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    announcement_id = Column(String(50), nullable=False, index=True)
    stock_code = Column(String(20), nullable=False, index=True)
    table_index = Column(Integer, nullable=False, comment="公告中的第几张表")
    table_title = Column(String(200), comment="表标题")
    table_type = Column(String(50), default="other", comment="income/balance/cash/other")
    page_number = Column(Integer, comment="所在页码")
    headers = Column(Text, comment="JSON表头")
    rows = Column(Text, comment="JSON行数据")
    html = Column(Text, comment="HTML格式表格")
    context = Column(Text, comment="表格前后文文本")
    row_count = Column(Integer, comment="行数")
    col_count = Column(Integer, comment="列数")
    created_at = Column(DateTime, default=datetime.now)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    return SessionLocal()
