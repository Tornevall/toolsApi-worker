param(
    [string]$Prefix = "$env:LOCALAPPDATA\toolsapi-worker",
    [switch]$RemoveConfig
)

$ErrorActionPreference = "Stop"
$TaskName = "ToolsAPI Worker"
$EnvFile = Join-Path $Prefix ".env"

$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$PreservedConfig = $null
if ((Test-Path $EnvFile) -and -not $RemoveConfig) {
    $PreservedConfig = Get-Content -Path $EnvFile -Raw
}

if (Test-Path $Prefix) {
    Remove-Item -Path $Prefix -Recurse -Force
}

if ($PreservedConfig -ne $null) {
    New-Item -ItemType Directory -Path $Prefix -Force | Out-Null
    Set-Content -Path $EnvFile -Value $PreservedConfig -Encoding UTF8
    Write-Host "Removed worker runtime and scheduled task. Preserved $EnvFile"
} else {
    Write-Host "Removed worker runtime and scheduled task."
}
