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
from gsc_service import analyze_gsc_page_patterns, count_md_actionable

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


def _content_dirs(root: Path):
    for d in (
        root / "app" / "content",
        root / "app" / "contents",
        root / "content",
    ):
        if d.is_dir():
            yield d


def _page_context_from_md(path: Path) -> dict[str, Any]:
    meta, _, body, _ = _parse_frontmatter(path)
    h1 = ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            h1 = stripped[2:].strip()
            break
    desc = (
        meta.get("seo_description")
        or meta.get("description")
        or meta.get("summary")
        or ""
    )
    return {
        "ok": True,
        "source": "md",
        "title": str(meta.get("seo_title") or meta.get("title") or ""),
        "description": str(desc)[:500],
        "h1": h1 or str(meta.get("title") or ""),
    }


def _resolve_item_from_json(root: Path, norm_path: str) -> list[Path]:
    m = re.search(r"/item/([^/?#]+)", norm_path)
    if not m:
        return []
    slug = m.group(1)
    data_file = root / "app" / "static" / "json" / "items_data.json"
    if not data_file.is_file():
        return []
    try:
        payload = json.loads(data_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("sushis") or payload.get("items") or []
    if not isinstance(rows, list):
        return []
    item_id = slug
    for row in rows:
        if not isinstance(row, dict):
            continue
        link = str(row.get("link") or "")
        rid = str(row.get("id") or "")
        if link == f"/item/{slug}" or rid == slug:
            item_id = rid or slug
            break
    for content_dir in _content_dirs(root):
        exact = content_dir / f"{item_id}.md"
        if exact.is_file():
            return [exact]
    return []


def resolve_content_files(site_id: str, url: str) -> list[Path]:
    svc = get_service(site_id)
    if not svc:
        return []
    root = repo_path(svc)
    parsed = urlparse(url)
    path = unquote(parsed.path or "/")
    qs = parse_qs(parsed.query)
    lang_kr = qs.get("lang", [""])[0].lower() in ("kr", "ko", "korean")
    lang_ja = qs.get("lang", [""])[0].lower() in ("ja", "jp", "japanese")

    if site_id == "jpcampus":
        return _resolve_jpcampus_files(root, path, lang_kr)
    if site_id == "krcampus":
        return _resolve_krcampus_files(root, path, lang_ja)

    norm_path = path.split("?")[0]

    if site_id == "okstats":
        m_insight = re.search(r"/insight/([^/?#]+)", norm_path)
        if m_insight:
            slug = m_insight.group(1)
            content = root / "app" / "content"
            for name in (f"{slug}_en.md", f"{slug}.md"):
                candidate = content / name
                if candidate.is_file():
                    return [candidate]
        m_guide = re.search(r"/guide/([^/?#]+)", norm_path)
        if m_guide:
            slug = m_guide.group(1)
            guides = root / "app" / "content" / "guides"
            for name in (f"{slug}.md", f"{slug}_en.md", f"guide_{slug}.md"):
                candidate = guides / name
                if candidate.is_file():
                    return [candidate]
        return []

    segment = path.rstrip("/").split("/")[-1] if path != "/" else ""

    # /item/{id} → {id}.md (oksushi, okcafejp, …)
    m_item = re.search(r"/item/([^/?#]+)", norm_path)
    if m_item:
        slug = m_item.group(1)
        for content_dir in _content_dirs(root):
            exact = content_dir / f"{slug}.md"
            if exact.is_file():
                return [exact]
        from_json = _resolve_item_from_json(root, norm_path)
        if from_json:
            return from_json

    m_guide = re.search(r"/guide/([^/?#]+)", norm_path)
    if m_guide:
        slug = m_guide.group(1)
        for content_dir in _content_dirs(root):
            for name in (f"guide_{slug}.md", f"{slug}.md"):
                for base in (content_dir, content_dir / "guides"):
                    candidate = base / name
                    if candidate.is_file():
                        return [candidate]

    for content_dir in _content_dirs(root):
        if segment:
            exact = content_dir / f"{segment}.md"
            if exact.is_file():
                return [exact]
            for md in content_dir.rglob("*.md"):
                if md.stem == segment:
                    return [md]
        for md in content_dir.rglob("*.md"):
            meta, _, _, _ = _parse_frontmatter(md)
            link = str(meta.get("link") or meta.get("id") or "")
            if norm_path and norm_path in link:
                return [md]
        if segment:
            for md in content_dir.rglob("*.md"):
                if segment in md.stem:
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


def _resolve_krcampus_files(root: Path, path: str, lang_ja: bool) -> list[Path]:
    """Map /guide/{slug} and /school/{school_id} to app/content/*.md (mirrors main.py)."""
    content = root / "app" / "content"
    if not content.is_dir():
        return []

    def _pick(basename: str) -> list[Path]:
        if lang_ja:
            primary, fallback = f"{basename}_ja.md", f"{basename}.md"
        else:
            primary, fallback = f"{basename}.md", f"{basename}_ja.md"
        p = content / primary
        if p.is_file():
            return [p]
        p = content / fallback
        return [p] if p.is_file() else []

    m = re.search(r"/guide/([^/?#]+)", path)
    if m:
        slug = m.group(1)
        return _pick(f"guide_{slug}") or _pick(slug)

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
    pattern: str = "low_ctr",
) -> dict[str, str]:
    gsc_line = (
        f"GSC: impressions={gsc.get('impressions')}, "
        f"CTR={gsc.get('ctr', 0) * 100:.2f}%, position={gsc.get('position', 0):.1f}"
    )
    if pattern == "low_impression":
        goal = (
            "Improve search visibility and ranking (more impressions). "
            "Strengthen title/meta for discovery and relevant keywords. "
            "Keep brand tone. description under 155 chars."
        )
    else:
        goal = (
            "Improve click-through on Google (CTR). "
            "Keep brand tone. description under 155 chars."
        )
    prompt = f"""You are an SEO editor for site "{site_id}".
URL: {url}
Pattern: {pattern}
{gsc_line}

Current:
- title: {page.get('title', '')}
- meta description: {page.get('description', '')}
- h1: {page.get('h1', '')}

Return ONLY valid JSON with keys:
title, description, seo_title, seo_description, summary_ko
{goal}
summary_ko: brief Korean note on what you changed and why."""
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
    url_patterns: dict[str, str] | None = None,
) -> dict[str, Any]:
    ac = site_analytics_config(site_id)
    gsc_url = ac.get("gsc_site_url")
    if not gsc_url:
        return {"error": "gsc_site_url not configured"}

    gsc_raw = fetch_gsc_pages(gsc_url)
    if gsc_raw.get("error"):
        return gsc_raw

    patterns = analyze_gsc_page_patterns(gsc_raw.get("rows") or [], key="page")
    candidates = patterns["low_ctr"] + patterns["low_impression"]
    by_label: dict[str, dict[str, Any]] = {}
    for row in candidates:
        label = (row.get("label") or row.get("page") or "").strip()
        if label:
            by_label[label] = row
    pattern_overrides = url_patterns or {}

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
            "low_ctr_count": patterns["low_ctr_count"],
            "low_impression_count": patterns["low_impression_count"],
        }

    model, gemini_err = _gemini_model()
    if not model:
        return {"error": gemini_err, "candidates": len(candidates)}

    results: list[dict[str, Any]] = []
    for row in picked:
        url = row.get("label") or row.get("page") or ""
        pat = pattern_overrides.get(url) or row.get("pattern") or "low_ctr"
        item: dict[str, Any] = {
            "url": url,
            "pattern": pat,
            "impressions": row.get("impressions"),
            "ctr": row.get("ctr"),
            "position": row.get("position"),
            "status": "pending",
        }
        paths = resolve_content_files(site_id, url)
        item["files"] = [str(p.relative_to(WORK_ROOT)) for p in paths]

        live = fetch_page_seo(url)
        if live.get("ok"):
            page = live
            item["page_source"] = "live"
        elif paths:
            page = _page_context_from_md(paths[0])
            item["page_source"] = "md"
            item["fetch_note"] = (
                f"live HTTP {live.get('status') or live.get('error') or '?'}"
                " — MD frontmatter 기준"
            )
        else:
            item["status"] = "no_md_file"
            item["error"] = (
                f"live HTTP {live.get('status') or live.get('error') or '?'}"
                " · 매칭 MD 없음"
            )
            results.append(item)
            continue

        try:
            seo = _suggest_seo(
                model,
                site_id=site_id,
                url=url,
                page=page,
                gsc=row,
                pattern=pat,
            )
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

        if not paths:
            item["status"] = "no_md_file"
            results.append(item)
            continue

        if apply_files:
            applied: list[str] = []
            for p in paths[:2]:
                applied.extend(_apply_to_md(p, seo))
            item["applied_fields"] = sorted(set(applied))
            item["status"] = "applied" if applied else "no_changes"
        else:
            item["status"] = "suggested"

        results.append(item)

    from gsc_url_store import record_seo_attempts

    record_seo_attempts(site_id, results)

    return {
        "site_id": site_id,
        "count": len(results),
        "candidates_total": len(candidates),
        "low_ctr_count": patterns["low_ctr_count"],
        "low_impression_count": patterns["low_impression_count"],
        "gsc_range": {"start": gsc_raw.get("start"), "end": gsc_raw.get("end")},
        "results": results,
    }


