import io
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from toolsapi_worker.cli import TimestampedTextStream, main
from toolsapi_worker.config import COMMON_WHISPER_MODELS


class CliTests(unittest.TestCase):
    def test_status(self):
        output = io.StringIO()
        with patch.dict("os.environ", {}, clear=True), redirect_stdout(output):
            code = main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("installed, credentials pending", output.getvalue())
        self.assertIn("device=cpu", output.getvalue())
        self.assertIn("models=" + ",".join(COMMON_WHISPER_MODELS), output.getvalue())
        self.assertFalse(output.getvalue().startswith("["))

    def test_status_loads_env_file_without_shell_evaluation(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as root:
            env_file = Path(root) / ".env"
            env_file.write_text(
                "TOOLS_API_BASE_URL=https://tools.example.test\n"
                "TOOLS_WORKER_TOKEN=12|token$with;separators\n"
                "TOOLS_WORKER_ID=mac-worker\n"
                "TOOLS_WORKER_WHISPER_DEVICE=metal\n"
                "TOOLS_WORKER_WHISPER_MODELS=large-v3,turbo\n",
                encoding="utf-8",
            )
            with patch.dict("os.environ", {}, clear=True), redirect_stdout(output):
                code = main(["status", "--env-file", str(env_file)])

        self.assertEqual(code, 0)
        self.assertIn("configured", output.getvalue())
        self.assertIn("device=metal", output.getvalue())
        self.assertIn("models=" + ",".join(COMMON_WHISPER_MODELS + ("large-v3",)), output.getvalue())

    def test_timestamped_stream_prefixes_multiline_and_partial_writes(self):
        output = io.StringIO()
        stream = TimestampedTextStream(output, timestamp_factory=lambda: "2026-09-03T09:12:34+02:00")

        self.assertEqual(stream.write("Detected "), len("Detected "))
        self.assertEqual(stream.write("language: Swedish\nnext line\n"), len("language: Swedish\nnext line\n"))
        stream.write("partial")
        stream.write(" continuation\n")

        self.assertEqual(
            output.getvalue(),
            "[2026-09-03T09:12:34+02:00] Detected language: Swedish\n"
            "[2026-09-03T09:12:34+02:00] next line\n"
            "[2026-09-03T09:12:34+02:00] partial continuation\n",
        )

    def test_run_timestamps_runtime_stdout_and_stderr(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        config = MagicMock()

        def run_forever():
            print("Detected language: Swedish")
            print("Configured speaker diarization accelerator is unavailable on this worker.", file=__import__("sys").stderr)

        with (
            patch("toolsapi_worker.cli.load_config", return_value=config),
            patch("toolsapi_worker.cli.WorkerRuntime") as runtime_class,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            runtime_class.return_value.run_forever.side_effect = run_forever
            code = main(["run"])

        self.assertEqual(code, 0)
        timestamp = r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}\] "
        self.assertRegex(stdout.getvalue(), "^" + timestamp + re.escape("Detected language: Swedish\n"))
        self.assertRegex(
            stderr.getvalue(),
            "^" + timestamp + re.escape("Configured speaker diarization accelerator is unavailable on this worker.\n"),
        )

    def test_run_timestamps_terminal_error(self):
        stderr = io.StringIO()
        config = MagicMock()

        with (
            patch("toolsapi_worker.cli.load_config", return_value=config),
            patch("toolsapi_worker.cli.WorkerRuntime") as runtime_class,
            redirect_stderr(stderr),
        ):
            runtime_class.return_value.run_forever.side_effect = RuntimeError("boom")
            code = main(["run"])

        self.assertEqual(code, 2)
        self.assertRegex(
            stderr.getvalue(),
            r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}\] toolsapi-worker: boom\n$",
        )

    def test_no_command_prints_help(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([])
        self.assertEqual(code, 0)
        self.assertIn("usage:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
