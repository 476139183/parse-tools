"""公众号贴图 / 小绿书 Live 配对提取。"""

from parse_tools.platforms.wechat.downloader import (
    CONTENT_TYPE_ARTICLE,
    CONTENT_TYPE_PICTURE,
    classify_wechat_content_type,
    content_type_from_show_type,
    extract_wechat_live_pairs,
    try_extract_gallery_article,
    upgrade_mmbiz_image_url,
)


SAMPLE = r"""
<script>
window.picture_page_info_list = [
  {
    cdn_url: 'https://mmbiz.qpic.cn/mmbiz_jpg/AAA/640?wx_fmt=jpeg',
    video_cdn_url: 'https://mpvideo.qpic.cn/xxx.mp4?foo=1',
  },
  {
    cdn_url: 'https://mmbiz.qpic.cn/mmbiz_jpg/BBB/640?wx_fmt=jpeg',
    is_watermark: true,
  },
  {
    cdn_url: 'https://mmbiz.qpic.cn/mmbiz_jpg/CCC/640?wx_fmt=jpeg',
  },
].slice(0, 20);
window.desc = "hello\nworld";
</script>
<div class="swiper_item_img">
  <video src="https://mpvideo.qpic.cn/swiper_live.mp4"></video>
  <img data-src="https://mmbiz.qpic.cn/mmbiz_jpg/DDD/640?wx_fmt=jpeg" />
</div>
"""


def test_upgrade_mmbiz_image_url():
    u = upgrade_mmbiz_image_url("https://mmbiz.qpic.cn/mmbiz_jpg/AAA/640?wx_fmt=jpeg")
    assert "/0?" in u
    assert "/640?" not in u


def test_extract_live_pairs_from_picture_list_and_swiper():
    pairs = extract_wechat_live_pairs(SAMPLE)
    imgs = [p["img"] for p in pairs if p.get("img")]
    lives = [p["live"] for p in pairs if p.get("live")]
    assert any("AAA" in u for u in imgs)
    assert any("CCC" in u for u in imgs)
    assert not any("BBB" in u for u in imgs)  # watermark skipped
    assert any("xxx.mp4" in u for u in lives)
    assert any("swiper_live.mp4" in u for u in lives)
    assert any("DDD" in u for u in imgs)


def test_gallery_html_includes_live_video():
    html = try_extract_gallery_article(SAMPLE)
    assert html is not None
    assert "<video" in html
    assert "hello" in html


def test_content_type_from_show_type():
    assert content_type_from_show_type(0) == CONTENT_TYPE_ARTICLE
    assert content_type_from_show_type(8) == CONTENT_TYPE_PICTURE
    assert content_type_from_show_type("8") == CONTENT_TYPE_PICTURE


def test_classify_picture_page_as_picture():
    assert classify_wechat_content_type(SAMPLE, item_show_type=8) == CONTENT_TYPE_PICTURE
    assert classify_wechat_content_type(SAMPLE) == CONTENT_TYPE_PICTURE


def test_classify_long_article():
    html = '<div id="js_content">' + ("段落内容足够长。" * 20) + "</div>"
    assert classify_wechat_content_type(html, item_show_type=0) == CONTENT_TYPE_ARTICLE
    assert classify_wechat_content_type(html) == CONTENT_TYPE_ARTICLE
