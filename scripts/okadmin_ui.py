#!/usr/bin/env python3
"""Open OK Admin in browser (dev) or native window (app)."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


def wait_health(port: int, *, attempts: int = 80) -> bool:
    url = f"http://127.0.0.1:{port}/healthz"
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1) as res:
                if res.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(0.25)
    return False


def kill_port(port: int) -> None:
    try:
        out = subprocess.run(
            ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            check=False,
        )
        for pid in (out.stdout or "").strip().split():
            if pid.isdigit():
                subprocess.run(["kill", pid], check=False)
    except OSError:
        pass


def open_browser(url: str) -> int:
    subprocess.run(["open", url], check=False)
    return 0


def open_chrome_app(url: str) -> bool:
    candidates = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Arc.app/Contents/MacOS/Arc",
    )
    for exe in candidates:
        if os.path.isfile(exe):
            subprocess.Popen(
                [exe, f"--app={url}", "--window-size=1280,900"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
    return False


def open_native_window(url: str, *, stop_on_close: bool, port: int) -> int:
    try:
        import webview
    except ImportError:
        if open_chrome_app(url):
            return 0
        return open_browser(url)

    closing = {"done": False}

    def on_closing() -> bool:
        closing["done"] = True
        if stop_on_close:
            kill_port(port)
        return True

    window = webview.create_window(
        "OK Admin",
        url,
        width=1280,
        height=880,
        min_size=(900, 600),
        background_color="#0a0a0a",
    )
    window.events.closing += on_closing
    webview.start()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("browser", "app", "chrome"),
        default="browser",
        help="browser=개발 · app=네이티브 창 · chrome=Chrome 앱 창",
    )
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8090")))
    parser.add_argument(
        "--stop-on-close",
        action="store_true",
        help="app 모드: 창 닫을 때 서버 종료",
    )
    parser.add_argument("--wait", action="store_true", help="healthz 대기")
    args = parser.parse_args()

    base = f"http://127.0.0.1:{args.port}/"
    if args.wait and not wait_health(args.port):
        print("서버 healthz 대기 시간 초과", file=sys.stderr)
        return 1

    if args.mode == "browser":
        return open_browser(base)
    if args.mode == "chrome":
        if open_chrome_app(base):
            return 0
        return open_browser(base)
    return open_native_window(base, stop_on_close=args.stop_on_close, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
