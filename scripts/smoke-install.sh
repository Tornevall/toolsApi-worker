#!/usr/bin/env bash
set -euo pipefail

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "${TMP_ROOT}"' EXIT

python3 -m venv "${TMP_ROOT}/venv"
"${TMP_ROOT}/venv/bin/python" -m pip install --upgrade pip >/dev/null
"${TMP_ROOT}/venv/bin/python" -m pip install . >/dev/null
"${TMP_ROOT}/venv/bin/toolsapi-worker" status | grep -q 'installed, credentials pending'
"${TMP_ROOT}/venv/bin/toolsapi-worker" status | grep -q 'device=cpu'
"${TMP_ROOT}/venv/bin/toolsapi-worker" status | grep -q 'models=large,turbo,medium,small,base,tiny'

echo "Package smoke install passed."
