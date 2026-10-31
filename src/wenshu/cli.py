"""Command line entry point."""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser

import uvicorn

from .app import create_app
from .config import DEFAULT_PORT, PORT_SCAN, VERSION, RuntimeConfig


def _find_port(host: str, start: int, attempts: int = PORT_SCAN) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise SystemExit(f"端口 {start}-{start + attempts - 1} 都被占用，请用 --port 指定。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wenshu",
        description="文枢 Wenshu —— 本地优先的中文文科科研写作工作台",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口（默认 8765，占用则顺延）")
    parser.add_argument("--data-dir", default=None, help="数据目录（默认系统应用数据目录）")
    parser.add_argument("--demo", action="store_true", help="演示模式：不调用真实 LLM")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--version", action="version", version=f"wenshu {VERSION}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = RuntimeConfig.build(
        data_dir=args.data_dir,
        port=args.port,
        demo=args.demo,
        no_browser=args.no_browser,
    )
    cfg.ensure_dirs()
    app = create_app(cfg)
    port = _find_port(cfg.host, cfg.port)
    url = f"http://{cfg.host}:{port}"
    print(f"文枢 Wenshu {VERSION}")
    print(f"  地址：{url}")
    print(f"  数据：{cfg.data_dir}")
    if cfg.demo:
        print("  模式：演示（不调用真实 LLM）")
    print("  按 Ctrl+C 停止")
    if not cfg.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=cfg.host, port=port, log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
