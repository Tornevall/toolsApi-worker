import unittest
from pathlib import Path


class InstallationAudioRuntimeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]

    def read(self, path):
        return (self.root / path).read_text(encoding="utf-8")

    def test_linux_installer_provisions_ffmpeg_and_validates_torchcodec(self):
        installer = self.read("scripts/install.sh")
        self.assertIn('scripts/ensure-ffmpeg.sh', installer)
        self.assertIn('-m toolsapi_worker.audio_runtime', installer)

    def test_macos_installer_provisions_ffmpeg_and_validates_torchcodec(self):
        installer = self.read("scripts/install-macos.sh")
        self.assertIn('scripts/ensure-ffmpeg.sh', installer)
        self.assertIn('-m toolsapi_worker.audio_runtime', installer)

    def test_macos_installer_replaces_stale_launchd_registration(self):
        installer = self.read("scripts/install-macos.sh")
        self.assertIn('SERVICE_TARGET="${DOMAIN}/${PLIST_LABEL}"', installer)
        self.assertIn('launchctl bootout "${SERVICE_TARGET}"', installer)
        self.assertIn('launchctl bootout "${DOMAIN}" "${PLIST_FILE}"', installer)
        self.assertIn('launchctl remove "${PLIST_LABEL}"', installer)
        self.assertIn('wait_for_launchd_removal', installer)
        self.assertIn('launchctl print "${SERVICE_TARGET}"', installer)
        self.assertIn('Do not rerun this per-user installer as root.', installer)

        uninstaller = self.read("scripts/uninstall-macos.sh")
        self.assertIn('launchctl bootout "${SERVICE_TARGET}"', uninstaller)
        self.assertIn('launchctl remove "${PLIST_LABEL}"', uninstaller)

    def test_local_make_install_uses_same_audio_runtime_validation(self):
        makefile = self.read("Makefile")
        self.assertIn('bash ./scripts/ensure-ffmpeg.sh', makefile)
        self.assertIn('-m toolsapi_worker.audio_runtime', makefile)

    def test_windows_installer_repairs_with_checksum_verified_shared_ffmpeg(self):
        installer = self.read("scripts/install-windows.ps1")
        self.assertIn('ffmpeg-master-latest-$ArchName-lgpl-shared.zip', installer)
        self.assertIn('BtbN/FFmpeg-Builds/releases/download/latest', installer)
        self.assertIn('checksums.sha256', installer)
        self.assertIn('Get-FileHash -Path $ArchivePath -Algorithm SHA256', installer)
        self.assertIn('TOOLS_WORKER_FFMPEG_BIN_DIR', installer)
        self.assertIn('-m toolsapi_worker.audio_runtime', installer)
        self.assertIn('avcodec-*.dll', installer)
        self.assertIn('Start-Process', installer)
        self.assertIn('RedirectStandardOutput $StdoutPath', installer)
        self.assertIn('RedirectStandardError $StderrPath', installer)
        self.assertIn('Success = ($Process.ExitCode -eq 0)', installer)
        self.assertNotIn('$Output = @(& $VenvPython -m toolsapi_worker.audio_runtime 2>&1)', installer)
        stop_index = installer.index('Stopping $ServiceName before updating the worker runtime')
        pip_index = installer.index('Could not update pip, setuptools and wheel')
        self.assertLess(stop_index, pip_index)

    def test_start_bat_self_elevates_then_updates_and_installs(self):
        start = self.read("start.bat")
        self.assertIn('fltmc >nul 2>&1', start)
        self.assertIn('if "%errorlevel%"=="0" goto elevated', start)
        self.assertIn(':elevated', start)
        self.assertIn('-Verb RunAs', start)
        self.assertNotIn('if errorlevel 1 (', start)
        self.assertIn('git pull --ff-only', start)
        self.assertIn('.\\scripts\\install-windows.ps1', start)
        self.assertIn('Administrator elevation was cancelled or failed.', start)


if __name__ == "__main__":
    unittest.main()
