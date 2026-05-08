"""并发下载封面图。"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests

import utils.config as config
from utils.parser import load_cover_items
from utils.pdf_utils import cleanup_images, images_to_pdf
from utils.tools import sanitize_filename

try:
    import httpx  # type: ignore
except ImportError:
    httpx = None


def run_download_job(name: str, index: dict, headers: dict) -> None:
    """执行单次抓取索引 -> 下载图片 -> 合成 PDF 的任务。"""
    items = load_cover_items(index)
    if not items:
        raise ValueError("未在索引文件中找到 cover 链接")

    image_dir = config.OUTPUT_DIR / name
    pdf_file = config.OUTPUT_DIR / f"{name}.pdf"

    downloaded = download_covers(items, image_dir, headers)
    if not downloaded:
        raise ValueError("图片下载全部失败，cover 链接可能已过期，请更新 review.json 后重试")
    images_to_pdf(downloaded, pdf_file)
    if config.DELETE_IMAGES_AFTER_PDF:
        cleanup_images(downloaded, image_dir)

    print(f"完成: 共下载 {len(downloaded)} 张图片")
    print(f"PDF 文件: {pdf_file}")


def submit_download_job(executor: ThreadPoolExecutor, name: str, index: dict, headers: dict) -> None:
    """提交下载任务到线程池，避免阻塞主监控流程。"""
    job_name = sanitize_filename(name)

    def task():
        try:
            print(f"任务开始: {job_name}")
            run_download_job(job_name, index, headers)
            print(f"任务完成: {job_name}")
        except Exception as e:
            print(f"任务失败: {job_name}: {e}")

    executor.submit(task)


def download_covers(items: list[tuple[int, str]], output_dir: Path, headers: dict) -> list[Path]:
    """并发下载封面图，返回按页码排序后的本地文件列表。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    success_map: dict[int, Path] = {}
    failed_items: list[tuple[int, str, str]] = []

    print(f"开始并发下载: 总数 {len(items)}，线程数 {config.MAX_WORKERS}，每张最多重试 {config.MAX_RETRIES} 次")

    client = None
    session = None
    if httpx is not None:
        client = httpx.Client(http2=True, verify=config.VERIFY_SSL, timeout=30.0, follow_redirects=True)
    else:
        session = requests.Session()

    def _download_one(index: int, url: str) -> tuple[int, Path | None, str | None]:
        filename = output_dir / f"{index:03d}.jpg"
        last_error: str | None = None
        actual_headers = dict(headers)
        actual_headers["Host"] = urlparse(url).netloc

        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                if client is not None:
                    resp = client.get(url, headers=actual_headers)
                    resp.raise_for_status()
                    content = resp.content
                else:
                    resp = session.get(url, headers=actual_headers, timeout=30, verify=config.VERIFY_SSL)
                    resp.raise_for_status()
                    content = resp.content
                filename.write_bytes(content)
                return index, filename, None
            except Exception as exc:
                last_error = f"第{attempt}次失败: {exc}"
                if attempt < config.MAX_RETRIES:
                    time.sleep(config.RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
        return index, None, last_error

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        future_to_item = {
            executor.submit(_download_one, index, url): (index, url)
            for index, url in items
        }

        for future in as_completed(future_to_item):
            index, url = future_to_item[future]
            try:
                result_index, saved_path, err = future.result()
                if saved_path is not None:
                    success_map[result_index] = saved_path
                    print(f"下载成功(第 {result_index} 页)")
                else:
                    failed_items.append((index, url, err or "未知错误"))
                    print(f"下载失败(第 {index} 页): {err}")
            except Exception as exc:
                failed_items.append((index, url, str(exc)))
                print(f"下载异常(第 {index} 页): {exc}")

    if client is not None:
        client.close()
    if session is not None:
        session.close()

    if failed_items:
        print(f"下载失败数量: {len(failed_items)}")

    return [success_map[idx] for idx in sorted(success_map)]
