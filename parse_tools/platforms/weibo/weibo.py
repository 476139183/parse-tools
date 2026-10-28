"""
微博单条博文解析与下载（MVP）

能力：
- 粘贴 Cookie
- 单条链接解析（图文 / 视频）
- 下载到 data/weibo_downloads
- 历史记录

接口优先走 m.weibo.cn，必要时回退 weibo.com ajax。
"""

from __future__ import annotations

import re
import sys
import time
import threading
import subprocess
import urllib.parse
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request

from parse_tools.core.config import (
    DATA_DIR,
    get_settings,
    save_settings,
    get_proxies_dict,
    load_json,
    save_json,
)

weibo_bp = Blueprint("weibo", __name__, url_prefix="/api/weibo")

WEIBO_DIR = DATA_DIR / "weibo_downloads"
HISTORY_FILE = DATA_DIR / "weibo_history.json"

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
    "Mobile/15E148 Safari/604.1"
)

_task_state = {
    "status": "idle",
    "total": 0,
    "current_index": 0,
    "current_title": "",
    "logs": [],
    "downloaded_count": 0,
    "failed_count": 0,
    "current_percent": 0,
    "saved_path": "",
}
_task_lock = threading.Lock()
_task_cancel_event = threading.Event()


def _sync_task_store():
    from parse_tools.core.task_bridge import sync_legacy_task
    sync_legacy_task("weibo", _task_state)


def _add_log(message: str):
    with _task_lock:
        timestamp = time.strftime("%H:%M:%S")
        _task_state["logs"].append(f"[{timestamp}] {message}")
        if len(_task_state["logs"]) > 300:
            _task_state["logs"] = _task_state["logs"][-300:]
    _sync_task_store()


def _set_task_state(**kwargs):
    with _task_lock:
        for k, v in kwargs.items():
            if k in _task_state and v is not None:
                _task_state[k] = v
    _sync_task_store()


def _reset_task_state(total: int = 1):
    with _task_lock:
        _task_state.update({
            "status": "running",
            "total": total,
            "current_index": 0,
            "current_title": "",
            "logs": [],
            "downloaded_count": 0,
            "failed_count": 0,
            "current_percent": 0,
            "saved_path": "",
        })
    _sync_task_store()
    _task_cancel_event.clear()


def ensure_dirs():
    WEIBO_DIR.mkdir(parents=True, exist_ok=True)


def clean_filename(filename: str) -> str:
    filename = re.sub(r'[\\/:*?"<>|\n\r\t]', "", filename or "")
    filename = filename.strip().replace(" ", "_")
    return (filename[:80] if filename else "untitled") or "untitled"


def add_history_item(title: str, item_type: str, file_path: str, size_bytes: int, status_id: str = ""):
    history = load_json(HISTORY_FILE, [])
    history.insert(0, {
        "title": title,
        "type": item_type,
        "path": str(file_path),
        "status_id": status_id,
        "size": f"{size_bytes / (1024 * 1024):.2f} MB" if size_bytes else "未知",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    save_json(HISTORY_FILE, history[:150])


def _get_cookie() -> str:
    return (get_settings().get("weibo_cookie") or "").strip()


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://m.weibo.cn/",
        "X-Requested-With": "XMLHttpRequest",
    })
    cookie = _get_cookie()
    if cookie:
        s.headers["Cookie"] = cookie
    proxies = get_proxies_dict()
    if proxies:
        s.proxies.update(proxies)
    return s


