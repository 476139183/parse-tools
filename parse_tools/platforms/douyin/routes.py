"""Douyin Flask routes."""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from parse_tools.core.config import DATA_DIR, load_json, save_json, get_settings
from parse_tools.platforms.douyin.client import DouyinClient, DOUYIN_DIR, HISTORY_FILE, clean_filename
from parse_tools.platforms.douyin.tasks import (
    _task_state, _task_cancel_event, _add_log, _set_task_state, _reset_task_state, request_cancel,
)
from parse_tools.platforms.douyin.download import (
    download_file, download_media, download_live_stream, download_music_file,
    _run_profile_download_task, _run_mix_download_task, _run_user_download_task,
    _run_liked_download_task, _run_batch_items_download_task, _run_live_download_task,
    ensure_douyin_dirs, add_history_item,
)

douyin_bp = Blueprint("douyin", __name__, url_prefix="/api/douyin")

# ── Blueprint API 路由 ────────────────────────────────────

@douyin_bp.route("/download-single", methods=["POST"])
def download_single():
    """解析并下载单条抖音视频/图文/直播回放/实时直播"""
    data = request.get_json() or {}
    raw_url = data.get("url", "").strip()
    quality = data.get("quality", "").strip()

    if not raw_url:
        return jsonify({"error": "请输入有效的链接"}), 400

    ensure_douyin_dirs()

    try:
        client = DouyinClient()

        # 1. 链接预解析
        final_url = client.resolve_share_url(raw_url)
        _add_log(f"链接解析完成: {final_url}")

        # Check if it is a mix/collection
        mix_match = re.search(r"(?:collection|mix)/(\d+)", final_url)
        if not mix_match:
            mix_match = re.search(r"mix_id=(\d+)", final_url)

        # Check if it is a music track
        music_match = re.search(r"music/(\d+)", final_url)
        if not music_match:
            music_match = re.search(r"music_id=(\d+)", final_url)

        # Check if it is a live replay (vsdetail / reflow episode)
        replay_match = re.search(r"vsdetail/(\d+)", final_url)
        if not replay_match:
            replay_match = re.search(r"(?:reflow/)?episode/(\d+)", final_url)
        if not replay_match:
            replay_match = re.search(r"episode_id=(\d+)", final_url)

        # Check if it is a live room
        live_match = re.search(r"live\.douyin\.com/(\d+)", final_url)
        if not live_match:
            live_match = re.search(r"/follow/live/(\d+)", final_url)
        if not live_match:
            live_match = re.search(r"webcast/reflow/(\d+)", final_url)

        if mix_match:
            mix_id = mix_match.group(1)
            # Check if there is already a running task
            if _task_state["status"] == "running":
                return jsonify({"error": "当前已有正在运行的批量下载任务，请等待完成"}), 400

            global _task_cancel_event
            _task_cancel_event.clear()
            _set_task_state(status="running")

            # Asynchronously start background task
            thread = threading.Thread(
                target=_run_mix_download_task,
                args=(mix_id, DOUYIN_DIR)
            )
            thread.daemon = True
            thread.start()

            return jsonify({
                "message": "已启动合集批量下载",
                "task_started": True
            })

        elif music_match:
            music_id = music_match.group(1)
            # Fetch music details
            music_info = client.get_music_detail(music_id)
            # Download music
            result = download_music_file(music_info, DOUYIN_DIR)
            return jsonify({
                "message": "下载成功",
                "data": result,
                "title": result["title"]
            })

        elif replay_match:
            replay_id = replay_match.group(1)
            _add_log(f"提取到直播回放 ID: {replay_id}")
            detail = client.get_replay_detail(replay_id)
            _add_log("成功获取直播回放详情")
            media_info = DouyinClient.parse_media_info(detail)
            media_info["is_replay"] = True
            if not media_info["urls"]:
                return jsonify({"error": "无法获取回放视频下载链接，可能需要有效 Cookie 或回放已过期/删除"}), 400
            result = download_media(media_info, DOUYIN_DIR)
            return jsonify({
                "message": "回放下载成功",
                "data": result,
                "title": media_info["title"]
            })

        elif live_match:
            room_id = live_match.group(1)
            sec_user_match = re.search(r"sec_user_id=([A-Za-z0-9_\-]+)", final_url)
            sec_uid = sec_user_match.group(1) if sec_user_match else ""
            _add_log(f"提取到直播间 ID: {room_id}")
            room_info = client.get_live_room_info(room_id, sec_uid)
            if not room_info:
                return jsonify({"error": f"无法获取直播间 {room_id} 的信息，可能主播尚未开播或链接已失效"}), 400

            room = room_info.get("room") or room_info
            user = room_info.get("user") or room.get("owner") or room.get("ownerUser") or {}
            live_title = room.get("title") or f"直播_{room_id}"
            anchor_name = user.get("nickname") or "未知主播"

            if _task_state["status"] == "running":
                return jsonify({"error": "当前已有正在运行的任务，请等待完成或先取消"}), 400

            _task_cancel_event.clear()
            _reset_task_state(total=1, task_type="live")
            _set_task_state(
                status="running",
                task_type="live",
                current_title=f"正在录制直播: {anchor_name} - {live_title}",
                duration_seconds=0,
                recorded_size=0
            )

            thread = threading.Thread(
                target=_run_live_download_task,
                args=(room_info, DOUYIN_DIR, quality)
            )
            thread.daemon = True
            thread.start()

            return jsonify({
                "message": f"已启动直播间「{anchor_name}」的实时录制，可在下方实时查看并随时停止",
                "task_started": True,
                "title": live_title
            })

        # 2. 提取 aweme_id
        aweme_id = DouyinClient.extract_aweme_id(final_url)
        if not aweme_id:
            return jsonify({"error": "无法从链接中提取作品 ID"}), 400
        _add_log(f"提取到作品 ID: {aweme_id}")

        # 3. 调用 API 获取详情
        detail = client.get_video_detail(aweme_id, share_url=final_url)
        _add_log("成功获取作品详情")

        # 4. 解析资源信息
        media_info = DouyinClient.parse_media_info(detail)
        if not media_info["urls"]:
            return jsonify({"error": "无法获取资源下载链接，可能需要有效的 Cookie"}), 400

        # 5. 下载
        result = download_media(media_info, DOUYIN_DIR)

        return jsonify({
            "message": "下载成功",
            "data": result,
            "title": media_info["title"]
        })

    except Exception as e:
        return jsonify({"error": f"下载失败: {str(e)}"}), 500


