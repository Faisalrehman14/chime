#!/usr/bin/env bash
# CHIMME Chrome — dedicated profile + debug port (Chrome 136+ requirement).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${CHROME_DEBUG_PORT:-9222}"
CDP="http://127.0.0.1:${PORT}"
PROFILE="${CHROME_USER_DATA_DIR:-${ROOT}/data/chrome_cdp_profile}"
LOG="${ROOT}/data/chrome-debug.log"
FORCE="${1:-}"

mkdir -p "${ROOT}/data" "${PROFILE}"

chrome_bin() {
  for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      command -v "${candidate}"
      return 0
    fi
  done
  return 1
}

cdp_ready() {
  curl -fsS "${CDP}/json/version" >/dev/null 2>&1
}

chimme_chrome_pids() {
  pgrep -af "user-data-dir=${PROFILE}" 2>/dev/null || true
}

stop_chimme_chrome() {
  if [[ -n "$(chimme_chrome_pids)" ]]; then
    pkill -f "user-data-dir=${PROFILE}" 2>/dev/null || true
    sleep 1
    pkill -9 -f "user-data-dir=${PROFILE}" 2>/dev/null || true
    sleep 1
  fi
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" 2>/dev/null || true
  fi
}

wait_for_cdp() {
  local tries="${1:-50}"
  for _ in $(seq 1 "${tries}"); do
    if cdp_ready; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

launch_args() {
  echo "--user-data-dir=${PROFILE}"
  echo "--remote-debugging-port=${PORT}"
  echo "--remote-debugging-address=127.0.0.1"
  echo "--no-first-run"
  echo "--no-default-browser-check"
  echo "--disable-session-crashed-bubble"
  if [[ -n "${WAYLAND_DISPLAY:-}" && -z "${CHIMME_FORCE_WAYLAND:-}" ]]; then
    echo "--ozone-platform=x11"
  fi
}

if cdp_ready; then
  echo "OK — CHIMME Chrome debug port already open: ${CDP}"
  echo "Profile: ${PROFILE}"
  curl -fsS "${CDP}/json/version" | head -c 220
  echo ""
  exit 0
fi

CHROME="$(chrome_bin || true)"
if [[ -z "${CHROME}" ]]; then
  echo "ERROR: Google Chrome install nahi mila."
  exit 1
fi

if [[ -n "$(chimme_chrome_pids)" ]] || [[ "${FORCE}" == "--restart" ]]; then
  echo "Restarting CHIMME Chrome (sirf is profile ka window)..."
  stop_chimme_chrome
fi

echo ""
echo "Starting CHIMME Chrome window..."
echo "  Debug:   ${CDP}"
echo "  Profile: ${PROFILE}"
echo "  Log:     ${LOG}"
echo ""
echo "NOTE: Yeh alag Chrome window hai (aapka normal Chrome band nahi hota)."
echo "                    Isi window mein Chime kholo — claim alag tab mein khulega, dashboard tab safe rahega."
echo ""

: >"${LOG}"

mapfile -t ARGS < <(launch_args)
nohup "${CHROME}" "${ARGS[@]}" >>"${LOG}" 2>&1 &
disown 2>/dev/null || true

if wait_for_cdp 50; then
  echo "OK — Ready: ${CDP}"
  echo "Ab isi Chrome window mein Chime kholo, phir dashboard → Connect Open Chrome"
  curl -fsS "${CDP}/json/version" | head -c 220
  echo ""
  exit 0
fi

echo ""
echo "ERROR: Debug port ${PORT} open nahi hua."
echo "Last log lines:"
tail -n 25 "${LOG}" 2>/dev/null || echo "(no log)"
echo ""
echo "Retry:  ./scripts/start-chrome-debug.sh --restart"
exit 1
