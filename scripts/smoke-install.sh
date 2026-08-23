#!/usr/bin/env bash
set -euo pipefail

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "${TMP_ROOT}"' EXIT

python3 -m venv "${TMP_ROOT}/venv"
"${TMP_ROOT}/venv/bin/python" -m pip install --upgrade pip >/dev/null
"${TMP_ROOT}/venv/bin/python" -m pip install . >/dev/null
"${TMP_ROOT}/venv/bin/toolsapi-worker" status | grep -q 'bootstrap runtime installed'

echo "Package smoke install passed."