@douyin_bp.route("/detect-url", methods=["POST"])
def detect_url():
    """检测并解析抖音链接类型"""
    data = request.get_json() or {}
    raw_url = data.get("url", "").strip()

    if not raw_url:
        return jsonify({"error": "请输入有效的链接"}), 400

    ensure_douyin_dirs()

    try:
        client = DouyinClient()

        # 1. 链接预解析
        final_url = client.resolve_share_url(raw_url)

        # 2. 类型识别
        # Check Live Replay (https://www.douyin.com/vsdetail/{id} or /reflow/episode/{id})
        replay_match = re.search(r"vsdetail/(\d+)", final_url)
        if not replay_match:
            replay_match = re.search(r"(?:reflow/)?episode/(\d+)", final_url)
        if not replay_match:
            replay_match = re.search(r"episode_id=(\d+)", final_url)

        if replay_match:
            replay_id = replay_match.group(1)
            replay_title = ""
            author_name = "未知主播"
            cover = ""
            try:
                detail = client.get_replay_detail(replay_id)
                media_info = DouyinClient.parse_media_info(detail)
                replay_title = media_info.get("title", "")
                author_name = media_info.get("nickname", "未知主播")
                cover = media_info.get("cover", "")
            except Exception:
                pass
            name_str = f"「{replay_title}」" if replay_title else ""
            return jsonify({
                "type": "replay",
                "id": replay_id,
                "title": replay_title,
                "nickname": author_name,
                "cover": cover,
                "item_type": "video",
                "resolved_url": final_url,
                "message": f"直播回放 {name_str}"
            })

        # Check Live Room (https://live.douyin.com/{room_id} or webcast/reflow/{room_id})
        live_match = re.search(r"live\.douyin\.com/(\d+)", final_url)
        if not live_match:
            live_match = re.search(r"/follow/live/(\d+)", final_url)
        if not live_match:
            live_match = re.search(r"webcast/reflow/(\d+)", final_url)

        if live_match:
            room_id = live_match.group(1)
            sec_user_match = re.search(r"sec_user_id=([A-Za-z0-9_\-]+)", final_url)
            sec_uid = sec_user_match.group(1) if sec_user_match else ""
            room_title = ""
            anchor_name = "未知主播"
            is_live = False
            avatar = ""
            cover = ""
            signature = ""
            unique_id = ""
            follower_count = 0
            total_favorited = 0
            aweme_count = 0

            # 1. 尝试获取博主完整主页信息
            if sec_uid:
                try:
                    user_res = client.get_user_detail(sec_uid)
                    if user_res and user_res.get("user"):
                        u = user_res["user"]
                        anchor_name = u.get("nickname", "未知主播")
                        signature = u.get("signature", "")
                        unique_id = u.get("unique_id") or u.get("short_id") or ""
                        follower_count = u.get("follower_count") or u.get("mplatform_followers_count") or 0
                        total_favorited = u.get("total_favorited", 0)
                        aweme_count = u.get("aweme_count", 0)
                        avatar_thumb = u.get("avatar_thumb", {})
                        avatar_urls = avatar_thumb.get("url_list", []) if isinstance(avatar_thumb, dict) else []
                        if avatar_urls:
                            avatar = avatar_urls[0]
                except Exception:
                    pass

            # 2. 获取直播间状态和流信息
            live_qualities = []
            try:
                room_info = client.get_live_room_info(room_id, sec_uid)
                room = room_info.get("room") or room_info
                user = room_info.get("user") or room.get("owner") or room.get("ownerUser") or {}
                room_title = room.get("title", "")
                if not anchor_name or anchor_name == "未知主播":
                    anchor_name = user.get("nickname", "未知主播")
                status = room.get("status")
                is_live = (status == 2)
                if not avatar:
                    avatar_thumb = user.get("avatar_thumb") or user.get("avatarThumb") or {}
                    avatar_urls = avatar_thumb.get("url_list") or avatar_thumb.get("urlList") or []
                    avatar = avatar_urls[0] if avatar_urls else ""
                cover_dict = room.get("cover") or {}
                cover_urls = cover_dict.get("url_list") or cover_dict.get("urlList") or []
                cover = cover_urls[0] if cover_urls else ""

                # 解析多码率清晰度
                stream_dict = room.get("stream_url") or room.get("streamUrl") or {}
                flv_map = stream_dict.get("flv_pull_url") or stream_dict.get("flvPullUrl") or {}
                hls_map = stream_dict.get("hls_pull_url_map") or stream_dict.get("hlsPullUrlMap") or {}
                avail_keys = list(flv_map.keys()) if flv_map else list(hls_map.keys())

                quality_labels = {
                    "FULL_HD1": "1080P 蓝光 / 原画 (最高画质 / 文件较大)",
                    "FULL_HD": "1080P 超清 (最高画质 / 文件较大)",
                    "ORIGIN": "1080P 原画 (最高画质 / 占用极大)",
                    "HD1": "720P 超清 60帧 (中高画质)",
                    "HD": "720P 高清 (推荐 / 体积画质平衡)",
                    "SD2": "720P 高清 30帧 (推荐 / 节省内存与磁盘空间)",
                    "SD1": "540P 标清 (极小体积 / 最省内存与磁盘)",
                    "SD": "480P 标清 (极小体积 / 最省空间)",
                    "LD": "360P 流畅 (极低码率)"
                }
                for qk in ["SD2", "HD", "SD1", "HD1", "FULL_HD1", "FULL_HD", "ORIGIN", "SD", "LD"]:
                    if qk in avail_keys:
                        live_qualities.append({
                            "key": qk,
                            "name": quality_labels.get(qk, qk),
                            "is_default": (qk in ["SD2", "HD", "SD1"])
                        })
            except Exception:
                pass

            if not live_qualities:
                live_qualities = [
                    {"key": "SD2", "name": "720P 高清 (推荐 / 节省内存与体积)", "is_default": True},
                    {"key": "FULL_HD1", "name": "1080P 蓝光 / 原画 (最高画质 / 文件较大)", "is_default": False},
                    {"key": "SD1", "name": "540P 标清 (极小体积 / 最省空间)", "is_default": False},
                    {"key": "auto", "name": "自动选择最高清晰度", "is_default": False}
                ]

            name_str = f"「{anchor_name}」- {room_title}" if room_title else f"「{anchor_name}」"
            live_status = "(正在直播)" if is_live else "(已下播/待开播)"
            has_replays = False
            if sec_uid:
                try:
                    sample_replays, _, _ = client.get_user_replays(sec_uid, count=18)
                    has_replays = bool(sample_replays)
                except Exception:
                    has_replays = False

            return jsonify({
                "type": "live",
                "id": room_id,
                "sec_uid": sec_uid,
                "title": room_title,
                "nickname": anchor_name,
                "signature": signature,
                "unique_id": unique_id,
                "follower_count": follower_count,
                "total_favorited": total_favorited,
                "aweme_count": aweme_count,
                "avatar": avatar,
                "cover": cover,
                "is_live": is_live,
                "has_replays": has_replays,
                "live_qualities": live_qualities,
                "resolved_url": final_url,
                "message": f"抖音直播间 {name_str} {live_status}"
            })

        # Check Mix/Collection
        mix_match = re.search(r"(?:collection|mix)/(\d+)", final_url)
        if not mix_match:
            mix_match = re.search(r"mix_id=(\d+)", final_url)

        if mix_match:
            mix_id = mix_match.group(1)
            mix_name = ""
            try:
                aweme_list, _, _ = client.get_mix_videos(mix_id, cursor=0, count=1)
                if aweme_list and aweme_list[0].get("mix_info"):
                    mix_name = aweme_list[0]["mix_info"].get("mix_name", "")
            except Exception:
                pass
            name_str = f"「{mix_name}」" if mix_name else ""
            return jsonify({
                "type": "mix",
                "id": mix_id,
                "title": mix_name,
                "resolved_url": final_url,
                "message": f"视频合集 {name_str}"
            })

        # Check Music
        music_match = re.search(r"music/(\d+)", final_url)
        if not music_match:
            music_match = re.search(r"music_id=(\d+)", final_url)

        if music_match:
            music_id = music_match.group(1)
            music_title = ""
            try:
                music_info = client.get_music_detail(music_id)
                music_title = music_info.get("title", "")
            except Exception:
                pass
            name_str = f"「{music_title}」" if music_title else ""
            return jsonify({
                "type": "music",
                "id": music_id,
                "title": music_title,
                "resolved_url": final_url,
                "message": f"音乐原声 {name_str}"
            })

        # Check Single Video/Note
        aweme_id = DouyinClient.extract_aweme_id(final_url)
        if aweme_id:
            title = ""
            item_type = "video"
            nickname = "未知作者"
            cover = ""
            live_count = 0
            image_count = 0
            try:
                detail = client.get_video_detail(aweme_id, share_url=final_url)
                media_info = DouyinClient.parse_media_info(detail)
                title = media_info.get("title", "")
                item_type = media_info.get("type", "video")
                nickname = media_info.get("nickname", "未知作者")
                cover = media_info.get("cover", "")
                live_count = sum(1 for u in (media_info.get("live_photo_urls") or []) if u)
                image_count = len(media_info.get("urls") or [])
            except Exception:
                pass
            type_name = "图文" if item_type == "image" else "视频"
            name_str = f"「{title}」" if title else ""
            live_hint = f"（含 {live_count} 张实况）" if live_count else ""
            return jsonify({
                "type": "single",
                "id": aweme_id,
                "title": title,
                "nickname": nickname,
                "cover": cover,
                "item_type": item_type,
                "image_count": image_count,
                "live_count": live_count,
                "resolved_url": final_url,
                "message": f"单个{type_name} {name_str}{live_hint}"
            })

        # Check User Profile
        user_match = re.search(r"(?:/user/|/share/user/)([A-Za-z0-9_\-]+)", final_url)
        if not user_match:
            user_match = re.search(r"sec_user_id=([A-Za-z0-9_\-]+)", final_url)

        if user_match:
            sec_uid = user_match.group(1)
            nickname = "未知用户"
            avatar = ""
            signature = ""
            unique_id = ""
            follower_count = 0
            total_favorited = 0
            aweme_count = 0
            try:
                user_res = client.get_user_detail(sec_uid)
                if user_res and user_res.get("user"):
                    u = user_res["user"]
                    nickname = u.get("nickname", "未知用户")
                    signature = u.get("signature", "")
                    unique_id = u.get("unique_id") or u.get("short_id") or ""
                    follower_count = u.get("follower_count") or u.get("mplatform_followers_count") or 0
                    total_favorited = u.get("total_favorited", 0)
                    aweme_count = u.get("aweme_count", 0)
                    avatar_thumb = u.get("avatar_thumb", {})
                    avatar_urls = avatar_thumb.get("url_list", []) if isinstance(avatar_thumb, dict) else []
                    avatar = avatar_urls[0] if avatar_urls else ""
            except Exception:
                pass
            has_replays = False
            try:
                sample_replays, _, _ = client.get_user_replays(sec_uid, count=18)
                has_replays = bool(sample_replays)
            except Exception:
                has_replays = False

            return jsonify({
                "type": "user",
                "id": sec_uid,
                "nickname": nickname,
                "signature": signature,
                "unique_id": unique_id,
                "follower_count": follower_count,
                "total_favorited": total_favorited,
                "aweme_count": aweme_count,
                "avatar": avatar,
                "has_replays": has_replays,
                "resolved_url": final_url,
                "message": f"博主 「{nickname}」 的主页"
            })

        return jsonify({"error": "无法识别此链接类型，请检查输入"}), 400

    except Exception as e:
        return jsonify({"error": f"链接检测失败: {str(e)}"}), 500


