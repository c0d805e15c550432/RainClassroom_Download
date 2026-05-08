"""通用工具函数：文件名清洗、JSON 读写等。"""

import json
import re
from pathlib import Path
from typing import Any

import requests

import utils.config as config


def sanitize_filename(name: str) -> str:
    """清洗文件名，避免路径非法字符导致写盘失败。"""
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", name).strip()
    return name[:180] or "untitled"


def load_json_file(path: Path, default: Any) -> Any:
    """读取 JSON；文件不存在时返回默认值。"""
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json_file(path: Path, data: Any) -> None:
    """原子语义较弱但简单可靠的 JSON 持久化。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def request_json(url: str, headers: dict, params: dict | None = None) -> dict:
    """发起 GET 并返回 JSON。"""
    resp = requests.get(url, headers=headers, params=params, timeout=30, verify=config.VERIFY_SSL)
    resp.raise_for_status()
    return resp.json()
