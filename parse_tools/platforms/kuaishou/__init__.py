"""Kuaishou platform."""

from flask import Flask


def register(app: Flask) -> None:
    from parse_tools.platforms.kuaishou.kuaishou import kuaishou_bp
    from parse_tools.platforms.kuaishou.kuaishou_auth import kuaishou_auth_bp

    app.register_blueprint(kuaishou_bp)
    app.register_blueprint(kuaishou_auth_bp)


PLATFORM_ID = "kuaishou"
PLATFORM_NAME = "快手"
