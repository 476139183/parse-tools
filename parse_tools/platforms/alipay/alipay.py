"""
支付宝生活号+ 单条内容解析与下载（MVP）

能力：
- 短链 / 分享页解析（图文 / 视频）
- 下载到 data/alipay_downloads
- 历史记录

公开接口：webgw ContentWebGWController.list（无需 Cookie）
"""

from __future__ import annotations

import json
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
    get_proxies_dict,
    load_json,
    save_json,
)

alipay_bp = Blueprint("alipay", __name__, url_prefix="/api/alipay")

ALIPAY_DIR = DATA_DIR / "alipay_downloads"
HISTORY_FILE = DATA_DIR / "alipay_history.json"

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)

CONTENT_API = (
    "https://webgw-internet.alipay.com/contentservice/"
    "com.alipay.sofa.function.SOFAFunction/apply/"
    "myjf.yuyan.contentservice.default.ContentWebGWController.list"
)
WEBGW_APP_ID = "180020010001266490"

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
    sync_legacy_task("alipay", _task_state)


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
    ALIPAY_DIR.mkdir(parents=True, exist_ok=True)


def clean_filename(filename: str) -> str:
    filename = re.sub(r'[\\/:*?"<>|\n\r\t]', "", filename or "")
    filename = filename.strip().replace(" ", "_")
    return (filename[:80] if filename else "untitled") or "untitled"


def add_history_item(title: str, item_type: str, file_path: str, size_bytes: int, content_id: str = ""):
    history = load_json(HISTORY_FILE, [])
    history.insert(0, {
        "title": title,
        "type": item_type,
        "path": str(file_path),
        "content_id": content_id,
        "size": f"{size_bytes / (1024 * 1024):.2f} MB" if size_bytes else "未知",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    save_json(HISTORY_FILE, history[:150])


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://render.alipay.com",
        "Referer": "https://render.alipay.com/",
    })
    proxies = get_proxies_dict()
    if proxies:
        s.proxies.update(proxies)
    return s


def extract_content_id(text: str) -> str:
    """从短链 / 分享页 / scheme 文本中提取 contentId。"""
    if not text:
        return ""
    text = text.strip()

    # 已是 contentId
    if re.fullmatch(r"\d{8}[A-Z0-9]{10,}", text):
        return text

    # 先展开短链（ur.lepudding.com / ur.alipay.com）
    m = re.search(r"https?://ur\.(?:lepudding|alipay)\.com/[A-Za-z0-9_\-]+", text)
    if m:
        try:
            sess = _session()
            r = sess.get(m.group(0), allow_redirects=True, timeout=20)
            text = r.url or text
            # Location may also be in history
            if r.history:
                for h in r.history:
                    loc = h.headers.get("Location") or ""
                    if "contentId" in loc:
                        text = loc + " " + text
                        break
        except Exception:
            pass

    # 直接匹配 contentId=
    for pat in (
        r"contentId[=%]3D([0-9A-Za-z]+)",
        r"contentId=([0-9A-Za-z]+)",
        r"topContentIds=([0-9A-Za-z,]+)",
    ):
        m = re.search(pat, text)
        if m:
            cid = m.group(1).split(",")[0].strip()
            if cid:
                return cid

    # URL decode 后再试一次
    try:
        decoded = urllib.parse.unquote(urllib.parse.unquote(text))
        if decoded != text:
            m = re.search(r"contentId=([0-9A-Za-z]+)", decoded)
            if m:
                return m.group(1)
    except Exception:
        pass

    return ""


def _pic_url(node) -> str:
    if isinstance(node, str) and node.startswith("http"):
        return node
    if isinstance(node, dict):
        for key in ("url", "src", "original", "picUrl", "imageUrl"):
            v = node.get(key)
            if isinstance(v, str) and v.startswith("http"):
                return v
    return ""


def _collect_http_urls(obj, out: list[str], *, prefer_video: bool = False):
    if isinstance(obj, str):
        if obj.startswith("http") and (not prefer_video or any(x in obj.lower() for x in (".mp4", ".m3u8", "video", "stream"))):
            out.append(obj)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if prefer_video and any(x in kl for x in ("cover", "poster", "thumb", "avatar", "pic", "image", "img")):
                continue
            _collect_http_urls(v, out, prefer_video=prefer_video)
    elif isinstance(obj, list):
        for item in obj:
            _collect_http_urls(item, out, prefer_video=prefer_video)


