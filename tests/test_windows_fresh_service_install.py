"""Regression guards for first-time Windows service installation."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WindowsFreshInstallServiceTest(unittest.TestCase):
    def test_start_batch_handles_absent_and_stopped_service(self):
        source = (ROOT / "start.bat").read_text(encoding="utf-8")
        self.assertIn("$null -eq $service", source)
        self.assertIn("$service.Status -eq 'Stopped'", source)
        self.assertIn("exit 0", source)
        self.assertIn("Stop-Service -Name 'ToolsAPIWorker' -Force", source)
        self.assertLess(source.index("Checking ToolsAPI Worker service"), source.index("Updating repository"))
        self.assertLess(source.index("Updating repository"), source.index("Installing and starting worker"))

    def test_missing_python_bootstraps_with_winget(self):
        source = (ROOT / "scripts" / "install-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("Python.Python.3.10", source)
        self.assertIn("winget.exe", source)
        self.assertIn("--accept-package-agreements", source)
        self.assertIn("--accept-source-agreements", source)
        self.assertIn("if ($LASTEXITCODE -ne 0)", source)
        self.assertIn("Test-PythonCommand -Command @($location)", source)
        self.assertLess(source.index("No usable Python 3.10+ found"), source.index("$PythonCommand = Resolve-PythonCommand"))

    def test_canonical_installer_skips_stop_on_fresh_install(self):
        source = (ROOT / "scripts" / "install-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("if ($null -eq $ExistingService)", source)
        self.assertIn('elseif ($ExistingService.Status -eq "Stopped")', source)
        self.assertIn("Stop-Service -Name $ServiceName -Force -ErrorAction Stop", source)
        self.assertLess(source.index("if ($null -eq $ExistingService)"), source.index('Invoke-ResolvedPython -Command $PythonCommand'))


if __name__ == "__main__":
    unittest.main()
