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


def write_ship_deploy_log(
    site_id: str,
    *,
    via: str,
    at: datetime | None = None,
    detail: str = "",
) -> Path | None:
    """Write a lightweight deploy-*.log so hub deploy row reflects Paperclip/site deploys."""
    sid = (site_id or "").strip()
    if not sid:
        return None
    try:
        from git_ops import DEPLOY_LOG_DIR
    except Exception:
        return None
    when = (at or datetime.now()).replace(microsecond=0)
    if when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    DEPLOY_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = when.strftime("%Y%m%d-%H%M%S")
    path = DEPLOY_LOG_DIR / f"deploy-{sid}-{ts}.log"
    lines = [
        f"# {sid} ship {when.isoformat(sep=' ')}",
        f"via: {via}",
        detail.strip(),
        "DONE",
        f"완료 ({via})",
        "",
    ]
    path.write_text("\n".join(x for x in lines if x is not None), encoding="utf-8")
    return path


def mark_content_cycle_shipped(
    site_id: str,
    *,
    via: str,
    at: datetime | None = None,
    record_deploy_log: bool = False,
    detail: str = "",
) -> dict[str, Any]:
    """Bump content 7-day cycle clock after successful git push / deploy.

    No-ops when an equal-or-newer finished_at is already recorded.
    """
    sid = (site_id or "").strip()
    if not sid:
        return {"ok": False, "error": "site_id required"}
    now = (at or datetime.now()).replace(microsecond=0)
    if now.tzinfo is not None:
        now = now.astimezone().replace(tzinfo=None)
    stamp = now.isoformat(sep=" ")
    prev = read_pipeline_status(sid) or {}
    prev_at = _parse_run_datetime(str(prev.get("finished_at") or prev.get("last_run_at") or ""))
    skipped = prev_at is not None and prev_at >= now
    log_path: Path | None = None
    if record_deploy_log:
        log_path = write_ship_deploy_log(sid, via=via, at=now, detail=detail)
    if skipped:
        return {
            "ok": True,
            "skipped": True,
            "site_id": sid,
            "finished_at": prev.get("finished_at") or prev.get("last_run_at"),
            "via": prev.get("content_cycle_via") or via,
            "deploy_log": str(log_path) if log_path else None,
        }
    data = {
        **prev,
        "ok": True,
        "finished_at": stamp,
        "content_cycle_via": via,
        "message": f"콘텐츠 주기 갱신 ({via})",
    }
    # Drop transient run flags so hub treats this as a completed ship.
    data.pop("running", None)
    data.pop("phase", None)
    write_pipeline_status(sid, data)
    return {
        "ok": True,
        "site_id": sid,
        "finished_at": stamp,
        "via": via,
        "deploy_log": str(log_path) if log_path else None,
    }


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

