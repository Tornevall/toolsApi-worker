# Verify the native Windows service and its polling child after installation.
# This cannot prove a remote ToolsAPI heartbeat; no token or secret is printed.
param(
    [string]$Prefix = "$env:ProgramData\Tornevall\toolsapi-worker",
    [string]$ServiceName = "ToolsAPIWorker",
    [ValidateRange(1, 30)][int]$StartupWaitSeconds = 8
)

$ErrorActionPreference = "Stop"
$EnvFile = Join-Path $Prefix ".env"
$VenvPython = Join-Path $Prefix ".venv\Scripts\python.exe"
$LogFile = Join-Path $Prefix "logs\worker-runtime.log"

function Show-WorkerStartupDiagnostics {
    if (Test-Path $LogFile) {
        Write-Host ""
        Write-Host "Recent local worker output ($LogFile):"
        Get-Content -Path $LogFile -Tail 25
    } else {
        Write-Host "No worker-runtime.log exists yet; the Python child may never have started."
    }

    try {
        $events = @(
            Get-WinEvent -FilterHashtable @{
                LogName = "Application"
                StartTime = (Get-Date).AddMinutes(-5)
            } -MaxEvents 100 -ErrorAction Stop |
                Where-Object {
                    $_.Message -match "ToolsAPI worker polling process exited|Tornevall ToolsAPI Worker failed"
                } |
                Select-Object -First 5
        )
        foreach ($event in $events) {
            Write-Host "Windows service event ($($event.TimeCreated)): $($event.Message)"
        }
    } catch {
        # Event Log access must not hide the primary startup error.
    }
}

try {
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        throw "$ServiceName was not registered. Review the installer output above."
    }
    if ($service.Status -ne "Running") {
        throw "$ServiceName is $($service.Status), not Running. Check the previous installer output and configured credentials."
    }
    if (-not (Test-Path $VenvPython) -or -not (Test-Path $EnvFile)) {
        throw "Worker Python or .env is missing under $Prefix."
    }

    & $VenvPython -m toolsapi_worker.cli status --env-file $EnvFile
    if ($LASTEXITCODE -ne 0) {
        throw "The worker's local configuration/status check failed (exit $LASTEXITCODE)."
    }

    Start-Sleep -Seconds $StartupWaitSeconds
    $service.Refresh()
    if ($service.Status -ne "Running") {
        throw "$ServiceName stopped during the first $StartupWaitSeconds seconds."
    }

    $workerProcesses = @(
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
            Where-Object {
                $command = [string]$_.CommandLine
                $command.IndexOf("toolsapi_worker.cli run", [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
                $command.IndexOf($EnvFile, [StringComparison]::OrdinalIgnoreCase) -ge 0
            }
    )
    if ($workerProcesses.Count -eq 0) {
        throw "Windows service is Running, but its Python polling process is absent."
    }

    $crashEvents = @(
        Get-WinEvent -FilterHashtable @{
            LogName = "Application"
            StartTime = (Get-Date).AddSeconds(-($StartupWaitSeconds + 10))
        } -MaxEvents 100 -ErrorAction SilentlyContinue |
            Where-Object { $_.Message -match "ToolsAPI worker polling process exited with status" }
    )
    if ($crashEvents.Count -gt 0) {
        throw "Worker process exited and restarted during startup; inspect worker-runtime.log."
    }

    Write-Host "OK: $ServiceName is Running and the Python polling process exists."
    Write-Host "Runtime output: $LogFile"
    Write-Host "Remote ToolsAPI heartbeat is not proven by this local check; confirm the worker appears in /whisper."
} catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    Show-WorkerStartupDiagnostics
    exit 1
}
