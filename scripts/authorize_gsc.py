#!/usr/bin/env python3
"""One-time OAuth: save Search Console API user token (webmasters.readonly)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

OKADMIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OKADMIN_ROOT))

from analytics_api import GSC_SCOPE, gsc_client_secrets_path, gsc_user_token_path, save_gsc_user_token

REDIRECT_URI = os.environ.get(
    "GSC_OAUTH_REDIRECT_URI", "http://127.0.0.1:8090/oauth/gsc/callback"
)


def main() -> int:
    secrets = gsc_client_secrets_path()
    if not secrets.is_file():
        print(f"Missing client secrets: {secrets}", file=sys.stderr)
        return 1
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        print("pip install google-auth-oauthlib", file=sys.stderr)
        return 1

    flow = Flow.from_client_secrets_file(
        str(secrets),
        scopes=[GSC_SCOPE],
        redirect_uri=REDIRECT_URI,
    )
    print(f"Open browser (redirect: {REDIRECT_URI})")
    print(f"GCP OAuth client에 redirect URI 등록 필요")
    creds = flow.run_local_server(port=8090, open_browser=True, prompt="consent")
    out = save_gsc_user_token(creds)
    print(f"Saved → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
