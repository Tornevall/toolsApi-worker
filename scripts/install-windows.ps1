param(
    [string]$Prefix = "$env:LOCALAPPDATA\toolsapi-worker",
    [string]$Python = "",
    [switch]$NoScheduledTask
)

$ErrorActionPreference = "Stop"
$SourceDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvFile = Join-Path $Prefix ".env"
$VenvDir = Join-Path $Prefix ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$RunnerScript = Join-Path $Prefix "run-worker.ps1"
$TaskName = "ToolsAPI Worker"

function Resolve-PythonCommand {
    param([string]$Requested)

    if ($Requested) {
        $command = Get-Command $Requested -ErrorAction Stop
        return @($command.Source)
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return @($pythonCommand.Source)
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        return @($pyCommand.Source, "-3")
    }

    throw "Python 3.10 or newer is required. Install Python and rerun this installer."
}

function Invoke-ResolvedPython {
    param(
        [string[]]$Command,
        [string[]]$Arguments
    )

    $executable = $Command[0]
    $prefixArguments = @()
    if ($Command.Count -gt 1) {
        $prefixArguments = $Command[1..($Command.Count - 1)]
    }
    & $executable @prefixArguments @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

$PythonCommand = Resolve-PythonCommand -Requested $Python
New-Item -ItemType Directory -Path $Prefix -Force | Out-Null

Invoke-ResolvedPython -Command $PythonCommand -Arguments @("-m", "venv", $VenvDir)
& $VenvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) {
    throw "Could not update the worker virtual environment."
}

$InstallTarget = "$SourceDir[whisper]"
& $VenvPython -m pip install $InstallTarget
if ($LASTEXITCODE -ne 0) {
    throw "Could not install toolsapi-worker Whisper and diarization dependencies."
}

if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $SourceDir ".env.example") $EnvFile
}

$RunnerContent = @"
`$ErrorActionPreference = "Continue"
`$python = "$VenvPython"
`$envFile = "$EnvFile"
`$logFile = "$Prefix\worker.log"
& `$python -m toolsapi_worker.cli run --env-file `$envFile *>> `$logFile
"@
Set-Content -Path $RunnerScript -Value $RunnerContent -Encoding UTF8

if (-not $NoScheduledTask) {
    $PowerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
    $Action = New-ScheduledTaskAction -Execute $PowerShellExe -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunnerScript`""
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Tornevall ToolsAPI background worker" -Force | Out-Null
}

Write-Host "Installed toolsapi-worker in $Prefix"
Write-Host "Configuration: $EnvFile"
Write-Host "Diarization is enabled by default. Set TOOLS_WORKER_DIARIZATION_HF_TOKEN in .env when Community-1 is not already available locally."
if (-not $NoScheduledTask) {
    Write-Host "Scheduled task '$TaskName' was registered for the current user."
}
