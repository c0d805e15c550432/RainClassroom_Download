import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event
from urllib.parse import urlparse

from PIL import Image

try:
	import httpx  # type: ignore
except ImportError:
	httpx = None

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

try:
	from playwright.sync_api import Error as PlaywrightError, Response, TimeoutError as PlaywrightTimeoutError, sync_playwright  # type: ignore
except ImportError:
	sync_playwright = None
	PlaywrightError = Exception  # type: ignore
	PlaywrightTimeoutError = TimeoutError  # type: ignore
	Response = object  # type: ignore


INDEX_URL = "https://pro.yuketang.cn/v2/web/index"
LESSON_INFO_URL = "https://pro.yuketang.cn/api/v3/classroom-report/student/lesson-info"
FETCH_URL = "https://pro.yuketang.cn/api/v3/lesson/presentation/fetch"
PPT_URL = "https://pro.yuketang.cn/api/v3/classroom-report/student/ppt"
PRO_BIND_URL = "https://pro.yuketang.cn/api/web/checkin/pro_bind"

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

VERIFY_SSL = False
MAX_WORKERS = 8
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 0.8
JOB_WORKERS = 3

BASE_DIR = Path(__file__).resolve().parent
STORAGE_FILE = BASE_DIR / "storage.json"
OUTPUT_DIR = BASE_DIR / "outputs"

DELETE_IMAGES_AFTER_PDF = True


if not VERIFY_SSL:
	urllib3.disable_warnings(category=InsecureRequestWarning)

def sanitize_filename(name: str) -> str:
	"""清洗文件名，避免路径非法字符导致写盘失败。"""
	name = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", name).strip()
	return name[:180] or "untitled"


def load_json_file(path: Path, default):
	"""读取 JSON；文件不存在时返回默认值。"""
	if not path.exists():
		return default
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def save_json_file(path: Path, data) -> None:
	"""原子语义较弱但简单可靠的 JSON 持久化。"""
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8") as f:
		json.dump(data, f, ensure_ascii=False, indent=2)


def save_storage_state(storage_state: dict) -> None:
	"""保存 Playwright storage_state"""
	if not isinstance(storage_state, dict):
		return
	existing = load_storage_state()
	if existing == storage_state:
		return
	save_json_file(STORAGE_FILE, storage_state)


def load_storage_state() -> dict:
	"""读取 Playwright storage_state。"""
	storage_state = load_json_file(STORAGE_FILE, default={})
	if isinstance(storage_state, dict) and isinstance(storage_state.get("storage_state"), dict):
		# 向后兼容旧结构: {"storage_state": {...}}
		storage_state = storage_state.get("storage_state", {})
	if isinstance(storage_state, dict):
		return storage_state
	return {}


def load_cookies() -> list[dict]:
	"""仅从 storage_state 读取 cookies。"""
	storage_state = load_storage_state()
	cookies = storage_state.get("cookies", [])
	if isinstance(cookies, list):
		return cookies
	return []


def cookies_to_header(cookies: list[dict]) -> str:
	"""将 cookie 列表转换为 HTTP Cookie 头字符串。"""
	pairs = []
	for c in cookies:
		name = c.get("name")
		value = c.get("value")
		if isinstance(name, str) and isinstance(value, str):
			pairs.append(f"{name}={value}")
	return "; ".join(pairs)


def request_json(url: str, headers: dict, params: dict | None = None) -> dict:
	"""发起 GET 并返回 JSON。"""
	resp = requests.get(url, headers=headers, params=params, timeout=30, verify=VERIFY_SSL)
	resp.raise_for_status()
	return resp.json()


