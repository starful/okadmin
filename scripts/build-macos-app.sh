#!/bin/bash
# macOS 더블클릭용 OK Admin.app (앱 창) / OK Admin Dev.app (브라우저)
set -euo pipefail

OKADMIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${OKADMIN_ROOT}/mac"
INSTALL=0

for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=1 ;;
    -h|--help)
      echo "Usage: $0 [--install]"
      echo "  OK Admin.app      — 네이티브 창 (사용)"
      echo "  OK Admin Dev.app  — 브라우저 (개발)"
      echo "  OK Admin Stop.app — 서버 종료"
      exit 0
      ;;
  esac
done

mkdir -p "${OUT_DIR}"

LAUNCHER_BIN="${OUT_DIR}/.okadmin-launch-stub"
compile_launcher() {
  if [[ ! -f "${LAUNCHER_BIN}" ]] || [[ "${OKADMIN_ROOT}/scripts/okadmin_launcher.c" -nt "${LAUNCHER_BIN}" ]]; then
    clang -O2 -Wall -Wextra -o "${LAUNCHER_BIN}" "${OKADMIN_ROOT}/scripts/okadmin_launcher.c"
  fi
}

install_app_launcher() {
  local app="$1"
  local exe_name="$2"
  compile_launcher
  cp "${LAUNCHER_BIN}" "${app}/Contents/MacOS/${exe_name}"
  chmod +x "${app}/Contents/MacOS/${exe_name}" "${app}/Contents/Resources/${exe_name}.sh"
}

sign_app_bundle() {
  local app="$1"
  local bundle_id="$2"
  local exe
  exe="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "${app}/Contents/Info.plist" 2>/dev/null || true)"
  codesign --remove-signature "${app}" 2>/dev/null || true
  if [[ -n "${exe}" && -f "${app}/Contents/MacOS/${exe}" ]]; then
    codesign --force --sign - --identifier "${bundle_id}" "${app}/Contents/MacOS/${exe}" 2>/dev/null || true
  fi
  codesign --force --sign - --identifier "${bundle_id}" "${app}" 2>/dev/null || true
}

register_app_bundle() {
  local app="$1"
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "${app}" 2>/dev/null || true
}

PYTHON="$(okadmin_resolve_python 2>/dev/null || echo /opt/homebrew/bin/python3)"
if [[ -x "${OKADMIN_ROOT}/scripts/okadmin_env.sh" ]]; then
  # shellcheck source=okadmin_env.sh
  source "${OKADMIN_ROOT}/scripts/okadmin_env.sh"
  okadmin_env_init "${OKADMIN_ROOT}"
  PYTHON="$(okadmin_resolve_python)"
fi
"${PYTHON}" "${OKADMIN_ROOT}/scripts/generate-macos-icon.py"

