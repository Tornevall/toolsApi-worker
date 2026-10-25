import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-windows.ps1"
POLICY = ROOT / "scripts" / "windows-env-policy.ps1"


def quote_ps(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class WindowsEnvPreservationTests(unittest.TestCase):
    def test_existing_configuration_is_read_only_by_contract(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        policy = POLICY.read_text(encoding="utf-8")

        self.assertIn("if (-not $FreshConfig)", policy)
        self.assertIn("Refusing to modify existing worker .env", policy)
        self.assertIn('if ($FreshConfig -and $null -ne $ExistingService)', installer)
        self.assertIn("Restore its original configuration", installer)
        self.assertIn("if ($FreshConfig)", installer)
        self.assertIn("Copy-Item (Join-Path $SourceDir", installer)
        self.assertIn(". $EnvPolicyScript", installer)
        self.assertEqual(2, installer.count("(Get-FileHash -LiteralPath $EnvFile -Algorithm SHA256).Hash"))
        self.assertIn("if ($CurrentConfigHash -ne $ExistingConfigHash)", installer)
        self.assertNotIn("Test-CanRepairGeneratedCudaDefault", installer)
        self.assertNotIn("RepairGeneratedCudaDefault", installer)

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell tests require Windows")
    def test_existing_env_bytes_cannot_be_changed_by_writer(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_path = Path(temporary) / ".env"
            original = (
                b"# Keep comments and CRLF exactly\r\n"
                b"TOOLS_WORKER_TOKEN=existing-test-token\r\n"
                b"TOOLS_WORKER_WHISPER_COMPUTE_TYPE=float32\r\n"
            )
            env_path.write_bytes(original)
            command = (
                "$ErrorActionPreference = 'Stop'; "
                f". {quote_ps(POLICY)}; "
                f"$EnvFile = {quote_ps(env_path)}; $FreshConfig = $false; "
                "try { Set-EnvValue -Name 'TOOLS_WORKER_WHISPER_COMPUTE_TYPE' "
                "-Value 'int8_float32'; exit 99 } "
                "catch { if ($_.Exception.Message -notlike "
                "'*Refusing to modify existing worker .env*') { throw } }"
            )
            process = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, process.returncode, process.stderr)
            self.assertEqual(original, env_path.read_bytes())

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell tests require Windows")
    def test_newly_created_env_can_receive_selected_compute_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_path = Path(temporary) / ".env"
            env_path.write_text(
                "TOOLS_WORKER_WHISPER_COMPUTE_TYPE=int8\n", encoding="utf-8"
            )
            command = (
                "$ErrorActionPreference = 'Stop'; "
                f". {quote_ps(POLICY)}; "
                f"$EnvFile = {quote_ps(env_path)}; $FreshConfig = $true; "
                "Set-EnvValue -Name 'TOOLS_WORKER_WHISPER_COMPUTE_TYPE' "
                "-Value 'int8_float32'"
            )
            process = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, process.returncode, process.stderr)
            self.assertIn(
                "TOOLS_WORKER_WHISPER_COMPUTE_TYPE=int8_float32",
                env_path.read_text(encoding="utf-8-sig"),
            )


if __name__ == "__main__":
    unittest.main()
