# Phase 2 — Work Hub

## 범위 (완료)

| 항목 | 설명 |
|------|------|
| **okadmin/ops** | Auto Register 스크립트·state·logs (`config.OPS_ROOT`) |
| **GSC 허브** (`/gsc`) | 사이트 선택 시 GSC·GA4 자동 로드, N개 URL SEO 작업(Gemini+MD 반영) |
| **GSC CSV 아카이브** | 수동 export: `okadmin/data/gsc_archive/` (구 `/opt/work/tmp_gsc*`) |
| **GSC/GA4 API** | 서비스 계정(`GOOGLE_APPLICATION_CREDENTIALS`) + `sites.yaml` `analytics` |
| **sites.yaml** | `links.gsc`, `analytics.gsc_site_url`, `analytics.ga4_property_id` |
| **운영 · 콘텐츠** (`/ops`) | 원클릭 파이프라인 · 주간 예정표 (구 `/content` 통합) |
| **대시보드** | `links.gsc` 버튼 (기존) |

## 제외

- Git 커밋 → 달력 자동 시드
- Cloud Run 전체 `WORK_ROOT` 마운트 배포 (Dockerfile만 유지, 낮은 우선순위)

## GSC / GA4 API

- **GSC**: Search Console API → 최근 28일 페이지별 데이터 → 저CTR·고노출 필터
- **GA4**: Data API → 최근 28일 세션·사용자·페이지뷰 (일별 + 합계)
- Search Console / GA4 속성에 Firebase 서비스 계정 **뷰어** 추가

## 액션 큐

- 컬렉션: `work_hub_gsc_actions`
- POST 시 `add_to_calendar: true` + `start_at`(선택) → `work_hub_ops_events`에 `kind: gsc` 이벤트 생성

## API 자격 증명

```bash
export GOOGLE_APPLICATION_CREDENTIALS=secrets/firebase-key.json
```

Search Console · GA4 속성에 `client_email`(서비스 계정) 추가.  
OAuth 대안: http://127.0.0.1:8090/oauth/gsc/setup

`sites.yaml` 예:

```yaml
analytics:
  gsc_site_url: https://example.com/
  ga4_property_id: "123456789"   # 숫자 Property ID
links:
  gsc: https://search.google.com/search-console?resource_id=...
```

## 콘텐츠 작업

`config.CONTENT_JOBS` — 각 사이트 repo `WORK_ROOT`에서 subprocess 실행. 로그: `okadmin/data/content_logs/`.
