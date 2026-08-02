"""Claude Code subscription usage (Pro/Max) for the hub dashboard.

Uses the same undocumented OAuth endpoint as Claude Code `/usage`.
Requires a local Claude CLI login (credentials file or macOS keychain).
Responses are cached to avoid rate limits.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

OKADMIN_ROOT = Path(__file__).resolve().parent
CACHE_PATH = OKADMIN_ROOT / "data" / "claude_usage_cache.json"
CACHE_VERSION = 1

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USER_AGENT = "claude-cli/2.1.119 (external, cli)"
BETA_HEADER = "oauth-2025-04-20"
KEYCHAIN_SERVICE = "Claude Code-credentials"

_lock = threading.Lock()
_CACHE_TTL_SEC = max(60, int(os.environ.get("CLAUDE_USAGE_CACHE_SEC", "300")))
_DISPLAY_TZ = ZoneInfo(os.environ.get("CLAUDE_USAGE_TZ", "Asia/Tokyo"))

# Windows we surface on the dashboard (order = display order)
WINDOW_SPECS: tuple[tuple[str, str], ...] = (
    ("five_hour", "5시간"),
    ("seven_day", "주간"),
    ("seven_day_sonnet", "주간 Sonnet"),
    ("seven_day_opus", "주간 Opus"),
)


def _level(pct: float) -> str:
    if pct >= 100:
        return "over"
    if pct >= 85:
        return "danger"
    if pct >= 70:
        return "warn"
    return "ok"


def _parse_resets_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_resets_at(raw: str | None, *, now: datetime | None = None) -> dict[str, Any]:
    """Human-friendly reset time in display TZ."""
    dt = _parse_resets_at(raw)
    if not dt:
        return {"iso": raw, "local": None, "in": None, "seconds": None}
    local = dt.astimezone(_DISPLAY_TZ)
    now = now or datetime.now(timezone.utc)
    delta = int((dt - now).total_seconds())
    if delta <= 0:
        return {
            "iso": dt.isoformat(),
            "local": local.strftime("%m/%d %H:%M"),
            "in": "리셋됨",
            "seconds": 0,
            "expired": True,
        }
    secs = delta
    h, rem = divmod(secs, 3600)
    m = rem // 60
    if h >= 24:
        remain = f"{h // 24}일 {h % 24}시간"
    elif h > 0:
        remain = f"{h}시간 {m}분"
    elif m > 0:
        remain = f"{m}분"
    else:
        remain = f"{secs}초"
    return {
        "iso": dt.isoformat(),
        "local": local.strftime("%m/%d %H:%M"),
        "in": remain,
        "seconds": secs,
        "expired": False,
    }


def _shape_window(key: str, label: str, raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    util = raw.get("utilization")
    if util is None:
        return None
    try:
        pct = float(util)
    except (TypeError, ValueError):
        return None
    pct = max(0.0, min(100.0, pct))
    reset = format_resets_at(raw.get("resets_at"))
    return {
        "key": key,
        "label": label,
        "percent": round(pct, 1),
        "remaining_percent": round(max(0.0, 100.0 - pct), 1),
        "level": _level(pct),
        "resets_at": reset.get("iso"),
        "resets_local": reset.get("local"),
        "resets_in": reset.get("in"),
        "resets_seconds": reset.get("seconds"),
    }


def shape_usage_payload(
    raw: dict[str, Any],
    *,
    subscription_type: str | None = None,
    rate_limit_tier: str | None = None,
    source: str = "live",
    note: str = "",
    error: str | None = None,
) -> dict[str, Any]:
    windows: list[dict[str, Any]] = []
    for key, label in WINDOW_SPECS:
        shaped = _shape_window(key, label, raw.get(key))
        if shaped:
            windows.append(shaped)

    extra = raw.get("extra_usage") if isinstance(raw.get("extra_usage"), dict) else {}
    return {
        "ok": error is None and bool(windows),
        "source": source,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "subscription_type": subscription_type,
        "rate_limit_tier": rate_limit_tier,
        "windows": windows,
        "extra_usage_enabled": bool(extra.get("is_enabled")),
        "note": note,
        "error": error,
        "cache_ttl_sec": _CACHE_TTL_SEC,
    }


_LEVEL_ORDER = {"ok": 0, "warn": 1, "danger": 2, "over": 3}
_PIPELINE_BLOCK_LEVELS = frozenset({"danger", "over"})
_WINDOW_PRIORITY = ("five_hour", "seven_day", "seven_day_sonnet", "seven_day_opus")


def attach_usage_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Add headline / worst_level / pipeline_ok for dashboard banner."""
    windows = [w for w in (summary.get("windows") or []) if isinstance(w, dict)]
    by_key = {str(w.get("key") or ""): w for w in windows if w.get("key")}

    worst_level = "ok"
    for w in windows:
        lv = str(w.get("level") or "ok")
        if _LEVEL_ORDER.get(lv, 0) > _LEVEL_ORDER.get(worst_level, 0):
            worst_level = lv

    primary: dict[str, Any] | None = None
    for key in _WINDOW_PRIORITY:
        if key in by_key:
            primary = by_key[key]
            break
    if primary is None and windows:
        primary = windows[0]

    pipeline_ok = True
    gate = by_key.get("five_hour") or primary
    if gate:
        lv = str(gate.get("level") or "ok")
        stale = bool(gate.get("percent_stale") or gate.get("expired"))
        try:
            pct = float(gate.get("percent") or 0)
        except (TypeError, ValueError):
            pct = 0.0
        pipeline_ok = (not stale) and lv not in _PIPELINE_BLOCK_LEVELS and pct < 85.0
    elif worst_level in _PIPELINE_BLOCK_LEVELS:
        pipeline_ok = False

    headline = ""
    if summary.get("error"):
        headline = str(summary["error"])[:120]
    elif primary:
        label = str(primary.get("label") or primary.get("key") or "Claude")
        if primary.get("percent_stale") or primary.get("expired"):
            headline = f"{label} 리셋됨 — 사용량 재조회 필요"
        else:
            pct = float(primary.get("percent") or 0)
            reset = primary.get("resets_in") or primary.get("resets_local") or ""
            headline = f"{label} {pct:.0f}%"
            if reset:
                headline += f" · 리셋 {reset} 후"
    elif summary.get("note"):
        headline = str(summary["note"])[:120]

    out = dict(summary)
    out["worst_level"] = worst_level
    out["pipeline_ok"] = pipeline_ok
    out["headline"] = headline
    out["primary_window"] = primary.get("key") if primary else None
    return out


