"""从多种 JSON 结构中提取封面链接。"""

import json


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
