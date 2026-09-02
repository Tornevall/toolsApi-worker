#!/usr/bin/env bash
set -euo pipefail

PYTHON="${1:-${PYTHON:-python3}}"
VENV="${2:-${VENV:-.venv}}"

if ! command -v "${PYTHON}" >/dev/null 2>&1; then
  echo "${PYTHON} is required" >&2
  exit 1
fi

error_file="$(mktemp)"
trap 'rm -f "${error_file}"' EXIT

if "${PYTHON}" -m venv "${VENV}" 2>"${error_file}"; then
  exit 0
fi

if ! grep -Eqi 'ensurepip is not available|No module named ensurepip|venv package' "${error_file}"; then
  cat "${error_file}" >&2
  exit 1
fi

if [[ "$(uname -s)" != "Linux" ]] || ! command -v apt-get >/dev/null 2>&1; then
  cat "${error_file}" >&2
  echo "Python venv support is missing. Install the venv package for ${PYTHON} and retry." >&2
  exit 1
fi

if [[ "${EUID}" -eq 0 ]]; then
  APT_PREFIX=()
elif command -v sudo >/dev/null 2>&1; then
  APT_PREFIX=(sudo)
else
  cat "${error_file}" >&2
  echo "Python venv support is missing and automatic apt installation requires root or sudo." >&2
  exit 1
fi

python_version="$(${PYTHON} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
versioned_package="python${python_version}-venv"

printf 'Python venv support is missing; installing %s (fallback: python3-venv).\n' "${versioned_package}"
"${APT_PREFIX[@]}" apt-get update
if ! "${APT_PREFIX[@]}" apt-get install -y "${versioned_package}"; then
  "${APT_PREFIX[@]}" apt-get install -y python3-venv
fi

rm -rf "${VENV}"
"${PYTHON}" -m venv "${VENV}"
