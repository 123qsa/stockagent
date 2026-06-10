"""全局配置"""
import os
from dotenv import load_dotenv

# 加载 .env 文件（如果存在）
load_dotenv()

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 数据目录
DATA_DIR = os.path.join(BASE_DIR, "data")
ANNOUNCEMENT_DIR = os.path.join(DATA_DIR, "announcements")

# 数据库
DATABASE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'stock.db')}"

# 巨潮资讯 API
CNINFO_BASE = "http://www.cninfo.com.cn"
CNINFO_STATIC = "http://static.cninfo.com.cn"
CNINFO_API_ANNOUNCEMENT = f"{CNINFO_BASE}/new/hisAnnouncement/query"
CNINFO_API_TOP_SEARCH = f"{CNINFO_BASE}/new/information/topSearch/query"

# 请求配置
REQUEST_TIMEOUT = 30
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}

# 轮询配置
POLL_INTERVAL_MINUTES = 5

# DeepSeek / OpenAI 兼容 API 配置
LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
LLM_MAX_TOKENS = int(os.getenv("DEEPSEEK_MAX_TOKENS", "4096"))
LLM_TEMPERATURE = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.3"))
# 单条公告最大分析字符数（防止超长）
LLM_MAX_TEXT_LENGTH = int(os.getenv("DEEPSEEK_MAX_TEXT_LENGTH", "12000"))



# 确保目录存在
os.makedirs(ANNOUNCEMENT_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
