"""API 请求头构建、接口回调处理、下载任务派发。"""

import time
from concurrent.futures import ThreadPoolExecutor

import utils.config as config
from utils.downloader import submit_download_job
from utils.tools import load_json_file, request_json


def build_api_headers() -> dict:
    """构建 API 请求头：固定请求头 + storage_state cookies。"""
    headers = dict(config.BASE_REQUEST_HEADERS)
    cookies = load_json_file(config.USER_DATA_DIR / "cookies.json", [])
    cookie_header = cookies_to_header(cookies)
    if cookie_header:
        headers["cookie"] = cookie_header
    headers["accept"] = "application/json, text/plain, */*"
    headers["referer"] = config.INDEX_URL
    return headers


def cookies_to_header(cookies: list[dict]) -> str:
    """将 cookie 列表转换为 HTTP Cookie 头字符串。"""
    pairs = []
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
        if isinstance(name, str) and isinstance(value, str):
            pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def permission_judge(payload: dict) -> bool:
    """权限校验，防判断是否登录成功。"""
    if not payload:
        return False
    if payload.get("code") == 0 and payload.get("msg", "") == "OK":
        return True
    return False


def handle_lesson_info(index: dict, job_executor: ThreadPoolExecutor, processed_keys: set[str]) -> None:
    """处理 lesson-info，补拉 PPT 接口并生成下载任务。"""
    data = index.get("data", {})
    lesson_id = data.get("lessonId")
    presentation_ids = data.get("presentationIds") or []
    lesson_name = str(data.get("lessonName") or "lesson")
    teacher_name = str(data.get("teacherName") or "teacher")

    if not lesson_id or not isinstance(presentation_ids, list) or not presentation_ids:
        return

    headers = build_api_headers()
    print(headers)
    for i, presentation_id in enumerate(presentation_ids, start=1):
        key = f"lesson:{lesson_id}:{presentation_id}"
        if key in processed_keys:
            continue
        processed_keys.add(key)

        params = {
            "lesson_id": lesson_id,
            "presentationId": presentation_id,
            "front_time": str(int(time.time() * 1000)),
        }
        try:
            ppt_payload = request_json(config.PPT_URL, headers=headers, params=params)
            suffix = f"_{i}" if len(presentation_ids) > 1 else ""
            name = f"{lesson_name}_{teacher_name}{suffix}"
            submit_download_job(job_executor, name, ppt_payload, headers)
        except Exception as e:
            print(f"获取 PPT 失败: lesson_id={lesson_id}, presentationId={presentation_id}, error={e}")


def handle_fetch(index: dict, job_executor: ThreadPoolExecutor, processed_keys: set[str]) -> None:
    """处理 fetch 接口回包并生成下载任务。"""
    data = index.get("data", {})
    activity_id = data.get("activityId") or data.get("activity_id") or "unknown"
    pages = len(data.get("slides") or [])
    title = str(data.get("title") or "fetch") + f"_{pages}pages"

    key = f"fetch:{activity_id}:{title}:_{pages}"
    if key in processed_keys:
        return
    processed_keys.add(key)

    headers = build_api_headers()
    submit_download_job(job_executor, title, index, headers)


