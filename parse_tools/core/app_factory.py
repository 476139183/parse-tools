"""Flask application factory for Parse Tools."""

from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from parse_tools import APP_NAME, APP_VERSION
from parse_tools.core.config import ensure_dirs, get_settings, save_settings
from parse_tools.core.registry import PlatformRegistry, build_default_registry
from parse_tools.core.runtime import configure_runtime, frontend_dir

_MP_ENABLED = [
    "公众号登录（微信读书扫码）",
    "公众号账号与文章列表",
    "文章下载 / 导出（HTML / Markdown / PDF）",
    "RSS 订阅与定时增量抓取",
    "代理配置",
]
_MP_DISABLED = ["抖音", "快手", "小红书", "哔哩哔哩", "微博", "微信视频号", "字幕擦除", "客户端自动更新"]


def create_app(
    mode: str = "full",
    *,
    start_services: bool = True,
    registry: PlatformRegistry | None = None,
) -> Flask:
    """Build Flask app.

    mode: "full" | "mp"
    start_services: when True, start RSS scheduler and related background work
                    AFTER blueprints are registered (no import-time side effects).
    """
    if mode not in ("full", "mp"):
        raise ValueError(f"unsupported mode: {mode}")

    configure_runtime()
    ensure_dirs()
    _migrate_legacy_data_files()

    static_folder = frontend_dir()
    app = Flask(
        __name__,
        static_folder=str(static_folder),
        static_url_path="",
    )
    CORS(app)
    app.config["PARSE_TOOLS_MODE"] = mode
    app.config["PARSE_TOOLS_NAME"] = APP_NAME

    reg = registry or build_default_registry()
    enabled_ids = reg.register_all(app, mode=mode)
    app.config["PARSE_TOOLS_PLATFORMS"] = enabled_ids

    _register_common_routes(app, mode=mode)

    if start_services:
        start_background_services(mode=mode)

    return app


def start_background_services(*, mode: str = "full") -> None:
    """Explicitly start daemons that used to run at import time."""
    try:
        from parse_tools.platforms.wechat.account_pool import migrate_legacy_config

        migrate_legacy_config()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] account pool migrate failed: {exc}", file=sys.stderr)

    try:
        from parse_tools.platforms.wechat.rss_scheduler import rss_scheduler

        rss_scheduler.start()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] RSS scheduler start failed: {exc}", file=sys.stderr)


def stop_background_services() -> None:
    try:
        from parse_tools.platforms.channels.mitm_proxy import ProxyManager

        ProxyManager.get_instance().stop()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] stop channels proxy: {exc}", file=sys.stderr)

    try:
        from parse_tools.platforms.wechat.rss_scheduler import rss_scheduler

        if hasattr(rss_scheduler, "stop"):
            rss_scheduler.stop()
    except Exception:
        pass


def _migrate_legacy_data_files() -> None:
    """Rename legacy wechat_tools DB / config paths to parse_tools names."""
    from parse_tools.core.config import DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pairs = [
        (DATA_DIR / "wechat_tools.db", DATA_DIR / "parse_tools.db"),
        (DATA_DIR / "wechat_mp_config.json", DATA_DIR / "parse_tools_config.json"),
    ]
    for old, new in pairs:
        if old.exists() and not new.exists():
            try:
                old.rename(new)
            except OSError:
                pass


def _register_common_routes(app: Flask, *, mode: str) -> None:
    @app.route("/favicon.ico")
    def favicon():
        return ("", 204)

    @app.route("/healthz")
    def healthz():
        payload = {"status": "ok", "version": APP_VERSION, "mode": mode if mode == "full" else "mp-only"}
        if mode == "mp":
            payload["modules"] = len(_MP_ENABLED)
        return jsonify(payload)

    @app.route("/api/capabilities")
    def capabilities():
        if mode == "mp":
            return jsonify({
                "mode": "mp-only",
                "version": APP_VERSION,
                "product": APP_NAME,
                "enabled": _MP_ENABLED,
                "disabled": _MP_DISABLED,
            })
        return jsonify({
            "mode": "full",
            "version": APP_VERSION,
            "product": APP_NAME,
            "platforms": app.config.get("PARSE_TOOLS_PLATFORMS", []),
        })

    @app.route("/api/settings", methods=["GET"])
    def read_settings():
        return jsonify(get_settings())

    @app.route("/api/settings", methods=["POST"])
    def update_settings():
        data = request.get_json() or {}
        settings = get_settings()
        settings.update(data)
        save_settings(settings)
        return jsonify({"message": "设置已保存"})

    @app.route("/")
    def serve_index():
        return send_from_directory(app.static_folder, "index.html")

    if mode == "mp":
        @app.errorhandler(404)
        def handle_404(err):
            if request.path.startswith("/api/"):
                return jsonify({
                    "error": "当前部署仅包含公众号与 RSS 功能，该接口未启用",
                    "path": request.path,
                }), 501
            index = Path(app.static_folder) / "index.html"
            if index.exists():
                return send_from_directory(app.static_folder, "index.html")
            return jsonify({"error": "前端资源缺失，请确认 parse_tools/frontend 已打包进镜像"}), 500

    @app.route("/<path:path>")
    def serve_static(path):
        file_path = Path(app.static_folder) / path
        if file_path.is_file():
            return send_from_directory(app.static_folder, path)
        return send_from_directory(app.static_folder, "index.html")
