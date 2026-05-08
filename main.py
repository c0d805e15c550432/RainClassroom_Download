"""Playwright 浏览器监控主循环，监听接口响应并异步派发下载任务。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import utils.config as config
from utils.api import handle_fetch, handle_lesson_info, permission_judge
from utils.tools import save_json_file

try:
    from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, sync_playwright  # type: ignore
except ImportError:
    sync_playwright = None
    PlaywrightError = Exception  # type: ignore
    PlaywrightTimeoutError = TimeoutError  # type: ignore


def monitor_with_playwright() -> None:
    """启动浏览器监听接口响应，并异步派发下载任务。"""
    if sync_playwright is None:
        raise RuntimeError("未安装 playwright，请先执行: pip install playwright && playwright install chromium")

    job_executor = ThreadPoolExecutor(max_workers=config.JOB_WORKERS)
    event_executor = ThreadPoolExecutor(max_workers=3)
    shutdown_event = Event()
    processed_keys: set[str] = set()

    def mark_shutdown(reason: str) -> None:
        if not shutdown_event.is_set():
            print(reason)
            shutdown_event.set()

    try:
        with sync_playwright() as p:
            context = None
            browser = None

            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(config.USER_DATA_DIR),
                    # channel="msedge",
                    headless=False,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                    ],
                    ignore_default_args=["--enable-automation"],
                    ignore_https_errors=not config.VERIFY_SSL,
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0",
                    extra_http_headers={
                        "sec-ch-ua": '"Microsoft Edge";v="147", "Not.A/Brand";v="8", "Chromium";v="147"'
                    }
                )
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """)
            except Exception as exc:
                print(f"加载存储态失败，使用空上下文继续: {exc}")
                browser = p.chromium.launch(headless=False)
                context = browser.new_context()

            context.on("close", lambda: mark_shutdown("检测到浏览器上下文已关闭，准备收尾..."))

            page = context.pages[0] if context.pages else context.new_page()

            def on_response(response):
                url = response.url

                if config.CHECK_PERMISSION_URL in url:
                    if permission_judge(response.json()):
                        save_json_file(config.USER_DATA_DIR / "cookies.json", context.cookies())
                        print("登录成功！")
                    else:
                        mark_shutdown("登录失效，请重新登录。")

                if config.LESSON_INFO_URL not in url and config.FETCH_URL not in url:
                    return

                print(f"命中目标响应: {url}", flush=True)
                try:
                    payload = response.json()
                except Exception as exc:
                    print(f"解析响应失败: {url}, error={exc}")
                    return

                if config.LESSON_INFO_URL in url:
                    event_executor.submit(handle_lesson_info, payload, job_executor, processed_keys)
                    return

                if config.FETCH_URL in url:
                    event_executor.submit(handle_fetch, payload, job_executor, processed_keys)

            context.on("response", on_response)

            try:
                page.goto(config.INDEX_URL, wait_until="networkidle", timeout=20000)
            except (PlaywrightTimeoutError, PlaywrightError) as e:
                print(f"首次打开页面失败(可能是代理/SSL握手问题)，监控继续运行，请手动刷新页面: {e}")

            print("监控已启动，关闭浏览器窗口后将等待已提交任务完成并退出。", flush=True)
            try:
                while not shutdown_event.is_set():
                    page.wait_for_timeout(500)
            except KeyboardInterrupt:
                mark_shutdown("收到中断信号，准备退出并等待任务完成...")
            except PlaywrightError as exc:
                mark_shutdown(f"监控循环结束: {exc}")

            finally:
                try:
                    if browser is not None and browser.is_connected():
                        browser.close()
                except Exception:
                    pass
    finally:
        print("浏览器已关闭，等待下载与合成任务收尾...")
        event_executor.shutdown(wait=True)
        job_executor.shutdown(wait=True)
        print("全部任务结束，进程退出。")

if __name__ == "__main__":
    monitor_with_playwright()