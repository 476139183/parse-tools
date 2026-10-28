"""Xiaohongshu platform."""

from flask import Flask


def register(app: Flask) -> None:
    from parse_tools.platforms.xiaohongshu.xiaohongshu import xhs_bp
    from parse_tools.platforms.xiaohongshu.xiaohongshu_login import xhs_login_bp

    app.register_blueprint(xhs_bp)
    app.register_blueprint(xhs_login_bp)


PLATFORM_ID = "xiaohongshu"
PLATFORM_NAME = "小红书"
