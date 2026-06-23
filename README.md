# Work Hub / OK Admin

로컬 운영 허브: 사이트 레지스트리, 달력, GSC, 콘텐츠 스크립트, GCS 이미지 (Flask).

## 실행

```bash
cd /opt/work/okadmin
chmod +x start.sh scripts/fetch_secrets.sh
./start.sh   # .env / secrets 없으면 GCP Secret Manager에서 자동 pull
```

수동으로 시크릿만 다시 받을 때:

```bash
./scripts/fetch_secrets.sh
```

브라우저: **http://127.0.0.1:8090** (8080은 okcaddie 등 로컬 Flask와 겹치기 쉬움)

### macOS — 앱처럼 더블클릭

```bash
/opt/homebrew/bin/python3 -m pip install pywebview pyobjc-framework-WebKit pyobjc-framework-Cocoa
./scripts/build-macos-app.sh --install
```

| 앱 | 용도 |
|----|------|
| **OK Admin.app** | 네이티브 창 (사용) |
| **OK Admin Dev.app** | 브라우저 (개발) |
| **OK Admin Stop.app** | 서버 종료 |

상세: [mac/README.md](mac/README.md)

재기동: `./restart.sh`

## 메뉴

| 메뉴 | 설명 |
|------|------|
| 대시보드 | `/opt/work/sites.yaml` · Git · GSC 링크 |
| 달력 | Firestore `work_hub_ops_events` · FullCalendar |
| 운영 · 콘텐츠 | 사이트별 원클릭 콘텐츠 생성 · 실행 상한/요약 (`/ops`) |
| 새 OK 사이트 | oktemplate 복사 |
| GSC | Search Console / GA4 · SEO |
| GCS 이미지 | 사이트별 버킷 관리 |

Phase 2 상세: [docs/PHASE2.md](docs/PHASE2.md)

## 설정

- `WORK_ROOT` — 기본 `/opt/work`
- `SITES_YAML` — 기본 `/opt/work/sites.yaml`
- `GOOGLE_APPLICATION_CREDENTIALS` — Firestore · GA4 (선택)
- `GSC_TOKEN_PATH` — GSC API OAuth (선택, `GCAL_TOKEN_PATH` 폴백)

Cloud Run 배포 시 `WORK_ROOT`가 없으면 Git·ops·oktemplate·콘텐츠는 비활성 메시지를 표시합니다.

### 로컬 OAuth (`redirect_uri_mismatch`)

포트 **8090** 사용 시 GCP OAuth 클라이언트에 추가:

- `http://127.0.0.1:8090/oauth/callback`
- `http://localhost:8090/oauth/callback`

기본 **`LOCAL_DEV_AUTH=1`** 이면 Google 로그인 없이 접속 가능합니다.
