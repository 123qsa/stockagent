"""巨潮资讯网 API 封装"""
import requests
import time
from typing import List, Dict, Optional
from config import (
    CNINFO_API_ANNOUNCEMENT,
    CNINFO_API_TOP_SEARCH,
    CNINFO_STATIC,
    REQUEST_TIMEOUT,
    REQUEST_HEADERS,
    ANNOUNCEMENT_DIR,
)


def search_stock(keyword: str) -> Optional[Dict]:
    """搜索股票，获取 orgId 等元数据"""
    try:
        resp = requests.post(
            CNINFO_API_TOP_SEARCH,
            data={"keyWord": keyword},
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            for item in data:
                if item.get("category") == "A股":
                    return {
                        "code": item["code"],
                        "name": item["zwjc"],
                        "orgId": item["orgId"],
                        "zwjc": item.get("zwjc", ""),
                    }
        return None
    except Exception as e:
        print(f"[search_stock] 搜索失败: {e}")
        return None


def _market_params(stock_code: str, org_id: str) -> Dict:
    """根据股票代码和 orgId 推断市场参数"""
    if org_id.startswith("gssz") or stock_code.startswith(("0", "3", "2")):
        return {"column": "szse", "plate": "sz", "secid": f"sz{stock_code}"}
    elif org_id.startswith("gssh") or stock_code.startswith(("6", "9")):
        return {"column": "sse", "plate": "sh", "secid": f"sh{stock_code}"}
    else:
        return {"column": "bse", "plate": "bj", "secid": f"bj{stock_code}"}


def fetch_announcement_list(
    stock_code: str,
    org_id: str,
    page_num: int = 1,
    page_size: int = 30,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict:
    """获取公告列表
    
    返回: {
        "total": int,
        "announcements": List[dict],
        "has_more": bool,
    }
    """
    mp = _market_params(stock_code, org_id)
    se_date = ""
    if start_date and end_date:
        se_date = f"{start_date}~{end_date}"

    payload = {
        "pageNum": page_num,
        "pageSize": page_size,
        "tabName": "fulltext",
        "stock": f"{stock_code},{org_id}",
        "column": mp["column"],
        "category": "category_all_szsh",
        "plate": mp["plate"],
        "seDate": se_date,
        "isHLtitle": "true",
    }

    resp = requests.post(
        CNINFO_API_ANNOUNCEMENT,
        data=payload,
        headers=REQUEST_HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    announcements = data.get("announcements") or []
    total = data.get("totalRecordNum", 0)

    return {
        "total": total,
        "announcements": announcements,
        "has_more": page_num * page_size < total,
    }


def fetch_all_announcements(
    stock_code: str,
    org_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[Dict]:
    """拉取某只股票的全部公告"""
    all_items = []
    page_num = 1
    page_size = 30

    while True:
        result = fetch_announcement_list(
            stock_code, org_id, page_num, page_size, start_date, end_date
        )
        items = result.get("announcements", [])
        if not items:
            break
        all_items.extend(items)
        if not result["has_more"]:
            break
        page_num += 1
        time.sleep(0.3)  # 礼貌限速

    return all_items


def download_announcement_pdf(adjunct_url: str, local_filename: str) -> str:
    """下载公告 PDF，返回本地绝对路径"""
    if not adjunct_url:
        raise ValueError("adjunct_url 为空")
    url = f"{CNINFO_STATIC}/{adjunct_url.lstrip('/')}"
    local_path = f"{ANNOUNCEMENT_DIR}/{local_filename}"

    resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    with open(local_path, "wb") as f:
        f.write(resp.content)

    return local_path
