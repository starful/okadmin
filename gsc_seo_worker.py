"""Fetch GSC targets, suggest SEO via Gemini, optionally patch site content MD."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

from analytics_api import (
    fetch_ga4_summary,
    fetch_gsc_daily,
    fetch_gsc_pages,
    site_analytics_config,
)
from config import WORK_ROOT, get_service, repo_path
from gsc_service import low_ctr_high_impression

FETCH_TIMEOUT = 20
USER_AGENT = "WorkHub-GSC/1.0"


def _gemini_model():
    from config_gemini import ensure_gemini_api_key

    ensure_gemini_api_key()
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None, (
            "GEMINI_API_KEY 없음 — okadmin/.env 에 추가하거나 "
            "./scripts/fetch_secrets.sh 실행"
        )
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        name = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
        return genai.GenerativeModel(name), None
    except ImportError:
        return None, "pip install google-generativeai"
    except Exception as e:
        return None, str(e)


def fetch_page_seo(url: str) -> dict[str, Any]:
    try:
        res = requests.get(
            url,
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        html = res.text
        status = res.status_code
    except requests.RequestException as e:
        return {"ok": False, "error": str(e), "url": url}

    def _meta(name: str) -> str:
        m = re.search(
            rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            re.I,
        )
        if m:
            return m.group(1).strip()
        m = re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(name)}["\']',
            html,
            re.I,
        )
        return m.group(1).strip() if m else ""

    title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    h1_m = re.search(r"<h1[^>]*>([^<]+)</h1>", html, re.I)
    return {
        "ok": status == 200,
        "status": status,
        "url": res.url if status == 200 else url,
        "title": (title_m.group(1).strip() if title_m else ""),
        "description": _meta("description"),
        "h1": (h1_m.group(1).strip() if h1_m else ""),
    }


def _parse_frontmatter(path: Path) -> tuple[dict[str, Any], str, str, str]:
    """Returns (meta, raw_block, body, format) where format is 'json' or 'yaml'."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text, text, "yaml"
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text, text, "yaml"
    raw = text[3:end].strip()
    body = text[end + 4 :]
    if raw.startswith("{"):
        try:
            meta = json.loads(raw)
            if isinstance(meta, dict):
                return meta, raw, body, "json"
        except json.JSONDecodeError:
            pass
    try:
        import yaml

        meta = yaml.safe_load(raw) or {}
        if isinstance(meta, dict):
            return meta, raw, body, "yaml"
    except Exception:
        pass
    return {}, raw, body, "yaml"


def _write_frontmatter(
    path: Path, meta: dict[str, Any], body: str, *, fmt: str = "json"
) -> None:
    if fmt == "json":
        block = json.dumps(meta, ensure_ascii=False, indent=2)
    else:
        import yaml

        block = yaml.safe_dump(
            meta,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ).rstrip()
    path.write_text(f"---\n{block}\n---\n{body}", encoding="utf-8")


def resolve_content_files(site_id: str, url: str) -> list[Path]:
    svc = get_service(site_id)
    if not svc:
        return []
    root = repo_path(svc)
    parsed = urlparse(url)
    path = unquote(parsed.path or "/")
    qs = parse_qs(parsed.query)
    lang_kr = qs.get("lang", [""])[0].lower() in ("kr", "ko", "korean")

    if site_id == "jpcampus":
        return _resolve_jpcampus_files(root, path, lang_kr)

    for content_dir in (root / "app" / "content", root / "content"):
        if not content_dir.is_dir():
            continue
        segment = path.rstrip("/").split("/")[-1] if path != "/" else ""
        for md in content_dir.glob("*.md"):
            if segment and segment in md.stem:
                return [md]
        norm_path = path.split("?")[0]
        for md in content_dir.glob("*.md"):
            meta, _, _, _ = _parse_frontmatter(md)
            link = str(meta.get("link") or meta.get("id") or "")
            if norm_path and norm_path in link:
                return [md]
    return []


def _resolve_jpcampus_files(root: Path, path: str, lang_kr: bool) -> list[Path]:
    """Map /guide/{slug} and /school/{school_id} to app/content/*.md (mirrors main.py)."""
    content = root / "app" / "content"
    if not content.is_dir():
        return []

    def _pick(basename: str) -> list[Path]:
        """One file per request, same order as jpcampus app/main.py school route."""
        if lang_kr:
            primary, fallback = f"{basename}_kr.md", f"{basename}.md"
        else:
            primary, fallback = f"{basename}.md", f"{basename}_kr.md"
        p = content / primary
        if p.is_file():
            return [p]
        p = content / fallback
        return [p] if p.is_file() else []

    m = re.search(r"/guide/([^/?#]+)", path)
    if m:
        return _pick(f"guide_{m.group(1)}")

    m = re.search(r"/school/([^/?#]+)", path)
    if m:
        return _pick(m.group(1))

    return []


