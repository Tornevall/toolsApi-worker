#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-/opt/toolsapi-worker}"
ENV_FILE="${ENV_FILE:-${PREFIX}/.env}"
SERVICE_NAME="${SERVICE_NAME:-toolsapi-worker}"
SERVICE_USER="${SERVICE_USER:-toolsapi-worker}"
PYTHON="${PYTHON:-python3}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "install.sh must run as root" >&2
  exit 1
fi

command -v "${PYTHON}" >/dev/null 2>&1 || {
  echo "${PYTHON} is required" >&2
  exit 1
}

set_env_value() {
  local key="$1"
  local value="$2"
  local file="$3"
  if grep -q "^${key}=" "${file}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${file}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${file}"
  fi
}

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home "${PREFIX}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

install -d -m 0755 "${PREFIX}"
bash "${SOURCE_DIR}/scripts/bootstrap-venv.sh" "${PYTHON}" "${PREFIX}/.venv"
"${PREFIX}/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
"${PREFIX}/.venv/bin/python" -m pip install "${SOURCE_DIR}[whisper]"

# Keep the canonical runtime .env in the installed project directory.
# Reinstall and deploy must preserve host-specific credentials and configuration.
fresh_env=false
if [[ ! -f "${ENV_FILE}" ]]; then
  install -m 0640 -o root -g "${SERVICE_USER}" "${SOURCE_DIR}/.env.example" "${ENV_FILE}"
  fresh_env=true
else
  chown root:"${SERVICE_USER}" "${ENV_FILE}"
  chmod 0640 "${ENV_FILE}"
fi

# Fresh Ubuntu hosts select the fastest runtime that is actually executable.
# Existing .env values are never rewritten during reinstall.
if [[ "${fresh_env}" == true ]]; then
  while IFS='=' read -r key value; do
    case "${key}" in
      TOOLS_WORKER_WHISPER_DEVICE|TOOLS_WORKER_WHISPER_COMPUTE_TYPE|TOOLS_WORKER_DIARIZATION_DEVICE)
        set_env_value "${key}" "${value}" "${ENV_FILE}"
        ;;
    esac
  done < <("${PREFIX}/.venv/bin/python" "${SOURCE_DIR}/scripts/detect-runtime-device.py")
fi

sed \
  -e "s|@PREFIX@|${PREFIX}|g" \
  -e "s|@SERVICE_USER@|${SERVICE_USER}|g" \
  "${SOURCE_DIR}/packaging/systemd/toolsapi-worker.service" \
  > "/etc/systemd/system/${SERVICE_NAME}.service"

chmod 0644 "/etc/systemd/system/${SERVICE_NAME}.service"
chown -R root:"${SERVICE_USER}" "${PREFIX}"
chmod -R g+rX "${PREFIX}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service" >/dev/null

TOKEN="$(grep -E '^TOOLS_WORKER_TOKEN=' "${ENV_FILE}" | cut -d= -f2- || true)"
BASE_URL="$(grep -E '^TOOLS_API_BASE_URL=' "${ENV_FILE}" | cut -d= -f2- || true)"
WHISPER_DEVICE="$(grep -E '^TOOLS_WORKER_WHISPER_DEVICE=' "${ENV_FILE}" | cut -d= -f2- || true)"
WHISPER_COMPUTE="$(grep -E '^TOOLS_WORKER_WHISPER_COMPUTE_TYPE=' "${ENV_FILE}" | cut -d= -f2- || true)"
DIARIZATION_DEVICE="$(grep -E '^TOOLS_WORKER_DIARIZATION_DEVICE=' "${ENV_FILE}" | cut -d= -f2- || true)"

echo "Whisper runtime: ${WHISPER_DEVICE:-unknown}/${WHISPER_COMPUTE:-unknown}; diarization: ${DIARIZATION_DEVICE:-unknown}"

if [[ -n "${TOKEN}" && -n "${BASE_URL}" && "${BASE_URL}" != "https://tools.example.test" ]]; then
  systemctl restart "${SERVICE_NAME}.service"
  echo "Installed and started ${SERVICE_NAME}."
else
  echo "Installed ${SERVICE_NAME}, but it was not started because ToolsAPI credentials are not configured."
  echo "Edit ${ENV_FILE} and then run: systemctl restart ${SERVICE_NAME}"
fi