def pipeline_blocked_message(summary: dict[str, Any] | None = None) -> str | None:
    data = attach_usage_summary(summary or {}) if summary else {}
    if data.get("pipeline_ok", True):
        return None
    headline = (data.get("headline") or "").strip()
    return headline or "Claude 사용량 한도 — 리셋 후 콘텐츠 생성"


def _reason_text(reason: Any) -> str:
    """Short human note from HTTP/error payload (avoid raw dict repr)."""
    if reason is None:
        return "unknown"
    retry_hint = None
    if isinstance(reason, dict):
        retry_hint = _format_retry_after(reason.get("_retry_after_sec"))
        err = reason.get("error")
        if isinstance(err, dict):
            msg = (err.get("message") or err.get("type") or "").strip()
            if msg:
                text = msg[:200]
            else:
                text = str(reason)[:200]
        elif reason.get("message"):
            text = str(reason["message"])[:200]
        else:
            text = str(reason)[:200]
    else:
        text = str(reason).strip()
    if "rate_limit" in text.lower() or "Rate limited" in text:
        text = "사용량 API rate limit (구독 5시간 창과 별개)"
    elif "authentication_error" in text.lower() or "Invalid authentication" in text:
        text = "Claude 인증 만료 — `claude` /login"
    if retry_hint:
        text = f"{text} · 약 {retry_hint} 후"
    return text[:220]


