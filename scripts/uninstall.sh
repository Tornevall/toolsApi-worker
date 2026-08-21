#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-/opt/toolsapi-worker}"
CONFIG_DIR="${CONFIG_DIR:-/etc/toolsapi-worker}"
SERVICE_NAME="${SERVICE_NAME:-toolsapi-worker}"
SERVICE_USER="${SERVICE_USER:-toolsapi-worker}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "uninstall.sh must run as root" >&2
  exit 1
fi

systemctl disable --now "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
rm -rf "${PREFIX}"

if [[ "${REMOVE_CONFIG:-false}" == "true" ]]; then
  rm -rf "${CONFIG_DIR}"
fi

if id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  userdel "${SERVICE_USER}" || true
fi

echo "Uninstalled ${SERVICE_NAME}. Configuration retained unless REMOVE_CONFIG=true was used."