def _extract_video_url(video) -> str:
    if not video:
        return ""
    if isinstance(video, str) and video.startswith("http"):
        return video
    if not isinstance(video, dict):
        return ""

    for key in (
        "url", "videoUrl", "playUrl", "hdUrl", "sdUrl", "mp4Url",
        "streamUrl", "src", "video_url", "play_url", "mediaUrl",
    ):
        v = video.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v
        if isinstance(v, dict):
            nested = _extract_video_url(v)
            if nested:
                return nested

    for nest in ("videos", "mediaList", "resources", "urlList", "streams", "definitions"):
        node = video.get(nest)
        if isinstance(node, list):
            for item in node:
                found = _extract_video_url(item) if isinstance(item, dict) else (
                    item if isinstance(item, str) and item.startswith("http") else ""
                )
                if found:
                    return found
        elif isinstance(node, dict):
            found = _extract_video_url(node)
            if found:
                return found

    urls: list[str] = []
    _collect_http_urls(video, urls, prefer_video=True)
    for u in urls:
        if ".mp4" in u.lower() or "m3u8" in u.lower():
            return u
    return urls[0] if urls else ""


def _normalize_item(raw: dict) -> dict:
    content_id = str(raw.get("contentId") or "")
    title = (raw.get("title") or "").strip()
    content = (raw.get("content") or "").strip()
    author_info = raw.get("author") or {}
    if not isinstance(author_info, dict):
        author_info = {}
    nickname = (author_info.get("nickName") or author_info.get("name") or "未知作者").strip()
    avatar = author_info.get("avatar") or ""

    images: list[str] = []
    for p in raw.get("picList") or []:
        url = _pic_url(p)
        if url and url not in images:
            images.append(url)

    cover = _pic_url(raw.get("coverPic") or {})
    if not cover and images:
        cover = images[0]
    if not cover:
        cover = avatar

    video_url = _extract_video_url(raw.get("video"))
    raw_type = (raw.get("type") or "").strip().lower()
    if video_url or raw_type == "video":
        item_type = "video"
    elif images or raw_type in ("image", "picture", "gallery", "atlas"):
        item_type = "image"
    else:
        item_type = "text"

    display_title = clean_filename(title or content[:40] or f"alipay_{content_id}")
    text_body = "\n\n".join(x for x in (title, content) if x)

    return {
        "content_id": content_id,
        "title": display_title,
        "text": text_body,
        "type": item_type,
        "author": nickname,
        "avatar": avatar,
        "cover": cover,
        "images": images,
        "video": video_url,
        "url": f"https://render.alipay.com/p/yuyan/{WEBGW_APP_ID}/video-share.html?contentId={content_id}" if content_id else "",
        "raw_type": raw_type,
    }


def fetch_content(content_id: str) -> dict:
    """拉取生活号+ 内容详情。"""
    sess = _session()
    headers = {
        "Content-Type": "application/json",
        "x-webgw-appId": WEBGW_APP_ID,
        "x-webgw-version": "2.0",
    }
    try:
        r = sess.post(
            CONTENT_API,
            headers=headers,
            data=json.dumps({"contentId": content_id}),
            timeout=25,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"请求支付宝内容接口失败: {e}") from e

    if not isinstance(data, dict) or not data.get("success"):
        msg = ""
        if isinstance(data, dict):
            msg = data.get("errorMessage") or data.get("errorCode") or ""
        raise RuntimeError(f"支付宝内容接口返回失败: {msg or '未知错误'}")

    result = data.get("resultObj") or {}
    items = result.get("data") if isinstance(result, dict) else None
    if not isinstance(items, list) or not items:
        raise RuntimeError("未找到内容，可能已删除或链接无效")

    first = items[0]
    if not isinstance(first, dict):
        raise RuntimeError("内容数据格式异常")
    return _normalize_item(first)


def download_file(url: str, dest: Path) -> int:
    sess = _session()
    with sess.get(url, stream=True, timeout=90) as r:
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