@douyin_bp.route("/download-user", methods=["POST"])
def download_user():
    """解析并批量下载博主的主页内容 (作品/喜欢/合集)"""
    if _task_state["status"] == "running":
        return jsonify({"error": "当前已有正在运行的批量下载任务，请等待完成"}), 400

    data = request.get_json() or {}
    sec_uid = data.get("sec_uid", "").strip()
    types = data.get("types", []) # ["post", "like", "mix"]
    max_pages = int(data.get("max_pages", 10))

    if not sec_uid:
        return jsonify({"error": "参数错误，缺失博主 ID"}), 400
    if not types:
        return jsonify({"error": "请至少选择一项要下载的内容"}), 400

    ensure_douyin_dirs()

    global _task_cancel_event
    _task_cancel_event.clear()
    _set_task_state(status="running")

    # Asynchronously start background task
    thread = threading.Thread(
        target=_run_user_download_task,
        args=(sec_uid, types, max_pages, DOUYIN_DIR)
    )
    thread.daemon = True
    thread.start()

    return jsonify({
        "message": "已启动博主主页批量下载任务",
        "task_started": True
    })


@douyin_bp.route("/download-profile", methods=["POST"])
def download_profile():
    """解析并批量下载抖音用户主页"""
    if _task_state["status"] == "running":
        return jsonify({"error": "当前已有正在运行的批量下载任务，请等待完成"}), 400

    data = request.get_json() or {}
    profile_url = data.get("url", "").strip()
    max_pages = int(data.get("scroll_depth", 10))

    if not profile_url:
        return jsonify({"error": "请输入有效的主页链接"}), 400

    # 解析真实主页 URL
    client = DouyinClient()
    resolved = client.resolve_share_url(profile_url)

    # 提取 sec_uid
    match = re.search(r"/user/([A-Za-z0-9_-]+)", resolved)
    if not match:
        return jsonify({"error": "未能从链接解析出用户的 sec_uid，请确认主页格式是否正确"}), 400

    sec_uid = match.group(1)
    ensure_douyin_dirs()

    # 启动异步后台批量下载任务
    _set_task_state(status="running")
    _task_cancel_event.clear()  # 清除取消标志
    thread = threading.Thread(
        target=_run_profile_download_task,
        args=(sec_uid, max_pages, DOUYIN_DIR),
        daemon=True
    )
    thread.start()

    return jsonify({
        "message": "已在后台启动主页批量解析下载任务",
        "sec_uid": sec_uid
    })


