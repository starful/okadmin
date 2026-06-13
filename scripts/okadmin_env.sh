# shellcheck shell=bash
# Shared PATH + Python for start.sh and macOS launcher.
okadmin_env_init() {
  local root="${1:?okadmin root required}"
  OKADMIN_ROOT="$root"
  export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"
}

okadmin_resolve_python() {
  local root="${OKADMIN_ROOT:-}"
  if [[ -n "${OKADMIN_PYTHON:-}" && -x "${OKADMIN_PYTHON}" ]]; then
    echo "${OKADMIN_PYTHON}"
    return
  fi
  local c
  for c in \
    "${root}/.venv/bin/python" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3"; do
    if [[ -x "$c" ]] && "$c" -c "import dotenv" 2>/dev/null; then
      echo "$c"
      return
    fi
  done
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  echo "python3"
}
