#!/usr/bin/env bash
set -euo pipefail

if command -v ffmpeg >/dev/null 2>&1; then
  exit 0
fi

case "$(uname -s)" in
  Linux)
    if ! command -v apt-get >/dev/null 2>&1; then
      echo "ffmpeg is required for TorchCodec audio processing and this installer only auto-provisions it through apt on Linux." >&2
      exit 1
    fi
    if [[ "${EUID}" -eq 0 ]]; then
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg
    elif command -v sudo >/dev/null 2>&1; then
      sudo apt-get update
      sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg
    else
      echo "ffmpeg is missing and apt installation requires root or sudo." >&2
      exit 1
    fi
    ;;
  Darwin)
    if ! command -v brew >/dev/null 2>&1; then
      echo "ffmpeg is missing. Install Homebrew first so the worker installer can provision FFmpeg automatically." >&2
      exit 1
    fi
    brew install ffmpeg
    ;;
  *)
    echo "ffmpeg is required for TorchCodec audio processing on this platform." >&2
    exit 1
    ;;
esac

command -v ffmpeg >/dev/null 2>&1 || {
  echo "ffmpeg installation completed without making the executable available in PATH." >&2
  exit 1
}
