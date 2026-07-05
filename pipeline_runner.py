"""Pipeline subprocess runner, logging, and GCS post-steps."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from pipeline_limits import SITE_GCS_BUCKETS, SITE_GCS_IMAGE_DIRS
from generation_result import last_generation_result
from topic_bank_registry import banks_for_site

Step = tuple[str, str, list[str], int]
PostStep = tuple[str, Callable[[Path, Any], dict[str, Any]]]

_CONTENT_ZERO_PATTERNS = (
    "no new guides to generate",
    "no missing en/ko",
    "no guide orphans",
    "no new items",
    "생성할 새",
    "모든 가이드가 이미",
    "모든 코스 콘텐츠가 이미",
    "모든 파일이 생성済",
    "すべてのファイルが生成済",
    "새로 생성할 컨텐츠가 없",
    "pending: 0",
)
_CONTENT_GEN_PATTERNS = (
    r"starting generation for (\d+)",
    r"generating (\d+) missing",
    r"🔔 (\d+) topic",
    r"🔔 (\d+)개",
    r"✅ \[done\]",
    r"✅ \[완료\]",
    r"✅ success:",
    r"✅ 完了:",
    r"✅ 생성 완료 \(\d+\)",
)


def _log_dir() -> Path:
    base = Path(__file__).resolve().parent / "data" / "content_logs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def pipeline_log_path(site_id: str) -> Path:
    return _log_dir() / f"{site_id}_pipeline.log"


def pipeline_status_path(site_id: str) -> Path:
    return _log_dir() / f"{site_id}_pipeline_status.json"


def read_pipeline_status(site_id: str) -> dict[str, Any] | None:
    path = pipeline_status_path(site_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_pipeline_status(site_id: str, data: dict[str, Any]) -> None:
    stamped = _stamp_pipeline_result(data)
    pipeline_status_path(site_id).write_text(
        json.dumps(stamped, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


_PIPELINE_HEADER_RE = re.compile(
    r"^# (\S+) pipeline (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*$",
    re.MULTILINE,
)


def _stamp_pipeline_result(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    if "finished_at" not in out:
        out["finished_at"] = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    return out


def _parse_run_datetime(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[: len(fmt)], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")[:19])
    except ValueError:
        return None


def pipeline_last_run(site_id: str) -> dict[str, Any]:
    """Last pipeline run time for UI (status file, log header, or file mtime)."""
    status = read_pipeline_status(site_id)
    ok: bool | None = status.get("ok") if status else None
    at: datetime | None = None

    status_path = pipeline_status_path(site_id)
    if status:
        at = _parse_run_datetime(str(status.get("finished_at") or status.get("last_run_at") or ""))
        if at is None and status_path.is_file():
            at = datetime.fromtimestamp(status_path.stat().st_mtime)

    log_path = pipeline_log_path(site_id)
    if at is None and log_path.is_file():
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        matches = _PIPELINE_HEADER_RE.findall(text)
        for sid, ts in reversed(matches):
            if sid == site_id:
                at = _parse_run_datetime(ts)
                break
        if at is None:
            at = datetime.fromtimestamp(log_path.stat().st_mtime)

    display = at.strftime("%Y-%m-%d %H:%M") if at else None
    return {
        "last_run_at": at.isoformat(sep=" ") if at else None,
        "last_run_display": display,
        "last_run_ok": ok,
    }
_STEP_FAILURE_MARKERS = (
    "❌ CSV file not found:",
    "❌ CSV not found:",
    "❌ CSV 없음:",
    "❌ CSV 파일을 찾을 수 없습니다:",
    "Traceback (most recent call last):",
)


def _step_output_indicates_failure(text: str) -> bool:
    if not text:
        return False
    return any(marker in text for marker in _STEP_FAILURE_MARKERS)


def _run_step(
    repo: Path,
    logf,
    *,
    label: str,
    argv: list[str],
    env: dict[str, str],
    timeout: int = 3600,
) -> dict[str, Any]:
    logf.write(f"\n{'=' * 50}\n[{datetime.now():%F %T}] {label}\n")
    logf.write(" ".join(argv) + "\n")
    logf.flush()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        logf.write(f"TIMEOUT after {timeout}s\n")
        if e.stdout:
            logf.write(e.stdout)
        if e.stderr:
            logf.write(e.stderr)
        return {"ok": False, "label": label, "error": "timeout", "exit_code": -1}

    if proc.stdout:
        logf.write(proc.stdout)
    if proc.stderr:
        logf.write(proc.stderr)
    logf.flush()
    combined_out = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0 and not _step_output_indicates_failure(combined_out)
    err_tail = ""
    if not ok:
        lines = [ln for ln in combined_out.splitlines() if ln.strip()]
        err_tail = "\n".join(lines[-12:])
    result: dict[str, Any] = {
        "ok": ok,
        "label": label,
        "exit_code": proc.returncode,
        "error": err_tail if not ok else "",
        "output": combined_out[-8000:],
    }
    gen_result = last_generation_result(combined_out)
    if gen_result:
        result["generation_result"] = gen_result
    return result
def execute_pipeline(
    site_id: str,
    repo: Path,
    *,
    ensure_fn,
    steps: list[tuple[str, str, list[str], int]],
    env: dict[str, str],
    optional_steps: list[tuple[str, str, list[str], int]] | None = None,
    extra_steps: list[tuple[str, str, list[str], int]] | None = None,
    post_steps: list[tuple[str, Callable[[Path, Any], dict[str, Any]]]] | None = None,
) -> dict[str, Any]:
    log_path = pipeline_log_path(site_id)
    steps_out: list[dict[str, Any]] = []
    optional_steps = optional_steps or []
    extra_steps = extra_steps or []
    post_steps = post_steps or []

    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n\n{'#' * 60}\n# {site_id} pipeline {datetime.now():%F %T}\n")
        if site_id == "krcampus":
            logf.write(
                "run limits: "
                f"guides={env.get('GUIDE_LIMIT', '?')} "
                f"schools={env.get('SCHOOL_LIMIT', '?')} "
                f"universities={env.get('UNIVERSITY_LIMIT', '?')}\n"
            )
        if ensure_fn:
            seed_info = call_ensure_csv(ensure_fn, repo, logf, env)
            steps_out.append({"step": "ensure_csv", "ok": True, **seed_info})
            from topic_queue_env import queue_env_for_site

            env.update(queue_env_for_site(site_id, sync=False))

        for step_id, label, argv, timeout in extra_steps:
            r = _run_step(repo, logf, label=label, argv=argv, env=env, timeout=timeout)
            steps_out.append({"step": step_id, **r})
            if not r["ok"]:
                return fail_pipeline(site_id, steps_out, r, log_path)

        for step_id, label, argv, timeout in steps:
            r = _run_step(repo, logf, label=label, argv=argv, env=env, timeout=timeout)
            steps_out.append({"step": step_id, **r})
            if r.get("ok"):
                try:
                    from ai_spend import record_pipeline_step

                    record_pipeline_step(site_id, step_id, env, r.get("output") or "")
                except Exception:
                    pass
            if not r["ok"]:
                return fail_pipeline(site_id, steps_out, r, log_path)

        for step_id, label, argv, timeout in optional_steps:
            r = _run_step(repo, logf, label=label, argv=argv, env=env, timeout=timeout)
            steps_out.append({"step": step_id, **r, "optional": True})
            if not r["ok"]:
                logf.write(f"⚠ optional step failed (continuing): {label}\n")

        for step_id, fn in post_steps:
            r = fn(repo, logf)
            steps_out.append({"step": step_id, **r, "optional": True})
            if not r.get("ok"):
                logf.write(f"⚠ post step failed (continuing): {r.get('label') or step_id}\n")

        if banks_for_site(site_id):
            try:
                from topic_bank_pipeline import refresh_topic_state
                from topic_bank import sync_queues

                refresh_topic_state(site_id, repo)
                sync_queues(site_id, logf)
            except Exception as exc:
                logf.write(f"⚠ queue finalize failed: {exc}\n")

        logf.write(f"\n[{datetime.now():%F %T}] Pipeline OK\n")

        warn = _content_generation_warning(steps_out)
        if warn:
            logf.write(f"⚠ content: {warn}\n")

    payload: dict[str, Any] = {
        "ok": True,
        "site_id": site_id,
        "steps": steps_out,
        "log_path": str(log_path),
        "message": f"{site_id} 콘텐츠 파이프라인 완료",
    }
    if warn:
        payload["content_warning"] = warn
        payload["message"] = f"{site_id} 완료 — {warn}"
    return _stamp_pipeline_result(payload)


def _content_generation_warning(steps: list[dict[str, Any]]) -> str | None:
    """True when generate steps ran OK but produced zero new content."""
    gen_ids = {
        "guides",
        "universities",
        "items",
        "guides_md",
        "py",
        "cloud",
        "korean",
        "schools",
    }
    structured_steps = [s for s in steps if s.get("step") in gen_ids and s.get("ok")]
    if structured_steps and all(s.get("generation_result") for s in structured_steps):
        saw_zero = False
        saw_gen = False
        for step in structured_steps:
            gr = step.get("generation_result") or {}
            generated = int(gr.get("generated") or 0)
            topics = int(gr.get("topics") or 0)
            failed = int(gr.get("failed") or 0)
            if generated > 0:
                saw_gen = True
            elif topics == 0 and failed == 0:
                saw_zero = True
            elif topics > 0 and generated == 0:
                return f"{step.get('label') or step.get('step')}: 생성 시도 {topics}건, 성공 0건"
        if saw_zero and not saw_gen:
            return "이번 실행에서 신규 콘텐츠 0건 (백로그 없음 또는 이미 완료)"
        return None

    for step in steps:
        if step.get("step") != "items" or not step.get("ok"):
            continue
        gr = step.get("generation_result")
        if gr:
            if int(gr.get("generated") or 0) == 0 and int(gr.get("topics") or 0) == 0:
                return "아이템 신규 0건 (큐에 이미 완료된 항목이 남았는지 확인)"
            continue
        text = (step.get("output") or "").lower()
        if text and any(p in text for p in _CONTENT_ZERO_PATTERNS) and not any(
            re.search(p, text) for p in _CONTENT_GEN_PATTERNS
        ):
            return "아이템 신규 0건 (큐에 이미 완료된 항목이 남았는지 확인)"

    gen_steps = [s for s in steps if s.get("step") in gen_ids and s.get("ok")]
    if not gen_steps:
        return None
    saw_zero = False
    saw_gen = False
    for step in gen_steps:
        gr = step.get("generation_result")
        if gr:
            if int(gr.get("generated") or 0) > 0:
                saw_gen = True
            elif int(gr.get("topics") or 0) == 0:
                saw_zero = True
            continue
        text = (step.get("output") or "").lower()
        if not text:
            continue
        if any(p in text for p in _CONTENT_ZERO_PATTERNS):
            saw_zero = True
        if any(re.search(p, text) for p in _CONTENT_GEN_PATTERNS):
            saw_gen = True
    if saw_zero and not saw_gen:
        return "이번 실행에서 신규 콘텐츠 0건 (백로그 없음 또는 이미 완료)"
    return None

def _gcs_images_dir(repo: Path, site_id: str) -> Path:
    rel = SITE_GCS_IMAGE_DIRS.get(site_id, "app/static/images")
    return repo / rel


def starful_gcs_normalize(repo: Path, logf) -> dict[str, Any]:
    """GCS rsync 전 legacy hyphen blob 정리."""
    script = repo / "scripts/normalize_image_names.py"
    logf.write(f"\n[{datetime.now():%F %T}] starful GCS image name normalize\n")
    if not script.is_file():
        return {"ok": False, "label": "GCS normalize", "error": "normalize_image_names.py missing"}
    try:
        proc = subprocess.run(
            ["python3", str(script), "--gcs"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "label": "GCS normalize", "error": "timeout"}
    if proc.stdout:
        logf.write(proc.stdout)
    if proc.stderr:
        logf.write(proc.stderr)
    logf.flush()
    ok = proc.returncode == 0
    return {
        "ok": ok,
        "label": "GCS normalize",
        "exit_code": proc.returncode,
        "error": "" if ok else (proc.stderr or proc.stdout or "normalize failed")[-500:],
    }


def gcs_image_sync(repo: Path, logf, site_id: str) -> dict[str, Any]:
    """Upload site image dir to GCS; never overwrite newer GCS blobs (admin uploads)."""
    images_dir = _gcs_images_dir(repo, site_id)
    env_key = f"{site_id.upper().replace('.', '_')}_GCS_BUCKET"
    bucket = os.environ.get(env_key) or SITE_GCS_BUCKETS.get(site_id, "")
    logf.write(f"\n{'=' * 50}\n[{datetime.now():%F %T}] GCS image sync\n")
    logf.flush()
    if not bucket:
        return {"ok": False, "label": "GCS images", "error": f"no GCS bucket for {site_id}"}
    if not images_dir.is_dir():
        return {"ok": False, "label": "GCS images", "error": "images dir missing"}

    rsync_flags = ["--recursive", "--checksums-only", "--skip-if-dest-has-newer-mtime"]

    # starful: pull newer GCS → local first (admin upload → repo stays current)
    if site_id == "starful.biz":
        logf.write(f"gcloud storage rsync {bucket} {images_dir} (pull newer)\n")
        logf.flush()
        try:
            pull = subprocess.run(
                ["gcloud", "storage", "rsync", bucket, str(images_dir), *rsync_flags],
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            if pull.stdout:
                logf.write(pull.stdout)
            if pull.stderr:
                logf.write(pull.stderr)
        except subprocess.TimeoutExpired:
            return {"ok": False, "label": "GCS images", "error": "pull timeout"}

    logf.write(f"gcloud storage rsync {images_dir} {bucket} (push, skip newer dest)\n")
    logf.flush()
    try:
        proc = subprocess.run(
            ["gcloud", "storage", "rsync", str(images_dir), bucket, *rsync_flags],
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "label": "GCS images", "error": "timeout"}
    if proc.stdout:
        logf.write(proc.stdout)
    if proc.stderr:
        logf.write(proc.stderr)
    logf.flush()
    ok = proc.returncode == 0
    return {
        "ok": ok,
        "label": "GCS images",
        "exit_code": proc.returncode,
        "error": "" if ok else (proc.stderr or proc.stdout or "gcloud rsync failed")[-500:],
    }


def pipeline_post_steps(site_id: str) -> list[tuple[str, Callable[[Path, Any], dict[str, Any]]]]:
    if site_id in SITE_GCS_BUCKETS:
        return [("gcs_images", lambda repo, logf, sid=site_id: gcs_image_sync(repo, logf, sid))]
    return []


def run_ok_site_pipeline(
    site_id: str,
    repo: Path,
    env: dict[str, str],
    *,
    ensure_fn,
    steps: list[tuple[str, str, list[str], int]],
    extra_steps: list[tuple[str, str, list[str], int]] | None = None,
) -> dict[str, Any]:
    return execute_pipeline(
        site_id,
        repo,
        ensure_fn=ensure_fn,
        steps=steps,
        env=env,
        extra_steps=extra_steps or [],
        post_steps=pipeline_post_steps(site_id),
    )


def fail_pipeline(site_id: str, steps: list, last: dict, log_path: Path) -> dict[str, Any]:
    return _stamp_pipeline_result(
        {
            "ok": False,
            "site_id": site_id,
            "steps": steps,
            "failed_step": last.get("label"),
            "error": last.get("error") or f"exit {last.get('exit_code')}",
            "log_path": str(log_path),
        }
    )


def tail_pipeline_log(site_id: str, *, max_chars: int = 16000) -> str:
    path = pipeline_log_path(site_id)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-max_chars:]
def call_ensure_csv(ensure_fn, repo: Path, logf, env: dict[str, str]) -> dict[str, Any]:
    try:
        return ensure_fn(repo, logf, env=env)
    except TypeError:
        return ensure_fn(repo, logf)
