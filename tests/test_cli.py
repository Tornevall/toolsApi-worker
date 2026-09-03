import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from toolsapi_worker.cli import main
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

    def test_no_command_prints_help(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([])
        self.assertEqual(code, 0)
        self.assertIn("usage:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
