"""Douyin download helpers and background tasks."""
from __future__ import annotations

import re
import string
import threading
import time
from pathlib import Path

import requests as http_requests

from parse_tools.core.config import (
    DATA_DIR, get_proxies_dict, report_proxy_status, load_json, save_json
)
from parse_tools.platforms.douyin.client import (
    DouyinClient, DOUYIN_DIR, HISTORY_FILE, PROGRESS_FILE,
    USER_AGENT, REFERER, clean_filename,
)
from parse_tools.platforms.douyin.tasks import (
    _task_state, _task_cancel_event, _add_log, _set_task_state, _reset_task_state,
)

_progress_lock = threading.Lock()

def ensure_douyin_dirs():
    """确保抖音下载目录存在"""
    DOUYIN_DIR.mkdir(parents=True, exist_ok=True)


from parse_tools.platforms.douyin.douyin_mstoken import get_real_ms_token

# Windows 禁用字符与控制字符; POSIX 只禁 / 与 NUL
_ILLEGAL_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_EDGE_STRIP_CHARS = ". "


def clean_filename(filename: str, max_length: int = 80) -> str:
    """清理文件名：只处理底层真正不能落盘的非法字符与控制字符，保留 #话题、连续空格等合法内容"""
    if not filename:
        return "untitled"
    filename = filename.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    filename = _ILLEGAL_FILENAME_CHARS_RE.sub("_", filename)
    filename = filename.strip(_EDGE_STRIP_CHARS)
    if len(filename) > max_length:
        filename = filename[:max_length].rstrip(_EDGE_STRIP_CHARS)
    return filename if filename else "untitled"


def generate_ms_token(size: int = 107) -> str:
    """生成有效 msToken（优先请求真实 Token 并自动降级）"""
    return get_real_ms_token(USER_AGENT)


def generate_verify_fp() -> str:
    """生成 verify_fp"""
    chars = string.ascii_lowercase + string.digits
    random_str = ''.join(random.choice(chars) for _ in range(16))
    return f"verify_0{random_str}"


def add_history_item(title: str, item_type: str, file_path: str, size_bytes: int, source: str = ""):
    """保存下载记录到历史记录文件"""
    # 提取来源（优先使用传入的 source，否则从下载目录下的第一级子目录名提取）
    path_str = str(file_path)
    if not source:
        marker = "douyin_downloads/"
        idx = path_str.find(marker)
        if idx >= 0:
            rest = path_str[idx + len(marker):]
            parts = rest.split("/")
            if parts:
                source = parts[0]

    history = load_json(HISTORY_FILE, [])
    history.insert(0, {
        "title": title,
        "type": item_type,
        "path": str(file_path),
        "source": source,
        "size": f"{size_bytes / (1024 * 1024):.2f} MB" if size_bytes else "未知",
        "time": time.strftime("%Y-%m-%d %H:%M:%S")
    })
    save_json(HISTORY_FILE, history[:150])


# ── 断点续传进度记录 ──────────────────────────────────────

def _progress_downloaded_ids(key: str) -> list:
    """读取某个任务键下已下载的作品 ID 列表（如 post:<sec_uid> / mix:<mix_id>）"""
    if not key:
        return []
    with _progress_lock:
        entry = load_json(PROGRESS_FILE, {}).get(key) or {}
        ids = entry.get("downloaded") or []
        return list(ids) if isinstance(ids, list) else []


def _progress_mark(key: str, aweme_id: str):
    """将一个作品标记为已下载并立即持久化（断点续传依据之一，磁盘文件存在性检查兜底）"""
    if not key or not aweme_id or aweme_id == "unknown":
        return
    with _progress_lock:
        data = load_json(PROGRESS_FILE, {})
        if not isinstance(data, dict):
            data = {}
        entry = data.get(key)
        if not isinstance(entry, dict):
            entry = {}
        ids = entry.get("downloaded")
        if not isinstance(ids, list):
            ids = []
        if aweme_id not in ids:
            ids.append(aweme_id)
            entry["downloaded"] = ids
            entry["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            data[key] = entry
            save_json(PROGRESS_FILE, data)


def _log_resume_status(task_label: str, all_items: list, progress_key: str):
    """批量任务收集完列表后，提示检测到的历史下载进度"""
    if not progress_key:
        return
    existing_ids = _progress_downloaded_ids(progress_key)
    if not existing_ids:
        return
    id_set = set(existing_ids)
    matched = 0
    for item in all_items:
        mid = str(item.get("aweme_id") or item.get("awemeId") or "")
        if mid and mid in id_set:
            matched += 1
    if matched > 0:
        _add_log(f"📂 {task_label}检测到历史下载进度：{matched} 个作品已下载过，将自动跳过并从上次进度继续")


# ── 抖音 API 客户端 ──────────────────────────────────────

# ── 文件下载 ──────────────────────────────────────────────

def download_file(url: str, save_path: Path) -> int:
    """下载文件到指定路径，返回文件大小(bytes)，支持流式读取中断自动重试与断点续传"""
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": REFERER,
    }

    proxies = get_proxies_dict()
    proxy_url = proxies.get("http") if proxies else None
    temp_path = save_path.with_suffix(save_path.suffix + ".tmp")
    save_path.parent.mkdir(parents=True, exist_ok=True)

    max_retries = 3
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            req_headers = headers.copy()
            start_byte = 0
            if temp_path.exists() and temp_path.stat().st_size > 0:
                start_byte = temp_path.stat().st_size
                req_headers["Range"] = f"bytes={start_byte}-"

            r = http_requests.get(url, headers=req_headers, proxies=proxies, stream=True, timeout=30)
            if r.status_code == 206:
                open_mode = "ab"
            elif r.status_code == 200:
                open_mode = "wb"
                start_byte = 0
            else:
                if temp_path.exists() and start_byte > 0:
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass
                raise Exception(f"HTTP {r.status_code}")

            with open(temp_path, open_mode) as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if _task_cancel_event.is_set():
                        raise Exception("用户取消了任务")
                    if chunk:
                        f.write(chunk)

            if temp_path.exists() and temp_path.stat().st_size > 0:
                if save_path.exists():
                    try:
                        save_path.unlink()
                    except Exception:
                        pass
                temp_path.rename(save_path)
                report_proxy_status(proxy_url, success=True)
                return save_path.stat().st_size

        except Exception as e:
            last_error = e
            err_msg = str(e)
            if "用户取消" in err_msg or _task_cancel_event.is_set():
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass
                raise e
            # 遇到 stream reading error: unexpected EOF 或连接中断，等待 1 秒后自动重试
            if "unexpected EOF" in err_msg or "IncompleteRead" in err_msg or "ChunkedEncodingError" in err_msg or "Connection" in err_msg or "timeout" in err_msg:
                time.sleep(1.0)
                continue
            else:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass
                report_proxy_status(proxy_url, success=False)
                time.sleep(1.0)

    if temp_path.exists():
        try:
            temp_path.unlink()
        except Exception:
            pass
    report_proxy_status(proxy_url, success=False)
    raise last_error or Exception("下载流读取失败: unexpected EOF")


