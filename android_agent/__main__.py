from __future__ import annotations

import argparse
import webbrowser

from .server import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="端侧智能体第一版 · 本地对话与命令桥梁")
    parser.add_argument("--port", type=int, default=8686, help="本地回环端口（默认8686）")
    parser.add_argument("--open-browser", action="store_true", help="启动后打开携带运行令牌的授权页面")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口必须在1024到65535之间")
    serve(port=args.port, open_browser=args.open_browser)


if __name__ == "__main__":
    main()
