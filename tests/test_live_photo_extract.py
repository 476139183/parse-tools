"""Live Photo URL extraction helpers."""

from parse_tools.platforms.douyin.client import DouyinClient
from parse_tools.platforms.xiaohongshu.xiaohongshu import _extract_xhs_live_url


def test_douyin_live_from_play_addr_dict():
    img = {
        "url_list": ["https://example.com/a.jpeg"],
        "video": {
            "play_addr": {"url_list": ["https://example.com/live1.mp4"]},
        },
    }
    assert DouyinClient._extract_live_photo_url(img) == "https://example.com/live1.mp4"


def test_douyin_live_from_bit_rate_fallback():
    img = {
        "video": {
            "bit_rate": [
                {"play_addr": {"url_list": ["https://example.com/br.mp4"]}},
            ],
        },
    }
    assert DouyinClient._extract_live_photo_url(img) == "https://example.com/br.mp4"


def test_douyin_live_from_download_addr():
    img = {
        "video": {
            "download_addr": {"url_list": ["https://example.com/dl.mp4"]},
        },
    }
    assert DouyinClient._extract_live_photo_url(img) == "https://example.com/dl.mp4"


def test_douyin_live_empty_when_missing():
    assert DouyinClient._extract_live_photo_url({"url_list": ["x"]}) == ""


def test_xhs_live_h264():
    img = {
        "stream": {
            "h264": [{"masterUrl": "https://sns-video.example/live.mp4"}],
        },
    }
    assert _extract_xhs_live_url(img) == "https://sns-video.example/live.mp4"


def test_xhs_live_h265_and_backup():
    img = {
        "stream": {
            "h265": [{"backupUrls": ["https://backup.example/live.mp4"]}],
        },
    }
    assert _extract_xhs_live_url(img) == "https://backup.example/live.mp4"


def test_weibo_extract_status_id():
    from parse_tools.platforms.weibo.weibo import extract_status_id

    assert extract_status_id("https://m.weibo.cn/detail/5123456789012345") == "5123456789012345"
    assert extract_status_id("https://weibo.com/1234567890/AbCdEfGhI") == "AbCdEfGhI"
    assert extract_status_id("https://weibo.com/status/AbCdEfGhI") == "AbCdEfGhI"
    assert extract_status_id("5123456789012345") == "5123456789012345"