def download_media(media_info: dict, target_dir: Path, custom_dir: Path = None,
                   skip_existing: bool = False, progress_key: str = "") -> dict:
    """根据解析的媒体信息执行下载

    skip_existing=True 时启用断点续传：目标文件/图集已完整存在于磁盘则跳过下载
    （用于批量任务重启后从上次进度继续）；单条下载保持默认覆盖重新下载。
    progress_key 非空时，会把已下载的作品 ID 记入持久化进度文件。
    """
    aweme_id = media_info["aweme_id"]
    title = media_info["title"]
    item_type = media_info["type"]
    urls = media_info["urls"]
    nickname = media_info.get("nickname", "未知用户")
    is_replay = media_info.get("is_replay", False)

    if not urls:
        raise Exception("无法获取资源下载链接")

    title_with_id = f"{aweme_id}_{title}"
    total_bytes = 0

    user_dir = custom_dir if custom_dir else (target_dir / nickname)
    user_dir.mkdir(parents=True, exist_ok=True)

    if item_type == "video":
        type_label = "直播回放" if is_replay else "无水印视频"
        history_type = "直播回放" if is_replay else "视频"

        # 如果是回放且未指定 custom_dir，放入作者的 回放/ 子目录
        if is_replay and not custom_dir:
            save_dir = user_dir / "回放"
            save_dir.mkdir(parents=True, exist_ok=True)
            save_file = save_dir / f"{title_with_id}.mp4"
        else:
            save_file = user_dir / f"{title_with_id}.mp4"

        if skip_existing and save_file.exists() and save_file.stat().st_size > 0:
            _add_log(f"⏭️ 已下载过，跳过: {save_file.name}")
            _progress_mark(progress_key, aweme_id)
            return {
                "id": aweme_id,
                "title": title,
                "type": "replay" if is_replay else item_type,
                "size_bytes": 0,
                "skipped": True,
            }

        _add_log(f"🎬 正在下载{type_label}: {save_file.name}")
        total_bytes = download_file(urls[0], save_file)
        _add_log(f"✅ {type_label}下载完成! 大小: {total_bytes / (1024 * 1024):.2f} MB")
        add_history_item(title, history_type, save_file, total_bytes)
        _progress_mark(progress_key, aweme_id)
    else:
        folder_path = user_dir / title_with_id
        folder_path.mkdir(parents=True, exist_ok=True)

        # 图集断点续传：文件夹内图片数量已达到预期张数则整个跳过
        if skip_existing:
            existing_imgs = len(list(folder_path.glob("*.jpeg")))
            if existing_imgs >= len(urls):
                _add_log(f"⏭️ 图集已下载过，跳过: {folder_path.name}")
                _progress_mark(progress_key, aweme_id)
                return {
                    "id": aweme_id,
                    "title": title,
                    "type": item_type,
                    "size_bytes": 0,
                    "skipped": True,
                }

        _add_log(f"📸 正在下载图集 (共 {len(urls)} 张) 到目录: {folder_path.name}")
        for idx, img_url in enumerate(urls, 1):
            save_file = folder_path / f"{idx}.jpeg"
            if skip_existing and save_file.exists() and save_file.stat().st_size > 0:
                total_bytes += save_file.stat().st_size
                continue
            img_bytes = download_file(img_url, save_file)
            total_bytes += img_bytes

        # 下载实况照片 (Live Photo) 对应的动态短视频
        live_photo_urls = media_info.get("live_photo_urls") or []
        for idx, live_url in enumerate(live_photo_urls, 1):
            if live_url:
                try:
                    live_file = folder_path / f"{idx}_live.mp4"
                    if skip_existing and live_file.exists() and live_file.stat().st_size > 0:
                        total_bytes += live_file.stat().st_size
                        continue
                    _add_log(f"🎬 发现第 {idx} 张为实况照片，正在下载动态视频...")
                    live_bytes = download_file(live_url, live_file)
                    total_bytes += live_bytes
                    _add_log(f"✅ 第 {idx} 张实况动态视频下载完成 ({live_bytes / (1024 * 1024):.2f} MB)")
                except Exception as le:
                    _add_log(f"⚠️ 第 {idx} 张实况动图下载跳过: {le}")

        _add_log(f"✅ 图集全部下载完成! 总大小: {total_bytes / (1024 * 1024):.2f} MB")

        # 下载图文背景音乐 (BGM)
        music_url = media_info.get("music_url")
        if music_url:
            save_music = folder_path / "bgm.mp3"
            if not (skip_existing and save_music.exists() and save_music.stat().st_size > 0):
                _add_log("🎵 发现图文背景音乐，正在下载...")
                try:
                    music_bytes = download_file(music_url, save_music)
                    total_bytes += music_bytes
                    _add_log(f"✅ 背景音乐下载成功! 大小: {music_bytes / (1024 * 1024):.2f} MB")
                except Exception as me:
                    _add_log(f"⚠️ 背景音乐下载失败: {me}")

        add_history_item(title, "图文", folder_path, total_bytes)
        _progress_mark(progress_key, aweme_id)

    return {
        "id": aweme_id,
        "title": title,
        "type": "replay" if is_replay else item_type,
        "size_bytes": total_bytes,
    }


