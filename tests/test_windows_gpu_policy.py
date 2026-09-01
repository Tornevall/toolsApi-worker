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
            'Write-Output "$pascalType|$modernType|$pascalLegacy|$turingLegacy|$autoIndex|$overrideIndex"'
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            "int8_float32|float16|True|False|https://download.pytorch.org/whl/cu126|https://example.test/custom",
            completed.stdout.strip(),
        )

    def test_installer_uses_selected_compute_type_and_kernel_probe(self):
        root = Path(__file__).resolve().parents[1]
        installer = (root / "scripts" / "install-windows.ps1").read_text(encoding="utf-8")

        self.assertIn("Select-CTranslate2ComputeType", installer)
        self.assertIn("get_supported_compute_types('cuda')", installer)
        self.assertIn("torch torchaudio", installer)
        self.assertIn("x=torch.ones(1, device='cuda')", installer)
        self.assertIn("nvidia-smi only confirms the NVIDIA driver", installer)
        self.assertNotIn('Set-EnvValue -Name "TOOLS_WORKER_WHISPER_COMPUTE_TYPE" -Value "float16"', installer)


if __name__ == "__main__":
    unittest.main()
