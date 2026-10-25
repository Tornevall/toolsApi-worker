import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class WindowsStartupSourceContractTests(unittest.TestCase):
    def test_start_bat_verifies_service_after_installer(self):
        launcher = (ROOT / "start.bat").read_text(encoding="utf-8").lower()
        self.assertIn("scripts\\install-windows.ps1", launcher)
        self.assertIn("scripts\\verify-windows-service.ps1", launcher)
        self.assertIn("worker service verification failed", launcher)

    def test_verifier_does_not_claim_remote_readiness(self):
        verifier = (ROOT / "scripts" / "verify-windows-service.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-Service", verifier)
        self.assertIn("Get-CimInstance Win32_Process", verifier)
        self.assertIn("toolsapi_worker.cli run", verifier)
        self.assertIn("Remote ToolsAPI heartbeat is not proven", verifier)
        self.assertIn("worker-runtime.log", verifier)

    def test_service_redirects_worker_output_and_rotates_log(self):
        source = (ROOT / "src" / "toolsapi_worker" / "windows_service.py").read_text(encoding="utf-8")
        self.assertIn("stdout=output", source)
        self.assertIn("stderr=subprocess.STDOUT", source)
        self.assertIn('log_path.with_suffix(".previous.log")', source)
        self.assertIn('Path(env_file).parent / "logs" / "worker-runtime.log"', source)


@unittest.skipUnless(sys.platform == "win32", "Native Windows subprocess test")
class WindowsStartupRuntimeTests(unittest.TestCase):
    def test_child_stdout_and_stderr_are_retained(self):
        from toolsapi_worker.windows_service import launch_worker_process

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "logs" / "worker-runtime.log"
            child = launch_worker_process(
                [sys.executable, "-c",
                 "import sys; print('stdout probe'); print('stderr probe', file=sys.stderr)"],
                0,
                log_path,
            )
            self.assertEqual(0, child.wait(timeout=20))
            text = log_path.read_text(encoding="utf-8")
            self.assertIn("Starting ToolsAPI worker polling process", text)
            self.assertIn("stdout probe", text)
            self.assertIn("stderr probe", text)

    def test_large_old_log_is_rotated_before_relaunch(self):
        import toolsapi_worker.windows_service as windows_service

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "worker-runtime.log"
            log_path.write_text("X" * 150, encoding="utf-8")
            with patch.object(windows_service, "WORKER_LOG_MAX_BYTES", 100):
                child = windows_service.launch_worker_process(
                    [sys.executable, "-c", "print('new process')"],
                    0,
                    log_path,
                )
                self.assertEqual(0, child.wait(timeout=20))
            self.assertEqual(
                "X" * 150,
                log_path.with_suffix(".previous.log").read_text(encoding="utf-8"),
            )
            self.assertIn("new process", log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
