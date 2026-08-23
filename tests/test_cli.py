import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from toolsapi_worker.cli import main


class CliTests(unittest.TestCase):
    def test_status(self):
        output = io.StringIO()
        with patch.dict("os.environ", {}, clear=True), redirect_stdout(output):
            code = main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("installed, credentials pending", output.getvalue())
        self.assertIn("device=cpu", output.getvalue())
        self.assertIn("models=small", output.getvalue())

    def test_no_command_prints_help(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([])
        self.assertEqual(code, 0)
        self.assertIn("usage:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
