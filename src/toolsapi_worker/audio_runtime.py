from __future__ import annotations

import io
import os
import sys
import wave
from pathlib import Path
from typing import Any

_WINDOWS_DLL_HANDLES: list[Any] = []


def _windows_ffmpeg_candidates() -> list[Path]:
    candidates: list[Path] = []

    configured = os.environ.get("TOOLS_WORKER_FFMPEG_BIN_DIR", "").strip()
    if configured:
        candidates.append(Path(configured))

    candidates.append(Path(sys.prefix) / "ffmpeg" / "bin")
    candidates.append(Path(sys.prefix).parent / "ffmpeg" / "bin")

    path_value = os.environ.get("PATH", "")
    for raw in path_value.split(os.pathsep):
        raw = raw.strip().strip('"')
        if raw:
            candidates.append(Path(raw))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def prepare_windows_ffmpeg_runtime() -> Path | None:
    if os.name != "nt":
        return None

    for candidate in _windows_ffmpeg_candidates():
        try:
            if not candidate.is_dir():
                continue
            has_avcodec = any(candidate.glob("avcodec-*.dll"))
            has_avformat = any(candidate.glob("avformat-*.dll"))
            has_avutil = any(candidate.glob("avutil-*.dll"))
            has_swresample = any(candidate.glob("swresample-*.dll"))
            if not all((has_avcodec, has_avformat, has_avutil, has_swresample)):
                continue

            if hasattr(os, "add_dll_directory"):
                _WINDOWS_DLL_HANDLES.append(os.add_dll_directory(str(candidate)))
            os.environ["PATH"] = str(candidate) + os.pathsep + os.environ.get("PATH", "")
            return candidate
        except OSError:
            continue

    return None


def _audio_decoder_class() -> Any:
    prepare_windows_ffmpeg_runtime()
    from torchcodec.decoders import AudioDecoder

    return AudioDecoder


def validate_torchcodec_audio_runtime() -> dict[str, str | None]:
    decoder_class = _audio_decoder_class()

    media = io.BytesIO()
    with wave.open(media, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)
    media.seek(0)

    decoder = decoder_class(media)
    samples = decoder.get_all_samples()
    data = getattr(samples, "data", None)
    numel = getattr(data, "numel", None)
    if data is None or not callable(numel) or int(numel()) < 1:
        raise RuntimeError("TorchCodec AudioDecoder returned no samples for the startup probe.")

    ffmpeg_bin_dir = prepare_windows_ffmpeg_runtime()
    return {
        "status": "ok",
        "ffmpeg_bin_dir": str(ffmpeg_bin_dir) if ffmpeg_bin_dir is not None else None,
    }


def main() -> int:
    try:
        result = validate_torchcodec_audio_runtime()
    except Exception as exc:  # noqa: BLE001
        print(f"TorchCodec audio runtime validation failed: {exc}", file=sys.stderr)
        return 2

    detail = "TorchCodec audio runtime validated."
    if result.get("ffmpeg_bin_dir"):
        detail += f" ffmpeg_bin_dir={result['ffmpeg_bin_dir']}"
    print(detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
