#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-${HOME}/.local/toolsapi-worker}"
ENV_FILE="${ENV_FILE:-${PREFIX}/.env}"
PLIST_LABEL="${PLIST_LABEL:-net.tornevall.toolsapi-worker}"
PLIST_DIR="${PLIST_DIR:-${HOME}/Library/LaunchAgents}"
PLIST_FILE="${PLIST_DIR}/${PLIST_LABEL}.plist"
REMOVE_CONFIG="${REMOVE_CONFIG:-false}"
DOMAIN="gui/$(id -u)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "uninstall-macos.sh only supports macOS" >&2
  exit 1
fi

launchctl bootout "${DOMAIN}" "${PLIST_FILE}" >/dev/null 2>&1 || true
rm -f "${PLIST_FILE}"

if [[ "${REMOVE_CONFIG}" == "true" ]]; then
  rm -rf "${PREFIX}"
  echo "Removed ${PLIST_LABEL}, runtime and configuration."
  exit 0
fi

SAVED_ENV=""
if [[ -f "${ENV_FILE}" ]]; then
  SAVED_ENV="$(mktemp)"
  cp "${ENV_FILE}" "${SAVED_ENV}"
fi

rm -rf "${PREFIX}"

if [[ -n "${SAVED_ENV}" ]]; then
  mkdir -p "${PREFIX}"
  mv "${SAVED_ENV}" "${ENV_FILE}"
  chmod 0600 "${ENV_FILE}"
  echo "Removed ${PLIST_LABEL} and runtime; preserved ${ENV_FILE}."
else
  echo "Removed ${PLIST_LABEL} and runtime."
fi
