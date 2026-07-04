"""Backfill ai_spend ledger from okadmin pipeline logs."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_spend import apply_backfill_day, estimate_pipeline_step

OKADMIN_ROOT = Path(__file__).resolve().parent
LOG_DIR = OKADMIN_ROOT / "data" / "content_logs"

_STEP_FAILURE_MARKERS = (
    "Traceback (most recent call last):",
    "❌ CSV file not found:",
)

_LABEL_TO_STEP: dict[str, str] = {
    "ai guides": "guides",
    "language schools": "schools",
    "universities": "universities",
    "japanese native": "japanese",
    "featured articles": "featured",
    "korean content": "korean",
    "guide_generator": "guides",
    "insight_generator": "items",
    "fetch_images": "images",
    "generate_images": "images",
    "generate_md_guides": "guides",
    "ramen_generator": "items",
    "onsen_generator": "items",
    "course_generator": "items",
    "unified_poster py": "py",
    "unified_poster cloud": "cloud",
}

_RUN_HEADER_RE = re.compile(
    r"^# (?P<site>.+?) pipeline (?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*$",
    re.MULTILINE,
)
_RUN_LIMITS_RE = re.compile(
    r"run limits: guides=(\d+) schools=(\d+) universities=(\d+)"
)
_STEP_HEADER_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (.+)$")


@dataclass
class DayTotals:
    gemini_yen: int = 0
    imagen_yen: int = 0
    imagen_images: int = 0
    gemini_events: int = 0
    gemini_by_site: dict[str, int] = field(default_factory=dict)
    imagen_by_site: dict[str, int] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)


def _default_env() -> dict[str, str]:
    return {
        "GUIDE_LIMIT": "3",
        "SCHOOL_LIMIT": "3",
        "UNIVERSITY_LIMIT": "3",
        "CONTENT_LIMIT": "6",
        "KOREAN_LIMIT": "6",
        "HATENA_MAX_POSTS": "6",
    }


def _step_failed(output: str) -> bool:
    text = output or ""
    if any(m in text for m in _STEP_FAILURE_MARKERS):
        return True
    if re.search(r"❌\s*\d+.*failed", text, re.I):
        return True
    return False


def _label_to_step(label: str) -> str | None:
    key = (label or "").strip().lower()
    return _LABEL_TO_STEP.get(key)


def _parse_run_limits(chunk: str, env: dict[str, str]) -> dict[str, str]:
    out = dict(env)
    m = _RUN_LIMITS_RE.search(chunk)
    if m:
        out["GUIDE_LIMIT"], out["SCHOOL_LIMIT"], out["UNIVERSITY_LIMIT"] = m.group(1), m.group(2), m.group(3)
    return out


def _parse_tqdm_done(output: str) -> int | None:
    matches = re.findall(r"\|\s*(\d+)/(\d+)\s*[\[\|]", output or "")
    if matches:
        return int(matches[-1][0])
    return None


def _adjust_env_for_output(site_id: str, step_id: str, env: dict[str, str], output: str) -> dict[str, str]:
    out = dict(env)
    text = output or ""
    low = text.lower()
    done_n = _parse_tqdm_done(text)
    if "no pending" in low:
        if step_id == "guides":
            out["GUIDE_LIMIT"] = "0"
        elif step_id == "schools":
            out["SCHOOL_LIMIT"] = "0"
        elif step_id == "universities":
            out["UNIVERSITY_LIMIT"] = "0"
        elif step_id == "japanese":
            out["GUIDE_LIMIT"] = "0"
            out["SCHOOL_LIMIT"] = "0"
            out["UNIVERSITY_LIMIT"] = "0"
    elif done_n is not None:
        if step_id == "guides":
            out["GUIDE_LIMIT"] = str(done_n)
        elif step_id == "schools":
            out["SCHOOL_LIMIT"] = str(done_n)
        elif step_id == "universities":
            out["UNIVERSITY_LIMIT"] = str(done_n)
    m = re.search(r"limits g=(\d+) s=(\d+) u=(\d+)", text)
    if m and step_id == "japanese":
        out["GUIDE_LIMIT"], out["SCHOOL_LIMIT"], out["UNIVERSITY_LIMIT"] = m.group(1), m.group(2), m.group(3)
    m = re.search(r"in queue:\s*(\d+)\s*\(limit\s*(\d+)\)", text, re.I)
    if m and step_id == "universities":
        out["UNIVERSITY_LIMIT"] = m.group(2)
    m = re.search(r"Total Universities to process:\s*(\d+)", text, re.I)
    if m and step_id == "universities" and int(m.group(1)) == 0:
        out["UNIVERSITY_LIMIT"] = "0"
    m = re.search(r"ターゲット:\s*(\d+)件", text)
    if m and site_id == "starful.biz" and step_id == "guides":
        out["CONTENT_LIMIT"] = m.group(1)
    return out


def _parse_run_steps(chunk: str) -> list[dict[str, str]]:
    parts = re.split(r"\n={50}\n", chunk)
    steps: list[dict[str, str]] = []
    for part in parts[1:]:
        lines = part.splitlines()
        if not lines:
            continue
        hdr = _STEP_HEADER_RE.match(lines[0].strip())
        if not hdr:
            continue
        label = hdr.group(2).strip()
        body_lines = lines[1:]
        if body_lines and not body_lines[0].startswith("["):
            body_lines = body_lines[1:]  # skip argv line
        output = "\n".join(body_lines)
        steps.append({"label": label, "output": output})
    return steps


def _accumulate_step(
    totals: DayTotals,
    *,
    site_id: str,
    step_id: str,
    env: dict[str, str],
    output: str,
) -> dict[str, int]:
    adj_env = _adjust_env_for_output(site_id, step_id, env, output)
    g, im_y, im_n = estimate_pipeline_step(site_id, step_id, adj_env, output)
    if g:
        totals.gemini_yen += g
        totals.gemini_events += 1
        totals.gemini_by_site[site_id] = totals.gemini_by_site.get(site_id, 0) + g
    if im_y or im_n:
        totals.imagen_yen += im_y
        totals.imagen_images += im_n
        totals.imagen_by_site[site_id] = totals.imagen_by_site.get(site_id, 0) + im_y
    return {"gemini_yen": g, "imagen_yen": im_y, "imagen_images": im_n}


def compute_day_totals(day: str) -> DayTotals:
    totals = DayTotals()
    if not LOG_DIR.is_dir():
        return totals
    for log_path in sorted(LOG_DIR.glob("*_pipeline.log")):
        text = log_path.read_text(encoding="utf-8", errors="replace")
        site_id = log_path.name.replace("_pipeline.log", "")
        headers = list(_RUN_HEADER_RE.finditer(text))
        for i, m in enumerate(headers):
            ts = m.group("ts")
            if not ts.startswith(day):
                continue
            start = m.start()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
            chunk = text[start:end]
            env = _parse_run_limits(chunk, _default_env())
            run_steps: list[dict[str, Any]] = []
            for step in _parse_run_steps(chunk):
                label = step["label"]
                output = step["output"]
                step_id = _label_to_step(label)
                if not step_id:
                    continue
                failed = _step_failed(output)
                spend = _accumulate_step(
                    totals,
                    site_id=site_id,
                    step_id=step_id,
                    env=env,
                    output=output,
                )
                run_steps.append(
                    {"label": label, "step_id": step_id, "ok": not failed, "spend": spend}
                )
                if failed:
                    break
            totals.runs.append(
                {
                    "site_id": site_id,
                    "started_at": ts,
                    "pipeline_ok": "Pipeline OK" in chunk,
                    "steps": run_steps,
                }
            )
    return totals


def backfill_day(day: str, *, dry_run: bool = False) -> dict[str, Any]:
    totals = compute_day_totals(day)
    result: dict[str, Any] = {
        "day": day,
        "dry_run": dry_run,
        "gemini_yen": totals.gemini_yen,
        "imagen_yen": totals.imagen_yen,
        "imagen_images": totals.imagen_images,
        "gemini_events": totals.gemini_events,
        "gemini_by_site": totals.gemini_by_site,
        "imagen_by_site": totals.imagen_by_site,
        "runs": totals.runs,
    }
    if not dry_run:
        result["summary"] = apply_backfill_day(
            day,
            gemini_yen=totals.gemini_yen,
            imagen_yen=totals.imagen_yen,
            imagen_images=totals.imagen_images,
            gemini_events=totals.gemini_events,
            gemini_by_site=totals.gemini_by_site,
            imagen_by_site=totals.imagen_by_site,
        )
    return result
