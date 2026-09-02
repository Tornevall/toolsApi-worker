from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    raise RuntimeError("The ToolsAPI Windows service module is only available on Windows.")

import pywintypes
import servicemanager
import win32api
import win32event
import win32service
import win32serviceutil
import winreg

SERVICE_NAME = "ToolsAPIWorker"
SERVICE_DISPLAY_NAME = "Tornevall ToolsAPI Worker"
SERVICE_DESCRIPTION = "Continuously polls ToolsAPI for delegated worker jobs."


def configured_parameter(name: str) -> str:
    key_path = rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}\Parameters"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError as exc:
        raise RuntimeError(f"ToolsAPI Worker service is missing its {name} registry setting.") from exc

    text = str(value).strip()
    if not text:
        raise RuntimeError(f"ToolsAPI Worker service {name} registry setting is empty.")
    return text


def configured_env_file() -> str:
    return configured_parameter("EnvFile")


def configured_python() -> Path:
    candidate = Path(configured_parameter("PythonExe"))
    if not candidate.is_file():
        raise RuntimeError(f"Worker virtual-environment Python was not found at {candidate}.")
    return candidate


def _copy_runtime_file(source: Path, target: Path) -> None:
    if not source.is_file():
        raise RuntimeError(f"Required Windows service runtime file was not found: {source}")

    try:
        same_file = source.resolve() == target.resolve()
    except OSError:
        same_file = False
    if same_file:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        try:
            if source.stat().st_size == target.stat().st_size:
                return
        except OSError:
            pass
    shutil.copy2(source, target)


def _pythonservice_source() -> Path:
    return Path(win32service.__file__).with_name("pythonservice.exe")


def _python_runtime_dll() -> Path:
    dll_handle = getattr(sys, "dllhandle", None)
    if dll_handle is None:
        raise RuntimeError("Could not determine the loaded Windows Python runtime DLL.")
    return Path(win32api.GetModuleFileName(dll_handle))


def _pywintypes_runtime_dll() -> Path:
    imported = Path(pywintypes.__file__)
    if imported.suffix.lower() == ".dll" and imported.is_file():
        return imported

    filename = f"pywintypes{sys.version_info.major}{sys.version_info.minor}.dll"
    candidates = [
        Path(sys.prefix) / filename,
        Path(win32service.__file__).parent.parent / "pywin32_system32" / filename,
        imported.parent / filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"Could not locate the pywin32 helper DLL {filename}.")


def prepare_service_host() -> Path:
    """Prepare a service host entirely inside the active worker virtualenv.

    pywin32's default service-registration path may try to copy pywintypesXX.dll
    beside the *base* Python DLL. Microsoft Store Python keeps that DLL under the
    protected WindowsApps package tree, which is intentionally not writable.
    Supplying an explicit pythonservice.exe skips that global-copy path. Keeping
    pythonservice.exe, the loaded Python DLL and pywintypesXX.dll together under
    sys.exec_prefix also gives the LocalSystem service a self-contained host in
    the worker-controlled installation directory.
    """

    host_dir = Path(sys.exec_prefix)
    host_exe = host_dir / "pythonservice.exe"
    source_host = _pythonservice_source()

    if source_host.is_file():
        _copy_runtime_file(source_host, host_exe)
    elif not host_exe.is_file():
        raise RuntimeError(
            "Could not locate pythonservice.exe in pywin32 or the worker virtual environment."
        )

    python_dll = _python_runtime_dll()
    _copy_runtime_file(python_dll, host_dir / python_dll.name)

    pywintypes_dll = _pywintypes_runtime_dll()
    _copy_runtime_file(pywintypes_dll, host_dir / pywintypes_dll.name)

    return host_exe


class ToolsApiWorkerService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.child: subprocess.Popen[str] | None = None

    def SvcStop(self) -> None:
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        self._stop_child()

    def SvcDoRun(self) -> None:
        servicemanager.LogInfoMsg(f"{SERVICE_DISPLAY_NAME} starting.")
        try:
            self._run_worker_process()
        except Exception as exc:  # noqa: BLE001
            servicemanager.LogErrorMsg(f"{SERVICE_DISPLAY_NAME} failed: {exc}")
            raise
        finally:
            self._stop_child()
            servicemanager.LogInfoMsg(f"{SERVICE_DISPLAY_NAME} stopped.")

    def _run_worker_process(self) -> None:
        env_file = configured_env_file()
        python = configured_python()
        command = [
            str(python),
            "-m",
            "toolsapi_worker.cli",
            "run",
            "--env-file",
            env_file,
        ]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.child = subprocess.Popen(command, creationflags=creation_flags, text=True)

        while True:
            wait_result = win32event.WaitForSingleObject(self.stop_event, 1000)
            if wait_result == win32event.WAIT_OBJECT_0:
                return

            exit_code = self.child.poll()
            if exit_code is not None:
                if exit_code != 0:
                    servicemanager.LogErrorMsg(
                        f"ToolsAPI worker polling process exited with status {exit_code}; service will restart it shortly."
                    )
                if win32event.WaitForSingleObject(self.stop_event, 5000) == win32event.WAIT_OBJECT_0:
                    return
                self.child = subprocess.Popen(command, creationflags=creation_flags, text=True)

    def _stop_child(self) -> None:
        child = self.child
        if child is None or child.poll() is not None:
            return

        child.terminate()
        deadline = time.monotonic() + 15
        while child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        if child.poll() is None:
            child.kill()
        self.child = None


def main(argv: list[str] | None = None) -> None:
    host_exe = prepare_service_host()
    ToolsApiWorkerService._exe_name_ = str(host_exe)
    result = win32serviceutil.HandleCommandLine(ToolsApiWorkerService, argv=argv)
    if result not in (None, 0):
        raise SystemExit(int(result))


if __name__ == "__main__":
    main()
