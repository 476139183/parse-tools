"""Douyin platform."""

from flask import Flask


def register(app: Flask) -> None:
    from parse_tools.platforms.douyin.douyin_auth import douyin_auth_bp
    from parse_tools.platforms.douyin.douyin_login import douyin_login_bp
    from parse_tools.platforms.douyin.routes import douyin_bp

    app.register_blueprint(douyin_bp)
    app.register_blueprint(douyin_login_bp)
    app.register_blueprint(douyin_auth_bp)


PLATFORM_ID = "douyin"
PLATFORM_NAME = "抖音"
