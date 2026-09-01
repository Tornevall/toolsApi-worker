param(
    [string]$Prefix = "$env:ProgramData\Tornevall\toolsapi-worker",
    [string]$Python = "",
    [string]$TorchIndexUrl = ""
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

function Get-EnvValue {
    param([string]$Name)

    if (-not (Test-Path $EnvFile)) {
        return ""
    }
    foreach ($Line in Get-Content $EnvFile) {
        if ($Line -match "^$([regex]::Escape($Name))=(.*)$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

function Set-EnvValue {
    param(
        [string]$Name,
        [string]$Value
    )

    $Lines = @(Get-Content $EnvFile)
    $Pattern = "^$([regex]::Escape($Name))="
    $Found = $false
    $Updated = foreach ($Line in $Lines) {
        if ($Line -match $Pattern) {
            $Found = $true
            "$Name=$Value"
        } else {
            $Line
        }
    }
    if (-not $Found) {
        $Updated += "$Name=$Value"
    }
    Set-Content -Path $EnvFile -Value $Updated -Encoding UTF8
}

function Test-Truthy {
    param([string]$Value)
    return $Value.Trim().ToLowerInvariant() -in @("1", "true", "yes", "on")
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "ffmpeg is required for pyannote audio processing. Install ffmpeg and ensure it is available in the system PATH."
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

if ($TorchIndexUrl) {
    & $VenvPython -m pip install --upgrade --index-url $TorchIndexUrl torch
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install the requested CUDA-enabled PyTorch build from the supplied index URL."
    }
}

$FreshConfig = -not (Test-Path $EnvFile)
if ($FreshConfig) {
    Copy-Item (Join-Path $SourceDir ".env.example") $EnvFile
}

$NativeNvidia = $null -ne (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue)
if ($FreshConfig -and $NativeNvidia) {
    Set-EnvValue -Name "TOOLS_WORKER_WHISPER_DEVICE" -Value "cuda"
    Set-EnvValue -Name "TOOLS_WORKER_WHISPER_COMPUTE_TYPE" -Value "float16"
    Set-EnvValue -Name "TOOLS_WORKER_DIARIZATION_DEVICE" -Value "cuda"
}

$WhisperDevice = (Get-EnvValue -Name "TOOLS_WORKER_WHISPER_DEVICE").ToLowerInvariant()
$DiarizationDevice = (Get-EnvValue -Name "TOOLS_WORKER_DIARIZATION_DEVICE").ToLowerInvariant()
$DiarizationEnabled = Test-Truthy (Get-EnvValue -Name "TOOLS_WORKER_DIARIZATION_ENABLED")

if ($WhisperDevice -eq "cuda") {
    if (-not $NativeNvidia) {
        throw "TOOLS_WORKER_WHISPER_DEVICE=cuda requires a native Windows NVIDIA driver visible through nvidia-smi.exe. WSL is not used by this worker."
    }
    & $VenvPython -c "import ctranslate2, sys; count=ctranslate2.get_cuda_device_count(); types=ctranslate2.get_supported_compute_types('cuda') if count else set(); raise SystemExit(0 if count > 0 and ('float16' in types or 'int8_float16' in types) else 3)"
    if ($LASTEXITCODE -ne 0) {
        throw "Native faster-whisper CUDA validation failed. Install CUDA 12 cuBLAS and cuDNN 9 for Windows and ensure their DLL directories are in the system PATH."
    }
}

if ($DiarizationEnabled -and $DiarizationDevice -eq "cuda") {
    if (-not $NativeNvidia) {
        throw "TOOLS_WORKER_DIARIZATION_DEVICE=cuda requires a native Windows NVIDIA driver. WSL is not used by this worker."
    }
    & $VenvPython -c "import torch; raise SystemExit(0 if torch.cuda.is_available() else 3)"
    if ($LASTEXITCODE -ne 0) {
        throw "Native pyannote CUDA validation failed because this PyTorch build cannot use CUDA. Install a CUDA-enabled PyTorch build and rerun the installer."
    }
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

$Token = Get-EnvValue -Name "TOOLS_WORKER_TOKEN"
$BaseUrl = Get-EnvValue -Name "TOOLS_API_BASE_URL"
if ($Token -and $BaseUrl -and $BaseUrl -ne "https://tools.example.test") {
    Start-Service -Name $ServiceName
    Write-Host "Installed and started $ServiceName as a continuous native Windows polling service."
} else {
    Write-Host "Installed $ServiceName as a continuous native Windows polling service, but it was not started because ToolsAPI credentials are not configured."
    Write-Host "Configure $EnvFile and then run: Start-Service $ServiceName"
}

Write-Host "Configuration: $EnvFile"
Write-Host "Diarization is enabled by default and can be disabled with TOOLS_WORKER_DIARIZATION_ENABLED=false."
if ($WhisperDevice -eq "cuda") {
    Write-Host "Whisper GPU: native Windows CUDA validated."
}
if ($DiarizationEnabled -and $DiarizationDevice -eq "cuda") {
    Write-Host "Diarization GPU: native Windows PyTorch CUDA validated."
}
Write-Host "Set TOOLS_WORKER_DIARIZATION_HF_TOKEN in .env when Community-1 is not already available locally."
