"""Load .env and paths before Flask / GSC (shared by start.sh and macOS app)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def bootstrap_okadmin(root: Path | str) -> Path:
    root = Path(root).resolve()
    os.chdir(root)
    from dotenv import load_dotenv

    load_dotenv(root / ".env")
    os.environ.setdefault("WORK_ROOT", "/opt/work")
    os.environ.setdefault("SITES_YAML", "/opt/work/sites.yaml")
    os.environ.setdefault("PORT", "8090")
    os.environ.setdefault("LOCAL_DEV_AUTH", "1")
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if creds and not creds.startswith("/"):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(root / creds)
    return root


def port_open(port: int) -> bool:
    try:
        r = subprocess.run(
            ["lsof", "-i", f":{port}", "-sTCP:LISTEN"],
            capture_output=True,
            check=False,
        )
        return r.returncode == 0
    except OSError:
        return False
