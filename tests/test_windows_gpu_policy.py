import os
import subprocess
import unittest
from pathlib import Path


class WindowsGpuPolicyTest(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows PowerShell policy test")
    def test_pascal_and_modern_gpu_policy(self):
        root = Path(__file__).resolve().parents[1]
        policy = root / "scripts" / "windows-gpu-policy.ps1"
        self.assertTrue(policy.is_file())

        command = (
            f'. "{policy}"; '
            '$pascalType = Select-CTranslate2ComputeType -SupportedTypes @("float32", "int8_float32"); '
            '$modernType = Select-CTranslate2ComputeType -SupportedTypes @("float32", "int8_float32", "int8_float16", "float16"); '
            '$pascalLegacy = Test-NvidiaNeedsCuda126PyTorch -ComputeCapability "6.1"; '
            '$turingLegacy = Test-NvidiaNeedsCuda126PyTorch -ComputeCapability "7.5"; '
            '$autoIndex = Resolve-PyTorchIndexUrl -RequestedIndexUrl "" -ComputeCapability "6.1"; '
            '$overrideIndex = Resolve-PyTorchIndexUrl -RequestedIndexUrl "https://example.test/custom" -ComputeCapability "6.1"; '
            '$repairFailedInstall = Test-CanRepairGeneratedCudaDefault -FreshConfig $false -ServiceExists $false -BaseUrl "https://tools.example.test" -WorkerToken "" -WhisperDevice "cuda" -WhisperComputeType "float16"; '
            '$preserveConfigured = Test-CanRepairGeneratedCudaDefault -FreshConfig $false -ServiceExists $true -BaseUrl "https://tools.example.test" -WorkerToken "" -WhisperDevice "cuda" -WhisperComputeType "float16"; '
            '$preserveCredential = Test-CanRepairGeneratedCudaDefault -FreshConfig $false -ServiceExists $false -BaseUrl "https://tools.example.test" -WorkerToken "configured-secret" -WhisperDevice "cuda" -WhisperComputeType "float16"; '
            'Write-Output "$pascalType|$modernType|$pascalLegacy|$turingLegacy|$autoIndex|$overrideIndex|$repairFailedInstall|$preserveConfigured|$preserveCredential"'
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            "int8_float32|float16|True|False|https://download.pytorch.org/whl/cu126|https://example.test/custom|True|False|False",
            completed.stdout.strip(),
        )

    def test_installer_uses_selected_compute_type_and_kernel_probe(self):
        root = Path(__file__).resolve().parents[1]
        installer = (root / "scripts" / "install-windows.ps1").read_text(encoding="utf-8")

        self.assertIn("Select-CTranslate2ComputeType", installer)
        self.assertIn("Test-CanRepairGeneratedCudaDefault", installer)
        self.assertIn("Recovered stale installer-generated CUDA compute type", installer)
        self.assertIn("get_supported_compute_types('cuda')", installer)
        self.assertIn('"torch", "torchaudio", "torchcodec"', installer)
        self.assertIn("x=torch.ones(1, device='cuda')", installer)
        self.assertIn("nvidia-smi only confirms the NVIDIA driver", installer)
        self.assertNotIn('Set-EnvValue -Name "TOOLS_WORKER_WHISPER_COMPUTE_TYPE" -Value "float16"', installer)

        torch_install = installer.index('"torch", "torchaudio", "torchcodec"')
        worker_install = installer.index('$InstallTarget = "$SourceDir[whisper,windows]"')
        self.assertLess(torch_install, worker_install)

    def test_installer_places_pywin32_options_before_service_action(self):
        root = Path(__file__).resolve().parents[1]
        installer = (root / "scripts" / "install-windows.ps1").read_text(encoding="utf-8")

        self.assertIn("toolsapi_worker.windows_service --startup auto update", installer)
        self.assertIn("toolsapi_worker.windows_service --startup auto install", installer)
        self.assertNotIn("toolsapi_worker.windows_service update --startup auto", installer)
        self.assertNotIn("toolsapi_worker.windows_service install --startup auto", installer)

    def test_installer_avoids_windowsapps_python_alias(self):
        root = Path(__file__).resolve().parents[1]
        installer = (root / "scripts" / "install-windows.ps1").read_text(encoding="utf-8")

        self.assertIn("function Test-PythonCommand", installer)
        self.assertIn('Contains("\\microsoft\\windowsapps\\")', installer)
        self.assertIn("Microsoft Store app execution alias is not sufficient", installer)

        py_probe = installer.index("Get-Command py")
        python_probe = installer.index("Get-Command python")
        self.assertLess(py_probe, python_probe)

    def test_whisper_extras_include_audio_runtime_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        project = (root / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('"torch>=2.8"', project)
        self.assertIn('"torchaudio>=2.8"', project)
        self.assertIn('"torchcodec>=0.7"', project)


if __name__ == "__main__":
    unittest.main()
