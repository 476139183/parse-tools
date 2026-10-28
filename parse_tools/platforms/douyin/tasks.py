"""Douyin task state backed by the unified TaskStore."""
from __future__ import annotations

import threading
import time

from parse_tools.core.task_store import task_store

PLATFORM = "douyin"
LEGACY_TASK_ID = "douyin-active"

_task_lock = threading.Lock()
_task_cancel_event = threading.Event()
_task_state = {
    "status": "idle",
    "task_type": "batch",
    "total": 0,
    "current_index": 0,
    "current_title": "",
    "logs": [],
    "downloaded_count": 0,
    "failed_count": 0,
    "start_time": 0,
    "duration_seconds": 0,
    "recorded_size": 0,
    "last_saved_path": "",
}


def _sync_store(**fields):
    if task_store.get(LEGACY_TASK_ID) is None:
        task_store.create(PLATFORM, _task_state.get("task_type", "batch"), task_id=LEGACY_TASK_ID)
    payload = {
        "status": _task_state.get("status"),
        "progress": 0,
        "message": _task_state.get("current_title") or "",
        "total": _task_state.get("total"),
        "current_index": _task_state.get("current_index"),
        "current_title": _task_state.get("current_title"),
        "downloaded_count": _task_state.get("downloaded_count"),
        "failed_count": _task_state.get("failed_count"),
        "logs": list(_task_state.get("logs") or []),
        "kind": _task_state.get("task_type"),
        "duration_seconds": _task_state.get("duration_seconds"),
        "recorded_size": _task_state.get("recorded_size"),
        "last_saved_path": _task_state.get("last_saved_path"),
    }
    payload.update(fields)
    total = payload.get("total") or 0
    cur = payload.get("current_index") or 0
    if total:
        payload["progress"] = round(100.0 * cur / total, 2)
    task_store.update_progress(LEGACY_TASK_ID, **payload)


def _add_log(message: str):
    with _task_lock:
        timestamp = time.strftime("%H:%M:%S")
        _task_state["logs"].append(f"[{timestamp}] {message}")
        if len(_task_state["logs"]) > 300:
            _task_state["logs"] = _task_state["logs"][-300:]
    task_store.add_log(LEGACY_TASK_ID, message)
    _sync_store()


def _set_task_state(status: str = None, total: int = None, current_index: int = None,
                     current_title: str = None, downloaded_count: int = None, failed_count: int = None,
                     task_type: str = None, duration_seconds: int = None, recorded_size: int = None,
                     last_saved_path: str = None):
    with _task_lock:
        if status is not None:
            _task_state["status"] = status
        if total is not None:
            _task_state["total"] = total
        if current_index is not None:
            _task_state["current_index"] = current_index
        if current_title is not None:
            _task_state["current_title"] = current_title
        if downloaded_count is not None:
            _task_state["downloaded_count"] = downloaded_count
        if failed_count is not None:
            _task_state["failed_count"] = failed_count
        if task_type is not None:
            _task_state["task_type"] = task_type
        if duration_seconds is not None:
            _task_state["duration_seconds"] = duration_seconds
        if recorded_size is not None:
            _task_state["recorded_size"] = recorded_size
        if last_saved_path is not None:
            _task_state["last_saved_path"] = last_saved_path
    _sync_store()


def _reset_task_state(total: int = 0, task_type: str = "batch"):
    with _task_lock:
        _task_state["status"] = "running"
        _task_state["task_type"] = task_type
        _task_state["total"] = total
        _task_state["current_index"] = 0
        _task_state["current_title"] = ""
        _task_state["logs"] = []
        _task_state["downloaded_count"] = 0
        _task_state["failed_count"] = 0
        _task_state["start_time"] = time.time()
        _task_state["duration_seconds"] = 0
        _task_state["recorded_size"] = 0
        _task_state["last_saved_path"] = ""
    _task_cancel_event.clear()
    task_store.create(PLATFORM, task_type, task_id=LEGACY_TASK_ID)
    _sync_store(status="running")
    _add_log(f"任务启动，共计需要处理 {total} 项内容" if task_type != "live" else "🔴 直播录制任务已启动")


def request_cancel():
    _task_cancel_event.set()
    task_store.cancel(LEGACY_TASK_ID)
