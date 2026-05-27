"""Google OAuth for OK Admin / Work Hub."""
from __future__ import annotations

import os
import secrets
from functools import wraps

import requests
from flask import Blueprint, redirect, request, session, url_for

from config import PLACES_TIMEOUT

auth_bp = Blueprint("auth", __name__)

GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
ALLOWED_EMAILS = {
    email.strip().lower()
    for email in os.environ.get("ALLOWED_EMAILS", "").split(",")
    if email.strip()
}
GOOGLE_OAUTH_SCOPE = "openid email profile"
GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def local_dev_auth_enabled() -> bool:
    """Cloud Run이 아니면 기본 로컬 자동 로그인 (LOCAL_DEV_AUTH=0 으로만 OAuth 사용)."""
    if os.environ.get("K_SERVICE") is not None:
        return False
    return os.environ.get("LOCAL_DEV_AUTH", "1") != "0"


def is_allowed_email(email: str | None) -> bool:
    return bool(email and email.lower() in ALLOWED_EMAILS)


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        email = session.get("user_email")
        if not is_allowed_email(email):
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)

    return decorated


@auth_bp.route("/login")
def login():
    if session.get("user_email") and is_allowed_email(session.get("user_email")):
        nxt = request.args.get("next") or url_for("pages.dashboard")
        return redirect(nxt)

    if local_dev_auth_enabled():
        dev_email = (os.environ.get("DEV_LOGIN_EMAIL") or "").strip().lower()
        if not dev_email:
            dev_email = next(iter(ALLOWED_EMAILS), "")
        if is_allowed_email(dev_email):
            session["user_email"] = dev_email
            nxt = request.args.get("next") or url_for("pages.dashboard")
            return redirect(nxt)

    if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_CLIENT_SECRET:
        return "Google OAuth 환경변수가 설정되지 않았습니다.", 500

    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    redirect_uri = url_for("auth.oauth_callback", _external=True)
    auth_params = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_OAUTH_SCOPE,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "state": state,
        "prompt": "select_account",
    }
    auth_url = requests.Request("GET", GOOGLE_OAUTH_AUTH_URL, params=auth_params).prepare().url
    return redirect(auth_url)


