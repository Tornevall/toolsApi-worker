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

        for module in (
            self.service.servicemanager,
            self.service.win32api,
            self.service.win32event,
            self.service.win32service,
        ):
            extension = self.service._pywin32_extension_file(module)
            self.assertTrue((host.parent / extension.name).is_file())

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
            servicemanager = package / "servicemanager.pyd"
            win32api = package / "win32api.pyd"
            win32event = package / "win32event.pyd"
            win32service = package / "win32service.pyd"
            service_host.write_bytes(b"service-host")
            python_dll.write_bytes(b"python-runtime")
            pywintypes_dll.write_bytes(b"pywintypes-runtime")
            servicemanager.write_bytes(b"servicemanager")
            win32api.write_bytes(b"win32api")
            win32event.write_bytes(b"win32event")
            win32service.write_bytes(b"win32service")

            with mock.patch.object(sys, "exec_prefix", str(target)), mock.patch.object(
                self.service, "_pythonservice_source", return_value=service_host
            ), mock.patch.object(
                self.service, "_python_runtime_dll", return_value=python_dll
            ), mock.patch.object(
                self.service, "_pywintypes_runtime_dll", return_value=pywintypes_dll
            ), mock.patch.object(
                self.service, "_pywin32_extension_file", side_effect=[servicemanager, win32api, win32event, win32service]
            ):
                host = self.service.prepare_service_host()

            self.assertEqual(target / "pythonservice.exe", host)
            self.assertEqual(b"service-host", host.read_bytes())
            self.assertEqual(b"python-runtime", (target / "python310.dll").read_bytes())
            self.assertEqual(b"pywintypes-runtime", (target / "pywintypes310.dll").read_bytes())
            self.assertEqual(b"servicemanager", (target / "servicemanager.pyd").read_bytes())
            self.assertEqual(b"win32api", (target / "win32api.pyd").read_bytes())
            self.assertEqual(b"win32event", (target / "win32event.pyd").read_bytes())
            self.assertEqual(b"win32service", (target / "win32service.pyd").read_bytes())
            self.assertEqual(b"python-runtime", python_dll.read_bytes())
            self.assertEqual(b"pywintypes-runtime", pywintypes_dll.read_bytes())

    def test_main_passes_explicit_service_host_to_pywin32(self):
        host = Path(sys.exec_prefix) / "pythonservice.exe"
        previous = getattr(self.service.ToolsApiWorkerService, "_exe_name_", None)
        try:
            with mock.patch.object(self.service, "prepare_service_host", return_value=host), mock.patch.object(
                self.service.win32serviceutil, "HandleCommandLine", return_value=0
            ) as handle, mock.patch.object(
                self.service, "configure_service_python_path"
            ) as configure_path, mock.patch.object(
                self.service, "configure_service_environment"
            ) as configure_environment:
                self.service.main(argv=["windows_service.py", "install"])

            self.assertEqual(str(host), self.service.ToolsApiWorkerService._exe_name_)
            handle.assert_called_once_with(
                self.service.ToolsApiWorkerService,
                serviceClassString=self.service.SERVICE_CLASS,
                argv=["windows_service.py", "install"],
            )
            configure_path.assert_called_once_with(host)
            configure_environment.assert_called_once_with(host)
        finally:
            self.service.ToolsApiWorkerService._exe_name_ = previous

    def test_main_propagates_pywin32_registration_failure(self):
        host = Path(sys.exec_prefix) / "pythonservice.exe"
        previous = getattr(self.service.ToolsApiWorkerService, "_exe_name_", None)
        try:
            with mock.patch.object(self.service, "prepare_service_host", return_value=host), mock.patch.object(
                self.service.win32serviceutil, "HandleCommandLine", return_value=5
            ), mock.patch.object(
                self.service, "configure_service_python_path"
            ) as configure_path, mock.patch.object(
                self.service, "configure_service_environment"
            ) as configure_environment:
                with self.assertRaises(SystemExit) as raised:
                    self.service.main(argv=["windows_service.py", "install"])

            self.assertEqual(5, raised.exception.code)
            configure_path.assert_not_called()
            configure_environment.assert_not_called()
        finally:
            self.service.ToolsApiWorkerService._exe_name_ = previous

    def test_service_python_path_includes_worker_and_pywin32_paths(self):
        host = Path(sys.exec_prefix) / "pythonservice.exe"
        paths = self.service.service_python_paths(host)
        site_packages = Path(self.service.__file__).resolve().parent.parent
        pywin32_lib = Path(self.service.win32serviceutil.__file__).resolve().parent
        pywin32_dir = pywin32_lib.parent

        self.assertIn(str(host.parent.resolve()), paths)
        self.assertIn(str(site_packages), paths)
        self.assertIn(str(pywin32_dir), paths)
        self.assertIn(str(pywin32_lib), paths)
        self.assertIn(str(pywin32_dir.parent / "pywin32_system32"), paths)

    def test_service_command_detects_update_after_pywin32_options(self):
        command = self.service._service_command(["windows_service.py", "--startup", "auto", "update"])

        self.assertEqual("update", command)


if __name__ == "__main__":
    unittest.main()