def _dashboard_fetch_ok(out: dict[str, Any]) -> bool:
    ga4 = out.get("ga4") or {}
    gsc = out.get("gsc") or {}
    ga4_err = ga4.get("error")
    if ga4_err and ga4_err != "ga4_property_id not set":
        return False
    if gsc.get("error"):
        return False
    return True


def enrich_gsc_rows_md(site_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from gsc_url_store import url_history_meta

    meta_by_url = url_history_meta(site_id)
    out: list[dict[str, Any]] = []
    for row in rows:
        url = (row.get("label") or row.get("page") or "").strip()
        paths = resolve_content_files(site_id, url) if url else []
        rel = [str(p.relative_to(WORK_ROOT)) for p in paths]
        hist = meta_by_url.get(url) or {}
        is_deleted = bool(hist.get("is_deleted"))
        out.append(
            {
                **row,
                "has_md": bool(paths) and not is_deleted,
                "md_files": rel,
                "url_history": hist,
                "is_deleted": is_deleted,
            }
        )
    return out


def delete_url_content_files(site_id: str, urls: list[str]) -> dict[str, Any]:
    """Delete MD/content files for URLs (manual GSC cleanup)."""
    from gsc_url_store import record_url_deletion, url_history_meta

    if not get_service(site_id):
        return {"error": f"unknown site: {site_id}"}

    results: list[dict[str, Any]] = []
    for raw in urls[:20]:
        url = (raw or "").strip()
        if not url:
            continue
        paths = resolve_content_files(site_id, url)
        if not paths:
            results.append(
                {
                    "url": url,
                    "status": "no_files",
                    "error": "삭제할 MD/콘텐츠 파일 없음",
                }
            )
            continue
        deleted: list[str] = []
        errors: list[str] = []
        for p in paths:
            rel = str(p.relative_to(WORK_ROOT))
            try:
                if p.is_file():
                    p.unlink()
                    deleted.append(rel)
            except OSError as e:
                errors.append(f"{rel}: {e}")
        if deleted:
            record_url_deletion(site_id, url, deleted_files=deleted)
            results.append(
                {
                    "url": url,
                    "status": "deleted",
                    "deleted_files": deleted,
                    "errors": errors or None,
                }
            )
        elif errors:
            results.append(
                {"url": url, "status": "error", "error": "; ".join(errors)}
            )
        else:
            results.append(
                {"url": url, "status": "no_files", "error": "파일 없음"}
            )

    if not results:
        return {"error": "urls required"}
    ok = any(r.get("status") == "deleted" for r in results)
    return {
        "site_id": site_id,
        "count": len(results),
        "ok": ok,
        "results": results,
        "url_history": url_history_meta(site_id),
    }


def load_dashboard(site_id: str) -> dict[str, Any]:
    from config_gemini import ensure_gemini_api_key
    from gsc_run_store import gsc_last_runs, write_gsc_dashboard_run

    from gsc_url_store import url_history_meta

    ac = site_analytics_config(site_id)
    out: dict[str, Any] = {
        "site_id": site_id,
        "analytics": ac,
        "gemini_configured": ensure_gemini_api_key(),
        "last_runs": gsc_last_runs(site_id),
        "url_history": url_history_meta(site_id),
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
            analyzed = analyze_gsc_page_patterns(pages["rows"], key="page")
            analyzed["low_ctr"] = enrich_gsc_rows_md(site_id, analyzed["low_ctr"])
            analyzed["low_impression"] = enrich_gsc_rows_md(
                site_id, analyzed["low_impression"]
            )
            all_pat = analyzed["low_ctr"] + analyzed["low_impression"]
            analyzed["md_actionable_count"] = count_md_actionable(all_pat)
            analyzed["md_missing_count"] = sum(1 for r in all_pat if not r.get("has_md"))
            gsc.update(analyzed)
        out["gsc"] = gsc
    else:
        out["gsc"] = {"error": "gsc_site_url not set"}

    ok = _dashboard_fetch_ok(out)
    write_gsc_dashboard_run(site_id, out, ok=ok)
    out["last_runs"] = gsc_last_runs(site_id)
    out["dashboard_ok"] = ok
    return out