def download_live_stream(room_info: dict, target_dir: Path, custom_dir: Path = None, max_duration: int = 0, quality: str = "") -> dict:
    """下载/录制抖音直播间实时流 (FLV)，支持自选清晰度/码率"""
    room = room_info.get("room") or room_info
    user = room_info.get("user") or room.get("owner") or room.get("ownerUser") or {}
    room_id = str(room.get("idStr") or room.get("id_str") or room.get("room_id") or room.get("id") or "live")
    title = clean_filename(room.get("title") or f"直播_{room_id}")
    author = clean_filename(user.get("nickname") or "未知主播")

    # 提取多清晰度流地址
    stream_url = ""
    stream_url_dict = room.get("stream_url") or room.get("streamUrl") or {}
    flv_map = stream_url_dict.get("flv_pull_url") or stream_url_dict.get("flvPullUrl") or {}
    hls_map = stream_url_dict.get("hls_pull_url_map") or stream_url_dict.get("hlsPullUrlMap") or {}

    # 如果用户指定了具体码率/清晰度
    if quality and quality != "auto":
        # 1. 精确匹配 FLV
        if quality in flv_map and flv_map[quality]:
            stream_url = flv_map[quality]
        # 2. 精确匹配 HLS
        elif quality in hls_map and hls_map[quality]:
            stream_url = hls_map[quality]
        # 3. 模糊匹配 (例如 'HD' 匹配 'HD1', 'SD' 匹配 'SD2', 'FULL_HD' 匹配 'FULL_HD1')
        else:
            for k in flv_map:
                if quality in k or k in quality:
                    stream_url = flv_map[k]
                    break
            if not stream_url:
                for k in hls_map:
                    if quality in k or k in quality:
                        stream_url = hls_map[k]
                        break

    # 兜底：如果未指定或没匹配到，按画质优先级选取
    if not stream_url:
        for q in ["HD", "SD2", "HD1", "FULL_HD1", "FULL_HD", "ORIGIN", "SD1", "SD", "LD"]:
            if q in flv_map and flv_map[q]:
                stream_url = flv_map[q]
                break
        if not stream_url and flv_map:
            stream_url = next(iter(flv_map.values()))
        if not stream_url:
            for q in ["HD", "SD2", "HD1", "FULL_HD1", "FULL_HD", "ORIGIN", "SD1", "SD", "LD"]:
                if q in hls_map and hls_map[q]:
                    stream_url = hls_map[q]
                    break
            if not stream_url and hls_map:
                stream_url = next(iter(hls_map.values()))

    if not stream_url:
        raise Exception(f"未找到直播间 {room_id} 的可用播放流地址，可能主播尚未开播或已下播")

    user_dir = custom_dir if custom_dir else (target_dir / author / "直播")
    user_dir.mkdir(parents=True, exist_ok=True)

    is_hls = ".m3u8" in stream_url.split("?")[0]
    ext = ".m3u8" if is_hls else ".flv"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    file_name = f"{timestamp}_{title}_{room_id}{ext}"
    save_file = user_dir / file_name

    _add_log(f"🔴 正在连接并录制直播流: {file_name}")
    total_bytes = 0
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://live.douyin.com/",
    }
    proxies = get_proxies_dict()
    s = http_requests.Session()
    if proxies:
        s.proxies.update(proxies)
    else:
        s.trust_env = False

    try:
        r = s.get(stream_url, headers=headers, stream=True, timeout=15)
        if r.status_code == 200:
            with open(save_file, "wb") as f:
                start_time = time.time()
                last_update = start_time
                for chunk in r.iter_content(chunk_size=128 * 1024):
                    if _task_cancel_event.is_set():
                        _add_log("⚠️ 收到取消信号，已停止直播录制")
                        break
                    if max_duration > 0 and (time.time() - start_time) > max_duration:
                        _add_log(f"⏰ 达到最大录制时长 {max_duration} 秒，停止录制")
                        break
                    if chunk:
                        f.write(chunk)
                        total_bytes += len(chunk)
                        now = time.time()
                        if now - last_update >= 0.8:
                            _set_task_state(
                                duration_seconds=int(now - start_time),
                                recorded_size=total_bytes
                            )
                            last_update = now
            total_bytes = save_file.stat().st_size if save_file.exists() else total_bytes
            _set_task_state(duration_seconds=int(time.time() - start_time), recorded_size=total_bytes, last_saved_path=str(save_file))
            _add_log(f"✅ 直播录制完成! 大小: {total_bytes / (1024 * 1024):.2f} MB")
            add_history_item(title, "直播", save_file, total_bytes)
        else:
            raise Exception(f"直播流 HTTP 错误 {r.status_code}")
    except Exception as e:
        if total_bytes > 0:
            _set_task_state(recorded_size=total_bytes, last_saved_path=str(save_file))
            _add_log(f"⚠️ 直播流断开，已保存录制内容: {total_bytes / (1024 * 1024):.2f} MB")
            add_history_item(title, "直播", save_file, total_bytes)
        else:
            raise e

    return {
        "id": room_id,
        "title": title,
        "type": "live",
        "size_bytes": total_bytes,
    }


def download_music_file(music_info: dict, target_dir: Path) -> dict:
    """下载音乐原声 mp3 文件"""
    music_id = str(music_info["id"])
    title = clean_filename(music_info["title"])
    author = clean_filename(music_info.get("author", "未知歌手"))

    play_url = music_info.get("play_url", {})
    urls = play_url.get("url_list", [])
    if not urls:
        raise Exception("该音乐没有可用的播放/下载链接")

    user_dir = target_dir / author
    user_dir.mkdir(parents=True, exist_ok=True)

    save_file = user_dir / f"原声_{music_id}_{title}.mp3"
    _add_log(f"🎵 正在下载音乐原声: {save_file.name}")

    total_bytes = download_file(urls[0], save_file)
    _add_log(f"✅ 音乐下载完成! 大小: {total_bytes / (1024 * 1024):.2f} MB")

    add_history_item(title, "音乐", save_file, total_bytes)

    return {
        "id": music_id,
        "title": f"原声 - {title}",
        "type": "music",
        "size_bytes": total_bytes,
    }


# ── 后台批处理执行器 ──────────────────────────────────────

