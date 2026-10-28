"""WeChat MP / Weread platform."""

from flask import Flask


def register(app: Flask) -> None:
    from parse_tools.platforms.wechat.account_pool_api import account_pool_bp
    from parse_tools.platforms.wechat.accounts import accounts_bp
    from parse_tools.platforms.wechat.articles import articles_bp
    from parse_tools.platforms.wechat.auth import auth_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(articles_bp)
    app.register_blueprint(account_pool_bp)


PLATFORM_ID = "wechat"
PLATFORM_NAME = "微信公众号"
