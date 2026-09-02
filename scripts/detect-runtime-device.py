#!/usr/bin/env python3
from __future__ import annotations


def _whisper_choice() -> tuple[str, str]:
    try:
        import ctranslate2
    except Exception:
        return "cpu", "int8"

    try:
        if int(ctranslate2.get_cuda_device_count()) > 0:
            supported = {
                str(value).strip().lower()
                for value in ctranslate2.get_supported_compute_types("cuda")
                if str(value).strip()
            }
            for compute_type in ("float16", "int8_float16", "int8_float32", "float32"):
                if compute_type in supported:
                    return "cuda", compute_type
    except Exception:
        pass

    try:
        supported_cpu = {
            str(value).strip().lower()
            for value in ctranslate2.get_supported_compute_types("cpu")
            if str(value).strip()
        }
        for compute_type in ("int8", "int8_float32", "float32"):
            if compute_type in supported_cpu:
                return "cpu", compute_type
    except Exception:
        pass

    return "cpu", "int8"


def _diarization_choice() -> str:
    try:
        import torch
        if not bool(torch.cuda.is_available()):
            return "cpu"
        probe = torch.ones(1, device="cuda") + 1
        if hasattr(torch.cuda, "synchronize"):
            torch.cuda.synchronize()
        if float(probe.item()) != 2.0:
            return "cpu"
        return "cuda"
    except Exception:
        return "cpu"


def main() -> None:
    whisper_device, whisper_compute = _whisper_choice()
    diarization_device = _diarization_choice()
    print(f"TOOLS_WORKER_WHISPER_DEVICE={whisper_device}")
    print(f"TOOLS_WORKER_WHISPER_COMPUTE_TYPE={whisper_compute}")
    print(f"TOOLS_WORKER_DIARIZATION_DEVICE={diarization_device}")


if __name__ == "__main__":
    main()
