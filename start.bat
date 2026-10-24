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
echo Checking ToolsAPI Worker service...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop'; try { $service = Get-Service -Name 'ToolsAPIWorker' -ErrorAction SilentlyContinue; if ($null -eq $service) { Write-Host 'ToolsAPIWorker is not installed; continuing with fresh installation.'; exit 0 }; if ($service.Status -eq 'Stopped') { Write-Host 'ToolsAPIWorker is already stopped.'; exit 0 }; Write-Host 'Stopping existing ToolsAPIWorker...'; Stop-Service -Name 'ToolsAPIWorker' -Force; $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30)); exit 0 } catch { Write-Error $_; exit 1 }"

if errorlevel 1 (
    echo Failed to stop an existing ToolsAPIWorker service.
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
