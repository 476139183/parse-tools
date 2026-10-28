"""Helpers to bridge legacy module-level task dicts into TaskStore."""

from __future__ import annotations

from parse_tools.core.task_store import task_store


def sync_legacy_task(platform: str, state: dict, *, task_id: str | None = None, kind: str = "batch") -> str:
    tid = task_id or f"{platform}-active"
    if task_store.get(tid) is None:
        task_store.create(platform, kind, task_id=tid)
    total = state.get("total") or 0
    cur = state.get("current_index") or 0
    progress = round(100.0 * cur / total, 2) if total else 0
    task_store.update_progress(
        tid,
        status=state.get("status") or "idle",
        progress=progress,
        message=state.get("current_title") or "",
        total=total,
        current_index=cur,
        current_title=state.get("current_title") or "",
        downloaded_count=state.get("downloaded_count") or 0,
        failed_count=state.get("failed_count") or 0,
        logs=list(state.get("logs") or []),
        kind=state.get("task_type") or kind,
    )
    return tid
