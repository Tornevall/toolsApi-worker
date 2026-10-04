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

bash "${SOURCE_DIR}/scripts/ensure-ffmpeg.sh"

FFMPEG_BIN="$(command -v ffmpeg)"
FFMPEG_DIR="$(dirname "${FFMPEG_BIN}")"
RUNTIME_PATH="${FFMPEG_DIR}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "${PREFIX}" "${PLIST_DIR}" "${HOME}/Library/Logs"
"${PYTHON}" -m venv "${PREFIX}/.venv"
"${PREFIX}/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
"${PREFIX}/.venv/bin/python" -m pip install "${SOURCE_DIR}[whisper-mlx]"
"${PREFIX}/.venv/bin/python" -m toolsapi_worker.audio_runtime

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${SOURCE_DIR}/.env.example" "${ENV_FILE}"
  sed -i '' \
    -e 's/^TOOLS_WORKER_ID=.*/TOOLS_WORKER_ID=macos-apple-silicon/' \
    -e 's/^TOOLS_WORKER_WHISPER_MODELS=.*/TOOLS_WORKER_WHISPER_MODELS=large,turbo,medium,small,base,tiny,large-v3/' \
    -e 's/^TOOLS_WORKER_WHISPER_DEVICE=.*/TOOLS_WORKER_WHISPER_DEVICE=metal/' \
    -e 's/^TOOLS_WORKER_WHISPER_COMPUTE_TYPE=.*/TOOLS_WORKER_WHISPER_COMPUTE_TYPE=float16/' \
    "${ENV_FILE}"
fi
chmod 0600 "${ENV_FILE}"

"${PYTHON}" - "${SOURCE_DIR}/packaging/launchd/net.tornevall.toolsapi-worker.plist" "${PLIST_FILE}" "${PREFIX}" "${HOME}" "${ENV_FILE}" "${RUNTIME_PATH}" <<'PY'
import sys
from pathlib import Path
from xml.sax.saxutils import escape

template_path, output_path, prefix, home, env_file, runtime_path = sys.argv[1:]
content = Path(template_path).read_text(encoding="utf-8")
content = (
    content.replace("@PREFIX@", escape(prefix))
    .replace("@HOME@", escape(home))
    .replace("@ENV_FILE@", escape(env_file))
    .replace("@RUNTIME_PATH@", escape(runtime_path))
)
Path(output_path).write_text(content, encoding="utf-8")
PY

chmod 0600 "${PLIST_FILE}"
plutil -lint "${PLIST_FILE}" >/dev/null
DOMAIN="gui/$(id -u)"
SERVICE_TARGET="${DOMAIN}/${PLIST_LABEL}"

wait_for_launchd_removal() {
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if ! launchctl print "${SERVICE_TARGET}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

unload_existing_launch_agent() {
  launchctl bootout "${SERVICE_TARGET}" >/dev/null 2>&1 || true
  launchctl bootout "${DOMAIN}" "${PLIST_FILE}" >/dev/null 2>&1 || true

  if wait_for_launchd_removal; then
    return 0
  fi

  # Older/stale launchd registrations can survive path-based bootout.
  # remove is a last-resort cleanup scoped to this worker label.
  launchctl remove "${PLIST_LABEL}" >/dev/null 2>&1 || true

  if wait_for_launchd_removal; then
    return 0
  fi

  echo "Could not unload existing launchd service ${SERVICE_TARGET}." >&2
  launchctl print "${SERVICE_TARGET}" >&2 || true
  return 1
}

bootstrap_launch_agent() {
  local bootstrap_status=0

  launchctl bootstrap "${DOMAIN}" "${PLIST_FILE}" || bootstrap_status=$?
  if [[ "${bootstrap_status}" -eq 0 ]]; then
    return 0
  fi

  echo "Failed to bootstrap launchd service ${SERVICE_TARGET} from ${PLIST_FILE} (exit ${bootstrap_status})." >&2
  echo "launchd service state:" >&2
  if ! launchctl print "${SERVICE_TARGET}" >&2; then
    echo "  ${SERVICE_TARGET} is not registered." >&2
  fi
  echo "LaunchAgent plist:" >&2
  /usr/bin/stat -f '  owner=%Su mode=%Sp path=%N' "${PLIST_FILE}" >&2 || true
  echo "Worker executable:" >&2
  /usr/bin/stat -f '  owner=%Su mode=%Sp path=%N' "${PREFIX}/.venv/bin/toolsapi-worker" >&2 || true
  echo "Do not rerun this per-user installer as root." >&2
  return "${bootstrap_status}"
}

unload_existing_launch_agent

if "${PREFIX}/.venv/bin/python" - "${ENV_FILE}" <<'PY'
import sys
from toolsapi_worker.config import WorkerConfig

config = WorkerConfig.from_env_file(sys.argv[1])
configured = bool(
    config.api_base_url
    and config.api_base_url != "https://tools.example.test"
    and config.worker_token
    and config.worker_id
)
raise SystemExit(0 if configured else 1)
PY
then
  bootstrap_launch_agent
  launchctl enable "${SERVICE_TARGET}" >/dev/null 2>&1 || true
  launchctl kickstart -k "${SERVICE_TARGET}"
  echo "Installed and started ${PLIST_LABEL}."
else
  echo "Installed ${PLIST_LABEL}, but it was not started because ToolsAPI credentials are not configured."
  echo "Edit ${ENV_FILE} and rerun: make install-system"
fi

echo "Configuration: ${ENV_FILE}"
echo "Logs: ${HOME}/Library/Logs/toolsapi-worker.log and toolsapi-worker.error.log"