@douyin_bp.route("/download-liked", methods=["POST"])
def download_liked():
    """批量下载抖音点赞视频"""
    if _task_state["status"] == "running":
        return jsonify({"error": "当前已有正在运行的批量下载任务，请等待完成"}), 400

    data = request.get_json() or {}
    sec_uid = data.get("sec_uid", "").strip()
    max_pages = int(data.get("max_pages", 10))

    ensure_douyin_dirs()

    # 启动异步后台批量下载任务
    _set_task_state(status="running")
    _task_cancel_event.clear()  # 清除取消标志
    thread = threading.Thread(
        target=_run_liked_download_task,
        args=(sec_uid, max_pages, DOUYIN_DIR),
        daemon=True
    )
    thread.start()

    return jsonify({
        "message": "已在后台启动点赞视频批量解析下载任务",
        "sec_uid": sec_uid
    })


@douyin_bp.route("/download-batch", methods=["POST"])
def download_batch():
    """批量下载选中的抖音视频"""
    if _task_state["status"] == "running":
        return jsonify({"error": "当前已有正在运行的批量下载任务，请等待完成"}), 400

    data = request.get_json() or {}
    items = data.get("items", [])
    source_name = data.get("source_name", "")

    if not items:
        return jsonify({"error": "没有选中任何视频"}), 400

    ensure_douyin_dirs()

    _set_task_state(status="running")
    _task_cancel_event.clear()
    thread = threading.Thread(
        target=_run_batch_items_download_task,
        args=(items, DOUYIN_DIR, source_name),
        daemon=True
    )
    thread.start()

    return jsonify({
        "message": "已在后台启动批量下载任务",
        "count": len(items)
    })


