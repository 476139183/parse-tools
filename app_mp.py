#!/usr/bin/env python3
"""Parse Tools — 公众号 + RSS 精简服务入口。"""

import argparse
import os
import sys

from parse_tools import APP_NAME, APP_VERSION
from parse_tools.core.app_factory import create_app
from parse_tools.core.config import ensure_dirs

app = create_app(mode="mp", start_services=True)


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} — 公众号 + RSS")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5200)))
    parser.add_argument("--host", type=str, default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--no-browser", action="store_true", help="占位参数（与全量入口一致）")
    args = parser.parse_args()

    ensure_dirs()

    print("=" * 56)
    print(f"  {APP_NAME} 公众号+RSS  v{APP_VERSION}")
    print(f"  http://{args.host}:{args.port}")
    print("  已启用：公众号登录 / 文章 / 下载导出 / RSS / 代理")
    print("=" * 56)

    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
