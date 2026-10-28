"""Unified in-memory (+ optional disk) task store for platform downloads."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from parse_tools.core.config import DATA_DIR

_VALID_STATUS = frozenset(
    {"pending", "running", "completed", "failed", "cancelled", "idle"}
)


class TaskStore:
    """Thread-safe task registry shared by all platforms."""

    def __init__(self, persist: bool = True):
        self._lock = threading.RLock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._persist = persist
        self._dir = DATA_DIR / "tasks"
        if persist:
            self._dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        platform: str,
        kind: str,
        *,
        params: dict | None = None,
        task_id: str | None = None,
        extra: dict | None = None,
    ) -> str:
        tid = task_id or uuid.uuid4().hex[:12]
        now = time.time()
        record: dict[str, Any] = {
            "task_id": tid,
            "platform": platform,
            "kind": kind,
            "status": "pending",
            "progress": 0,
            "message": "",
            "result": None,
            "error": None,
            "params": params or {},
            "created_at": now,
            "updated_at": now,
            "logs": [],
            "total": 0,
            "current_index": 0,
            "current_title": "",
            "downloaded_count": 0,
            "failed_count": 0,
        }
        if extra:
            record.update(extra)
        with self._lock:
            self._tasks[tid] = record
            self._cancel_events[tid] = threading.Event()
            self._flush(tid)
        return tid

    def get(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def list(self, platform: str | None = None, limit: int = 100) -> list[dict]:
        with self._lock:
            items = list(self._tasks.values())
        if platform:
            items = [t for t in items if t.get("platform") == platform]
        items.sort(key=lambda t: t.get("updated_at", 0), reverse=True)
        return [dict(t) for t in items[:limit]]

    def update_progress(
        self,
        task_id: str,
        *,
        status: str | None = None,
        progress: float | None = None,
        message: str | None = None,
        result: Any = None,
        error: str | None = None,
        **fields: Any,
    ) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            if status is not None:
                if status not in _VALID_STATUS:
                    raise ValueError(f"invalid status: {status}")
                task["status"] = status
            if progress is not None:
                task["progress"] = progress
            if message is not None:
                task["message"] = message
            if result is not None:
                task["result"] = result
            if error is not None:
                task["error"] = error
            for key, value in fields.items():
                task[key] = value
            task["updated_at"] = time.time()
            self._flush(task_id)
            return dict(task)

    def add_log(self, task_id: str, message: str, *, keep: int = 300) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            logs = task.setdefault("logs", [])
            ts = time.strftime("%H:%M:%S")
            logs.append(f"[{ts}] {message}")
            if len(logs) > keep:
                task["logs"] = logs[-keep:]
            task["updated_at"] = time.time()

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(task_id)
            task = self._tasks.get(task_id)
            if event:
                event.set()
            if task and task.get("status") in ("pending", "running"):
                task["status"] = "cancelled"
                task["updated_at"] = time.time()
                self._flush(task_id)
                return True
            return bool(event)

    def is_cancelled(self, task_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(task_id)
            return bool(event and event.is_set())

    def cancel_event(self, task_id: str) -> threading.Event | None:
        with self._lock:
            return self._cancel_events.get(task_id)

    def upsert_legacy(
        self,
        task_id: str,
        platform: str,
        kind: str,
        state: dict,
    ) -> str:
        """Adopt a platform-local dict into the store (migration helper)."""
        with self._lock:
            if task_id not in self._tasks:
                self.create(platform, kind, task_id=task_id, extra=state)
            else:
                self._tasks[task_id].update(state)
                self._tasks[task_id]["updated_at"] = time.time()
                self._flush(task_id)
        return task_id

    def _flush(self, task_id: str) -> None:
        if not self._persist:
            return
        task = self._tasks.get(task_id)
        if not task:
            return
        path = self._dir / f"{task_id}.json"
        try:
            path.write_text(
                json.dumps(task, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass


# Process-wide singleton
task_store = TaskStore()