def download_covers(items: list[tuple[int, str]], output_dir: Path, headers: dict) -> list[Path]:
	"""并发下载封面图，返回按页码排序后的本地文件列表。"""
	output_dir.mkdir(parents=True, exist_ok=True)
	success_map: dict[int, Path] = {}
	failed_items: list[tuple[int, str, str]] = []

	print(f"开始并发下载: 总数 {len(items)}，线程数 {MAX_WORKERS}，每张最多重试 {MAX_RETRIES} 次")
	
	client = None
	session = None
	if httpx is not None:
		client = httpx.Client(http2=True, verify=VERIFY_SSL, timeout=30.0, follow_redirects=True)
	else:
		session = requests.Session()

	def _download_one(index: int, url: str) -> tuple[int, Path | None, str | None]:
		filename = output_dir / f"{index:03d}.jpg"
		last_error: str | None = None
		actual_headers = dict(headers)
		actual_headers["Host"] = urlparse(url).netloc

		for attempt in range(1, MAX_RETRIES + 1):
			try:
				if client is not None:
					resp = client.get(url, headers=actual_headers)
					resp.raise_for_status()
					content = resp.content
				else:
					resp = session.get(url, headers=actual_headers, timeout=30, verify=VERIFY_SSL)
					resp.raise_for_status()
					content = resp.content
				filename.write_bytes(content)
				return index, filename, None
			except Exception as exc:
				last_error = f"第{attempt}次失败: {exc}"
				if attempt < MAX_RETRIES:
					time.sleep(RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
		return index, None, last_error

	with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
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


def images_to_pdf(image_files: list[Path], pdf_path: Path) -> None:
	"""将图片顺序合并为单个 PDF。"""
	if not image_files:
		raise ValueError("没有可用于合成 PDF 的图片")

	images = []
	for img_file in image_files:
		img = Image.open(img_file)
		if img.mode != "RGB":
			rgb_img = img.convert("RGB")
			img.close()
			images.append(rgb_img)
		else:
			images.append(img)

	try:
		if images:
			first_img, *rest_imgs = images
			first_img.save(pdf_path, save_all=True, append_images=rest_imgs)
	finally:
		for img in images:
			img.close()


def cleanup_images(image_files: list[Path], image_dir: Path) -> None:
	"""可选清理临时图片与空目录。"""
	for img_file in image_files:
		try:
			img_file.unlink(missing_ok=True)
		except Exception as exc:
			print(f"删除图片失败: {img_file.name}: {exc}")
	try:
		next(image_dir.iterdir())
	except StopIteration:
		try:
			image_dir.rmdir()
		except Exception as exc:
			print(f"删除空目录失败: {image_dir}: {exc}")
	except Exception:
		pass

def load_cover_items(index_payload: dict) -> list[tuple[int, str]]:
	"""从多种可能结构中提取 (页码, cover_url)。"""
	if not isinstance(index_payload, dict):
		print(f"索引结构异常: 根对象不是 dict，而是 {type(index_payload).__name__}")
		return []

	data = index_payload.get("data", {})
	if isinstance(data, str):
		# 某些场景下 data 可能是被字符串包裹的 JSON。
		text = data.strip()
		if text and text[0] in "[{":
			try:
				parsed = json.loads(text)
				data = parsed
			except Exception as exc:
				print(f"索引结构异常: data 为字符串且 JSON 解析失败: {exc}")
				print(data)
				return []
		else:
			print("索引结构异常: data 为普通字符串，无法提取 slides")
			print(data)
			return []

	if isinstance(data, list):
		timeline = data
	elif isinstance(data, dict):
		list_name = "timelineList"
		for n in ("slideList", "timelineList", "slides"):
			if n in data:
				list_name = n
				break
		timeline = data.get(list_name, [])
	else:
		print(f"索引结构异常: data 不是 dict/list，而是 {type(data).__name__}")
		return []

	if isinstance(timeline, str):
		text = timeline.strip()
		if text and text[0] in "[{":
			try:
				timeline = json.loads(text)
			except Exception as exc:
				print(f"索引结构异常: timeline 为字符串且 JSON 解析失败: {exc}")
				return []
		else:
			print("索引结构异常: timeline 为普通字符串，无法提取 covers")
			return []

	if not isinstance(timeline, list):
		print(f"索引结构异常: timeline 不是 list，而是 {type(timeline).__name__}")
		return []

	items: list[tuple[int, str]] = []
	for pos, entry in enumerate(timeline, start=1):
		cover = None
		page_index = None

		if isinstance(entry, dict):
			cover = entry.get("cover")
			page_index = entry.get("index")
		elif isinstance(entry, str):
			# 兼容仅返回 URL 字符串的列表。
			cover = entry
			page_index = pos
		else:
			continue

		if isinstance(page_index, str) and page_index.isdigit():
			page_index = int(page_index)

		if isinstance(cover, str) and cover.strip() and isinstance(page_index, int):
			items.append((page_index, cover))

	# Keep the first cover for each index and sort by index.
	seen_index = set()
	deduped: list[tuple[int, str]] = []
	for page_index, cover in sorted(items, key=lambda x: x[0]):
		if page_index in seen_index:
			continue
		seen_index.add(page_index)
		deduped.append((page_index, cover))
	return deduped

def run_download_job(name: str, index: dict, headers: dict) -> None:
	"""执行单次抓取索引 -> 下载图片 -> 合成 PDF 的任务。"""

	items = load_cover_items(index)
	if not items:
		raise ValueError("未在索引文件中找到 cover 链接")

	image_dir = OUTPUT_DIR / name
	pdf_file = OUTPUT_DIR / f"{name}.pdf"

	downloaded = download_covers(items, image_dir, headers)
	if not downloaded:
		raise ValueError("图片下载全部失败，cover 链接可能已过期，请更新 review.json 后重试")
	images_to_pdf(downloaded, pdf_file)
	if DELETE_IMAGES_AFTER_PDF:
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


def build_api_headers() -> dict:
	"""构建 API 请求头：固定请求头 + storage_state cookies。"""
	headers = dict(BASE_REQUEST_HEADERS)
	cookies = load_cookies()
	cookie_header = cookies_to_header(cookies)
	if cookie_header:
		headers["cookie"] = cookie_header
	headers["accept"] = "application/json, text/plain, */*"
	headers["referer"] = INDEX_URL
	return headers


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
			ppt_payload = request_json(PPT_URL, headers=headers, params=params)
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
	title = str(data.get("title") or "fetch") + f"{pages}pages"

	key = f"fetch:{activity_id}:{title}:_{pages}"
	if key in processed_keys:
		return
	processed_keys.add(key)

	headers = build_api_headers()
	submit_download_job(job_executor, title, index, headers)


def monitor_with_playwright() -> None:
	"""启动浏览器监听接口响应，并异步派发下载任务。"""
	if sync_playwright is None:
		raise RuntimeError("未安装 playwright，请先执行: pip install playwright && playwright install chromium")

	job_executor = ThreadPoolExecutor(max_workers=JOB_WORKERS)
	event_executor = ThreadPoolExecutor(max_workers=3)
	shutdown_event = Event()
	processed_keys: set[str] = set()

	def mark_shutdown(reason: str) -> None:
		if not shutdown_event.is_set():
			print(reason)
			shutdown_event.set()

	try:
		with sync_playwright() as p:
			browser = p.chromium.launch(headless=False)
			storage_state = load_storage_state()
			try:
				if storage_state:
					context = browser.new_context(storage_state=storage_state)
				else:
					context = browser.new_context()
			except Exception as exc:
				print(f"加载存储态失败，使用空上下文继续: {exc}")
				context = browser.new_context()

			browser.on("disconnected", lambda: mark_shutdown("检测到浏览器已断开连接，准备收尾..."))
			context.on("close", lambda: mark_shutdown("检测到浏览器上下文已关闭，准备收尾..."))

			def persist_login_state(reason: str) -> None:
				try:
					save_storage_state(context.storage_state())
					print(f"已保存最新登录态: {reason}")
				except Exception as exc:
					print(f"保存登录态失败({reason}): {exc}")

			page = context.new_page()

			def on_response(response):
				url = response.url
				if PRO_BIND_URL in url:
					persist_login_state("检测到已成功登录，保存登录状态")

				if LESSON_INFO_URL not in url and FETCH_URL not in url:
					return

				print(f"命中目标响应: {url}", flush=True)
				try:
					payload = response.json()
				except Exception as exc:
					print(f"解析响应失败: {url}, error={exc}")
					return

				if LESSON_INFO_URL in url:
					event_executor.submit(handle_lesson_info, payload, job_executor, processed_keys)
					return

				if FETCH_URL in url:
					event_executor.submit(handle_fetch, payload, job_executor, processed_keys)

			context.on("response", on_response)

			try:
				page.goto(INDEX_URL, wait_until="domcontentloaded", timeout=20000)
			except (PlaywrightTimeoutError, PlaywrightError) as exc:
				print(f"首次打开页面失败(可能是代理/SSL握手问题)，监控继续运行，请手动刷新页面: {exc}")

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
					if browser.is_connected():
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

