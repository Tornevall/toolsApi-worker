param(
    [string]$Prefix = "$env:ProgramData\Tornevall\toolsapi-worker",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$SourceDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvFile = Join-Path $Prefix ".env"
$VenvDir = Join-Path $Prefix ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$ServiceName = "ToolsAPIWorker"

$Principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "install-windows.ps1 must be run from an elevated PowerShell session."
}

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

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "ffmpeg is required for Whisper/pyannote audio processing. Install ffmpeg and ensure it is available in PATH."
}

$PythonCommand = Resolve-PythonCommand -Requested $Python
New-Item -ItemType Directory -Path $Prefix -Force | Out-Null

Invoke-ResolvedPython -Command $PythonCommand -Arguments @("-m", "venv", $VenvDir)
& $VenvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.10 or newer is required."
}

& $VenvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) {
    throw "Could not update the worker virtual environment."
}

$InstallTarget = "$SourceDir[whisper,windows]"
& $VenvPython -m pip install $InstallTarget
if ($LASTEXITCODE -ne 0) {
    throw "Could not install toolsapi-worker Whisper, diarization and Windows service dependencies."
}

if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $SourceDir ".env.example") $EnvFile
}

$ExistingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($ExistingService) {
    if ($ExistingService.Status -ne "Stopped") {
        Stop-Service -Name $ServiceName -Force
        $ExistingService.WaitForStatus("Stopped", (New-TimeSpan -Seconds 30))
    }
    & $VenvPython -m toolsapi_worker.windows_service update --startup auto
} else {
    & $VenvPython -m toolsapi_worker.windows_service install --startup auto
}
if ($LASTEXITCODE -ne 0) {
    throw "Could not install or update the ToolsAPI Worker Windows service."
}

$ParametersKey = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName\Parameters"
New-Item -Path $ParametersKey -Force | Out-Null
New-ItemProperty -Path $ParametersKey -Name "EnvFile" -PropertyType String -Value $EnvFile -Force | Out-Null

$Token = ""
$BaseUrl = ""
foreach ($Line in Get-Content $EnvFile) {
    if ($Line -match '^TOOLS_WORKER_TOKEN=(.*)$') { $Token = $Matches[1].Trim() }
    if ($Line -match '^TOOLS_API_BASE_URL=(.*)$') { $BaseUrl = $Matches[1].Trim() }
}

if ($Token -and $BaseUrl -and $BaseUrl -ne "https://tools.example.test") {
    Start-Service -Name $ServiceName
    Write-Host "Installed and started $ServiceName as a continuous polling service."
} else {
    Write-Host "Installed $ServiceName as a continuous polling service, but it was not started because ToolsAPI credentials are not configured."
    Write-Host "Configure $EnvFile and then run: Start-Service $ServiceName"
}

Write-Host "Configuration: $EnvFile"
Write-Host "Diarization is enabled by default and can be disabled with TOOLS_WORKER_DIARIZATION_ENABLED=false."
Write-Host "Set TOOLS_WORKER_DIARIZATION_HF_TOKEN in .env when Community-1 is not already available locally."
