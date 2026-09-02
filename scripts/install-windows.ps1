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
$GpuPolicyScript = Join-Path $SourceDir "scripts\windows-gpu-policy.ps1"

if (-not (Test-Path $GpuPolicyScript)) {
    throw "Windows GPU policy helper is missing: $GpuPolicyScript"
}
. $GpuPolicyScript

$Principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "install-windows.ps1 must be run from an elevated PowerShell session."
}

function Resolve-PythonCommand {
    param([string]$Requested)

    if ($Requested) {
        $command = Get-Command $Requested -ErrorAction Stop
        $candidate = @($command.Source)
        if (Test-PythonCommand -Command $candidate) {
            return $candidate
        }
        throw "Requested Python command '$Requested' is not a usable Python 3.10+ runtime. Install Python 3.10 or newer and rerun this installer."
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        $candidate = @($pyCommand.Source, "-3")
        if (Test-PythonCommand -Command $candidate) {
            return $candidate
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $candidate = @($pythonCommand.Source)
        if (Test-PythonCommand -Command $candidate) {
            return $candidate
        }
    }

    throw "Python 3.10 or newer is required. Install Python from python.org or install the Python Launcher, then rerun this installer. The Microsoft Store app execution alias is not sufficient for this service installation."
}

function Test-PythonCommand {
    param([string[]]$Command)

    if (-not $Command -or $Command.Count -lt 1) {
        return $false
    }

    $source = ([string]$Command[0]).Trim()
    if (-not $source) {
        return $false
    }

    if ($source.ToLowerInvariant().Contains("\microsoft\windowsapps\")) {
        return $false
    }

    $executable = $Command[0]
    $prefixArguments = @()
    if ($Command.Count -gt 1) {
        $prefixArguments = $Command[1..($Command.Count - 1)]
    }

    try {
        $output = @(& $executable @prefixArguments -c "import sys; print(sys.executable); raise SystemExit(0 if sys.version_info >= (3, 10) else 2)" 2>$null)
        if ($LASTEXITCODE -ne 0 -or $output.Count -lt 1) {
            return $false
        }
    } catch {
        return $false
    }

    $resolvedExecutable = ([string]($output | Select-Object -Last 1)).Trim()
    if (-not $resolvedExecutable) {
        return $false
    }

    return -not $resolvedExecutable.ToLowerInvariant().Contains("\microsoft\windowsapps\")
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

function Invoke-PipInstall {
    param(
        [string[]]$Arguments,
        [string]$FailureMessage
    )

    & $VenvPython -m pip install --disable-pip-version-check --prefer-binary @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
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
$NativeNvidia = $null -ne (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue)
$GpuComputeCapability = if ($NativeNvidia) { Get-NvidiaComputeCapability } else { "" }
$EffectiveTorchIndexUrl = Resolve-PyTorchIndexUrl -RequestedIndexUrl $TorchIndexUrl -ComputeCapability $GpuComputeCapability
$FreshConfig = -not (Test-Path $EnvFile)
$ExistingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Path $Prefix -Force | Out-Null

Invoke-ResolvedPython -Command $PythonCommand -Arguments @("-m", "venv", $VenvDir)
& $VenvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.10 or newer is required."
}

Invoke-PipInstall `
    -Arguments @("--upgrade", "pip", "setuptools", "wheel") `
    -FailureMessage "Could not update pip, setuptools and wheel in the worker virtual environment."

if ($EffectiveTorchIndexUrl) {
    Invoke-PipInstall `
        -Arguments @("--upgrade", "--index-url", $EffectiveTorchIndexUrl, "torch", "torchaudio", "torchcodec") `
        -FailureMessage "Could not install CUDA-enabled PyTorch, torchaudio and torchcodec from $EffectiveTorchIndexUrl. Verify that the selected PyTorch wheel channel supports this Python version and GPU architecture."
} else {
    Invoke-PipInstall `
        -Arguments @("--upgrade", "torch", "torchaudio", "torchcodec") `
        -FailureMessage "Could not install PyTorch, torchaudio and torchcodec. Verify that this Python version is supported by the current PyTorch Windows wheels."
}

$InstallTarget = "$SourceDir[whisper,windows]"
Invoke-PipInstall `
    -Arguments @($InstallTarget) `
    -FailureMessage "Could not install toolsapi-worker Whisper, diarization and Windows service dependencies after PyTorch was installed. Review the pip resolver output above for the failing package."

if ($FreshConfig) {
    Copy-Item (Join-Path $SourceDir ".env.example") $EnvFile
}

if ($FreshConfig -and $NativeNvidia) {
    Set-EnvValue -Name "TOOLS_WORKER_WHISPER_DEVICE" -Value "cuda"
    Set-EnvValue -Name "TOOLS_WORKER_DIARIZATION_DEVICE" -Value "cuda"
}

$WhisperDevice = (Get-EnvValue -Name "TOOLS_WORKER_WHISPER_DEVICE").ToLowerInvariant()
$WhisperComputeType = (Get-EnvValue -Name "TOOLS_WORKER_WHISPER_COMPUTE_TYPE").ToLowerInvariant()
$DiarizationDevice = (Get-EnvValue -Name "TOOLS_WORKER_DIARIZATION_DEVICE").ToLowerInvariant()
$DiarizationEnabled = Test-Truthy (Get-EnvValue -Name "TOOLS_WORKER_DIARIZATION_ENABLED")
$ConfigBaseUrl = Get-EnvValue -Name "TOOLS_API_BASE_URL"
$ConfigWorkerToken = Get-EnvValue -Name "TOOLS_WORKER_TOKEN"
$CanRepairGeneratedCudaDefault = Test-CanRepairGeneratedCudaDefault `
    -FreshConfig $FreshConfig `
    -ServiceExists ($null -ne $ExistingService) `
    -BaseUrl $ConfigBaseUrl `
    -WorkerToken $ConfigWorkerToken `
    -WhisperDevice $WhisperDevice `
    -WhisperComputeType $WhisperComputeType

if ($WhisperDevice -eq "cuda") {
    if (-not $NativeNvidia) {
        throw "TOOLS_WORKER_WHISPER_DEVICE=cuda requires a native Windows NVIDIA driver visible through nvidia-smi.exe. WSL is not used by this worker."
    }

    $CudaProbeOutput = @(& $VenvPython -c "import ctranslate2,json; count=int(ctranslate2.get_cuda_device_count()); types=sorted(str(v).strip().lower() for v in ctranslate2.get_supported_compute_types('cuda')) if count else []; print(json.dumps({'count': count, 'types': types}))" 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Native faster-whisper CUDA runtime validation failed before compute-type validation. nvidia-smi only confirms the NVIDIA driver; current CTranslate2/faster-whisper requires CUDA 12 cuBLAS and cuDNN 9 DLLs visible to the Windows service process."
    }

    try {
        $CudaProbe = ($CudaProbeOutput | Select-Object -Last 1) | ConvertFrom-Json
    } catch {
        throw "Native faster-whisper CUDA validation returned an unreadable capability result."
    }

    if ([int]$CudaProbe.count -lt 1) {
        throw "CTranslate2 found no usable native CUDA device. nvidia-smi driver visibility alone is not sufficient; verify the CUDA 12 runtime and cuDNN 9 installation."
    }

    $SupportedComputeTypes = @(
        $CudaProbe.types |
            ForEach-Object { ([string]$_).Trim().ToLowerInvariant() } |
            Where-Object { $_ }
    )

    $RepairGeneratedCudaDefault = $CanRepairGeneratedCudaDefault -and ($SupportedComputeTypes -notcontains $WhisperComputeType)
    if ($FreshConfig -or $RepairGeneratedCudaDefault) {
        $SelectedComputeType = Select-CTranslate2ComputeType -SupportedTypes $SupportedComputeTypes
        if (-not $SelectedComputeType) {
            throw "CTranslate2 detected the NVIDIA GPU but reported no supported worker compute type. Reported types: $($SupportedComputeTypes -join ', ')."
        }
        Set-EnvValue -Name "TOOLS_WORKER_WHISPER_COMPUTE_TYPE" -Value $SelectedComputeType
        $WhisperComputeType = $SelectedComputeType
        if ($RepairGeneratedCudaDefault) {
            Write-Host "Recovered stale installer-generated CUDA compute type from a previous incomplete installation: $SelectedComputeType"
        }
    }

    if ($WhisperComputeType -notin @("", "auto", "default") -and $SupportedComputeTypes -notcontains $WhisperComputeType) {
        throw "Configured TOOLS_WORKER_WHISPER_COMPUTE_TYPE=$WhisperComputeType is not supported by this NVIDIA GPU. CTranslate2 reports: $($SupportedComputeTypes -join ', '). Update $EnvFile explicitly; configured existing workers are never rewritten on reinstall."
    }
}

if ($DiarizationEnabled -and $DiarizationDevice -eq "cuda") {
    if (-not $NativeNvidia) {
        throw "TOOLS_WORKER_DIARIZATION_DEVICE=cuda requires a native Windows NVIDIA driver. WSL is not used by this worker."
    }

    & $VenvPython -c "import torch; assert torch.cuda.is_available(); x=torch.ones(1, device='cuda'); y=(x + 1).cpu(); assert float(y.item()) == 2.0; torch.cuda.synchronize()"
    if ($LASTEXITCODE -ne 0) {
        if (Test-NvidiaNeedsCuda126PyTorch -ComputeCapability $GpuComputeCapability) {
            throw "Native pyannote CUDA validation failed on NVIDIA compute capability $GpuComputeCapability. Maxwell/Pascal/Volta workers require the supported PyTorch CUDA 12.6 wheel channel; rerun with -TorchIndexUrl https://download.pytorch.org/whl/cu126 if the automatic selection was overridden."
        }
        throw "Native pyannote CUDA validation failed because this PyTorch build cannot execute a CUDA kernel on the detected GPU. Install a compatible official CUDA-enabled PyTorch build and rerun the installer."
    }
}

if ($ExistingService) {
    if ($ExistingService.Status -ne "Stopped") {
        Stop-Service -Name $ServiceName -Force
        $ExistingService.WaitForStatus("Stopped", (New-TimeSpan -Seconds 30))
    }
    & $VenvPython -m toolsapi_worker.windows_service --startup auto update
} else {
    & $VenvPython -m toolsapi_worker.windows_service --startup auto install
}
if ($LASTEXITCODE -ne 0) {
    throw "Could not install or update the ToolsAPI Worker Windows service."
}

$ParametersKey = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName\Parameters"
New-Item -Path $ParametersKey -Force | Out-Null
New-ItemProperty -Path $ParametersKey -Name "EnvFile" -PropertyType String -Value $EnvFile -Force | Out-Null
New-ItemProperty -Path $ParametersKey -Name "PythonExe" -PropertyType String -Value $VenvPython -Force | Out-Null

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
if ($NativeNvidia -and $GpuComputeCapability) {
    Write-Host "NVIDIA compute capability: $GpuComputeCapability"
}
if ($EffectiveTorchIndexUrl -and -not $TorchIndexUrl -and (Test-NvidiaNeedsCuda126PyTorch -ComputeCapability $GpuComputeCapability)) {
    Write-Host "PyTorch compatibility: selected CUDA 12.6 wheel channel for Maxwell/Pascal/Volta."
}
if ($WhisperDevice -eq "cuda") {
    Write-Host "Whisper GPU: native Windows CUDA validated with compute type $WhisperComputeType."
}
if ($DiarizationEnabled -and $DiarizationDevice -eq "cuda") {
    Write-Host "Diarization GPU: native Windows PyTorch CUDA kernel validated."
}
Write-Host "Set TOOLS_WORKER_DIARIZATION_HF_TOKEN in .env when Community-1 is not already available locally."