def _run_profile_download_task(sec_uid: str, max_pages: int, target_dir: Path):
    """后台线程：使用 API 获取用户所有发布作品并下载"""
    _add_log(f"正在准备抓取主页资源，目标 sec_uid: {sec_uid[:20]}...")

    client = DouyinClient()

    try:
        nickname = "未知用户"
        try:
            user_res = client.get_user_detail(sec_uid)
            if user_res and user_res.get("user"):
                nickname = user_res["user"].get("nickname", "未知用户")
        except Exception:
            pass
        nickname = clean_filename(nickname)
        profile_dir = target_dir / f"{nickname}的作品"
        profile_dir.mkdir(parents=True, exist_ok=True)

        # 第一步：收集所有作品列表
        _add_log("正在通过 API 获取用户作品列表...")
        all_items = []
        cursor = 0
        page = 0

        while page < max_pages:
            # 检查是否取消
            if _task_cancel_event.is_set():
                _add_log("⚠️ 用户取消了任务")
                _set_task_state(status="cancelled")
                return

            page += 1
            _add_log(f"正在获取第 {page} 页作品数据 (cursor={cursor})...")

            try:
                aweme_list, next_cursor, has_more = client.get_user_videos(sec_uid, cursor)
            except Exception as e:
                _add_log(f"⚠️ 获取第 {page} 页数据失败: {str(e)}，尝试继续...")
                break

            if not aweme_list:
                _add_log(f"第 {page} 页返回空数据，已到达最后一页")
                break

            all_items.extend(aweme_list)
            _add_log(f"第 {page} 页获取到 {len(aweme_list)} 个作品，累计 {len(all_items)} 个")

            if not has_more:
                _add_log("已获取全部作品数据")
                break

            cursor = next_cursor
            # 随机延迟避免风控
            delay = random.uniform(1.5, 4.0)
            _add_log(f"休眠 {delay:.1f} 秒规避频率风控...")
            time.sleep(delay)

        if not all_items:
            _set_task_state(status="failed")
            _add_log("❌ 未能获取到任何作品数据，请确认用户主页链接正确")
            return

        progress_key = f"profile:{sec_uid}"
        _log_resume_status("主页批量任务", all_items, progress_key)
        _add_log(f"🚀 作品列表获取完成！共 {len(all_items)} 个作品待处理")
        _reset_task_state(total=len(all_items))

        # 第二步：逐个下载
        downloaded = 0
        skipped = 0
        failed = 0

        for idx, item in enumerate(all_items, 1):
            # 检查是否取消
            if _task_cancel_event.is_set():
                _add_log("⚠️ 用户取消了任务")
                _set_task_state(status="cancelled")
                return

            _set_task_state(current_index=idx)

            try:
                media_info = DouyinClient.parse_media_info(item)
                if not media_info["urls"]:
                    _add_log(f"⚠️ 第 {idx} 项无可用资源链接，跳过")
                    failed += 1
                    _set_task_state(failed_count=failed)
                    continue

                _add_log(f"[{idx}/{len(all_items)}] 正在下载: {media_info['title'][:30]}...")
                result = download_media(media_info, target_dir, custom_dir=profile_dir,
                                        skip_existing=True, progress_key=progress_key)
                if result.get("skipped"):
                    skipped += 1
                downloaded += 1
                _set_task_state(downloaded_count=downloaded, current_title=result["title"])
            except Exception as e:
                failed += 1
                _set_task_state(failed_count=failed)
                _add_log(f"❌ 第 {idx} 项下载失败: {str(e)}")

            # 每个作品之间的间隔
            if idx < len(all_items):
                delay = random.uniform(1.0, 3.0)
                time.sleep(delay)

        _add_log(f"🎉 批量下载任务结束! 成功: {downloaded - skipped}，跳过已下载: {skipped}，失败: {failed}")
        add_history_item(f"{nickname}的作品", "批量", profile_dir, downloaded)
        _set_task_state(status="completed")

    except Exception as outer_err:
        _add_log(f"💥 批量下载任务发生错误: {str(outer_err)}")
        _set_task_state(status="failed")


def _run_mix_download_task(mix_id: str, target_dir: Path):
    """后台线程：使用 API 获取合集所有视频并下载"""
    _add_log(f"正在准备抓取合集资源，目标 mix_id: {mix_id}...")

    client = DouyinClient()

    try:
        # 第一步：收集所有作品列表
        _add_log("正在通过 API 获取合集作品列表...")
        all_items = []
        cursor = 0
        page = 0
        mix_name = ""

        # Capture cookies first
        try:
            client.session.get("https://www.douyin.com/", timeout=10)
        except Exception:
            pass

        while True:
            # 检查是否取消
            if _task_cancel_event.is_set():
                _add_log("⚠️ 用户取消了任务")
                _set_task_state(status="cancelled")
                return

            page += 1
            _add_log(f"正在获取第 {page} 页合集数据 (cursor={cursor})...")

            try:
                aweme_list, next_cursor, has_more = client.get_mix_videos(mix_id, cursor)
            except Exception as e:
                _add_log(f"⚠️ 获取第 {page} 页数据失败: {str(e)}，尝试继续...")
                break

            if not aweme_list:
                _add_log(f"第 {page} 页返回空数据，已到达最后一页")
                break

            # Extract mix name if not already done
            if not mix_name and aweme_list[0].get("mix_info"):
                mix_name = aweme_list[0]["mix_info"].get("mix_name", "")

            all_items.extend(aweme_list)
            _add_log(f"第 {page} 页获取到 {len(aweme_list)} 个作品，累计 {len(all_items)} 个")

            if not has_more:
                _add_log("已获取全部合集作品数据")
                break

            cursor = next_cursor
            # 随机延迟避免风控
            delay = random.uniform(1.5, 4.0)
            _add_log(f"休眠 {delay:.1f} 秒规避频率风控...")
            time.sleep(delay)

        if not all_items:
            _set_task_state(status="failed")
            _add_log("❌ 未能获取到任何合集作品数据，请确认合集 ID 正确")
            return

        mix_name = clean_filename(mix_name or f"合集_{mix_id}")
        progress_key = f"mix:{mix_id}"
        _log_resume_status(f"合集 「{mix_name}」", all_items, progress_key)
        _add_log(f"🚀 合集列表获取完成！合集名称: {mix_name}，共 {len(all_items)} 个作品待处理")
        _reset_task_state(total=len(all_items))

        # 第二步：逐个下载
        downloaded = 0
        skipped = 0
        failed = 0

        # 获取作者昵称
        first_author = all_items[0].get("author", {})
        nickname = "未知用户"
        if isinstance(first_author, dict):
            nickname = first_author.get("nickname", "未知用户")
        nickname = clean_filename(nickname)

        mix_dir = target_dir / nickname / f"合集_{mix_name}"
        mix_dir.mkdir(parents=True, exist_ok=True)

        for idx, item in enumerate(all_items, 1):
            # 检查是否取消
            if _task_cancel_event.is_set():
                _add_log("⚠️ 用户取消了任务")
                _set_task_state(status="cancelled")
                return

            _set_task_state(current_index=idx)

            try:
                media_info = DouyinClient.parse_media_info(item)
                if not media_info["urls"]:
                    _add_log(f"⚠️ 第 {idx} 项无可用资源链接，跳过")
                    failed += 1
                    _set_task_state(failed_count=failed)
                    continue

                _add_log(f"[{idx}/{len(all_items)}] 正在下载: {media_info['title'][:30]}...")
                result = download_media(media_info, target_dir, custom_dir=mix_dir,
                                        skip_existing=True, progress_key=progress_key)
                if result.get("skipped"):
                    skipped += 1
                downloaded += 1
                _set_task_state(downloaded_count=downloaded, current_title=result["title"])
            except Exception as e:
                failed += 1
                _set_task_state(failed_count=failed)
                _add_log(f"❌ 第 {idx} 项下载失败: {str(e)}")

            # 每个作品之间的间隔
            if idx < len(all_items):
                delay = random.uniform(1.0, 3.0)
                time.sleep(delay)

        _add_log(f"🎉 批量下载合集任务结束! 成功: {downloaded - skipped}，跳过已下载: {skipped}，失败: {failed}")
        add_history_item(mix_name, "合集", mix_dir, 0)
        _set_task_state(status="completed")

    except Exception as outer_err:
        _add_log(f"💥 批量下载合集任务发生错误: {str(outer_err)}")
        _set_task_state(status="failed")


