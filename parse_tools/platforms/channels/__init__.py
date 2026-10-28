"""WeChat Channels (视频号) platform."""

from flask import Flask


def register(app: Flask) -> None:
    from parse_tools.platforms.channels.channels import channels_bp

    app.register_blueprint(channels_bp)


PLATFORM_ID = "channels"
PLATFORM_NAME = "微信视频号"
