"""One-click content pipelines (okcafejp: seed CSV → generate → build)."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from config import get_service, repo_path, work_root_available

MIN_ITEM_ROWS = 8
MIN_GUIDE_ROWS = 3

# Tokyo cafe seeds when items.csv is nearly empty
DEFAULT_ITEM_SEEDS: list[dict[str, str]] = [
    {
        "Name": "Marunouchi Blend Lab",
        "Lat": "35.6812",
        "Lng": "139.7671",
        "Address": "Tokyo, Marunouchi",
        "Features": "Specialty coffee | Wi-Fi",
        "Agoda": "",
    },
    {
        "Name": "Shinjuku South Latte Lab",
        "Lat": "35.6895",
        "Lng": "139.7005",
        "Address": "Tokyo, Shinjuku",
        "Features": "Third wave espresso | Laptop friendly",
        "Agoda": "",
    },
    {
        "Name": "Shibuya Morning Club",
        "Lat": "35.6581",
        "Lng": "139.7017",
        "Address": "Tokyo, Shibuya",
        "Features": "Brunch set | Tourist friendly",
        "Agoda": "",
    },
    {
        "Name": "Ginza Patisserie Bloom",
        "Lat": "35.6718",
        "Lng": "139.7645",
        "Address": "Tokyo, Ginza",
        "Features": "Dessert pairing | English menu",
        "Agoda": "",
    },
    {
        "Name": "Ueno Parkside Drip",
        "Lat": "35.7089",
        "Lng": "139.7310",
        "Address": "Tokyo, Ueno",
        "Features": "Pour-over bar | Calm vibe",
        "Agoda": "",
    },
    {
        "Name": "Ebisu Workbench Cafe",
        "Lat": "35.6467",
        "Lng": "139.7100",
        "Address": "Tokyo, Ebisu",
        "Features": "Work-friendly | Wi-Fi",
        "Agoda": "",
    },
    {
        "Name": "Ikebukuro Sun City Espresso",
        "Lat": "35.7289",
        "Lng": "139.7101",
        "Address": "Tokyo, Ikebukuro",
        "Features": "House roast | Easy access",
        "Agoda": "",
    },
    {
        "Name": "Roppongi Origin Lab",
        "Lat": "35.6655",
        "Lng": "139.7293",
        "Address": "Tokyo, Roppongi",
        "Features": "Single origin | Late hours",
        "Agoda": "",
    },
]

DEFAULT_GUIDE_SEEDS: list[dict[str, str]] = [
    {
        "id": "guide_seed_001",
        "topic_en": "Best Specialty Cafes in Tokyo (2026)",
        "topic_ko": "2026 도쿄 스페셜티 카페 가이드",
        "keywords": "tokyo specialty cafe",
    },
    {
        "id": "guide_seed_002",
        "topic_en": "Quiet Work-Friendly Cafes in Tokyo",
        "topic_ko": "도쿄 노트북 카페",
        "keywords": "tokyo work cafe wifi",
    },
    {
        "id": "guide_seed_003",
        "topic_en": "Best Dessert Cafes in Tokyo for Travelers",
        "topic_ko": "도쿄 디저트 카페",
        "keywords": "tokyo dessert cafe",
    },
]

ITEM_HEADERS = ["Name", "Lat", "Lng", "Address", "Features", "Agoda"]
GUIDE_HEADERS = ["id", "topic_en", "topic_ko", "keywords"]


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


def _count_csv_rows(path: Path, *, required_col: str | None = None) -> int:
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return 0
    reader = csv.DictReader(io.StringIO(text))
    n = 0
    for row in reader:
        if required_col:
            if not (row.get(required_col) or "").strip():
                continue
        n += 1
    return n


def _append_csv_rows(path: Path, headers: list[str], rows: list[dict[str, str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, str]] = []
    if path.is_file() and path.read_text(encoding="utf-8-sig").strip():
        existing = []
        with path.open(encoding="utf-8-sig") as f:
            existing = list(csv.DictReader(f))
    names = {(r.get(headers[0]) or "").strip().lower() for r in existing}
    added = 0
    for row in rows:
        key = (row.get(headers[0]) or "").strip().lower()
        if key and key in names:
            continue
        existing.append({h: row.get(h, "") for h in headers})
        names.add(key)
        added += 1
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(existing)
    path.write_text(buf.getvalue(), encoding="utf-8-sig")
    return added


def ensure_okcafejp_csv(repo: Path, logf) -> dict[str, Any]:
    """Add CSV rows when items/guides are insufficient."""
    items_path = repo / "script/csv/items.csv"
    guides_path = repo / "script/csv/guides.csv"
    out: dict[str, Any] = {"seeded_items": 0, "seeded_guides": 0, "messages": []}

    n_items = _count_csv_rows(items_path, required_col="Name")
    if n_items < MIN_ITEM_ROWS:
        added = _append_csv_rows(items_path, ITEM_HEADERS, DEFAULT_ITEM_SEEDS)
        out["seeded_items"] = added
        msg = f"items.csv: {n_items}행 → 시드 {added}행 추가 (최소 {MIN_ITEM_ROWS}행 목표)"
        out["messages"].append(msg)
        logf.write(msg + "\n")
    else:
        logf.write(f"items.csv: {n_items}행 (시드 생략)\n")

    n_guides = _count_csv_rows(guides_path, required_col="topic_en")
    if n_guides < MIN_GUIDE_ROWS:
        added = _append_csv_rows(guides_path, GUIDE_HEADERS, DEFAULT_GUIDE_SEEDS)
        out["seeded_guides"] = added
        msg = f"guides.csv: {n_guides}행 → 시드 {added}행 추가"
        out["messages"].append(msg)
        logf.write(msg + "\n")
    else:
        logf.write(f"guides.csv: {n_guides}행 (시드 생략)\n")

    out["item_rows"] = _count_csv_rows(items_path, required_col="Name")
    out["guide_rows"] = _count_csv_rows(guides_path, required_col="topic_en")
    return out


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
    ok = proc.returncode == 0
    err_tail = ""
    if not ok:
        combined = (proc.stderr or "") + "\n" + (proc.stdout or "")
        lines = [ln for ln in combined.splitlines() if ln.strip()]
        err_tail = "\n".join(lines[-12:])
    return {
        "ok": ok,
        "label": label,
        "exit_code": proc.returncode,
        "error": err_tail if not ok else "",
    }


def _merge_pipeline_env(repo: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in ("CONTENT_LIMIT", "GUIDE_LIMIT", "GEMINI_API_KEY", "GEMINI_MODEL", "GOOGLE_PLACES_API_KEY"):
        if key not in env:
            if key == "CONTENT_LIMIT":
                env[key] = "10"
            elif key == "GUIDE_LIMIT":
                env[key] = "3"
    repo_env = repo / ".env"
    if repo_env.is_file():
        try:
            from dotenv import dotenv_values

            for k, v in (dotenv_values(repo_env) or {}).items():
                if v and k not in env:
                    env[k] = str(v)
        except ImportError:
            pass
    okadmin_env = Path(__file__).resolve().parent / ".env"
    if okadmin_env.is_file():
        try:
            from dotenv import dotenv_values

            for k, v in (dotenv_values(okadmin_env) or {}).items():
                if v and k in (
                    "GEMINI_API_KEY",
                    "GEMINI_MODEL",
                    "GOOGLE_PLACES_API_KEY",
                    "HATENA_USERNAME",
                    "HATENA_PYTHON_BLOG_ID",
                    "HATENA_PYTHON_API_KEY",
                ) and k not in env:
                    env[k] = str(v)
        except ImportError:
            pass
    return env


def ensure_dual_csv(
    repo: Path,
    logf,
    *,
    items_rel: str,
    guides_rel: str,
    item_headers: list[str],
    guide_headers: list[str],
    item_seeds: list[dict[str, str]],
    guide_seeds: list[dict[str, str]],
    item_col: str = "Name",
    guide_col: str = "topic_en",
) -> dict[str, Any]:
    items_path = repo / items_rel
    guides_path = repo / guides_rel
    out: dict[str, Any] = {"messages": []}
    n_items = _count_csv_rows(items_path, required_col=item_col)
    if n_items < MIN_ITEM_ROWS:
        added = _append_csv_rows(items_path, item_headers, item_seeds)
        out["seeded_items"] = added
        msg = f"{items_rel}: {n_items}행 → +{added}행 시드"
        out["messages"].append(msg)
        logf.write(msg + "\n")
    else:
        logf.write(f"{items_rel}: {n_items}행 OK\n")
    n_guides = _count_csv_rows(guides_path, required_col=guide_col)
    if n_guides < MIN_GUIDE_ROWS:
        added = _append_csv_rows(guides_path, guide_headers, guide_seeds)
        out["seeded_guides"] = added
        msg = f"{guides_rel}: {n_guides}행 → +{added}행 시드"
        out["messages"].append(msg)
        logf.write(msg + "\n")
    else:
        logf.write(f"{guides_rel}: {n_guides}행 OK\n")
    return out


def ensure_starful_csv(repo: Path, logf) -> dict[str, Any]:
    path = repo / "scripts/data/positions.csv"
    headers = ["position_name"]
    seeds = [{"position_name": t} for t in ("AI Engineer", "Product Manager", "Data Analyst", "DevOps Engineer", "UX Designer", "Backend Developer", "Cloud Architect", "Security Engineer", "Technical Writer", "QA Engineer")]
    n = _count_csv_rows(path, required_col="position_name")
    out: dict[str, Any] = {"messages": []}
    if n < 15:
        added = _append_csv_rows(path, headers, seeds)
        out["seeded"] = added
        logf.write(f"positions.csv: {n}행 → +{added}행\n")
    else:
        logf.write(f"positions.csv: {n}행 OK\n")
    return out


def ensure_hatena_csv(repo: Path, logf) -> dict[str, Any]:
    out: dict[str, Any] = {"messages": []}
    py_path = repo / "csv/python.csv"
    if _count_csv_rows(py_path, required_col="lib_name") < 5:
        added = _append_csv_rows(py_path, ["lib_name"], [{"lib_name": x} for x in ("NumPy", "Pandas", "FastAPI", "Pydantic", "httpx")])
        logf.write(f"python.csv: +{added}행\n")
        out["messages"].append(f"python +{added}")
    cloud_path = repo / "csv/cloud.csv"
    if _count_csv_rows(cloud_path, required_col="Topic") < 5:
        topics = [
            {"Topic": "AWS Lambda vs GCP Cloud Functions vs Azure Functions"},
            {"Topic": "Amazon S3 vs Google Cloud Storage vs Azure Blob Storage"},
            {"Topic": "AWS RDS vs Cloud SQL vs Azure Database for PostgreSQL"},
            {"Topic": "Amazon EKS vs GKE vs AKS comparison"},
            {"Topic": "CloudFront vs Cloud CDN vs Azure CDN"},
        ]
        added = _append_csv_rows(cloud_path, ["Topic"], topics)
        logf.write(f"cloud.csv: +{added}행\n")
        out["messages"].append(f"cloud +{added}")
    pos_path = repo / "csv/positions.csv"
    if not pos_path.is_file() or _count_csv_rows(pos_path, required_col="position_name") < 3:
        added = _append_csv_rows(pos_path, ["position_name"], [{"position_name": "Site Reliability Engineer"}, {"position_name": "Platform Engineer"}, {"position_name": "MLOps Engineer"}])
        logf.write(f"positions.csv: +{added}행\n")
    return out


def ensure_jpcampus_csv(repo: Path, logf) -> dict[str, Any]:
    path = repo / "data/guide_topics.csv"
    headers = ["slug", "category", "title", "description", "prompt"]
    seeds = [
        {"slug": "cost-seed", "category": "Budget", "title": "1-Year Study Cost in Japan", "description": "Budget overview", "prompt": "Write a realistic 1-year study cost guide for Tokyo."},
        {"slug": "visa-seed", "category": "Visa", "title": "Student Visa Steps", "description": "Visa guide", "prompt": "Step-by-step student visa guide for Japan."},
        {"slug": "housing-seed", "category": "Housing", "title": "Student Housing Options", "description": "Housing compare", "prompt": "Compare dorm, share house, and apartment for students."},
    ]
    n = _count_csv_rows(path, required_col="slug")
    if n < MIN_GUIDE_ROWS:
        added = _append_csv_rows(path, headers, seeds)
        logf.write(f"guide_topics.csv: {n}행 → +{added}행\n")
        return {"seeded": added}
    logf.write(f"guide_topics.csv: {n}행 OK\n")
    return {}


def _execute_pipeline(
    site_id: str,
    repo: Path,
    *,
    ensure_fn,
    steps: list[tuple[str, str, list[str], int]],
    env: dict[str, str],
    optional_steps: list[tuple[str, str, list[str], int]] | None = None,
    extra_steps: list[tuple[str, str, list[str], int]] | None = None,
) -> dict[str, Any]:
    log_path = pipeline_log_path(site_id)
    steps_out: list[dict[str, Any]] = []
    optional_steps = optional_steps or []
    extra_steps = extra_steps or []

    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n\n{'#' * 60}\n# {site_id} pipeline {datetime.now():%F %T}\n")
        if ensure_fn:
            seed_info = ensure_fn(repo, logf)
            steps_out.append({"step": "ensure_csv", "ok": True, **seed_info})

        for step_id, label, argv, timeout in extra_steps:
            r = _run_step(repo, logf, label=label, argv=argv, env=env, timeout=timeout)
            steps_out.append({"step": step_id, **r})
            if not r["ok"]:
                return _fail(site_id, steps_out, r, log_path)

        for step_id, label, argv, timeout in steps:
            r = _run_step(repo, logf, label=label, argv=argv, env=env, timeout=timeout)
            steps_out.append({"step": step_id, **r})
            if not r["ok"]:
                return _fail(site_id, steps_out, r, log_path)

        for step_id, label, argv, timeout in optional_steps:
            r = _run_step(repo, logf, label=label, argv=argv, env=env, timeout=timeout)
            steps_out.append({"step": step_id, **r, "optional": True})
            if not r["ok"]:
                logf.write(f"⚠ optional step failed (continuing): {label}\n")

        logf.write(f"\n[{datetime.now():%F %T}] Pipeline OK\n")

    return _stamp_pipeline_result(
        {
            "ok": True,
            "site_id": site_id,
            "steps": steps_out,
            "log_path": str(log_path),
            "message": f"{site_id} 콘텐츠 파이프라인 완료",
        }
    )


def _pipeline_for_site(site_id: str, repo: Path) -> dict[str, Any]:
    env = _merge_pipeline_env(repo)
    optional: list[tuple[str, str, list[str], int]] = []
    extra: list[tuple[str, str, list[str], int]] = []
    steps: list[tuple[str, str, list[str], int]] = []

    if site_id == "okcafejp":
        item_limit = env.get("CONTENT_LIMIT", "10")

        def ensure(repo_p: Path, logf):
            return ensure_okcafejp_csv(repo_p, logf)

        if env.get("GOOGLE_PLACES_API_KEY"):
            extra.append(
                (
                    "places",
                    "Places → items.csv",
                    ["python3", "script/fetch_items_from_places.py", "--input", "script/csv/items.csv", "--in-place"],
                    600,
                )
            )
        steps = [
            ("guides", "guide_generator", ["python3", "script/guide_generator.py"], 3600),
            ("items", "item_generator", ["python3", "script/item_generator.py", "--limit", item_limit], 3600),
            ("build", "build_data", ["python3", "script/build_data.py"], 600),
        ]
        return _execute_pipeline(site_id, repo, ensure_fn=ensure, steps=steps, env=env, extra_steps=extra)

    if site_id in ("oksushi",):
        item_limit = env.get("CONTENT_LIMIT", "10")

        def ensure(repo_p: Path, logf):
            return ensure_dual_csv(
                repo_p,
                logf,
                items_rel="script/csv/items.csv",
                guides_rel="script/csv/guides.csv",
                item_headers=ITEM_HEADERS,
                guide_headers=GUIDE_HEADERS,
                item_seeds=DEFAULT_ITEM_SEEDS,
                guide_seeds=DEFAULT_GUIDE_SEEDS,
            )

        steps = [
            ("guides", "guide_generator", ["python3", "script/guide_generator.py"], 3600),
            ("items", "item_generator", ["python3", "script/item_generator.py", "--limit", item_limit], 3600),
            ("build", "build_data", ["python3", "script/build_data.py"], 600),
        ]
        return _execute_pipeline(site_id, repo, ensure_fn=ensure, steps=steps, env=env)

    if site_id == "okramen":
        ramen_seeds = [
            {"Name": "Ichiran Shinjuku", "Lat": "35.6909", "Lng": "139.7018", "Address": "Tokyo, Shinjuku", "Thumbnail": "", "Features": "Tonkotsu", "Agoda": ""},
            {"Name": "Ippudo Ginza", "Lat": "35.6711", "Lng": "139.7662", "Address": "Tokyo, Chuo", "Thumbnail": "", "Features": "Tonkotsu", "Agoda": ""},
        ]
        ramen_headers = ["Name", "Lat", "Lng", "Address", "Thumbnail", "Features", "Agoda"]

        def ensure(repo_p: Path, logf):
            return ensure_dual_csv(
                repo_p,
                logf,
                items_rel="script/csv/ramens.csv",
                guides_rel="script/csv/guides.csv",
                item_headers=ramen_headers,
                guide_headers=GUIDE_HEADERS,
                item_seeds=ramen_seeds,
                guide_seeds=DEFAULT_GUIDE_SEEDS,
            )

        limit = env.get("CONTENT_LIMIT", "10")
        glimit = env.get("GUIDE_LIMIT", "3")
        steps = [
            ("items", "ramen_generator", ["python3", "script/ramen_generator.py", limit], 3600),
            ("guides", "guide_generator", ["python3", "script/guide_generator.py", glimit], 3600),
            ("build", "build_data", ["python3", "script/build_data.py"], 600),
        ]
        return _execute_pipeline(site_id, repo, ensure_fn=ensure, steps=steps, env=env)

    if site_id == "okonsen":
        onsen_headers = ["Name", "Lat", "Lng", "Address", "Thumbnail", "Features", "Agoda"]
        onsen_seeds = [
            {"Name": "Hakone Ten-yu", "Lat": "35.2393", "Lng": "139.0456", "Address": "Hakone", "Thumbnail": "", "Features": "Family bath", "Agoda": ""},
            {"Name": "Gora Kadan", "Lat": "35.2492", "Lng": "139.0465", "Address": "Hakone", "Thumbnail": "", "Features": "Ryokan onsen", "Agoda": ""},
        ]

        def ensure(repo_p: Path, logf):
            return ensure_dual_csv(
                repo_p,
                logf,
                items_rel="script/csv/onsens.csv",
                guides_rel="script/csv/guides.csv",
                item_headers=onsen_headers,
                guide_headers=GUIDE_HEADERS,
                item_seeds=onsen_seeds,
                guide_seeds=DEFAULT_GUIDE_SEEDS,
            )

        limit = env.get("CONTENT_LIMIT", "10")
        glimit = env.get("GUIDE_LIMIT", "3")
        steps = [
            ("items", "onsen_generator", ["python3", "script/onsen_generator.py", limit], 3600),
            ("guides", "guide_generator", ["python3", "script/guide_generator.py", glimit], 3600),
            ("build", "build_data", ["python3", "script/build_data.py"], 600),
        ]
        return _execute_pipeline(site_id, repo, ensure_fn=ensure, steps=steps, env=env)

    if site_id == "okcaddie":
        course_headers = ["Name", "Lat", "Lng", "Address", "Features", "Booking"]
        course_seeds = [
            {"Name": "Sample Golf Club", "Lat": "35.0", "Lng": "135.0", "Address": "Hyogo", "Features": "Public", "Booking": ""},
        ]

        def ensure(repo_p: Path, logf):
            return ensure_dual_csv(
                repo_p,
                logf,
                items_rel="script/csv/courses.csv",
                guides_rel="script/csv/guides.csv",
                item_headers=course_headers,
                guide_headers=GUIDE_HEADERS,
                item_seeds=course_seeds,
                guide_seeds=DEFAULT_GUIDE_SEEDS,
                item_col="Name",
            )

        limit = env.get("CONTENT_LIMIT", "10")
        glimit = env.get("GUIDE_LIMIT", "3")
        steps = [
            ("items", "course_generator", ["python3", "script/course_generator.py", limit], 3600),
            ("guides", "guide_generator", ["python3", "script/guide_generator.py", glimit], 3600),
            ("build", "build_data", ["python3", "script/build_data.py"], 600),
        ]
        return _execute_pipeline(site_id, repo, ensure_fn=ensure, steps=steps, env=env)

    if site_id == "starful.biz":
        steps = [
            ("guides", "generate_md_guides", ["python3", "scripts/generate_md_guides.py"], 3600),
            ("build", "build_data", ["python3", "scripts/build_data.py"], 600),
        ]
        return _execute_pipeline(site_id, repo, ensure_fn=ensure_starful_csv, steps=steps, env=env)

    if site_id == "hatena":
        max_posts = env.get("HATENA_MAX_POSTS", "5")
        steps = [
            ("py", "unified_poster py", ["python3", "unified_poster.py", "py", "--max_posts", max_posts], 3600),
            ("cloud", "unified_poster cloud", ["python3", "unified_poster.py", "cloud", "--max_posts", max_posts], 3600),
        ]
        return _execute_pipeline(site_id, repo, ensure_fn=ensure_hatena_csv, steps=steps, env=env)

    if site_id == "jpcampus":
        steps = [
            ("guides", "AI guides", ["python3", "scripts/2.generate_ai_guides.py"], 3600),
            ("korean", "Korean content", ["python3", "scripts/3.create_korean_content.py"], 3600),
            ("featured", "featured articles", ["python3", "scripts/auto_generate_featured.py"], 1800),
            ("build", "build_data", ["python3", "scripts/build_data.py"], 600),
        ]
        optional = [
            ("seo", "seo_guard", ["python3", "scripts/seo_guard.py"], 300),
        ]
        return _execute_pipeline(site_id, repo, ensure_fn=ensure_jpcampus_csv, steps=steps, env=env, optional_steps=optional)

    return {"ok": False, "error": f"no pipeline definition for {site_id}"}


def run_pipeline(site_id: str) -> dict[str, Any]:
    if not work_root_available():
        return {"ok": False, "error": "WORK_ROOT not available"}
    svc = get_service(site_id)
    if not svc:
        return {"ok": False, "error": f"{site_id} not in sites.yaml"}
    repo = repo_path(svc)
    if not repo.is_dir():
        return {"ok": False, "error": f"missing repo {repo}"}
    return _pipeline_for_site(site_id, repo)


def run_okcafejp_pipeline() -> dict[str, Any]:
    return run_pipeline("okcafejp")


def _fail(site_id: str, steps: list, last: dict, log_path: Path) -> dict[str, Any]:
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


def _int_env(env: dict[str, str], key: str, default: int) -> int:
    try:
        return int(str(env.get(key, default)).strip() or default)
    except (TypeError, ValueError):
        return default


def pipeline_env_for_site(site_id: str) -> dict[str, str]:
    if not work_root_available():
        return {}
    svc = get_service(site_id)
    if not svc:
        return {}
    repo = repo_path(svc)
    if not repo.is_dir():
        return {}
    return _merge_pipeline_env(repo)


def pipeline_run_caps(site_id: str) -> dict[str, Any]:
    """Per-run caps shown in Work Hub (only missing MD/posts are actually created)."""
    env = pipeline_env_for_site(site_id)
    item_n = _int_env(env, "CONTENT_LIMIT", 10)
    guide_n = _int_env(env, "GUIDE_LIMIT", 3)
    hatena_n = _int_env(env, "HATENA_MAX_POSTS", 5)
    parts: list[dict[str, str]] = []

    if site_id in ("okcafejp", "oksushi"):
        parts = [
            {
                "label": "가이드",
                "cap": f"토픽 {guide_n}개 · 최대 {guide_n * 2} MD",
                "note": "없는 en/ko만",
            },
            {
                "label": "아이템",
                "cap": f"CSV {item_n}행 · 최대 {item_n * 2} MD",
                "note": "없는 en/ko만",
            },
            {"label": "빌드", "cap": "build_data 1회", "note": ""},
        ]
        if site_id == "okcafejp" and env.get("GOOGLE_PLACES_API_KEY"):
            parts.insert(0, {"label": "Places", "cap": "items.csv 갱신", "note": "API 키 있을 때"})
    elif site_id in ("okramen", "okonsen", "okcaddie"):
        kind = {"okramen": "라멘", "okonsen": "온천", "okcaddie": "코스"}[site_id]
        parts = [
            {"label": kind, "cap": f"CSV {item_n}행 · 최대 {item_n * 2} MD", "note": "없는 MD만"},
            {"label": "가이드", "cap": f"토픽 {guide_n}개 · 최대 {guide_n * 2} MD", "note": "없는 en/ko만"},
            {"label": "빌드", "cap": "build_data 1회", "note": ""},
        ]
    elif site_id == "starful.biz":
        parts = [
            {"label": "가이드 MD", "cap": "positions.csv 기준", "note": "없는 MD만"},
            {"label": "빌드", "cap": "build_data 1회", "note": ""},
        ]
    elif site_id == "hatena":
        parts = [
            {"label": "Python", "cap": f"최대 {hatena_n}건", "note": "신규 포스트"},
            {"label": "Cloud", "cap": f"최대 {hatena_n}건", "note": "신규 포스트"},
        ]
    elif site_id == "jpcampus":
        parts = [
            {"label": "가이드 AI", "cap": "토픽 배치", "note": "없는 가이드"},
            {"label": "한국어", "cap": "배치", "note": ""},
            {"label": "featured", "cap": "배치", "note": ""},
            {"label": "빌드", "cap": "build_data 1회", "note": "seo_guard 선택"},
        ]

    summary = " · ".join(f"{p['label']} {p['cap']}" for p in parts[:3])
    if len(parts) > 3:
        summary += " …"
    return {"parts": parts, "summary": summary or "—"}


def summarize_pipeline_status(status: dict[str, Any] | None, log_text: str = "") -> dict[str, Any]:
    """Short result for UI after a pipeline run."""
    lines: list[str] = []
    title = "대기"
    ok: bool | None = None

    if status:
        ok = status.get("ok")
        if ok is True:
            title = "완료"
        elif ok is False:
            title = "실패"
            failed = status.get("failed_step") or status.get("error") or ""
            if failed:
                lines.append(f"중단: {str(failed)[:120]}")

        for step in status.get("steps") or []:
            name = step.get("label") or step.get("step") or "?"
            if step.get("ok") is True:
                extra = []
                if step.get("item_rows"):
                    extra.append(f"items {step['item_rows']}행")
                if step.get("guide_rows"):
                    extra.append(f"guides {step['guide_rows']}행")
                if step.get("seeded_items"):
                    extra.append(f"시드 +{step['seeded_items']}")
                suffix = f" ({', '.join(extra)})" if extra else ""
                lines.append(f"✓ {name}{suffix}")
            elif step.get("ok") is False:
                code = step.get("exit_code")
                lines.append(f"✗ {name}" + (f" (exit {code})" if code is not None else ""))

    if log_text:
        for pat, label in (
            (r"Starting generation for (\d+) guide files", "가이드 생성 {0}건"),
            (r"Starting generation for (\d+) files", "아이템 생성 {0}건"),
            (r"No new guides to generate", "가이드: 신규 없음"),
            (r"No new items to generate", "아이템: 신규 없음"),
            (r"Wrote (\d+) rows", "CSV {0}행 기록"),
            (r"Pipeline OK", "파이프라인 정상 종료"),
        ):
            m = re.search(pat, log_text)
            if m:
                msg = label.format(m.group(1)) if "{0}" in label and m.lastindex else label
                if msg not in lines:
                    lines.append(msg)

    snippet = _log_snippet(log_text)
    return {"title": title, "ok": ok, "lines": lines[:12], "log_snippet": snippet}


def _log_snippet(log_text: str, *, max_lines: int = 14) -> str:
    if not log_text:
        return ""
    picked: list[str] = []
    for line in log_text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("[") and "]" in s[:30]:
            picked.append(s)
        elif any(
            k in s
            for k in (
                "Starting generation",
                "No new",
                "Pipeline OK",
                "Failed",
                "Wrote ",
                "✨",
                "🔔",
                "✅",
                "❌",
                "⚠",
            )
        ):
            picked.append(s)
    if not picked:
        picked = [ln.strip() for ln in log_text.splitlines() if ln.strip()][-max_lines:]
    return "\n".join(picked[-max_lines:])


CONTENT_PIPELINES: dict[str, dict[str, str]] = {
    "okcafejp": {"label": "OK Cafe JP", "description": "카페 · 가이드 AI + build"},
    "oksushi": {"label": "OK Sushi", "description": "스시 · 가이드 AI + build"},
    "okramen": {"label": "OK Ramen", "description": "라멘 · 가이드 AI + build"},
    "okonsen": {"label": "OK Onsen", "description": "온천 · 가이드 AI + build"},
    "okcaddie": {"label": "OK Caddie", "description": "골프 · 가이드 AI + build"},
    "starful.biz": {"label": "Starful Biz", "description": "포지션 가이드 MD + build"},
    "hatena": {"label": "Hatena · okpy", "description": "Python / Cloud 포스트"},
    "jpcampus": {"label": "JP Campus", "description": "가이드 · 한국어 · featured · build"},
}
