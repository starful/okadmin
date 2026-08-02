"""OKPy: AI topic rows for python / cloud / terraform banks (목록 추가)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config_gemini import ensure_gemini_api_key
from statfacts_topic_ai import _clamp_count, _gemini_json
from topic_bank import _append_bank_rows, read_bank
from topic_bank_registry import banks_for_site

DEFAULT_PYTHON_COUNT = 2
DEFAULT_CLOUD_COUNT = 2
DEFAULT_TERRAFORM_COUNT = 2
MAX_COUNT = 15


def _existing_python() -> set[str]:
    return {
        (row.get("lib_name") or "").strip().lower()
        for row in read_bank("okpy", "python")
        if (row.get("lib_name") or "").strip()
    }


def _existing_topics(bank_id: str) -> set[str]:
    return {
        (row.get("Topic") or "").strip().lower()
        for row in read_bank("okpy", bank_id)
        if (row.get("Topic") or "").strip()
    }


def append_okpy_topics(
    site_id: str,
    repo: Path,
    logf: Any,
    *,
    python_count: int = DEFAULT_PYTHON_COUNT,
    cloud_count: int = DEFAULT_CLOUD_COUNT,
    terraform_count: int = DEFAULT_TERRAFORM_COUNT,
) -> dict[str, Any]:
    if site_id != "okpy":
        return {"ok": False, "error": f"unsupported site {site_id}"}

    p_n = _clamp_count(python_count, DEFAULT_PYTHON_COUNT, MAX_COUNT)
    c_n = _clamp_count(cloud_count, DEFAULT_CLOUD_COUNT, MAX_COUNT)
    t_n = _clamp_count(terraform_count, DEFAULT_TERRAFORM_COUNT, MAX_COUNT)
    if p_n == c_n == t_n == 0:
        return {"ok": False, "error": "python/cloud/terraform 중 1개 이상 입력하세요"}
    if not ensure_gemini_api_key():
        return {"ok": False, "error": "Claude CLI 미로그인 — `claude` 후 /login"}

    exist_py = _existing_python()
    exist_cloud = _existing_topics("cloud")
    exist_tf = _existing_topics("terraform")

    blocks = []
    if p_n:
        blocks.append(f"Generate exactly {p_n} NEW Python library names (lib_name).")
    if c_n:
        blocks.append(
            f"Generate exactly {c_n} NEW cloud comparison Topics "
            "(AWS vs GCP vs Azure style, English Topic string)."
        )
    if t_n:
        blocks.append(f"Generate exactly {t_n} NEW Terraform Topics (English Topic string).")

    prompt = f"""You are an editor for OKPy (Japanese tech blog: Python, multi-cloud, Terraform).
{chr(10).join(blocks)}

Do NOT duplicate:
python: {", ".join(sorted(exist_py)[:80])}
cloud: {", ".join(sorted(exist_cloud)[:40])}
terraform: {", ".join(sorted(exist_tf)[:40])}

Return ONLY valid JSON (omit empty arrays):
{{
  "python": [{{"lib_name": "LibraryName"}}],
  "cloud": [{{"Topic": "AWS X vs GCP Y vs Azure Z"}}],
  "terraform": [{{"Topic": "Terraform ..."}}]
}}
"""
    data = _gemini_json(prompt) or {}
    messages: list[str] = []
    bank_appended: dict[str, int] = {}

    py_rows: list[dict[str, str]] = []
    for item in data.get("python") or []:
        if not isinstance(item, dict) or len(py_rows) >= p_n:
            break
        name = str(item.get("lib_name") or "").strip()
        if not name or name.lower() in exist_py:
            continue
        py_rows.append({"lib_name": name})
        exist_py.add(name.lower())

    cloud_rows: list[dict[str, str]] = []
    for item in data.get("cloud") or []:
        if not isinstance(item, dict) or len(cloud_rows) >= c_n:
            break
        topic = str(item.get("Topic") or "").strip()
        if not topic or topic.lower() in exist_cloud:
            continue
        cloud_rows.append({"Topic": topic})
        exist_cloud.add(topic.lower())

    tf_rows: list[dict[str, str]] = []
    for item in data.get("terraform") or []:
        if not isinstance(item, dict) or len(tf_rows) >= t_n:
            break
        topic = str(item.get("Topic") or "").strip()
        if not topic or topic.lower() in exist_tf:
            continue
        tf_rows.append({"Topic": topic})
        exist_tf.add(topic.lower())

    specs = {s.bank_id: s for s in banks_for_site(site_id)}
    if py_rows and "python" in specs:
        n = _append_bank_rows(site_id, specs["python"], py_rows)
        bank_appended["python"] = n
        messages.append(f"python +{n}")
        logf.write(f"토픽뱅크 python: +{n}행\n")
    if cloud_rows and "cloud" in specs:
        n = _append_bank_rows(site_id, specs["cloud"], cloud_rows)
        bank_appended["cloud"] = n
        messages.append(f"cloud +{n}")
        logf.write(f"토픽뱅크 cloud: +{n}행\n")
    if tf_rows and "terraform" in specs:
        n = _append_bank_rows(site_id, specs["terraform"], tf_rows)
        bank_appended["terraform"] = n
        messages.append(f"terraform +{n}")
        logf.write(f"토픽뱅크 terraform: +{n}행\n")

    try:
        from topic_bank_pipeline import refresh_topic_state

        refresh_topic_state(site_id, repo)
    except Exception as exc:
        messages.append(f"state refresh warn: {exc}")

    rows_added = sum(bank_appended.values())
    return {
        "ok": True,
        "site_id": site_id,
        "rows_added": rows_added,
        "bank_appended": bank_appended,
        "messages": messages,
        "expanded_items": rows_added,
        "expanded_guides": 0,
    }
