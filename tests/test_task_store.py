"""Unit tests for unified TaskStore."""

from parse_tools.core.task_store import TaskStore


def test_create_update_cancel():
    store = TaskStore(persist=False)
    tid = store.create("douyin", "batch", params={"url": "x"})
    assert store.get(tid)["status"] == "pending"
    store.update_progress(tid, status="running", progress=10, message="go")
    assert store.get(tid)["progress"] == 10
    store.add_log(tid, "hello")
    assert any("hello" in x for x in store.get(tid)["logs"])
    assert store.cancel(tid) is True
    assert store.get(tid)["status"] == "cancelled"
    assert store.is_cancelled(tid) is True


def test_list_filter():
    store = TaskStore(persist=False)
    store.create("douyin", "a")
    store.create("kuaishou", "b")
    assert len(store.list(platform="douyin")) == 1
