# Windows worker configuration mutation policy.
# Sourced by install-windows.ps1; requires $EnvFile and $FreshConfig from caller.
# Existing .env files are immutable, even when an earlier install was incomplete.

function Set-EnvValue {
    param(
        [string]$Name,
        [string]$Value
    )

    # Only the template created during this same first installation may be edited.
    # Previous incomplete installations are still existing configurations: never
    # infer permission to change their bytes from the service/credential state.
    if (-not $FreshConfig) {
        throw "Refusing to modify existing worker .env at $EnvFile ($Name). Update the file explicitly instead."
    }

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

