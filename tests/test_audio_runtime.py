import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from toolsapi_worker import audio_runtime


class _Data:
    def __init__(self, count=1):
        self.count = count

    def numel(self):
        return self.count


class _Samples:
    def __init__(self, count=1):
        self.data = _Data(count)


class _Decoder:
    last_source = None

    def __init__(self, source):
        type(self).last_source = source

    def get_all_samples(self):
        return _Samples(1)


class _EmptyDecoder(_Decoder):
    def get_all_samples(self):
        return _Samples(0)


class AudioRuntimeTest(unittest.TestCase):
    def test_probe_decodes_generated_wav(self):
        with patch("toolsapi_worker.audio_runtime._audio_decoder_class", return_value=_Decoder):
            result = audio_runtime.validate_torchcodec_audio_runtime()

        self.assertEqual("ok", result["status"])
        self.assertTrue(hasattr(_Decoder.last_source, "read"))
        self.assertTrue(hasattr(_Decoder.last_source, "seek"))
        self.assertFalse(isinstance(_Decoder.last_source, (str, Path)))

    def test_probe_rejects_decoder_that_returns_no_samples(self):
        with patch("toolsapi_worker.audio_runtime._audio_decoder_class", return_value=_EmptyDecoder):
            with self.assertRaisesRegex(RuntimeError, "returned no samples"):
                audio_runtime.validate_torchcodec_audio_runtime()

    def test_cli_returns_nonzero_with_provider_detail_when_probe_fails(self):
        stderr = io.StringIO()
        with (
            patch(
                "toolsapi_worker.audio_runtime.validate_torchcodec_audio_runtime",
                side_effect=RuntimeError("Could not load libtorchcodec"),
            ),
            redirect_stderr(stderr),
        ):
            code = audio_runtime.main()

        self.assertEqual(2, code)
        self.assertIn("Could not load libtorchcodec", stderr.getvalue())

    def test_windows_runtime_accepts_worker_local_shared_ffmpeg_dlls(self):
        with tempfile.TemporaryDirectory() as root:
            bin_dir = Path(root)
            for name in (
                "avcodec-61.dll",
                "avformat-61.dll",
                "avutil-59.dll",
                "swresample-5.dll",
            ):
                (bin_dir / name).write_bytes(b"fake")

            handle = object()
            original_path = os.environ.get("PATH", "")
            with (
                patch("toolsapi_worker.audio_runtime.os.name", "nt"),
                patch("toolsapi_worker.audio_runtime._windows_ffmpeg_candidates", return_value=[bin_dir]),
                patch("toolsapi_worker.audio_runtime.os.add_dll_directory", return_value=handle, create=True),
                patch.dict(os.environ, {"PATH": original_path}, clear=False),
            ):
                resolved = audio_runtime.prepare_windows_ffmpeg_runtime()

            self.assertEqual(bin_dir, resolved)
            self.assertIn(handle, audio_runtime._WINDOWS_DLL_HANDLES)


if __name__ == "__main__":
    unittest.main()
