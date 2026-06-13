# macOS 앱처럼 쓰기

## 앱 2종

| 앱 | 용도 | UI |
|----|------|-----|
| **OK Admin.app** | 평소 사용 | **네이티브 창** (주소창 없음, Dock에 앱처럼 유지) |
| **OK Admin Dev.app** | 개발·디버그 | **브라우저** 탭으로 열림 |
| **OK Admin Stop.app** | 종료 | 8090 서버 종료 |

앱 창을 닫으면 **서버도 함께 종료**됩니다 (Dev 브라우저 모드는 서버 유지).

## 설치

```bash
cd /opt/work/okadmin
/opt/homebrew/bin/python3 -m pip install pywebview pyobjc-framework-WebKit pyobjc-framework-Cocoa
./scripts/build-macos-app.sh --install
```

`~/Applications`에 3개 앱이 복사됩니다. Dock에 **OK Admin**만 고정해 두면 됩니다.

## 첫 실행

macOS 보안 경고 → 앱 **우클릭 → 열기** (1회).

## pywebview 없을 때

**OK Admin.app**은 Chrome **앱 창**(프레임 없음)으로 대체됩니다. Chrome이 없으면 일반 브라우저로 열립니다.

## 터미널

```bash
./scripts/okadmin_launch.sh app      # 앱 창
./scripts/okadmin_launch.sh browser  # 브라우저
./restart.sh
```

로그: `~/Library/Logs/okadmin/server.log`
