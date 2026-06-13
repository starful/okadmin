"""Load GEMINI_API_KEY into os.environ if missing."""
from __future__ import annotations

import os
import re
from pathlib import Path

from config import WORK_ROOT


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        out[key] = val
    return out


def ensure_gemini_api_key() -> bool:
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return True
    okadmin_root = Path(__file__).resolve().parent
    candidates = [
        okadmin_root / ".env",
        WORK_ROOT / "jpcampus" / ".env",
        WORK_ROOT / "krcampus" / ".env",
        WORK_ROOT / "starful.biz" / ".env",
        WORK_ROOT / "okramen" / ".env",
        WORK_ROOT / "okstats" / ".env",
    ]
    for path in candidates:
        for key, val in _read_env_file(path).items():
            if key == "GEMINI_API_KEY" and val:
                os.environ["GEMINI_API_KEY"] = val
                return True
    return False