@auth_bp.route("/oauth/callback")
def oauth_callback():
    if request.args.get("state") != session.get("oauth_state"):
        return "Invalid OAuth state", 400
    code = request.args.get("code")
    if not code:
        return "OAuth code not found", 400

    redirect_uri = url_for("auth.oauth_callback", _external=True)
    token_data = {
        "code": code,
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        token_res = requests.post(GOOGLE_OAUTH_TOKEN_URL, data=token_data, timeout=PLACES_TIMEOUT)
        token_res.raise_for_status()
        access_token = token_res.json().get("access_token")
        if not access_token:
            return "OAuth token fetch failed", 400
        user_res = requests.get(
            GOOGLE_OAUTH_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=PLACES_TIMEOUT,
        )
        user_res.raise_for_status()
    except requests.RequestException:
        return "Google OAuth request failed", 502

    user_email = user_res.json().get("email", "").lower()
    if not is_allowed_email(user_email):
        session.clear()
        return "허용되지 않은 계정입니다.", 403

    session["user_email"] = user_email
    session.pop("oauth_state", None)
    nxt = request.args.get("next") or url_for("pages.dashboard")
    return redirect(nxt)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/oauth/gsc/setup")
def gsc_oauth_setup():
    """GSC API 인증 안내 (OAuth / 서비스 계정)."""
    from analytics_api import GSC_SCOPE, gsc_auth_setup_info

    info = gsc_auth_setup_info()
    sa = info.get("service_account") or "(없음)"
    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<title>GSC API 설정</title>
<style>body{{font-family:system-ui;max-width:720px;margin:2rem auto;padding:0 1rem}}
code,pre{{background:#111;color:#eee;padding:2px 6px;border-radius:4px}}
li{{margin:.5rem 0}}</style></head><body>
<h1>GSC API 인증</h1>
<h2>방법 A (권장): 서비스 계정</h2>
<ol>
<li>Search Console → 각 속성 → <strong>설정 → 사용자 및 권한</strong></li>
<li>사용자 추가: <pre>{sa}</pre> (권한: 제한 또는 전체)</li>
<li>저장 후 GSC 화면에서 <strong>API 가져오기</strong> — OAuth 불필요</li>
</ol>
<h2>방법 B: OAuth (브라우저)</h2>
<p>Google Cloud → OAuth 클라이언트 ID <code>{info.get("client_id","")}</code></p>
<ul>
<li><strong>승인된 리디렉션 URI</strong> (둘 다 추가 권장):<br>
<code>http://127.0.0.1:8090/oauth/gsc/callback</code><br>
<code>http://localhost:8090/oauth/gsc/callback</code><br>
<code>http://127.0.0.1:8090</code></li>
<li><strong>승인된 JavaScript 원본</strong>: <code>http://127.0.0.1:8090</code></li>
<li>OAuth 동의 화면 → 테스트 사용자에 본인 Gmail</li>
<li>API 라이브러리 → Search Console API 사용</li>
</ul>
<p>Scope: <code>{GSC_SCOPE}</code></p>
<p>Redirect (현재 코드): <code>{info.get("redirect_uri","")}</code></p>
<p><a href="/oauth/gsc/start">OAuth 시작</a> · <a href="/gsc">GSC 분석</a></p>
</body></html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@auth_bp.route("/oauth/gsc/start")
def gsc_oauth_start():
    """Search Console API용 OAuth (webmasters.readonly)."""
    from analytics_api import GSC_SCOPE, gsc_oauth_redirect_uri, load_gsc_oauth_client

    client = load_gsc_oauth_client()
    if not client:
        return "gsc-token.json 또는 GOOGLE_OAUTH_CLIENT_ID/SECRET 필요", 500
    client_id, _client_secret = client
    state = secrets.token_urlsafe(24)
    session["gsc_oauth_state"] = state
    redirect_uri = gsc_oauth_redirect_uri()
    session["gsc_oauth_redirect_uri"] = redirect_uri
    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GSC_SCOPE,
        "access_type": "offline",
        "state": state,
        "prompt": "consent",
    }
    auth_url = requests.Request("GET", GOOGLE_OAUTH_AUTH_URL, params=auth_params).prepare().url
    return redirect(auth_url)


@auth_bp.route("/oauth/gsc/callback")
def gsc_oauth_callback():
    from analytics_api import gsc_oauth_redirect_uri, load_gsc_oauth_client, save_gsc_user_token

    if request.args.get("state") != session.get("gsc_oauth_state"):
        return "Invalid OAuth state", 400
    code = request.args.get("code")
    if not code:
        return "OAuth code not found", 400
    client = load_gsc_oauth_client()
    if not client:
        return "OAuth client not configured", 500
    client_id, client_secret = client
    redirect_uri = session.get("gsc_oauth_redirect_uri") or gsc_oauth_redirect_uri()
    token_data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        from analytics_api import GSC_SCOPE
        from google.oauth2.credentials import Credentials

        token_res = requests.post(GOOGLE_OAUTH_TOKEN_URL, data=token_data, timeout=PLACES_TIMEOUT)
        token_res.raise_for_status()
        payload = token_res.json()
        scope_raw = payload.get("scope") or GSC_SCOPE
        scopes = scope_raw.split() if isinstance(scope_raw, str) else [GSC_SCOPE]
        creds = Credentials(
            token=payload.get("access_token"),
            refresh_token=payload.get("refresh_token"),
            token_uri=GOOGLE_OAUTH_TOKEN_URL,
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
        )
        path = save_gsc_user_token(creds)
        session.pop("gsc_oauth_state", None)
        session.pop("gsc_oauth_redirect_uri", None)
        return (
            f"<p>GSC API 토큰 저장됨: <code>{path}</code></p>"
            f"<p><a href='/gsc'>GSC 분석으로</a></p>",
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )
    except requests.RequestException as e:
        return f"Token exchange failed: {e}", 502


@auth_bp.route("/local-login")
def local_login():
    """로컬 전용 바로가기 (Google OAuth 우회)."""
    if os.environ.get("K_SERVICE") is not None:
        return "Cloud Run에서는 /login (Google OAuth)을 사용하세요.", 404
    dev_email = (os.environ.get("DEV_LOGIN_EMAIL") or "").strip().lower()
    if not dev_email:
        dev_email = next(iter(ALLOWED_EMAILS), "")
    if not is_allowed_email(dev_email):
        return "허용되지 않은 DEV_LOGIN_EMAIL", 403
    session["user_email"] = dev_email
    return redirect(url_for("pages.dashboard"))
