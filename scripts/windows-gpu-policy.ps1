function Select-CTranslate2ComputeType {
    param([string[]]$SupportedTypes)

    $normalized = @(
        $SupportedTypes |
            ForEach-Object { ([string]$_).Trim().ToLowerInvariant() } |
            Where-Object { $_ }
    )

    foreach ($candidate in @("float16", "int8_float16", "int8_float32", "float32")) {
        if ($normalized -contains $candidate) {
            return $candidate
        }
    }

    return ""
}

function Test-NvidiaNeedsCuda126PyTorch {
    param([string]$ComputeCapability)

    $value = $ComputeCapability.Trim()
    if ($value -notmatch '^(\d+)(?:\.(\d+))?$') {
        return $false
    }

    $major = [int]$Matches[1]
    $minor = if ($Matches[2]) { [int]$Matches[2] } else { 0 }

    # Current PyTorch CUDA 13 wheels no longer cover Maxwell, Pascal or Volta.
    # Turing begins at compute capability 7.5, so older NVIDIA architectures use
    # the maintained CUDA 12.6 wheel channel for worker-side diarization.
    return ($major -lt 7) -or ($major -eq 7 -and $minor -lt 5)
}

function Resolve-PyTorchIndexUrl {
    param(
        [string]$RequestedIndexUrl,
        [string]$ComputeCapability
    )

    if ($RequestedIndexUrl.Trim()) {
        return $RequestedIndexUrl.Trim()
    }

    if (Test-NvidiaNeedsCuda126PyTorch -ComputeCapability $ComputeCapability) {
        return "https://download.pytorch.org/whl/cu126"
    }

    return ""
}

function Test-CanRepairGeneratedCudaDefault {
    param(
        [bool]$FreshConfig,
        [bool]$ServiceExists,
        [string]$BaseUrl,
        [string]$WorkerToken,
        [string]$WhisperDevice,
        [string]$WhisperComputeType
    )

    if ($FreshConfig -or $ServiceExists) {
        return $false
    }

    $base = $BaseUrl.Trim()
    $token = $WorkerToken.Trim()
    $device = $WhisperDevice.Trim().ToLowerInvariant()
    $computeType = $WhisperComputeType.Trim().ToLowerInvariant()

    return (-not $token) `
        -and ($base -eq "" -or $base -eq "https://tools.example.test") `
        -and $device -eq "cuda" `
        -and $computeType -eq "float16"
}

function Get-NvidiaComputeCapability {
    param([string]$NvidiaSmi = "nvidia-smi.exe")

    try {
        $output = @(& $NvidiaSmi --query-gpu=compute_cap --format=csv,noheader,nounits 2>$null)
        if ($LASTEXITCODE -ne 0 -or $output.Count -lt 1) {
            return ""
        }

        $value = ([string]$output[0]).Trim()
        if ($value -match '^(\d+)(?:\.(\d+))?$') {
            $minor = if ($Matches[2]) { $Matches[2] } else { "0" }
            return "$($Matches[1]).$minor"
        }
    } catch {
        return ""
    }

    return ""
}
