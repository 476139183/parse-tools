"""支付宝 contentId 提取与归一化单测。"""

from parse_tools.platforms.alipay.alipay import (
    _extract_video_url,
    _normalize_item,
    extract_content_id,
)


def test_extract_content_id_from_plain():
    cid = "20261018OB020010023739705723"
    assert extract_content_id(cid) == cid


def test_extract_content_id_from_scheme_query():
    raw = (
        "https://render.alipay.com/p/yuyan/180020010001266490/video-share.html"
        "?scheme=alipays%3A%2F%2Fplatformapi%2Fstartapp%3FcontentId%3D20261018OB020010023739705723"
    )
    assert extract_content_id(raw) == "20261018OB020010023739705723"


def test_extract_content_id_direct_param():
    raw = "https://example.com/x?contentId=20261018OB020010023739705723&refer=share"
    assert extract_content_id(raw) == "20261018OB020010023739705723"


def test_normalize_image_item():
    raw = {
        "contentId": "20261018OB020010023739705723",
        "type": "image",
        "title": "测试标题",
        "content": "正文内容",
        "author": {"nickName": "作者A", "avatar": "https://a/avatar.jpg"},
        "coverPic": {"url": "https://a/cover.jpg"},
        "picList": [
            {"url": "https://a/1.jpg"},
            {"url": "https://a/2.jpg"},
        ],
        "video": None,
    }
    item = _normalize_item(raw)
    assert item["type"] == "image"
    assert item["author"] == "作者A"
    assert len(item["images"]) == 2
    assert item["cover"] == "https://a/cover.jpg"
    assert item["video"] == ""


def test_normalize_video_item():
    raw = {
        "contentId": "cid1",
        "type": "video",
        "title": "视频标题",
        "content": "",
        "author": {"nickName": "作者B"},
        "coverPic": {"url": "https://a/cover.jpg"},
        "picList": [],
        "video": {"url": "https://cdn.example.com/a.mp4"},
    }
    item = _normalize_item(raw)
    assert item["type"] == "video"
    assert item["video"] == "https://cdn.example.com/a.mp4"


def test_extract_video_url_nested():
    assert _extract_video_url({"playUrl": "https://x.com/v.mp4"}) == "https://x.com/v.mp4"
    assert _extract_video_url({"videos": [{"hdUrl": "https://x.com/hd.mp4"}]}) == "https://x.com/hd.mp4"
