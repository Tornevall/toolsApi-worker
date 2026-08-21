#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-/opt/toolsapi-worker}"
CONFIG_DIR="${CONFIG_DIR:-/etc/toolsapi-worker}"
ENV_FILE="${ENV_FILE:-${CONFIG_DIR}/.env}"
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

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home "${PREFIX}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

install -d -m 0755 "${PREFIX}" "${CONFIG_DIR}"
"${PYTHON}" -m venv "${PREFIX}/.venv"
"${PREFIX}/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
"${PREFIX}/.venv/bin/python" -m pip install "${SOURCE_DIR}"

# Keep one canonical runtime .env outside the application directory so upgrades
# and deploys cannot overwrite host-specific credentials or configuration.
if [[ ! -f "${ENV_FILE}" ]]; then
  install -m 0640 -o root -g "${SERVICE_USER}" "${SOURCE_DIR}/.env.example" "${ENV_FILE}"
else
  chown root:"${SERVICE_USER}" "${ENV_FILE}"
  chmod 0640 "${ENV_FILE}"
fi

# Expose the canonical host configuration at the application root as well.
# The symlink is safe to recreate and makes normal .env discovery predictable.
ln -sfn "${ENV_FILE}" "${PREFIX}/.env"

sed \
  -e "s|@PREFIX@|${PREFIX}|g" \
  -e "s|@CONFIG_DIR@|${CONFIG_DIR}|g" \
  "${SOURCE_DIR}/packaging/systemd/toolsapi-worker.service" \
  > "/etc/systemd/system/${SERVICE_NAME}.service"

chmod 0644 "/etc/systemd/system/${SERVICE_NAME}.service"
chown -R root:"${SERVICE_USER}" "${PREFIX}"
chmod -R g+rX "${PREFIX}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service" >/dev/null

TOKEN="$(grep -E '^TOOLS_WORKER_TOKEN=' "${ENV_FILE}" | cut -d= -f2- || true)"
BASE_URL="$(grep -E '^TOOLS_API_BASE_URL=' "${ENV_FILE}" | cut -d= -f2- || true)"

if [[ -n "${TOKEN}" && -n "${BASE_URL}" && "${BASE_URL}" != "https://tools.example.test" ]]; then
  systemctl restart "${SERVICE_NAME}.service"
  echo "Installed and started ${SERVICE_NAME}."
else
  echo "Installed ${SERVICE_NAME}, but it was not started because ToolsAPI credentials are not configured."
  echo "Edit ${ENV_FILE} and then run: systemctl restart ${SERVICE_NAME}"
fi