# Content gens may soft-fail (bad queue row / quality reject). Continue so guides etc. still run.
# Image steps also soft-fail: missing/failed Imagen → default_gcs post-step fills placeholders.
_SOFT_CONTINUE_STEPS = frozenset(
    {
        "items",
        "guides",
        "python",
        "cloud",
        "terraform",
        "schools",
        "universities",
        "images",
        "images_places",
        "images_opt",
        "img_names",
        "nearby",
        "stay_images",
    }
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
    """Run a pipeline subprocess, streaming stdout/stderr into the log in real time."""
    import select
    import time as _time

    logf.write(f"\n{'=' * 50}\n[{datetime.now():%F %T}] {label}\n")
    logf.write(" ".join(argv) + "\n")
    logf.flush()

    run_env = dict(env)
    run_env["PYTHONUNBUFFERED"] = "1"
    run_env.setdefault("PYTHONIOENCODING", "utf-8")

    chunks: list[str] = []
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(repo),
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as e:
        logf.write(f"spawn failed: {e}\n")
        logf.flush()
        return {"ok": False, "label": label, "error": str(e), "exit_code": -1}

    assert proc.stdout is not None
    deadline = _time.monotonic() + max(1, timeout)
    timed_out = False
    try:
        while True:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                timed_out = True
                proc.kill()
                break
            ready, _, _ = select.select([proc.stdout], [], [], min(1.0, remaining))
            if ready:
                line = proc.stdout.readline()
                if line:
                    chunks.append(line)
                    logf.write(line)
                    logf.flush()
                    continue
            if proc.poll() is not None:
                # Drain any remaining buffered lines.
                for line in proc.stdout:
                    chunks.append(line)
                    logf.write(line)
                break
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except Exception as e:
        proc.kill()
        logf.write(f"step runner error: {e}\n")
        logf.flush()
        return {"ok": False, "label": label, "error": str(e), "exit_code": -1}

    if timed_out:
        logf.write(f"TIMEOUT after {timeout}s\n")
        logf.flush()
        combined_out = "".join(chunks)
        return {
            "ok": False,
            "label": label,
            "error": "timeout",
            "exit_code": -1,
            "output": combined_out[-8000:],
        }

    combined_out = "".join(chunks)
    logf.flush()
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
        logf.write(
            "run limits: "
            f"content={env.get('CONTENT_LIMIT', '?')} "
            f"guides={env.get('GUIDE_LIMIT', '?')} "
            f"schools={env.get('SCHOOL_LIMIT', '-')} "
            f"universities={env.get('UNIVERSITY_LIMIT', '-')} "
            f"python={env.get('PYTHON_LIMIT', '-')} "
            f"cloud={env.get('CLOUD_LIMIT', '-')} "
            f"terraform={env.get('TERRAFORM_LIMIT', '-')} "
            f"images={env.get('CONTENT_PIPELINE_WITH_IMAGES', '0')}\n"
        )
        soft_failures: list[str] = []
        if ensure_fn:
            logf.write(f"[ensure] start\n")
            logf.flush()
            seed_info = call_ensure_csv(ensure_fn, repo, logf, env)
            steps_out.append({"step": "ensure_csv", "ok": True, **seed_info})
            logf.write(f"[ensure] ok\n")
            logf.flush()
            from topic_queue_env import queue_env_for_site

            env.update(queue_env_for_site(site_id, sync=False))

        for step_id, label, argv, timeout in extra_steps:
            logf.write(f"[{step_id}] start · {label}\n")
            logf.flush()
            r = _run_step(repo, logf, label=label, argv=argv, env=env, timeout=timeout)
            steps_out.append({"step": step_id, **r})
            logf.write(f"[{step_id}] {'ok' if r.get('ok') else 'FAIL'}\n")
            logf.flush()
            if not r["ok"]:
                return fail_pipeline(site_id, steps_out, r, log_path)

        for step_id, label, argv, timeout in steps:
            logf.write(f"[{step_id}] start · {label}\n")
            logf.flush()
            r = _run_step(repo, logf, label=label, argv=argv, env=env, timeout=timeout)
            steps_out.append({"step": step_id, **r})
            logf.write(f"[{step_id}] {'ok' if r.get('ok') else 'FAIL'}\n")
            logf.flush()
            if not r["ok"]:
                if step_id in _SOFT_CONTINUE_STEPS:
                    soft_failures.append(label)
                    logf.write(f"⚠ continuing after content step failure: {label}\n")
                    continue
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
        if soft_failures:
            soft_msg = "일부 생성 단계 실패(이후 단계 계속): " + ", ".join(soft_failures)
            warn = f"{warn}; {soft_msg}" if warn else soft_msg
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
    if soft_failures:
        payload["soft_failures"] = soft_failures
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


_IMAGE_STEP_IDS = frozenset(
    {
        "images",
        "images_places",
        "images_opt",
        "img_names",
        "nearby",
        "stay_images",
    }
)


def pipeline_images_enabled(env: dict[str, str] | None) -> bool:
    raw = str((env or {}).get("CONTENT_PIPELINE_WITH_IMAGES", "0")).strip().lower()
    return raw in ("1", "true", "yes")


def filter_pipeline_steps(
    steps: list[Step],
    env: dict[str, str] | None,
) -> list[Step]:
    """Drop or keep image steps based on CONTENT_PIPELINE_WITH_IMAGES / IMAGES_ONLY."""
    images_only = str((env or {}).get("CONTENT_PIPELINE_IMAGES_ONLY", "0")).strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if images_only:
        only = [s for s in steps if s[0] in _IMAGE_STEP_IDS]
        return only
    if pipeline_images_enabled(env):
        return steps
    return [s for s in steps if s[0] not in _IMAGE_STEP_IDS]


def pipeline_post_steps(
    site_id: str,
    env: dict[str, str] | None = None,
) -> list[tuple[str, Callable[[Path, Any], dict[str, Any]]]]:
    """Post content: sync generated images, then fill any GCS gaps with defaults."""
    out: list[tuple[str, Callable[[Path, Any], dict[str, Any]]]] = []
    if pipeline_images_enabled(env) and site_id in SITE_GCS_BUCKETS:
        out.append(
            ("gcs_images", lambda repo, logf, sid=site_id: gcs_image_sync(repo, logf, sid))
        )

    if site_id in SITE_GCS_BUCKETS:
        from image_site_content import upload_default_gcs_placeholders
        from image_site_meta import SITE_IMAGE_META
        from config import image_site_key

        if image_site_key(site_id) in SITE_IMAGE_META:
            # Always run after image steps (or alone when images=0): covers failures / missing.
            out.append(
                (
                    "default_gcs",
                    lambda repo, logf, sid=site_id: upload_default_gcs_placeholders(sid, repo, logf),
                )
            )
    return out


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
        steps=filter_pipeline_steps(steps, env),
        env=env,
        extra_steps=filter_pipeline_steps(extra_steps or [], env),
        post_steps=pipeline_post_steps(site_id, env),
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