def _run_user_download_task(sec_uid: str, types: list, max_pages: int, target_dir: Path):
    """后台线程：下载博主的作品、喜欢或合集（支持组合）"""
    _add_log(f"正在准备抓取博主资源，目标 sec_uid: {sec_uid[:20]}...")
    client = DouyinClient()

    try:
        # Capture cookies first
        try:
            client.session.get("https://www.douyin.com/", timeout=10)
        except Exception:
            pass

        # 解析昵称
        _add_log("正在获取博主资料...")
        nickname = "未知用户"
        try:
            user_res = client.get_user_detail(sec_uid)
            if user_res and user_res.get("user"):
                nickname = user_res["user"].get("nickname", "未知用户")
        except Exception:
            pass
        nickname = clean_filename(nickname)
        _add_log(f"当前博主: {nickname}")

        # 1. 下载作品 (Post)
        if "post" in types:
            if _task_cancel_event.is_set():
                _add_log("⚠️ 用户取消了任务")
                _set_task_state(status="cancelled")
                return

            _add_log(f"🚀 [1/4] 开始抓取博主作品列表...")
            all_items = []
            cursor = 0
            page = 0
            while page < max_pages if max_pages > 0 else True:
                if _task_cancel_event.is_set():
                    _add_log("⚠️ 用户取消了任务")
                    _set_task_state(status="cancelled")
                    return
                page += 1
                _add_log(f"正在获取作品第 {page} 页 (cursor={cursor})...")
                try:
                    aweme_list, next_cursor, has_more = client.get_user_videos(sec_uid, cursor)
                except Exception as e:
                    _add_log(f"⚠️ 获取作品第 {page} 页失败: {e}")
                    break
                if not aweme_list:
                    break
                all_items.extend(aweme_list)
                if not has_more:
                    break
                cursor = next_cursor
                time.sleep(random.uniform(1.0, 2.5))

            if all_items:
                post_key = f"post:{sec_uid}"
                _log_resume_status("作品批量任务", all_items, post_key)
                _add_log(f"作品列表获取完成！共 {len(all_items)} 个作品待下载。")
                _reset_task_state(total=len(all_items))
                downloaded = 0
                skipped = 0
                failed = 0
                for idx, item in enumerate(all_items, 1):
                    if _task_cancel_event.is_set():
                        _add_log("⚠️ 用户取消了任务")
                        _set_task_state(status="cancelled")
                        return
                    _set_task_state(current_index=idx)
                    try:
                        media_info = DouyinClient.parse_media_info(item)
                        _add_log(f"[{idx}/{len(all_items)}] 正在下载作品: {media_info['title'][:30]}")
                        result = download_media(media_info, target_dir, custom_dir=target_dir / nickname,
                                                skip_existing=True, progress_key=post_key)
                        if result.get("skipped"):
                            skipped += 1
                        downloaded += 1
                        _set_task_state(downloaded_count=downloaded, current_title=result["title"])
                    except Exception as e:
                        if _task_cancel_event.is_set() or "用户取消" in str(e):
                            _add_log("⚠️ 用户取消了任务")
                            _set_task_state(status="cancelled")
                            return
                        failed += 1
                        _set_task_state(failed_count=failed)
                        _add_log(f"❌ 第 {idx} 项作品下载失败: {e}")
                    if _task_cancel_event.is_set():
                        _add_log("⚠️ 用户取消了任务")
                        _set_task_state(status="cancelled")
                        return
                    time.sleep(random.uniform(0.3, 0.8))
                _add_log(f"🎉 博主作品下载结束! 成功: {downloaded - skipped}，跳过已下载: {skipped}，失败: {failed}")
                add_history_item(f"{nickname}的作品", "批量", target_dir / nickname, downloaded)
            else:
                _add_log("该博主作品列表为空或获取失败。")

        # 2. 下载喜欢 (Like)
        if "like" in types:
            if _task_cancel_event.is_set():
                _add_log("⚠️ 用户取消了任务")
                _set_task_state(status="cancelled")
                return

            _add_log(f"🚀 [2/4] 开始抓取博主喜欢列表...")
            all_items = []
            cursor = 0
            page = 0
            while page < max_pages if max_pages > 0 else True:
                if _task_cancel_event.is_set():
                    _add_log("⚠️ 用户取消了任务")
                    _set_task_state(status="cancelled")
                    return
                page += 1
                _add_log(f"正在获取喜欢第 {page} 页 (cursor={cursor})...")
                try:
                    res = client.get_liked_videos(sec_uid, cursor)
                    if res.get("status_code") != 0:
                        _add_log(f"⚠️ 获取喜欢失败: {res.get('status_msg')}")
                        break
                    aweme_list = res.get("aweme_list") or []
                    next_cursor = res.get("max_cursor", 0)
                    has_more = res.get("has_more", 0)
                    has_more_bool = has_more if isinstance(has_more, bool) else (int(has_more) == 1)
                except Exception as e:
                    _add_log(f"⚠️ 获取喜欢第 {page} 页失败: {e}")
                    break
                if not aweme_list:
                    break
                all_items.extend(aweme_list)
                if not has_more_bool:
                    break
                cursor = next_cursor
                time.sleep(random.uniform(1.0, 2.5))

            if all_items:
                like_dir = target_dir / f"{nickname}的喜欢"
                like_key = f"like:{sec_uid}"
                _log_resume_status("喜欢批量任务", all_items, like_key)
                _add_log(f"喜欢列表获取完成！共 {len(all_items)} 个作品待下载。")
                _reset_task_state(total=len(all_items))
                downloaded = 0
                skipped = 0
                failed = 0
                for idx, item in enumerate(all_items, 1):
                    if _task_cancel_event.is_set():
                        _add_log("⚠️ 用户取消了任务")
                        _set_task_state(status="cancelled")
                        return
                    _set_task_state(current_index=idx)
                    try:
                        media_info = DouyinClient.parse_media_info(item)
                        _add_log(f"[{idx}/{len(all_items)}] 正在下载喜欢: {media_info['title'][:30]}")
                        result = download_media(media_info, target_dir, custom_dir=like_dir,
                                                skip_existing=True, progress_key=like_key)
                        if result.get("skipped"):
                            skipped += 1
                        downloaded += 1
                        _set_task_state(downloaded_count=downloaded, current_title=result["title"])
                    except Exception as e:
                        failed += 1
                        _set_task_state(failed_count=failed)
                        _add_log(f"❌ 第 {idx} 项喜欢下载失败: {e}")
                    time.sleep(random.uniform(0.5, 1.5))
                _add_log(f"🎉 博主喜欢下载结束! 成功: {downloaded - skipped}，跳过已下载: {skipped}，失败: {failed}")
                add_history_item(f"{nickname}的喜欢", "批量", like_dir, downloaded)
                _set_task_state(last_saved_path=str(like_dir))
            else:
                _add_log("该博主未公开喜欢列表，或喜欢列表为空。")

        # 3. 下载合集 (Mix)
        if "mix" in types:
            if _task_cancel_event.is_set():
                _add_log("⚠️ 用户取消了任务")
                _set_task_state(status="cancelled")
                return

            _add_log(f"🚀 [3/4] 开始抓取博主创建的合集列表...")
            mix_infos = []
            try:
                mix_infos, _, _ = client.get_user_mixes(sec_uid)
            except Exception as e:
                _add_log(f"⚠️ 获取合集列表失败: {e}")

            if mix_infos:
                _add_log(f"已获取到 {len(mix_infos)} 个合集，开始逐个下载...")
                for m_idx, m_info in enumerate(mix_infos, 1):
                    if _task_cancel_event.is_set():
                        _add_log("⚠️ 用户取消了任务")
                        _set_task_state(status="cancelled")
                        return
                    mix_id = m_info.get("mix_id")
                    mix_name = m_info.get("mix_name", f"合集_{mix_id}")
                    _add_log(f"📦 正在处理第 {m_idx}/{len(mix_infos)} 个合集: 「{mix_name}」")

                    mix_items = []
                    cursor = 0
                    while True:
                        if _task_cancel_event.is_set():
                            _add_log("⚠️ 用户取消了任务")
                            _set_task_state(status="cancelled")
                            return
                        try:
                            aweme_list, next_cursor, has_more = client.get_mix_videos(mix_id, cursor)
                            if not aweme_list:
                                break
                            mix_items.extend(aweme_list)
                            if not has_more:
                                break
                            cursor = next_cursor
                            time.sleep(random.uniform(1.0, 2.5))
                        except Exception as e:
                            _add_log(f"⚠️ 获取合集 {mix_name} 列表失败: {e}")
                            break

                    if mix_items:
                        mix_key = f"mix:{mix_id}"
                        _log_resume_status(f"合集 「{mix_name}」", mix_items, mix_key)
                        _reset_task_state(total=len(mix_items))
                        downloaded = 0
                        skipped = 0
                        failed = 0
                        mix_dir = target_dir / nickname / f"合集_{clean_filename(mix_name)}"
                        mix_dir.mkdir(parents=True, exist_ok=True)
                        for idx, item in enumerate(mix_items, 1):
                            if _task_cancel_event.is_set():
                                _add_log("⚠️ 用户取消了任务")
                                _set_task_state(status="cancelled")
                                return
                            _set_task_state(current_index=idx)
                            try:
                                media_info = DouyinClient.parse_media_info(item)
                                _add_log(f"[{idx}/{len(mix_items)}] 正在下载合集视频: {media_info['title'][:30]}")
                                result = download_media(media_info, target_dir, custom_dir=mix_dir,
                                                        skip_existing=True, progress_key=mix_key)
                                if result.get("skipped"):
                                    skipped += 1
                                downloaded += 1
                                _set_task_state(downloaded_count=downloaded, current_title=result["title"], last_saved_path=str(mix_dir))
                            except Exception as e:
                                failed += 1
                                _set_task_state(failed_count=failed)
                                _add_log(f"❌ 下载失败: {e}")
                            time.sleep(random.uniform(0.5, 1.5))
                        _add_log(f"🎉 合集 「{mix_name}」 下载结束! 成功: {downloaded - skipped}，跳过已下载: {skipped}，失败: {failed}")
                        add_history_item(mix_name, "合集", mix_dir, downloaded)
            else:
                _add_log("该博主未创建任何合集。")

        # 4. 下载日常 (Story)
        if "story" in types:
            if _task_cancel_event.is_set():
                _add_log("⚠️ 用户取消了任务")
                _set_task_state(status="cancelled")
                return

            _add_log(f"🚀 [4/4] 开始抓取博主日常列表...")
            all_items = []
            cursor = 0
            page = 0
            while page < max_pages if max_pages > 0 else True:
                if _task_cancel_event.is_set():
                    _add_log("⚠️ 用户取消了任务")
                    _set_task_state(status="cancelled")
                    return
                page += 1
                _add_log(f"正在获取日常第 {page} 页 (cursor={cursor})...")
                try:
                    aweme_list, next_cursor, has_more = client.get_user_stories(sec_uid, cursor)
                except Exception as e:
                    _add_log(f"⚠️ 获取日常第 {page} 页失败: {e}")
                    break
                if not aweme_list:
                    break
                all_items.extend(aweme_list)
                if not has_more:
                    break
                cursor = next_cursor
                time.sleep(random.uniform(1.0, 2.5))

            if all_items:
                story_key = f"story:{sec_uid}"
                _log_resume_status("日常批量任务", all_items, story_key)
                _add_log(f"日常列表获取完成！共 {len(all_items)} 个日常待下载。")
                _reset_task_state(total=len(all_items))
                downloaded = 0
                skipped = 0
                failed = 0
                for idx, item in enumerate(all_items, 1):
                    if _task_cancel_event.is_set():
                        _add_log("⚠️ 用户取消了任务")
                        _set_task_state(status="cancelled")
                        return
                    _set_task_state(current_index=idx)
                    try:
                        media_info = DouyinClient.parse_media_info(item)
                        _add_log(f"[{idx}/{len(all_items)}] 正在下载日常: {media_info['title'][:30]}")
                        result = download_media(media_info, target_dir, custom_dir=target_dir / f"{nickname}的日常",
                                                skip_existing=True, progress_key=story_key)
                        if result.get("skipped"):
                            skipped += 1
                        downloaded += 1
                        _set_task_state(downloaded_count=downloaded, current_title=result["title"])
                    except Exception as e:
                        failed += 1
                        _set_task_state(failed_count=failed)
                        _add_log(f"❌ 第 {idx} 项日常下载失败: {e}")
                    time.sleep(random.uniform(0.5, 1.5))
                _add_log(f"🎉 博主日常下载结束! 成功: {downloaded - skipped}，跳过已下载: {skipped}，失败: {failed}")
                add_history_item(f"{nickname}的日常", "批量", target_dir / f"{nickname}的日常", downloaded)
            else:
                _add_log("该博主日常列表为空或获取失败。")

        # 5. 下载收藏 (Collect)
        if "collect" in types:
            if _task_cancel_event.is_set():
                _add_log("⚠️ 用户取消了任务")
                _set_task_state(status="cancelled")
                return

            _add_log(f"🚀 开始抓取您的个人收藏列表...")
            all_items = []
            cursor = 0
            page = 0
            while page < max_pages if max_pages > 0 else True:
                if _task_cancel_event.is_set():
                    _add_log("⚠️ 用户取消了任务")
                    _set_task_state(status="cancelled")
                    return
                page += 1
                _add_log(f"正在获取收藏第 {page} 页 (cursor={cursor})...")
                try:
                    res = client.get_collected_videos(cursor)
                    aweme_list = res.get("aweme_list") or []
                    next_cursor = res.get("cursor") if res.get("cursor") is not None else res.get("max_cursor", 0)
                    has_more = res.get("has_more", False)
                except Exception as e:
                    _add_log(f"⚠️ 获取收藏第 {page} 页失败: {e}")
                    break
                if not aweme_list:
                    break
                all_items.extend(aweme_list)
                if not has_more:
                    break
                cursor = next_cursor
                time.sleep(random.uniform(1.0, 2.5))

            if all_items:
                collect_key = f"collect:{sec_uid}"
                _log_resume_status("收藏批量任务", all_items, collect_key)
                _add_log(f"收藏列表获取完成！共 {len(all_items)} 个作品待下载。")
                _reset_task_state(total=len(all_items))
                downloaded = 0
                skipped = 0
                failed = 0
                collect_dir = target_dir / f"{nickname}的收藏"
                collect_dir.mkdir(parents=True, exist_ok=True)
                for idx, item in enumerate(all_items, 1):
                    if _task_cancel_event.is_set():
                        _add_log("⚠️ 用户取消了任务")
                        _set_task_state(status="cancelled")
                        return
                    _set_task_state(current_index=idx)
                    try:
                        media_info = DouyinClient.parse_media_info(item)
                        _add_log(f"[{idx}/{len(all_items)}] 正在下载收藏: {media_info['title'][:30]}")
                        result = download_media(media_info, target_dir, custom_dir=collect_dir,
                                                skip_existing=True, progress_key=collect_key)
                        if result.get("skipped"):
                            skipped += 1
                        downloaded += 1
                        _set_task_state(downloaded_count=downloaded, current_title=result["title"])
                    except Exception as e:
                        failed += 1
                        _set_task_state(failed_count=failed)
                        _add_log(f"❌ 第 {idx} 项收藏下载失败: {e}")
                    time.sleep(random.uniform(0.5, 1.5))
                _add_log(f"🎉 个人收藏下载结束! 成功: {downloaded - skipped}，跳过已下载: {skipped}，失败: {failed}")
                add_history_item(f"{nickname}的收藏", "批量", collect_dir, downloaded)
                _set_task_state(last_saved_path=str(collect_dir))
            else:
                _add_log("您的收藏列表为空。")

        # 6. 下载直播回放 (Replay)
        if "replay" in types:
            if _task_cancel_event.is_set():
                _add_log("⚠️ 用户取消了任务")
                _set_task_state(status="cancelled")
                return

            _add_log(f"🚀 开始抓取博主直播回放列表...")
            all_items = []
            cursor = 0
            page = 0
            while page < max_pages if max_pages > 0 else True:
                if _task_cancel_event.is_set():
                    _add_log("⚠️ 用户取消了任务")
                    _set_task_state(status="cancelled")
                    return
                page += 1
                _add_log(f"正在获取直播回放第 {page} 页 (cursor={cursor})...")
                try:
                    aweme_list, next_cursor, has_more = client.get_user_replays(sec_uid, cursor)
                except Exception as e:
                    _add_log(f"⚠️ 获取直播回放第 {page} 页失败: {e}")
                    break
                if not aweme_list:
                    break
                all_items.extend(aweme_list)
                if not has_more:
                    break
                cursor = next_cursor
                time.sleep(random.uniform(1.0, 2.5))

            if all_items:
                replay_key = f"replay:{sec_uid}"
                _log_resume_status("直播回放批量任务", all_items, replay_key)
                _add_log(f"直播回放列表获取完成！共 {len(all_items)} 个回放待下载。")
                _reset_task_state(total=len(all_items))
                downloaded = 0
                skipped = 0
                failed = 0
                replay_dir = target_dir / f"{nickname}的直播回放"
                replay_dir.mkdir(parents=True, exist_ok=True)
                for idx, item in enumerate(all_items, 1):
                    if _task_cancel_event.is_set():
                        _add_log("⚠️ 用户取消了任务")
                        _set_task_state(status="cancelled")
                        return
                    _set_task_state(current_index=idx)
                    try:
                        media_info = DouyinClient.parse_media_info(item)
                        media_info["is_replay"] = True
                        _add_log(f"[{idx}/{len(all_items)}] 正在下载直播回放: {media_info['title'][:30]}")
                        result = download_media(media_info, target_dir, custom_dir=replay_dir,
                                                skip_existing=True, progress_key=replay_key)
                        if result.get("skipped"):
                            skipped += 1
                        downloaded += 1
                        _set_task_state(downloaded_count=downloaded, current_title=result["title"], last_saved_path=str(replay_dir))
                    except Exception as e:
                        failed += 1
                        _set_task_state(failed_count=failed)
                        _add_log(f"❌ 第 {idx} 项直播回放下载失败: {e}")
                    time.sleep(random.uniform(0.5, 1.5))
                _add_log(f"🎉 博主直播回放下载结束! 成功: {downloaded - skipped}，跳过已下载: {skipped}，失败: {failed}")
                add_history_item(f"{nickname}的直播回放", "批量", replay_dir, downloaded)
                _set_task_state(last_saved_path=str(replay_dir))
            else:
                _add_log("该博主暂无公开直播回放记录。")

        _add_log(f"🎉 博主 「{nickname}」 的所有抓取下载任务已全部完成！")
        _set_task_state(status="completed")

    except Exception as outer_err:
        _add_log(f"💥 批量下载任务发生错误: {str(outer_err)}")
        _set_task_state(status="failed")


