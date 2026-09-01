#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-${HOME}/.local/toolsapi-worker}"
ENV_FILE="${ENV_FILE:-${PREFIX}/.env}"
PLIST_LABEL="${PLIST_LABEL:-net.tornevall.toolsapi-worker}"
PLIST_DIR="${PLIST_DIR:-${HOME}/Library/LaunchAgents}"
PLIST_FILE="${PLIST_DIR}/${PLIST_LABEL}.plist"
PYTHON="${PYTHON:-python3}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "install-macos.sh only supports macOS" >&2
  exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "Apple Silicon (arm64) is required for the MLX Whisper runtime" >&2
  exit 1
fi

command -v "${PYTHON}" >/dev/null 2>&1 || {
  echo "${PYTHON} is required" >&2
  exit 1
}

command -v ffmpeg >/dev/null 2>&1 || {
  echo "ffmpeg is required for Whisper. Install it with: brew install ffmpeg" >&2
  exit 1
}

mkdir -p "${PREFIX}" "${PLIST_DIR}" "${HOME}/Library/Logs"
"${PYTHON}" -m venv "${PREFIX}/.venv"
"${PREFIX}/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
"${PREFIX}/.venv/bin/python" -m pip install "${SOURCE_DIR}[whisper-mlx]"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${SOURCE_DIR}/.env.example" "${ENV_FILE}"
  sed -i '' \
    -e 's/^TOOLS_WORKER_ID=.*/TOOLS_WORKER_ID=macos-apple-silicon/' \
    -e 's/^TOOLS_WORKER_WHISPER_MODELS=.*/TOOLS_WORKER_WHISPER_MODELS=large-v3,turbo/' \
    -e 's/^TOOLS_WORKER_WHISPER_DEVICE=.*/TOOLS_WORKER_WHISPER_DEVICE=metal/' \
    -e 's/^TOOLS_WORKER_WHISPER_COMPUTE_TYPE=.*/TOOLS_WORKER_WHISPER_COMPUTE_TYPE=float16/' \
    "${ENV_FILE}"
fi
chmod 0600 "${ENV_FILE}"

cat > "${PREFIX}/run-worker.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
set -a
source "${ENV_FILE}"
set +a
exec "${PREFIX}/.venv/bin/toolsapi-worker" run
EOF
chmod 0755 "${PREFIX}/run-worker.sh"

python3 - "${SOURCE_DIR}/packaging/launchd/net.tornevall.toolsapi-worker.plist" "${PLIST_FILE}" "${PREFIX}" "${HOME}" <<'PY'
import sys
from pathlib import Path
from xml.sax.saxutils import escape

template_path, output_path, prefix, home = sys.argv[1:]
content = Path(template_path).read_text(encoding="utf-8")
content = content.replace("@PREFIX@", escape(prefix)).replace("@HOME@", escape(home))
Path(output_path).write_text(content, encoding="utf-8")
PY

plutil -lint "${PLIST_FILE}" >/dev/null

TOKEN="$(grep -E '^TOOLS_WORKER_TOKEN=' "${ENV_FILE}" | cut -d= -f2- || true)"
BASE_URL="$(grep -E '^TOOLS_API_BASE_URL=' "${ENV_FILE}" | cut -d= -f2- || true)"
DOMAIN="gui/$(id -u)"

launchctl bootout "${DOMAIN}" "${PLIST_FILE}" >/dev/null 2>&1 || true
if [[ -n "${TOKEN}" && -n "${BASE_URL}" && "${BASE_URL}" != "https://tools.example.test" ]]; then
  launchctl bootstrap "${DOMAIN}" "${PLIST_FILE}"
  launchctl enable "${DOMAIN}/${PLIST_LABEL}" >/dev/null 2>&1 || true
  launchctl kickstart -k "${DOMAIN}/${PLIST_LABEL}"
  echo "Installed and started ${PLIST_LABEL}."
else
  echo "Installed ${PLIST_LABEL}, but it was not started because ToolsAPI credentials are not configured."
  echo "Edit ${ENV_FILE} and rerun: make install-system"
fi

echo "Configuration: ${ENV_FILE}"
echo "Logs: ${HOME}/Library/Logs/toolsapi-worker.log and toolsapi-worker.error.log"