def extract_status_id(text: str) -> str:
    """从分享文本 / URL 中提取微博 status id 或 mid。"""
    if not text:
        return ""
    text = text.strip()

    # 先展开短链
    m = re.search(r"https?://t\.cn/\w+", text)
    if m:
        try:
            sess = _session()
            r = sess.get(m.group(0), allow_redirects=True, timeout=15)
            text = r.url or text
        except Exception:
            pass

    patterns = [
        r"m\.weibo\.cn/(?:detail|status)/([A-Za-z0-9]+)",
        r"weibo\.com/\d+/([A-Za-z0-9]+)",
        r"weibo\.com/status/([A-Za-z0-9]+)",
        r"weibo\.cn/status/([A-Za-z0-9]+)",
        r"[?&]id=([A-Za-z0-9]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    # 纯数字 mid
    if re.fullmatch(r"\d{10,20}", text):
        return text
    return ""


def _pick_pic_url(info: dict) -> str:
    if not isinstance(info, dict):
        return ""
    for key in ("largest", "original", "mw2000", "large", "bmiddle"):
        node = info.get(key)
        if isinstance(node, dict) and node.get("url"):
            return node["url"]
        if isinstance(node, str) and node.startswith("http"):
            return node
    return info.get("url") or ""


def _parse_mblog(mblog: dict) -> dict:
    status_id = str(mblog.get("id") or mblog.get("mid") or mblog.get("idstr") or "")
    text = mblog.get("text") or mblog.get("raw_text") or ""
    # 去简单 HTML
    text_plain = re.sub(r"<[^>]+>", "", text).strip()
    user = mblog.get("user") or {}
    nickname = (user.get("screen_name") or user.get("name") or "未知用户").strip()
    avatar = user.get("profile_image_url") or user.get("avatar_hd") or ""

    images: list[str] = []
    pic_infos = mblog.get("pic_infos") or {}
    if isinstance(pic_infos, dict) and pic_infos:
        for pid in (mblog.get("pic_ids") or list(pic_infos.keys())):
            url = _pick_pic_url(pic_infos.get(pid) or {})
            if url:
                images.append(url)
    else:
        for p in mblog.get("pics") or []:
            if isinstance(p, dict):
                large = p.get("large") or {}
                url = large.get("url") if isinstance(large, dict) else ""
                url = url or p.get("url") or ""
                if url:
                    images.append(url)

    video_url = ""
    page_info = mblog.get("page_info") or {}
    if isinstance(page_info, dict):
        media = page_info.get("media_info") or page_info.get("urls") or {}
        if isinstance(media, dict):
            for key in (
                "stream_url_hd", "stream_url", "mp4_720p_mp4", "mp4_hd_url",
                "mp4_sd_url", "hevc_mp4_hd", "mp4_ld_mp4",
            ):
                if media.get(key):
                    video_url = media[key]
                    break
            if not video_url:
                for v in media.values():
                    if isinstance(v, str) and ".mp4" in v:
                        video_url = v
                        break
        if not video_url and page_info.get("type") in ("video", "live"):
            video_url = page_info.get("media_info", {}).get("stream_url") or ""

    # 转发微博：若自身无媒体则取原博
    retweet = mblog.get("retweeted_status")
    if isinstance(retweet, dict) and not images and not video_url:
        nested = _parse_mblog(retweet)
        images = nested.get("images") or []
        video_url = nested.get("video") or ""
        if not text_plain:
            text_plain = nested.get("text") or ""

    cover = images[0] if images else (page_info.get("page_pic", {}) or {}).get("url", "")
    if not cover and isinstance(page_info.get("page_pic"), str):
        cover = page_info["page_pic"]

    item_type = "video" if video_url else ("image" if images else "text")
    title = clean_filename(text_plain[:40] or f"微博_{status_id}")

    return {
        "status_id": status_id,
        "title": title,
        "text": text_plain,
        "type": item_type,
        "author": nickname,
        "avatar": avatar,
        "cover": cover or avatar,
        "images": images,
        "video": video_url,
        "url": f"https://m.weibo.cn/detail/{status_id}" if status_id else "",
    }


def fetch_status(status_id: str) -> dict:
    """拉取博文详情，返回统一结构。"""
    sess = _session()
    errors: list[str] = []

    # 1) 移动端 statuses/show
    try:
        r = sess.get(
            "https://m.weibo.cn/statuses/show",
            params={"id": status_id},
            timeout=20,
        )
        data = r.json()
        mblog = data.get("data") if isinstance(data, dict) else None
        if isinstance(mblog, dict) and (mblog.get("id") or mblog.get("mid")):
            return _parse_mblog(mblog)
        if isinstance(data, dict) and data.get("ok") == 0:
            errors.append(data.get("msg") or "m.weibo.cn 拒绝访问")
    except Exception as e:
        errors.append(f"m.weibo.cn: {e}")

    # 2) 详情页 HTML 内嵌 render_data
    try:
        r = sess.get(f"https://m.weibo.cn/detail/{status_id}", timeout=20)
        html = r.text or ""
        m = re.search(r"var\s+\$render_data\s*=\s*(\[.*?\])\s*\[0\]", html, re.S)
        if not m:
            m = re.search(r"\$render_data\s*=\s*(\[.*?\])\s*;", html, re.S)
        if m:
            import json
            arr = json.loads(m.group(1))
            status = None
            if isinstance(arr, list) and arr:
                status = arr[0].get("status") if isinstance(arr[0], dict) else None
            if isinstance(status, dict):
                return _parse_mblog(status)
        errors.append("详情页未找到 render_data")
    except Exception as e:
        errors.append(f"detail html: {e}")

    # 3) PC ajax（需 Cookie）
    try:
        sess.headers["Referer"] = "https://weibo.com/"
        sess.headers["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        r = sess.get(
            "https://weibo.com/ajax/statuses/show",
            params={"id": status_id},
            timeout=20,
        )
        data = r.json()
        if isinstance(data, dict) and (data.get("id") or data.get("mid")):
            return _parse_mblog(data)
        errors.append(data.get("message") if isinstance(data, dict) else "ajax 无数据")
    except Exception as e:
        errors.append(f"ajax: {e}")

    hint = "；".join(errors[-3:]) if errors else "未知错误"
    if not _get_cookie():
        hint += "。建议在「Cookie 配置」粘贴登录后的 Cookie 后重试"
    raise RuntimeError(f"解析微博失败: {hint}")


def download_file(url: str, dest: Path) -> int:
    sess = _session()
    sess.headers["Referer"] = "https://weibo.com/"
    with sess.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if _task_cancel_event.is_set():
                    raise RuntimeError("已取消")
                if chunk:
                    f.write(chunk)
                    total += len(chunk)
        return total


def _download_worker(detail: dict):
    try:
        ensure_dirs()
        author = clean_filename(detail.get("author") or "未知用户")
        title = clean_filename(detail.get("title") or detail.get("status_id") or "weibo")
        status_id = detail.get("status_id") or ""
        folder = WEIBO_DIR / author / f"{title}_{status_id}"
        folder.mkdir(parents=True, exist_ok=True)

        _set_task_state(current_title=title, current_index=1)
        _add_log(f"开始下载: {title}")

        # 保存文案
        text_path = folder / "content.txt"
        text_path.write_text(
            f"{detail.get('author', '')}\n{detail.get('url', '')}\n\n{detail.get('text', '')}\n",
            encoding="utf-8",
        )
        total_bytes = text_path.stat().st_size

        if detail.get("type") == "video" and detail.get("video"):
            save_file = folder / f"{title}.mp4"
            _add_log("下载视频…")
            total_bytes += download_file(detail["video"], save_file)
            _add_log(f"视频完成 ({total_bytes / (1024 * 1024):.2f} MB)")
            item_type = "视频"
        elif detail.get("images"):
            imgs = detail["images"]
            _add_log(f"下载图集共 {len(imgs)} 张…")
            for i, img_url in enumerate(imgs, 1):
                if _task_cancel_event.is_set():
                    raise RuntimeError("已取消")
                ext = ".jpg"
                path_part = urllib.parse.urlparse(img_url).path.lower()
                if ".png" in path_part:
                    ext = ".png"
                elif ".gif" in path_part:
                    ext = ".gif"
                elif ".webp" in path_part:
                    ext = ".webp"
                save_file = folder / f"{i:02d}{ext}"
                total_bytes += download_file(img_url, save_file)
                pct = int(i / max(len(imgs), 1) * 100)
                _set_task_state(current_percent=pct)
                _add_log(f"图片 {i}/{len(imgs)} 完成")
            item_type = "图文"
        else:
            item_type = "文本"
            _add_log("无媒体，仅保存文案")

        add_history_item(title, item_type, str(folder), total_bytes, status_id)
        _set_task_state(
            status="completed",
            downloaded_count=1,
            current_percent=100,
            saved_path=str(folder),
        )
        _add_log(f"全部完成 → {folder}")
    except Exception as e:
        _set_task_state(status="cancelled" if _task_cancel_event.is_set() else "failed", failed_count=1)
        _add_log(f"失败: {e}")


# ── Routes ──────────────────────────────────────────────

@weibo_bp.route("/cookie", methods=["GET"])
def get_cookie():
    cookie = _get_cookie()
    return jsonify({
        "has_cookie": bool(cookie),
        "cookie": cookie,
        "cookie_preview": (cookie[:24] + "…") if len(cookie) > 24 else cookie,
    })


@weibo_bp.route("/cookie", methods=["POST"])
def save_cookie():
    data = request.get_json() or {}
    cookie = (data.get("cookie") or "").strip()
    settings = get_settings()
    settings["weibo_cookie"] = cookie
    save_settings(settings)
    return jsonify({"message": "Cookie 已保存" if cookie else "Cookie 已清空", "has_cookie": bool(cookie)})


@weibo_bp.route("/parse", methods=["POST"])
def parse_status():
    data = request.get_json() or {}
    raw = (data.get("url") or data.get("text") or "").strip()
    if not raw:
        return jsonify({"error": "请粘贴微博链接"}), 400
    status_id = extract_status_id(raw)
    if not status_id:
        return jsonify({"error": "未能识别微博 ID，请检查链接"}), 400
    try:
        detail = fetch_status(status_id)
        return jsonify(detail)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@weibo_bp.route("/download", methods=["POST"])
def download_status():
    data = request.get_json() or {}
    with _task_lock:
        if _task_state["status"] == "running":
            return jsonify({"error": "已有下载任务进行中"}), 409

    detail = data.get("item")
    if not detail:
        raw = (data.get("url") or data.get("text") or "").strip()
        if not raw:
            return jsonify({"error": "请提供链接或解析结果"}), 400
        status_id = extract_status_id(raw)
        if not status_id:
            return jsonify({"error": "未能识别微博 ID"}), 400
        try:
            detail = fetch_status(status_id)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    _reset_task_state(1)
    t = threading.Thread(target=_download_worker, args=(detail,), daemon=True)
    t.start()
    return jsonify({"message": "下载已开始", "status_id": detail.get("status_id")})


@weibo_bp.route("/progress", methods=["GET"])
def progress():
    with _task_lock:
        return jsonify(dict(_task_state))


@weibo_bp.route("/cancel", methods=["POST"])
def cancel():
    _task_cancel_event.set()
    _add_log("收到取消请求…")
    return jsonify({"message": "正在取消"})


@weibo_bp.route("/history", methods=["GET"])
def history():
    return jsonify(load_json(HISTORY_FILE, []))


@weibo_bp.route("/history", methods=["DELETE"])
def clear_history():
    save_json(HISTORY_FILE, [])
    return jsonify({"message": "历史已清空"})


@weibo_bp.route("/open-folder", methods=["POST"])
def open_folder():
    ensure_dirs()
    path = WEIBO_DIR
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)])
        elif sys.platform == "win32":
            subprocess.run(["explorer", str(path)])
        else:
            subprocess.run(["xdg-open", str(path)])
        return jsonify({"message": "文件夹已打开"})
    except Exception as e:
        return jsonify({"error": f"打开失败: {e}"}), 500


@weibo_bp.route("/open-file", methods=["POST"])
def open_file():
    data = request.get_json() or {}
    path_str = data.get("path", "")
    if not path_str:
        return jsonify({"error": "路径不能为空"}), 400
    path = Path(path_str)
    if not path.exists():
        return jsonify({"error": "路径不存在"}), 404
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)])
        elif sys.platform == "win32":
            subprocess.run(["explorer", str(path)])
        else:
            subprocess.run(["xdg-open", str(path)])
        return jsonify({"message": "已打开"})
    except Exception as e:
        return jsonify({"error": f"打开失败: {e}"}), 500
