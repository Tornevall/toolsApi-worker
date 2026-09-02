import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "detect-runtime-device.py"
SPEC = importlib.util.spec_from_file_location("toolsapi_detect_runtime_device", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class _Probe:
    def __init__(self, value=2.0):
        self.value = value

    def __add__(self, _other):
        return self

    def item(self):
        return self.value


class RuntimeDeviceDetectionTest(unittest.TestCase):
    def test_whisper_uses_cpu_when_cuda_is_not_executable(self):
        ctranslate2 = types.SimpleNamespace(
            get_cuda_device_count=lambda: 0,
            get_supported_compute_types=lambda device: {"int8", "float32"} if device == "cpu" else set(),
        )
        with patch.dict(sys.modules, {"ctranslate2": ctranslate2}):
            self.assertEqual(("cpu", "int8"), MODULE._whisper_choice())

    def test_whisper_prefers_cuda_float16_when_supported(self):
        ctranslate2 = types.SimpleNamespace(
            get_cuda_device_count=lambda: 1,
            get_supported_compute_types=lambda device: {"float16", "int8_float16"} if device == "cuda" else {"int8"},
        )
        with patch.dict(sys.modules, {"ctranslate2": ctranslate2}):
            self.assertEqual(("cuda", "float16"), MODULE._whisper_choice())

    def test_whisper_selects_supported_pascal_safe_cuda_type(self):
        ctranslate2 = types.SimpleNamespace(
            get_cuda_device_count=lambda: 1,
            get_supported_compute_types=lambda device: {"int8_float32", "float32"} if device == "cuda" else {"int8"},
        )
        with patch.dict(sys.modules, {"ctranslate2": ctranslate2}):
            self.assertEqual(("cuda", "int8_float32"), MODULE._whisper_choice())

    def test_diarization_requires_a_real_cuda_kernel(self):
        cuda = types.SimpleNamespace(is_available=lambda: True, synchronize=lambda: None)
        torch = types.SimpleNamespace(cuda=cuda, ones=lambda *_args, **_kwargs: _Probe())
        with patch.dict(sys.modules, {"torch": torch}):
            self.assertEqual("cuda", MODULE._diarization_choice())

    def test_diarization_falls_back_to_cpu_when_cuda_kernel_fails(self):
        cuda = types.SimpleNamespace(is_available=lambda: True, synchronize=lambda: None)

        def fail_kernel(*_args, **_kwargs):
            raise RuntimeError("no compatible CUDA kernel")

        torch = types.SimpleNamespace(cuda=cuda, ones=fail_kernel)
        with patch.dict(sys.modules, {"torch": torch}):
            self.assertEqual("cpu", MODULE._diarization_choice())


if __name__ == "__main__":
    unittest.main()