def refresh_summary_resets(summary: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Recompute resets_in from resets_at; mark expired windows so stale % is obvious."""
    out = dict(summary)
    windows: list[dict[str, Any]] = []
    any_expired = False
    for raw in summary.get("windows") or []:
        if not isinstance(raw, dict):
            continue
        w = dict(raw)
        reset = format_resets_at(w.get("resets_at"), now=now)
        if reset.get("local"):
            w["resets_local"] = reset["local"]
        if reset.get("in") is not None:
            w["resets_in"] = reset["in"]
        if reset.get("seconds") is not None:
            w["resets_seconds"] = reset["seconds"]
        if reset.get("expired"):
            any_expired = True
            w["expired"] = True
            # Past reset: cached utilization is meaningless until live fetch works
            w["percent_stale"] = True
            label = w.get("label") or w.get("key") or "창"
            w["stale_hint"] = f"{label} 리셋됨 — %는 캐시(재조회 필요)"
        else:
            w.pop("expired", None)
            w.pop("percent_stale", None)
            w.pop("stale_hint", None)
        windows.append(w)
    out["windows"] = windows
    if any_expired and out.get("source") in ("cache", "stale_cache"):
        note = (out.get("note") or "").strip()
        hint = "일부 창 리셋됨 · %는 오래된 캐시"
        if hint not in note:
            out["note"] = f"{note} · {hint}".strip(" ·") if note else hint
    return out



def _creds_paths() -> list[Path]:
    paths: list[Path] = []
    env = (os.environ.get("CLAUDE_CREDENTIALS") or "").strip()
    if env:
        paths.append(Path(env).expanduser())
    paths.append(Path.home() / ".claude" / ".credentials.json")
    # Server may run as another user; allow override to the logged-in human home
    hub_home = (os.environ.get("CLAUDE_HOME") or "").strip()
    if hub_home:
        paths.append(Path(hub_home).expanduser() / ".claude" / ".credentials.json")
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _oauth_from_mapping(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    oauth = data.get("claudeAiOauth") if isinstance(data.get("claudeAiOauth"), dict) else data
    if not isinstance(oauth, dict):
        return None
    if not (oauth.get("accessToken") or "").strip():
        return None
    return oauth


def load_oauth() -> tuple[dict[str, Any] | None, str | None]:
    """Return (oauth_dict, source_label) or (None, reason)."""
    for path in _creds_paths():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        oauth = _oauth_from_mapping(data)
        if oauth:
            return oauth, f"file:{path}"

    if platform.system() == "Darwin":
        try:
            out = subprocess.check_output(
                ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).strip()
            data = json.loads(out)
            oauth = _oauth_from_mapping(data)
            if oauth:
                return oauth, "keychain"
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

    return None, "Claude CLI 로그인 없음 — `claude` 실행 후 /login"


def _fetch_usage(token: str) -> tuple[int | None, Any]:
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "anthropic-beta": BETA_HEADER,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.getcode(), json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        try:
            parsed: Any = json.loads(body)
        except json.JSONDecodeError:
            parsed = body
        if isinstance(parsed, dict):
            retry_after = exc.headers.get("Retry-After") or exc.headers.get("retry-after")
            if retry_after:
                try:
                    parsed["_retry_after_sec"] = int(float(str(retry_after).strip()))
                except ValueError:
                    parsed["_retry_after_sec"] = str(retry_after).strip()
            return exc.code, parsed
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return None, f"network: {exc.reason}"
    except TimeoutError:
        return None, "timeout"


def _format_retry_after(sec: Any) -> str | None:
    try:
        n = int(sec)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n >= 3600:
        h, rem = divmod(n, 3600)
        m = rem // 60
        return f"{h}시간 {m}분" if m else f"{h}시간"
    if n >= 60:
        return f"{n // 60}분"
    return f"{n}초"


def _load_cache() -> dict[str, Any] | None:
    if not CACHE_PATH.is_file():
        return None
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("cache_version") != CACHE_VERSION:
        return None
    fetched = data.get("fetched_at")
    if not isinstance(fetched, (int, float)):
        return None
    age = time.time() - fetched
    data["_cache_age_sec"] = int(age)
    data["_cache_fresh"] = age <= _CACHE_TTL_SEC
    return data


def _save_cache(summary: dict[str, Any], raw: dict[str, Any]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cache_version": CACHE_VERSION,
            "fetched_at": time.time(),
            "summary": summary,
            "raw": {
                k: raw.get(k)
                for k in (
                    "five_hour",
                    "seven_day",
                    "seven_day_sonnet",
                    "seven_day_opus",
                    "extra_usage",
                )
            },
        }
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(CACHE_PATH)
    except OSError:
        pass


def _finalize_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return attach_usage_summary(refresh_summary_resets(summary))


def usage_summary(*, force: bool = False) -> dict[str, Any]:
    """Dashboard payload: windows with utilization % and reset times."""
    with _lock:
        cached = _load_cache()
        if cached and cached.get("_cache_fresh") and not force:
            summary = dict(cached.get("summary") or {})
            summary["source"] = "cache"
            summary["cache_age_sec"] = cached.get("_cache_age_sec")
            return _finalize_summary(summary)

        oauth, src = load_oauth()
        if not oauth:
            err = src or "no credentials"
            if cached and cached.get("summary"):
                summary = dict(cached["summary"])
                summary["source"] = "stale_cache"
                summary["cache_age_sec"] = cached.get("_cache_age_sec")
                summary["note"] = f"{err} · 캐시 표시"
                summary["error"] = err
                return _finalize_summary(summary)
            return _finalize_summary(shape_usage_payload({}, note=err, error=err, source="none"))

        status, payload = _fetch_usage(oauth["accessToken"])
        sub = oauth.get("subscriptionType")
        tier = oauth.get("rateLimitTier")

        if status == 200 and isinstance(payload, dict):
            summary = shape_usage_payload(
                payload,
                subscription_type=str(sub) if sub else None,
                rate_limit_tier=str(tier) if tier else None,
                source="live",
                note=f"Claude Code · {src}",
            )
            _save_cache(summary, payload)
            return _finalize_summary(summary)

        if isinstance(payload, dict):
            reason = _reason_text(payload)
        elif isinstance(payload, str):
            reason = _reason_text(payload)
        else:
            reason = f"HTTP {status}" if status else _reason_text(payload)

        if cached and cached.get("summary"):
            summary = dict(cached["summary"])
            summary["source"] = "stale_cache"
            summary["cache_age_sec"] = cached.get("_cache_age_sec")
            summary["note"] = f"{reason} · 캐시 표시"
            summary["error"] = reason
            return _finalize_summary(summary)

        return _finalize_summary(
            shape_usage_payload(
                {},
                subscription_type=str(sub) if sub else None,
                rate_limit_tier=str(tier) if tier else None,
                source="error",
                note=reason,
                error=reason,
            )
        )