def _run_liked_download_task(sec_uid: str, max_pages: int, target_dir: Path):
    """后台线程：使用 API 获取用户所有点赞作品并下载"""
    _add_log(f"正在准备抓取点赞资源，目标 sec_uid: {sec_uid[:20] if sec_uid else '当前登录用户'}...")

    client = DouyinClient()

    try:
        # 优化：如果是空，先获取一次自己的 sec_uid
        if not sec_uid:
            _add_log("未提供 sec_uid，正在获取登录用户自己的 sec_uid...")
            sec_uid = client.get_self_sec_uid()
            if not sec_uid:
                raise Exception("未登录或获取个人信息失败，请先扫码登录获取 Cookie")
            _add_log(f"成功获取当前登录用户 sec_uid: {sec_uid[:20]}...")

        # 解析昵称
        _add_log("正在获取点赞用户资料...")
        nickname = "未知用户"
        try:
            user_res = client.get_user_detail(sec_uid)
            if user_res and user_res.get("user"):
                nickname = user_res["user"].get("nickname", "未知用户")
        except Exception:
            pass
        nickname = clean_filename(nickname)
        liked_dir = target_dir / f"{nickname}的喜欢"
        liked_dir.mkdir(parents=True, exist_ok=True)

        # 第一步：收集所有作品列表
        _add_log("正在通过 API 获取用户点赞作品列表...")
        all_items = []
        cursor = 0
        page = 0

        while page < max_pages:
            # 检查是否取消
            if _task_cancel_event.is_set():
                _add_log("⚠️ 用户取消了任务")
                _set_task_state(status="cancelled")
                return

            page += 1
            _add_log(f"正在获取第 {page} 页点赞数据 (cursor={cursor})...")

            try:
                res = client.get_liked_videos(sec_uid, cursor)
                if res.get("status_code") != 0:
                    msg = res.get("status_msg", "未知错误")
                    raise Exception(f"获取失败: {msg}")
                aweme_list = res.get("aweme_list") or []
                next_cursor = res.get("max_cursor", 0)
                has_more = res.get("has_more", 0)
                if isinstance(has_more, bool):
                    has_more_bool = has_more
                else:
                    has_more_bool = int(has_more) == 1
            except Exception as e:
                _add_log(f"⚠️ 获取第 {page} 页点赞数据失败: {str(e)}，尝试继续...")
                break

            if not aweme_list:
                _add_log(f"第 {page} 页返回空数据，已到达最后一页")
                break

            all_items.extend(aweme_list)
            _add_log(f"第 {page} 页获取到 {len(aweme_list)} 个作品，累计 {len(all_items)} 个")

            if not has_more_bool:
                _add_log("已获取全部点赞作品数据")
                break

            cursor = next_cursor
            # 随机延迟避免风控
            delay = random.uniform(1.5, 4.0)
            _add_log(f"休眠 {delay:.1f} 秒规避频率风控...")
            time.sleep(delay)

        if not all_items:
            _set_task_state(status="failed")
            _add_log("❌ 未能获取到任何点赞作品数据，请确认登录状态或链接")
            return

        liked_key = f"like:{sec_uid}" if sec_uid else "like:self"
        _log_resume_status("点赞批量任务", all_items, liked_key)
        _add_log(f"🚀 点赞作品列表获取完成！共 {len(all_items)} 个作品待处理")
        _reset_task_state(total=len(all_items))

        # 第二步：逐个下载
        downloaded = 0
        skipped = 0
        failed = 0

        for idx, item in enumerate(all_items, 1):
            # 检查是否取消
            if _task_cancel_event.is_set():
                _add_log("⚠️ 用户取消了任务")
                _set_task_state(status="cancelled")
                return

            _set_task_state(current_index=idx)

            try:
                media_info = DouyinClient.parse_media_info(item)
                if not media_info["urls"]:
                    _add_log(f"⚠️ 第 {idx} 项无可用资源链接，跳过")
                    failed += 1
                    _set_task_state(failed_count=failed)
                    continue

                _add_log(f"[{idx}/{len(all_items)}] 正在下载: {media_info['title'][:30]}...")
                result = download_media(media_info, target_dir, custom_dir=liked_dir,
                                        skip_existing=True, progress_key=liked_key)
                if result.get("skipped"):
                    skipped += 1
                downloaded += 1
                _set_task_state(downloaded_count=downloaded, current_title=result["title"])
            except Exception as e:
                failed += 1
                _set_task_state(failed_count=failed)
                _add_log(f"❌ 第 {idx} 项下载失败: {str(e)}")

            # 每个作品之间的间隔
            if idx < len(all_items):
                delay = random.uniform(1.0, 3.0)
                time.sleep(delay)

        _add_log(f"🎉 批量下载点赞任务结束! 成功: {downloaded - skipped}，跳过已下载: {skipped}，失败: {failed}")
        add_history_item(f"{nickname}的喜欢", "批量", liked_dir, downloaded)
        _set_task_state(status="completed")

    except Exception as outer_err:
        _add_log(f"💥 批量下载点赞任务发生错误: {str(outer_err)}")
        _set_task_state(status="failed")


