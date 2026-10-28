"""Weibo platform."""

from flask import Flask


def register(app: Flask) -> None:
    from parse_tools.platforms.weibo.weibo import weibo_bp

    app.register_blueprint(weibo_bp)


PLATFORM_ID = "weibo"
PLATFORM_NAME = "微博"
