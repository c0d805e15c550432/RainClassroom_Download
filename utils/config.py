"""全局常量、URL、请求头、可调参数。"""

from pathlib import Path

import urllib3
from urllib3.exceptions import InsecureRequestWarning

# ---------- API 端点 ----------
INDEX_URL = "https://pro.yuketang.cn/v2/web/index"
LESSON_INFO_URL = "https://pro.yuketang.cn/api/v3/classroom-report/student/lesson-info"
FETCH_URL = "https://pro.yuketang.cn/api/v3/lesson/presentation/fetch"
PPT_URL = "https://pro.yuketang.cn/api/v3/classroom-report/student/ppt"
CHECK_PERMISSION_URL = "https://pro.yuketang.cn/api/v3/lesson/meeting/meds/check-permission"

# ---------- HTTP 基础请求头 ----------
BASE_REQUEST_HEADERS = {
    "sec-ch-ua-platform": '"Windows"',
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Chromium";v="145", "Not:A-Brand";v="99"',
    "dnt": "1",
    "sec-ch-ua-mobile": "?0",
    "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "sec-fetch-site": "same-site",
    "sec-fetch-mode": "no-cors",
    "sec-fetch-dest": "image",
    "referer": "https://pro.yuketang.cn/",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,en-GB;q=0.6",
    "priority": "u=1, i",
    "upgrade-insecure-requests": "1",
}

# ---------- 运行参数 ----------
VERIFY_SSL = False
MAX_WORKERS = 8
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 0.8
JOB_WORKERS = 3

# ---------- 路径 ----------
BASE_DIR = Path(__file__).resolve().parent.parent
USER_DATA_DIR = BASE_DIR / "user_data"
OUTPUT_DIR = BASE_DIR / "downloads"
DELETE_IMAGES_AFTER_PDF = True

# ---------- 初始化 ----------
if not VERIFY_SSL:
    urllib3.disable_warnings(category=InsecureRequestWarning)
