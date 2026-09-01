from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    raise RuntimeError("The ToolsAPI Windows service module is only available on Windows.")

import servicemanager
import win32event
import win32service
import win32serviceutil
import winreg

SERVICE_NAME = "ToolsAPIWorker"
SERVICE_DISPLAY_NAME = "Tornevall ToolsAPI Worker"
SERVICE_DESCRIPTION = "Continuously polls ToolsAPI for delegated worker jobs."


def configured_env_file() -> str:
    key_path = rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}\Parameters"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "EnvFile")
    except OSError as exc:
        raise RuntimeError("ToolsAPI Worker service is missing its EnvFile registry setting.") from exc

    env_file = str(value).strip()
    if not env_file:
        raise RuntimeError("ToolsAPI Worker service EnvFile registry setting is empty.")
    return env_file


def venv_python() -> Path:
    candidate = Path(sys.prefix) / "Scripts" / "python.exe"
    if not candidate.is_file():
        raise RuntimeError(f"Worker virtual-environment Python was not found at {candidate}.")
    return candidate


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
        python = venv_python()
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


def main() -> None:
    win32serviceutil.HandleCommandLine(ToolsApiWorkerService)


if __name__ == "__main__":
    main()
