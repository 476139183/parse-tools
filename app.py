#!/usr/bin/env python3
"""Parse Tools — full desktop / browser entry (all platforms)."""

import os
import sys


def ensure_virtualenv():
    if getattr(sys, "frozen", False):
        return
    project_root = os.path.dirname(os.path.abspath(__file__))
    if sys.platform == "win32":
        venv_python = os.path.join(project_root, "venv312", "Scripts", "python.exe")
    else:
        venv_python = os.path.join(project_root, "venv312", "bin", "python")
    if os.path.exists(venv_python):
        current_exe = os.path.abspath(sys.executable)
        target_exe = os.path.abspath(venv_python)
        if current_exe != target_exe:
            print(f"[Env Auto-Switch] 检测到虚拟环境，正在自动切换至: {venv_python}", flush=True)
            os.execv(venv_python, [venv_python] + sys.argv)


ensure_virtualenv()

import argparse
import threading
import webbrowser

from parse_tools import APP_NAME, APP_VERSION
from parse_tools.core.app_factory import create_app, stop_background_services
from parse_tools.core.config import ensure_dirs

app = create_app(mode="full", start_services=True)


def open_browser(port: int):
    import time

    time.sleep(1)
    webbrowser.open(f"http://localhost:{port}")


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} — 多平台解析下载工具")
    parser.add_argument("--port", type=int, default=5200, help="服务端口 (默认 5200)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()

    ensure_dirs()

    print()
    print("=" * 56)
    print(f"  {APP_NAME}  v{APP_VERSION}")
    print(f"  http://{args.host}:{args.port}")
    print("=" * 56)
    print()

    if not args.no_browser:
        threading.Thread(target=open_browser, args=(args.port,), daemon=True).start()

    try:
        app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    finally:
        stop_background_services()


if __name__ == "__main__":
    main()
