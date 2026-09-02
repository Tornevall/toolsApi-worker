import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


@unittest.skipUnless(os.name == "nt", "Windows service regression tests")
class WindowsServiceRegistrationTest(unittest.TestCase):
    def setUp(self):
        from toolsapi_worker import windows_service

        self.service = windows_service

    def test_prepare_service_host_keeps_runtime_files_under_exec_prefix(self):
        host = self.service.prepare_service_host()

        self.assertTrue(host.is_file())
        self.assertEqual(Path(sys.exec_prefix).resolve(), host.parent.resolve())

        python_dll = self.service._python_runtime_dll()
        self.assertTrue((host.parent / python_dll.name).is_file())

        pywintypes_dll = self.service._pywintypes_runtime_dll()
        self.assertTrue((host.parent / pywintypes_dll.name).is_file())

    def test_store_python_sources_are_copied_to_worker_controlled_host_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            protected = root / "Program Files" / "WindowsApps" / "PythonSoftwareFoundation.Python.3.10_test"
            package = root / "site-packages" / "win32"
            pywin32_system32 = root / "site-packages" / "pywin32_system32"
            target = root / "ProgramData" / "Tornevall" / "toolsapi-worker" / ".venv"
            protected.mkdir(parents=True)
            package.mkdir(parents=True)
            pywin32_system32.mkdir(parents=True)
            target.mkdir(parents=True)

            service_host = package / "pythonservice.exe"
            python_dll = protected / "python310.dll"
            pywintypes_dll = pywin32_system32 / "pywintypes310.dll"
            service_host.write_bytes(b"service-host")
            python_dll.write_bytes(b"python-runtime")
            pywintypes_dll.write_bytes(b"pywintypes-runtime")

            with mock.patch.object(sys, "exec_prefix", str(target)), mock.patch.object(
                self.service, "_pythonservice_source", return_value=service_host
            ), mock.patch.object(
                self.service, "_python_runtime_dll", return_value=python_dll
            ), mock.patch.object(
                self.service, "_pywintypes_runtime_dll", return_value=pywintypes_dll
            ):
                host = self.service.prepare_service_host()

            self.assertEqual(target / "pythonservice.exe", host)
            self.assertEqual(b"service-host", host.read_bytes())
            self.assertEqual(b"python-runtime", (target / "python310.dll").read_bytes())
            self.assertEqual(b"pywintypes-runtime", (target / "pywintypes310.dll").read_bytes())
            self.assertEqual(b"python-runtime", python_dll.read_bytes())
            self.assertEqual(b"pywintypes-runtime", pywintypes_dll.read_bytes())

    def test_main_passes_explicit_service_host_to_pywin32(self):
        host = Path(sys.exec_prefix) / "pythonservice.exe"
        previous = getattr(self.service.ToolsApiWorkerService, "_exe_name_", None)
        try:
            with mock.patch.object(self.service, "prepare_service_host", return_value=host), mock.patch.object(
                self.service.win32serviceutil, "HandleCommandLine", return_value=0
            ) as handle:
                self.service.main(argv=["windows_service.py", "install"])

            self.assertEqual(str(host), self.service.ToolsApiWorkerService._exe_name_)
            handle.assert_called_once_with(
                self.service.ToolsApiWorkerService,
                argv=["windows_service.py", "install"],
            )
        finally:
            self.service.ToolsApiWorkerService._exe_name_ = previous

    def test_main_propagates_pywin32_registration_failure(self):
        host = Path(sys.exec_prefix) / "pythonservice.exe"
        previous = getattr(self.service.ToolsApiWorkerService, "_exe_name_", None)
        try:
            with mock.patch.object(self.service, "prepare_service_host", return_value=host), mock.patch.object(
                self.service.win32serviceutil, "HandleCommandLine", return_value=5
            ):
                with self.assertRaises(SystemExit) as raised:
                    self.service.main(argv=["windows_service.py", "install"])

            self.assertEqual(5, raised.exception.code)
        finally:
            self.service.ToolsApiWorkerService._exe_name_ = previous


if __name__ == "__main__":
    unittest.main()