def _guess_ext(url: str, default: str = ".jpg") -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for ext in (".mp4", ".m3u8", ".mov", ".png", ".gif", ".webp", ".jpeg", ".jpg"):
        if ext in path:
            return ".jpg" if ext == ".jpeg" else ext
    if "video" in url.lower() or "mp4" in url.lower():
        return ".mp4"
    return default


def _download_worker(detail: dict):
    try:
        ensure_dirs()
        author = clean_filename(detail.get("author") or "未知作者")
        title = clean_filename(detail.get("title") or detail.get("content_id") or "alipay")
        content_id = detail.get("content_id") or ""
        folder = ALIPAY_DIR / author / f"{title}_{content_id}"
        folder.mkdir(parents=True, exist_ok=True)

        _set_task_state(current_title=title, current_index=1)
        _add_log(f"开始下载: {title}")

        text_path = folder / "content.txt"
        text_path.write_text(
            f"{detail.get('author', '')}\n{detail.get('url', '')}\n\n{detail.get('text', '')}\n",
            encoding="utf-8",
        )
        total_bytes = text_path.stat().st_size

        if detail.get("type") == "video" and detail.get("video"):
            save_file = folder / f"{title}{_guess_ext(detail['video'], '.mp4')}"
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
                save_file = folder / f"{i:02d}{_guess_ext(img_url, '.jpg')}"
                total_bytes += download_file(img_url, save_file)
                pct = int(i / max(len(imgs), 1) * 100)
                _set_task_state(current_percent=pct)
                _add_log(f"图片 {i}/{len(imgs)} 完成")
            item_type = "图文"
        else:
            item_type = "文本"
            _add_log("无媒体，仅保存文案")

        add_history_item(title, item_type, str(folder), total_bytes, content_id)
        _set_task_state(
            status="completed",
            downloaded_count=1,
            current_percent=100,
            saved_path=str(folder),
        )
        _add_log(f"全部完成 → {folder}")
    except Exception as e:
        _set_task_state(
            status="cancelled" if _task_cancel_event.is_set() else "failed",
            failed_count=1,
        )
        _add_log(f"失败: {e}")


# ── Routes ──────────────────────────────────────────────

@alipay_bp.route("/parse", methods=["POST"])
def parse_content():
    data = request.get_json() or {}
    raw = (data.get("url") or data.get("text") or "").strip()
    if not raw:
        return jsonify({"error": "请粘贴支付宝分享链接"}), 400
    content_id = extract_content_id(raw)
    if not content_id:
        return jsonify({"error": "未能识别 contentId，请检查链接"}), 400
    try:
        detail = fetch_content(content_id)
        return jsonify(detail)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@alipay_bp.route("/download", methods=["POST"])
def download_content():
    data = request.get_json() or {}
    with _task_lock:
        if _task_state["status"] == "running":
            return jsonify({"error": "已有下载任务进行中"}), 409

    detail = data.get("item")
    if not detail:
        raw = (data.get("url") or data.get("text") or "").strip()
        if not raw:
            return jsonify({"error": "请提供链接或解析结果"}), 400
        content_id = extract_content_id(raw)
        if not content_id:
            return jsonify({"error": "未能识别 contentId"}), 400
        try:
            detail = fetch_content(content_id)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    _reset_task_state(1)
    t = threading.Thread(target=_download_worker, args=(detail,), daemon=True)
    t.start()
    return jsonify({"message": "下载已开始", "content_id": detail.get("content_id")})


@alipay_bp.route("/progress", methods=["GET"])
def progress():
    with _task_lock:
        return jsonify(dict(_task_state))


@alipay_bp.route("/cancel", methods=["POST"])
def cancel():
    _task_cancel_event.set()
    _add_log("收到取消请求…")
    return jsonify({"message": "正在取消"})


@alipay_bp.route("/history", methods=["GET"])
def history():
    return jsonify(load_json(HISTORY_FILE, []))


@alipay_bp.route("/history", methods=["DELETE"])
def clear_history():
    save_json(HISTORY_FILE, [])
    return jsonify({"message": "历史已清空"})


@alipay_bp.route("/open-folder", methods=["POST"])
def open_folder():
    ensure_dirs()
    path = ALIPAY_DIR
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


@alipay_bp.route("/open-file", methods=["POST"])
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
