"""Bilibili platform."""

from flask import Flask


def register(app: Flask) -> None:
    from parse_tools.platforms.bilibili.bilibili import bilibili_bp
    from parse_tools.platforms.bilibili.bilibili_login import bilibili_login_bp

    app.register_blueprint(bilibili_bp)
    app.register_blueprint(bilibili_login_bp)


PLATFORM_ID = "bilibili"
PLATFORM_NAME = "哔哩哔哩"
