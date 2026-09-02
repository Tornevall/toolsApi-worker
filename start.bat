@echo off
setlocal

cd /d "%~dp0"

echo Stopping ToolsAPI Worker...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$service = Get-Service -Name 'ToolsAPIWorker' -ErrorAction SilentlyContinue; if ($service -and $service.Status -ne 'Stopped') { Stop-Service -Name 'ToolsAPIWorker' -Force; $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30)) }"

if errorlevel 1 (
    echo Failed to stop ToolsAPIWorker.
    exit /b 1
)

echo.
echo Updating repository...
git pull --ff-only

if errorlevel 1 (
    echo Git pull failed. Worker will NOT be started.
    exit /b 1
)

echo.
echo .env location...
echo C:\ProgramData\Tornevall\toolsapi-worker

echo.
echo Installing and starting worker...
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1

if errorlevel 1 (
    echo Worker installation/start failed.
    exit /b 1
)

endlocal
