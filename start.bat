@echo off
setlocal

cd /d "%~dp0"

fltmc >nul 2>&1
if "%errorlevel%"=="0" goto elevated

echo Requesting administrator privileges...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
if not "%errorlevel%"=="0" goto elevation_failed
exit /b 0

:elevation_failed
echo Administrator elevation was cancelled or failed.
exit /b 1

:elevated
echo Checking current ToolsAPI Worker service state (no restart yet)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop'; try { $service = Get-Service -Name 'ToolsAPIWorker' -ErrorAction SilentlyContinue; if ($null -eq $service) { Write-Host 'ToolsAPIWorker is not installed yet. The installer will register and start it when configured.'; exit 0 }; if ($service.Status -eq 'Running') { Write-Host 'ToolsAPIWorker is running. It will stay running during the Git update; the installer will handle restart.'; exit 0 }; Write-Host ('ToolsAPIWorker is currently ' + $service.Status + '. The installer will start it after its checks if credentials are configured.'); exit 0 } catch { Write-Error $_; exit 1 }"

if errorlevel 1 (
    echo Failed to check the existing ToolsAPIWorker service.
    exit /b 1
)

echo.
echo Updating repository...
git pull --ff-only

if errorlevel 1 (
    echo Git pull failed. Existing service state was not changed; installation will not run.
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

echo.
echo Verifying Windows service and worker process...
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-windows-service.ps1

if errorlevel 1 (
    echo Worker service verification failed. See diagnostics above.
    exit /b 1
)

echo.
echo Windows worker installation and local process verification succeeded.
echo Check the remote ToolsAPI dashboard to confirm the worker is reporting.

endlocal