def _run_batch_items_download_task(items: list, target_dir: Path, source_name: str = ""):
    """后台线程：下载指定的作品列表"""
    _add_log(f"正在准备批量下载选中的 {len(items)} 个作品...")
    progress_key = f"batch:{source_name}" if source_name else ""
    _log_resume_status("批量下载任务", items, progress_key)
    _reset_task_state(total=len(items))

    downloaded = 0
    skipped = 0
    failed = 0

    for idx, item in enumerate(items, 1):
        # 检查是否取消
        if _task_cancel_event.is_set():
            _add_log("⚠️ 用户取消了任务")
            _set_task_state(status="cancelled")
            return

        _set_task_state(current_index=idx)

        try:
            media_info = DouyinClient.parse_media_info(item)
            if not media_info["urls"]:
                _add_log(f"⚠️ 第 {idx} 项无可用资源链接，跳过")
                failed += 1
                _set_task_state(failed_count=failed)
                continue

            _add_log(f"[{idx}/{len(items)}] 正在下载: {media_info['title'][:30]}...")
            custom_dir = target_dir / source_name if source_name else None
            result = download_media(media_info, target_dir, custom_dir=custom_dir,
                                    skip_existing=True, progress_key=progress_key)
            if result.get("skipped"):
                skipped += 1
            downloaded += 1
            _set_task_state(downloaded_count=downloaded, current_title=result["title"])
        except Exception as e:
            failed += 1
            _set_task_state(failed_count=failed)
            _add_log(f"❌ 第 {idx} 项下载失败: {str(e)}")

        # 每个作品之间的间隔
        if idx < len(items):
            delay = random.uniform(1.0, 3.0)
            time.sleep(delay)

    _add_log(f"🎉 批量下载任务结束! 成功: {downloaded - skipped}，跳过已下载: {skipped}，失败: {failed}")
    if source_name and len(items) > 1 and downloaded > 0:
        add_history_item(f"{source_name} (批量下载)", "批量", target_dir / source_name, 0)
    _set_task_state(status="completed")


def _run_live_download_task(room_info: dict, target_dir: Path, quality: str = ""):
    """后台线程：实时录制直播流"""
    try:
        download_live_stream(room_info, target_dir, quality=quality)
        if _task_cancel_event.is_set():
            _set_task_state(status="cancelled", task_type="live")
        else:
            _set_task_state(status="completed", task_type="live")
    except Exception as e:
        _add_log(f"💥 直播录制任务异常: {e}")
        _set_task_state(status="failed", task_type="live")



