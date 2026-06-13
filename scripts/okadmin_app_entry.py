#!/usr/bin/env python3
"""macOS .app entry: one process (Flask thread + webview) → single Dock icon."""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def _app_root() -> Path:
    env_root = os.environ.get("OKADMIN_APP_ROOT", "").strip()
    if env_root:
        p = Path(env_root)
        if p.is_dir():
            return p
    exe = Path(sys.argv[0]).resolve()
    # Contents/MacOS/okadmin-launch → Contents
    if (exe.parent.parent / "Resources").is_dir():
        return exe.parent.parent
    return exe.parent


def _okadmin_root(app_root: Path) -> Path:
    p = app_root / "Resources" / "okadmin-root"
    if p.is_file():
        text = p.read_text(encoding="utf-8").strip()
        if text and Path(text).is_dir():
            return Path(text)
    if (app_root.parent / "start.sh").is_file():
        return app_root.parent
    return Path("/opt/work/okadmin")


def _ui_mode(app_root: Path) -> str:
    p = app_root / "Resources" / "ui-mode"
    if p.is_file():
        return p.read_text(encoding="utf-8").strip() or "app"
    return (sys.argv[1] if len(sys.argv) > 1 else "app").strip()


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
    import subprocess

    try:
        out = subprocess.run(
            ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            check=False,
        )
        for pid in (out.stdout or "").strip().split():
            if pid.isdigit() and int(pid) != os.getpid():
                subprocess.run(["kill", pid], check=False)
    except OSError:
        pass


def start_flask_thread(port: int) -> None:
    from app_factory import create_app

    app = create_app()

    def _run() -> None:
        app.run(
            host="127.0.0.1",
            port=port,
            threaded=True,
            use_reloader=False,
        )

    t = threading.Thread(target=_run, daemon=True, name="okadmin-flask")
    t.start()


def run_app_window(port: int, *, own_server: bool) -> int:
    import webview

    url = f"http://127.0.0.1:{port}/"

    def on_closing() -> bool:
        if own_server:
            os._exit(0)
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
    webview.start(debug=False)
    return 0


def alert(title: str, message: str) -> None:
    import subprocess

    msg = message.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        [
            "osascript",
            "-e",
            f'display alert "{title}" message "{msg}" as warning',
        ],
        check=False,
    )


def main() -> int:
    app_root = _app_root()
    okadmin_root = _okadmin_root(app_root)
    ui_mode = _ui_mode(app_root)

    if str(okadmin_root) not in sys.path:
        sys.path.insert(0, str(okadmin_root))
    scripts = okadmin_root / "scripts"
    if scripts.is_dir() and str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

    from okadmin_bootstrap import bootstrap_okadmin, port_open

    bootstrap_okadmin(okadmin_root)
    port = int(os.environ.get("PORT", "8090"))

    own_server = False
    if not port_open(port):
        start_flask_thread(port)
        own_server = True
        if not wait_health(port):
            log = Path.home() / "Library/Logs/okadmin/server.log"
            alert("OK Admin", f"서버 기동 실패.\n{log}")
            return 1

    base = f"http://127.0.0.1:{port}/"

    if ui_mode in ("browser", "dev"):
        import subprocess

        subprocess.run(["open", base], check=False)
        return 0

    # app — same process as webview (no second Python in Dock)
    try:
        return run_app_window(port, own_server=own_server)
    except ImportError:
        from okadmin_ui import open_chrome_app, open_browser

        if open_chrome_app(base):
            return 0
        return open_browser(base)


if __name__ == "__main__":
    raise SystemExit(main())
