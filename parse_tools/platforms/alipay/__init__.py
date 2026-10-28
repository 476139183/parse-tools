"""Alipay (生活号+) platform."""

from flask import Flask


def register(app: Flask) -> None:
    from parse_tools.platforms.alipay.alipay import alipay_bp

    app.register_blueprint(alipay_bp)


PLATFORM_ID = "alipay"
PLATFORM_NAME = "支付宝"