@douyin_bp.route("/cancel-download", methods=["POST"])
def cancel_download():
    """取消正在进行的批量下载任务"""
    if _task_state["status"] != "running":
        return jsonify({"error": "当前没有正在运行的下载任务"}), 400

    _task_cancel_event.set()  # 设置取消标志
    _add_log("⚠️ 收到取消请求，正在停止任务...")

    return jsonify({"message": "已发送取消信号，任务将在当前项完成后停止"})


@douyin_bp.route("/progress", methods=["GET"])
def get_progress():
    """获取当前批量下载的实时进度和日志"""
    with _task_lock:
        return jsonify(_task_state)


@douyin_bp.route("/history", methods=["GET"])
def get_history():
    """获取抖音下载历史记录"""
    history = load_json(HISTORY_FILE, [])
    # 自动过滤并清理 0.00 MB 或无效的虚假批量记录
    valid_history = []
    cleaned = False
    for item in history:
        if item.get("type") == "批量" and (item.get("size") in ["0.00 MB", "0.00 B", "0 MB", "0 B", "未知"] or not item.get("path") or not Path(item.get("path", "")).exists()):
            cleaned = True
            continue
        valid_history.append(item)
    if cleaned:
        save_json(HISTORY_FILE, valid_history)
    return jsonify(valid_history)


@douyin_bp.route("/history", methods=["DELETE"])
def clear_history():
    """清除抖音下载历史记录及下载的文件"""
    import shutil
    save_json(HISTORY_FILE, [])
    # 清空下载文件夹中的所有文件和文件夹
    if DOUYIN_DIR.exists():
        for item in DOUYIN_DIR.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                _add_log(f"⚠️ 清理文件 {item.name} 失败: {e}")
    return jsonify({"message": "历史记录和已下载的文件已清空"})


@douyin_bp.route("/history/delete-item", methods=["POST"])
def delete_history_item():
    """从下载历史中删除单条记录"""
    data = request.get_json() or {}
    idx = data.get("index")
    history = load_json(HISTORY_FILE, [])
    if isinstance(idx, int) and 0 <= idx < len(history):
        removed = history.pop(idx)
        save_json(HISTORY_FILE, history)
        return jsonify({"message": "记录已删除", "item": removed})
    return jsonify({"error": "记录索引无效"}), 400


@douyin_bp.route("/open-folder", methods=["POST"])
def open_folder():
    """在系统文件管理器中打开抖音下载目录或定位指定文件"""
    import subprocess
    import sys

    data = request.get_json() or {}
    custom_path = data.get("path", "").strip()

    target_path = Path(custom_path) if custom_path else DOUYIN_DIR
    if not target_path.exists():
        if target_path.parent.exists():
            target_path = target_path.parent
        else:
            target_path = DOUYIN_DIR
    target_path.mkdir(parents=True, exist_ok=True)

    path_str = str(target_path)
    try:
        if sys.platform == "darwin":
            if target_path.is_file():
                subprocess.run(["open", "-R", path_str])
            else:
                subprocess.run(["open", path_str])
        elif sys.platform == "win32":
            if target_path.is_file():
                subprocess.run(["explorer", f"/select,{path_str}"])
            else:
                subprocess.run(["explorer", path_str])
        else:
            subprocess.run(["xdg-open", path_str if target_path.is_dir() else str(target_path.parent)])
        return jsonify({"message": "已打开对应目录"})
    except Exception as e:
        return jsonify({"error": f"打开文件夹失败: {str(e)}"}), 500


