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

    def test_start_bat_self_elevates_then_updates_and_installs(self):
        start = self.read("start.bat")
        self.assertIn('WindowsBuiltInRole]::Administrator', start)
        self.assertIn('-Verb RunAs', start)
        self.assertIn('git pull --ff-only', start)
        self.assertIn('.\\scripts\\install-windows.ps1', start)
        self.assertIn('Administrator elevation was cancelled or failed.', start)


if __name__ == "__main__":
    unittest.main()