build_start_app() {
  local app="$1"
  local name="$2"
  local bundle_id="$3"
  local ui_mode="$4"
  local icon_file="$5"

  rm -rf "$app"
  mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"

  cp "${OUT_DIR}/${icon_file}.icns" "$app/Contents/Resources/${icon_file}.icns"

  printf '%s\n' "${OKADMIN_ROOT}" >"$app/Contents/Resources/okadmin-root"
  printf '%s\n' "${ui_mode}" >"$app/Contents/Resources/ui-mode"

  cat >"$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>ko</string>
  <key>CFBundleExecutable</key>
  <string>okadmin-launch</string>
  <key>CFBundleIconFile</key>
  <string>${icon_file}</string>
  <key>CFBundleIdentifier</key>
  <string>${bundle_id}</string>
  <key>CFBundleName</key>
  <string>${name}</string>
  <key>CFBundleDisplayName</key>
  <string>${name}</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.5</string>
  <key>CFBundleVersion</key>
  <string>5</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>LSMinimumSystemVersion</key>
  <string>11.0</string>
</dict>
</plist>
PLIST

  if [[ "${ui_mode}" == "app" ]]; then
    printf '%s\n' "${PYTHON}" >"$app/Contents/Resources/python-path"
    cat >"$app/Contents/Resources/okadmin-launch.sh" <<'LAUNCH'
#!/bin/bash
set -euo pipefail
APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OKADMIN_ROOT="$(tr -d '\r\n' < "${APP_ROOT}/Resources/okadmin-root" || true)"
PYTHON="$(tr -d '\r\n' < "${APP_ROOT}/Resources/python-path" 2>/dev/null || true)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
if [[ -z "${OKADMIN_ROOT}" || ! -d "${OKADMIN_ROOT}" ]]; then
  OKADMIN_ROOT="/opt/work/okadmin"
fi
if [[ -z "${PYTHON}" || ! -x "${PYTHON}" ]]; then
  for c in "${OKADMIN_ROOT}/.venv/bin/python" "/opt/homebrew/bin/python3" "/usr/local/bin/python3"; do
    if [[ -x "$c" ]]; then PYTHON="$c"; break; fi
  done
fi
if [[ -z "${PYTHON}" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
if [[ -z "${PYTHON}" || ! -x "${PYTHON}" ]]; then
  osascript -e 'display alert "OK Admin" message "Python3 를 찾을 수 없습니다." as critical' 2>/dev/null || true
  exit 1
fi
export OKADMIN_APP_ROOT="${APP_ROOT}"
exec "${PYTHON}" "${OKADMIN_ROOT}/scripts/okadmin_app_entry.py"
LAUNCH
    install_app_launcher "$app" "okadmin-launch"
  else
    cat >"$app/Contents/Resources/okadmin-launch.sh" <<'LAUNCH'
#!/bin/bash
set -euo pipefail
APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OKADMIN_ROOT="$(cat "${APP_ROOT}/Resources/okadmin-root" 2>/dev/null | tr -d '\r\n' || true)"
if [[ -z "${OKADMIN_ROOT}" || ! -d "${OKADMIN_ROOT}" ]]; then
  OKADMIN_ROOT="/opt/work/okadmin"
fi
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"
exec "${OKADMIN_ROOT}/scripts/okadmin_launch.sh" browser
LAUNCH
    install_app_launcher "$app" "okadmin-launch"
  fi
  sign_app_bundle "$app" "${bundle_id}"
}

build_stop_app() {
  local app="${OUT_DIR}/OK Admin Stop.app"
  rm -rf "$app"
  mkdir -p "$app/Contents/Resources" "$app/Contents/MacOS"
  cp "${OUT_DIR}/AppIconStop.icns" "$app/Contents/Resources/AppIconStop.icns"

  cat >"$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>okadmin-stop</string>
  <key>CFBundleIconFile</key>
  <string>AppIconStop</string>
  <key>CFBundleIdentifier</key>
  <string>net.okseries.okadmin.stop</string>
  <key>CFBundleName</key>
  <string>OK Admin Stop</string>
  <key>CFBundleDisplayName</key>
  <string>OK Admin Stop</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.2</string>
</dict>
</plist>
PLIST

  cat >"$app/Contents/Resources/okadmin-stop.sh" <<'STOP'
#!/bin/bash
PORT="${PORT:-8090}"
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-/usr/bin:/bin}"
if lsof -i ":${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  kill $(lsof -i ":${PORT}" -sTCP:LISTEN -t) 2>/dev/null || true
  /usr/bin/osascript -e 'display notification "서버 종료됨" with title "OK Admin"' 2>/dev/null || true
else
  /usr/bin/osascript -e 'display notification "실행 중인 서버 없음" with title "OK Admin"' 2>/dev/null || true
fi
STOP
  install_app_launcher "$app" "okadmin-stop"
  sign_app_bundle "$app" "net.okseries.okadmin.stop"
}

build_start_app "${OUT_DIR}/OK Admin.app" "OK Admin" "net.okseries.okadmin" "app" "AppIcon"
build_start_app "${OUT_DIR}/OK Admin Dev.app" "OK Admin Dev" "net.okseries.okadmin.dev" "browser" "AppIconDev"
build_stop_app

chmod +x "${OKADMIN_ROOT}/scripts/okadmin_launch.sh"

echo "✅ ${OUT_DIR}/OK Admin.app       (네이티브 창 · 사용)"
echo "✅ ${OUT_DIR}/OK Admin Dev.app   (브라우저 · 개발)"
echo "✅ ${OUT_DIR}/OK Admin Stop.app"
echo ""
echo "앱 창 모드: pywebview 필요"
echo "  ${OKADMIN_ROOT}/scripts/okadmin_env.sh  # 또는:"
echo "  /opt/homebrew/bin/python3 -m pip install pywebview pyobjc-framework-WebKit pyobjc-framework-Cocoa"
echo ""
echo "로그: ~/Library/Logs/okadmin/server.log"

if [[ "$INSTALL" -eq 1 ]]; then
  for app in "OK Admin.app" "OK Admin Dev.app" "OK Admin Stop.app"; do
    rm -rf "${HOME}/Applications/${app}"
    cp -R "${OUT_DIR}/${app}" "${HOME}/Applications/"
  done
  for app in "OK Admin.app" "OK Admin Dev.app" "OK Admin Stop.app"; do
    xattr -cr "${HOME}/Applications/${app}" 2>/dev/null || true
    case "$app" in
      "OK Admin.app") sign_app_bundle "${HOME}/Applications/${app}" "net.okseries.okadmin" ;;
      "OK Admin Dev.app") sign_app_bundle "${HOME}/Applications/${app}" "net.okseries.okadmin.dev" ;;
      "OK Admin Stop.app") sign_app_bundle "${HOME}/Applications/${app}" "net.okseries.okadmin.stop" ;;
    esac
    register_app_bundle "${HOME}/Applications/${app}"
    touch "${HOME}/Applications/${app}"
  done
  echo ""
  echo "📦 ~/Applications 에 설치됨"
  echo "   아이콘이 안 바뀌면 Dock에서 앱 제거 후 다시 추가"
fi