@douyin_bp.route("/open-file", methods=["POST"])
def open_file():
    """在系统默认程序中打开特定的文件或文件夹"""
    import subprocess
    import sys

    data = request.get_json() or {}
    path_str = data.get("path", "")
    if not path_str:
        return jsonify({"error": "路径不能为空"}), 400

    try:
        path = Path(path_str)
        if not path.exists():
            return jsonify({"error": "文件或文件夹不存在"}), 404

        if sys.platform == "darwin":
            subprocess.run(["open", str(path)])
        elif sys.platform == "win32":
            subprocess.run(["explorer", str(path)])
        else:
            subprocess.run(["xdg-open", str(path)])
        return jsonify({"message": "已打开"})
    except Exception as e:
        return jsonify({"error": f"打开失败: {str(e)}"}), 500


@douyin_bp.route("/search", methods=["GET"])
def api_search():
    keyword = request.args.get("keyword", "")
    offset = int(request.args.get("offset", 0))
    if not keyword:
        return jsonify({"error": "关键字不能为空"}), 400
    try:
        api = DouyinClient()
        
        # 1. 自动检测是否为 raw sec_uid 或分享/主页链接
        sec_uid = None
        is_direct = False
        kw_strip = keyword.strip()
        
        if kw_strip.startswith("MS4wLjAB") and len(kw_strip) > 40:
            sec_uid = kw_strip
            is_direct = True
        elif kw_strip.startswith("http://") or kw_strip.startswith("https://") or "douyin.com" in kw_strip:
            try:
                final_url = api.resolve_share_url(kw_strip)
                user_match = re.search(r"user/([A-Za-z0-9_\-]+)", final_url)
                if not user_match:
                    user_match = re.search(r"sec_user_id=([A-Za-z0-9_\-]+)", final_url)
                if user_match:
                    sec_uid = user_match.group(1)
                    is_direct = True
            except Exception as e:
                _add_log(f"⚠️ 解析搜索链接失败: {e}")

        if is_direct and sec_uid:
            try:
                detail = api.get_user_detail(sec_uid)
                if detail and detail.get("user"):
                    return jsonify({
                        "status_code": 0,
                        "user_list": [{
                            "user_info": detail["user"]
                        }],
                        "has_more": 0
                    })
            except Exception as e:
                return jsonify({"error": f"直接获取博主详情失败: {str(e)}"}), 500

        # 2. 模糊搜索并处理验证拦截 fallback
        res = api.search_user(keyword, offset)
        if isinstance(res, dict) and res.get("search_nil_info", {}).get("search_nil_type") == "verify_check":
            return jsonify({
                "error": "由于抖音安全验证拦截，无法进行模糊搜索。请直接复制该博主的「主页链接」或「sec_uid」在此搜索，我们将自动解析并跳转！"
            }), 400

        # 3. 补全搜索结果中的博主作品数、粉丝数等数据 (抖音搜索接口默认不返回 aweme_count)
        user_list = res.get("user_list") if isinstance(res, dict) else []
        if isinstance(user_list, list) and user_list:
            from concurrent.futures import ThreadPoolExecutor

            def _enrich_user(item):
                if not isinstance(item, dict):
                    return
                user_info = item.get("user_info") if isinstance(item.get("user_info"), dict) else item
                sec_uid = user_info.get("sec_uid")
                # 如果 aweme_count 为 0 或未提供，通过详情接口补全
                if sec_uid and not user_info.get("aweme_count"):
                    try:
                        u_res = api.get_user_detail(sec_uid)
                        if u_res and isinstance(u_res.get("user"), dict):
                            real_user = u_res["user"]
                            if "aweme_count" in real_user:
                                user_info["aweme_count"] = real_user["aweme_count"]
                            if "follower_count" in real_user and not user_info.get("follower_count"):
                                user_info["follower_count"] = real_user["follower_count"]
                            if "total_favorited" in real_user and not user_info.get("total_favorited"):
                                user_info["total_favorited"] = real_user["total_favorited"]
                            if "following_count" in real_user and not user_info.get("following_count"):
                                user_info["following_count"] = real_user["following_count"]
                    except Exception:
                        pass

            with ThreadPoolExecutor(max_workers=min(len(user_list), 6)) as executor:
                list(executor.map(_enrich_user, user_list))

        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@douyin_bp.route("/user-detail", methods=["GET"])
