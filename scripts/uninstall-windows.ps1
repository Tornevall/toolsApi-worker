param(
    [string]$Prefix = "$env:ProgramData\Tornevall\toolsapi-worker",
    [switch]$RemoveConfig
)

$ErrorActionPreference = "Stop"
$ServiceName = "ToolsAPIWorker"
$EnvFile = Join-Path $Prefix ".env"
$VenvPython = Join-Path $Prefix ".venv\Scripts\python.exe"

$Principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "uninstall-windows.ps1 must be run from an elevated PowerShell session."
}

$PreservedConfig = $null
if ((Test-Path -LiteralPath $EnvFile -PathType Leaf) -and -not $RemoveConfig) {
    # Preserve exact bytes, including BOM, line endings and trailing newlines.
    # Get-Content/Set-Content would re-encode operator-owned credentials.
    $PreservedConfig = [System.IO.File]::ReadAllBytes($EnvFile)
}

$Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($Service) {
    if ($Service.Status -ne "Stopped") {
        Stop-Service -Name $ServiceName -Force
        $Service.WaitForStatus("Stopped", (New-TimeSpan -Seconds 30))
    }

    if (Test-Path $VenvPython) {
        & $VenvPython -m toolsapi_worker.windows_service remove
        if ($LASTEXITCODE -ne 0) {
            throw "Could not remove the ToolsAPI Worker Windows service."
        }
    } else {
        sc.exe delete $ServiceName | Out-Null
    }
}

$ParametersKey = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName\Parameters"
if (Test-Path $ParametersKey) {
    Remove-Item -Path $ParametersKey -Recurse -Force
}

if (Test-Path $Prefix) {
    Remove-Item -Path $Prefix -Recurse -Force
}

if ($null -ne $PreservedConfig) {
    New-Item -ItemType Directory -Path $Prefix -Force | Out-Null
    [System.IO.File]::WriteAllBytes($EnvFile, $PreservedConfig)
    Write-Host "Removed worker runtime and Windows polling service. Preserved $EnvFile without re-encoding"
} else {
    Write-Host "Removed worker runtime and Windows polling service."
}