def _suggest_seo(
    model,
    *,
    site_id: str,
    url: str,
    page: dict[str, Any],
    gsc: dict[str, Any],
) -> dict[str, str]:
    prompt = f"""You are an SEO editor for site "{site_id}".
URL: {url}
GSC: impressions={gsc.get('impressions')}, CTR={gsc.get('ctr', 0)*100:.2f}%, position={gsc.get('position', 0):.1f}

Current:
- title: {page.get('title', '')}
- meta description: {page.get('description', '')}
- h1: {page.get('h1', '')}

Return ONLY valid JSON with keys:
title, description, seo_title, seo_description, summary_ko
Improve for click-through on Google. Keep brand tone. description under 155 chars."""
    res = model.generate_content(prompt)
    text = (res.text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    data = json.loads(text)
    return {
        "title": str(data.get("title") or page.get("title") or ""),
        "description": str(data.get("description") or page.get("description") or ""),
        "seo_title": str(data.get("seo_title") or data.get("title") or ""),
        "seo_description": str(
            data.get("seo_description") or data.get("description") or ""
        ),
        "summary_ko": str(data.get("summary_ko") or ""),
    }


def _apply_to_md(path: Path, seo: dict[str, str]) -> list[str]:
    meta, _, body, fmt = _parse_frontmatter(path)
    if not meta and fmt == "yaml" and not body.strip():
        return []
    changed: list[str] = []
    for key in ("title", "description", "seo_title", "seo_description"):
        val = seo.get(key)
        if val and meta.get(key) != val:
            meta[key] = val
            changed.append(key)
    if changed:
        _write_frontmatter(path, meta, body, fmt=fmt)
    return changed


def run_seo_jobs(
    site_id: str,
    *,
    urls: list[str],
    apply_files: bool = True,
) -> dict[str, Any]:
    ac = site_analytics_config(site_id)
    gsc_url = ac.get("gsc_site_url")
    if not gsc_url:
        return {"error": "gsc_site_url not configured"}

    gsc_raw = fetch_gsc_pages(gsc_url)
    if gsc_raw.get("error"):
        return gsc_raw

    candidates = low_ctr_high_impression(gsc_raw.get("rows") or [], key="page")
    by_label: dict[str, dict[str, Any]] = {}
    for row in candidates:
        label = (row.get("label") or row.get("page") or "").strip()
        if label:
            by_label[label] = row

    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_url in urls[:20]:
        url = (raw_url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        if url in by_label:
            picked.append(by_label[url])
        else:
            picked.append(
                {
                    "label": url,
                    "impressions": 0,
                    "ctr": 0,
                    "position": 0,
                }
            )

    if not picked:
        return {
            "error": "처리할 URL을 1개 이상 선택하세요",
            "candidates_total": len(candidates),
        }

    model, gemini_err = _gemini_model()
    if not model:
        return {"error": gemini_err, "candidates": len(candidates)}

    results: list[dict[str, Any]] = []
    for row in picked:
        url = row.get("label") or row.get("page") or ""
        item: dict[str, Any] = {
            "url": url,
            "impressions": row.get("impressions"),
            "ctr": row.get("ctr"),
            "position": row.get("position"),
            "status": "pending",
        }
        page = fetch_page_seo(url)
        if not page.get("ok"):
            item["status"] = "fetch_failed"
            item["error"] = page.get("error") or f"HTTP {page.get('status')}"
            results.append(item)
            continue

        try:
            seo = _suggest_seo(model, site_id=site_id, url=url, page=page, gsc=row)
        except Exception as e:
            item["status"] = "ai_failed"
            item["error"] = str(e)
            item["before"] = {
                "title": page.get("title"),
                "description": page.get("description"),
            }
            results.append(item)
            continue

        item["before"] = {
            "title": page.get("title"),
            "description": page.get("description"),
            "h1": page.get("h1"),
        }
        item["after"] = seo
        item["summary_ko"] = seo.get("summary_ko", "")

        paths = resolve_content_files(site_id, url)
        item["files"] = [str(p.relative_to(WORK_ROOT)) for p in paths]

        if apply_files and paths:
            applied: list[str] = []
            for p in paths[:2]:
                applied.extend(_apply_to_md(p, seo))
            item["applied_fields"] = sorted(set(applied))
            item["status"] = "applied" if applied else "no_changes"
        elif paths:
            item["status"] = "suggested"
        else:
            item["status"] = "suggested_no_file"

        results.append(item)

    return {
        "site_id": site_id,
        "count": len(results),
        "candidates_total": len(candidates),
        "gsc_range": {"start": gsc_raw.get("start"), "end": gsc_raw.get("end")},
        "results": results,
    }


def load_dashboard(site_id: str) -> dict[str, Any]:
    from config_gemini import ensure_gemini_api_key

    ac = site_analytics_config(site_id)
    out: dict[str, Any] = {
        "site_id": site_id,
        "analytics": ac,
        "gemini_configured": ensure_gemini_api_key(),
    }

    ga4_id = ac.get("ga4_property_id")
    if ga4_id:
        out["ga4"] = fetch_ga4_summary(ga4_id)
    else:
        out["ga4"] = {"error": "ga4_property_id not set"}

    gsc_url = ac.get("gsc_site_url")
    if gsc_url:
        daily = fetch_gsc_daily(gsc_url)
        pages = fetch_gsc_pages(gsc_url)
        gsc: dict[str, Any] = {
            "start": daily.get("start") or pages.get("start"),
            "end": daily.get("end") or pages.get("end"),
        }
        if daily.get("error"):
            gsc["error"] = daily["error"]
        else:
            gsc["totals"] = daily.get("totals") or {}
            gsc["daily"] = daily.get("rows") or []
        if pages.get("error") and "error" not in gsc:
            gsc["pages_error"] = pages["error"]
        elif pages.get("rows"):
            low = low_ctr_high_impression(pages["rows"], key="page")
            gsc["low_ctr"] = low
            gsc["low_ctr_count"] = len(low)
            gsc["page_rows"] = len(pages["rows"])
        out["gsc"] = gsc
    else:
        out["gsc"] = {"error": "gsc_site_url not set"}

    return out