def api_user_detail():
    sec_uid = request.args.get("sec_uid", "")
    if not sec_uid:
        return jsonify({"error": "sec_uid不能为空"}), 400
    try:
        api = DouyinClient()
        res = api.get_user_detail(sec_uid)
        if isinstance(res, dict) and "user" in res:
            self_sec_uid = api.get_self_sec_uid()
            res["user"]["is_self"] = (sec_uid == self_sec_uid)
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@douyin_bp.route("/feed", methods=["GET"])
def api_feed():
    count = int(request.args.get("count", 10))
    cursor = int(request.args.get("cursor", 0))
    try:
        api = DouyinClient()
        res = api.get_recommended_feed(count, cursor)
        if isinstance(res, dict):
            if res.get("aweme_list") is None:
                res["aweme_list"] = []
            if res.get("has_more") is not None:
                res["has_more"] = res["has_more"] if isinstance(res["has_more"], bool) else int(res["has_more"]) == 1
            else:
                res["has_more"] = False
            if res.get("max_cursor") is None:
                res["max_cursor"] = res.get("cursor") or 0
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@douyin_bp.route("/liked", methods=["GET"])
def api_liked():
    sec_uid = request.args.get("sec_uid", "").strip()
    max_cursor = int(request.args.get("max_cursor", 0))
    count = int(request.args.get("count", 18))
    try:
        api = DouyinClient()
        res = api.get_liked_videos(sec_uid, max_cursor, count)
        if isinstance(res, dict):
            if res.get("aweme_list") is None:
                res["aweme_list"] = []
            if res.get("has_more") is not None:
                res["has_more"] = res["has_more"] if isinstance(res["has_more"], bool) else int(res["has_more"]) == 1
            else:
                res["has_more"] = False
            if res.get("max_cursor") is None:
                res["max_cursor"] = res.get("cursor") or 0
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@douyin_bp.route("/user-videos", methods=["GET"])
def api_user_videos():
    sec_uid = request.args.get("sec_uid", "")
    max_cursor = int(request.args.get("max_cursor", 0))
    count = int(request.args.get("count", 18))
    if not sec_uid:
        return jsonify({"error": "sec_uid不能为空"}), 400
    try:
        api = DouyinClient()
        aweme_list, next_cursor, has_more = api.get_user_videos(sec_uid, max_cursor, count)
        return jsonify({
            "aweme_list": aweme_list,
            "max_cursor": next_cursor,
            "has_more": has_more
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@douyin_bp.route("/user-stories", methods=["GET"])
def api_user_stories():
    sec_uid = request.args.get("sec_uid", "")
    max_cursor = int(request.args.get("max_cursor", 0))
    count = int(request.args.get("count", 18))
    if not sec_uid:
        return jsonify({"error": "sec_uid不能为空"}), 400
    try:
        api = DouyinClient()
        aweme_list, next_cursor, has_more = api.get_user_stories(sec_uid, max_cursor, count)
        return jsonify({
            "aweme_list": aweme_list,
            "max_cursor": next_cursor,
            "has_more": has_more
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@douyin_bp.route("/user-mixes", methods=["GET"])
def api_user_mixes():
    sec_uid = request.args.get("sec_uid", "")
    cursor = int(request.args.get("cursor", 0))
    count = int(request.args.get("count", 20))
    if not sec_uid:
        return jsonify({"error": "sec_uid不能为空"}), 400
    try:
        api = DouyinClient()
        mix_infos, next_cursor, has_more = api.get_user_mixes(sec_uid, cursor, count)
        return jsonify({
            "mix_infos": mix_infos,
            "max_cursor": next_cursor,
            "has_more": has_more
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@douyin_bp.route("/collected", methods=["GET"])
def api_collected():
    cursor = int(request.args.get("cursor", 0))
    count = int(request.args.get("count", 18))
    try:
        api = DouyinClient()
        res = api.get_collected_videos(cursor, count)
        if isinstance(res, dict):
            # 兼容前端的 max_cursor 字段
            next_cursor = res.get("cursor") if res.get("cursor") is not None else res.get("max_cursor", 0)
            res["max_cursor"] = next_cursor
            if res.get("has_more") is not None:
                res["has_more"] = res["has_more"] if isinstance(res["has_more"], bool) else int(res["has_more"]) == 1
            else:
                res["has_more"] = False
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@douyin_bp.route("/collects/list", methods=["GET"])
def api_collects_list():
    cursor = int(request.args.get("cursor", 0))
    count = int(request.args.get("count", 20))
    try:
        api = DouyinClient()
        res = api.get_collect_folders(cursor, count)
        if isinstance(res, dict):
            next_cursor = res.get("cursor") if res.get("cursor") is not None else res.get("max_cursor", 0)
            res["max_cursor"] = next_cursor
            if res.get("has_more") is not None:
                res["has_more"] = res["has_more"] if isinstance(res["has_more"], bool) else int(res["has_more"]) == 1
            else:
                res["has_more"] = False
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@douyin_bp.route("/collects/video/list", methods=["GET"])
def api_collects_video_list():
    collect_id = request.args.get("collect_id", "")
    cursor = int(request.args.get("cursor", 0))
    count = int(request.args.get("count", 18))
    if not collect_id:
        return jsonify({"error": "collect_id 不能为空"}), 400
    try:
        api = DouyinClient()
        res = api.get_collect_folder_videos(collect_id, cursor, count)
        if isinstance(res, dict):
            next_cursor = res.get("cursor") if res.get("cursor") is not None else res.get("max_cursor", 0)
            res["max_cursor"] = next_cursor
            if res.get("has_more") is not None:
                res["has_more"] = res["has_more"] if isinstance(res["has_more"], bool) else int(res["has_more"]) == 1
            else:
                res["has_more"] = False
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@douyin_bp.route("/collects/mixes", methods=["GET"])
def api_collects_mixes():
    cursor = int(request.args.get("cursor", 0))
    count = int(request.args.get("count", 18))
    try:
        api = DouyinClient()
        res = api.get_collected_mixes(cursor, count)
        if isinstance(res, dict):
            next_cursor = res.get("cursor") if res.get("cursor") is not None else res.get("max_cursor", 0)
            res["max_cursor"] = next_cursor
            if res.get("has_more") is not None:
                res["has_more"] = res["has_more"] if isinstance(res["has_more"], bool) else int(res["has_more"]) == 1
            else:
                res["has_more"] = False
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@douyin_bp.route("/open-parent", methods=["POST"])
def open_parent():
    """打开文件或文件夹所在的父目录并选中当前文件"""
    import subprocess
    import sys

    data = request.get_json() or {}
    path_str = data.get("path", "")
    if not path_str:
        return jsonify({"error": "路径不能为空"}), 400

    try:
        path = Path(path_str)
        if not path.exists():
            return jsonify({"error": "文件或文件夹不存在"}), 404
            
        if path.is_file():
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", str(path)])
            elif sys.platform == "win32":
                subprocess.run(f'explorer /select,"{path.resolve()}"', shell=True)
            else:
                subprocess.run(["xdg-open", str(path.parent)])
        else:
            if sys.platform == "darwin":
                subprocess.run(["open", str(path)])
            elif sys.platform == "win32":
                subprocess.run(f'explorer "{path.resolve()}"', shell=True)
            else:
                subprocess.run(["xdg-open", str(path)])
        return jsonify({"message": "已打开"})
    except Exception as e:
        return jsonify({"error": f"打开失败: {str(e)}"}), 500


@douyin_bp.route("/comments", methods=["GET"])
def api_comments():
    """获取视频评论列表（单页）"""
    aweme_id = request.args.get("aweme_id", "").strip()
    if not aweme_id:
        return jsonify({"error": "aweme_id 不能为空"}), 400
    cursor = int(request.args.get("cursor", 0))
    count = int(request.args.get("count", 20))
    include_replies = request.args.get("include_replies", "false").lower() in ("true", "1")

    try:
        client = DouyinClient()
        data = client.get_aweme_comments(aweme_id, cursor=cursor, count=count, include_replies=include_replies)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@douyin_bp.route("/comments/download", methods=["POST"])
def api_download_comments():
    """下载并导出作品的全部评论为 JSON 文件（与视频保存在同一作者目录下）"""
    data = request.get_json() or {}
    aweme_id = str(data.get("aweme_id", "")).strip()
    if not aweme_id:
        return jsonify({"error": "aweme_id 不能为空"}), 400

    title = data.get("title", f"aweme_{aweme_id}")
    nickname = str(data.get("nickname", "")).strip()
    source_name = str(data.get("source_name", "")).strip()
    max_comments = int(data.get("max_comments", 0))
    include_replies = bool(data.get("include_replies", False))
    save_dir_str = data.get("save_dir", "").strip()

    try:
        client = DouyinClient()
        if not nickname and not source_name:
            try:
                detail = client.get_aweme_detail(aweme_id)
                if detail and detail.get("author"):
                    nickname = detail["author"].get("nickname", "")
            except Exception:
                pass

        comments = client.get_all_comments(aweme_id, max_comments=max_comments, include_replies=include_replies)

        # 确定保存目录：与视频保存在同一作者目录下
        if save_dir_str:
            target_dir = Path(save_dir_str)
        elif source_name:
            target_dir = DOUYIN_DIR / clean_filename(source_name)
        elif nickname:
            target_dir = DOUYIN_DIR / clean_filename(nickname)
        else:
            # 尝试在已有下载目录中寻找此 aweme_id 的视频文件所在目录
            found_dir = None
            if DOUYIN_DIR.exists():
                for sub in DOUYIN_DIR.iterdir():
                    if sub.is_dir() and sub.name != "comments":
                        for f in sub.iterdir():
                            if aweme_id in f.name:
                                found_dir = sub
                                break
                    if found_dir:
                        break
            target_dir = found_dir if found_dir else (DOUYIN_DIR / clean_filename(title))

        target_dir.mkdir(parents=True, exist_ok=True)

        clean_stem = clean_filename(title)
        title_with_id = f"{aweme_id}_{clean_stem}"
        file_path = target_dir / f"{title_with_id}_comments.json"

        output_payload = {
            "aweme_id": aweme_id,
            "title": title,
            "count": len(comments),
            "include_replies": include_replies,
            "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "comments": comments,
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(output_payload, f, ensure_ascii=False, indent=2)

        _add_log(f"✅ 评论抓取完成！共抓取 {len(comments)} 条评论，已保存至: {file_path.name}")
        record_source = source_name or nickname or (target_dir.name if target_dir != DOUYIN_DIR else "单条解析")
        add_history_item(f"{title} (评论)", "评论", file_path, file_path.stat().st_size, source=record_source)

        return jsonify({
            "message": "评论导出成功",
            "file_path": str(file_path),
            "count": len(comments),
        })
    except Exception as e:
        return jsonify({"error": f"导出评论失败: {str(e)}"}), 500

