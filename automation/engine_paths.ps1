# Resolve current engine names while existing local installations are migrated.
# Dot-source this file; loading it performs no work and changes no scheduled jobs.

function Resolve-TRDLabRoot {
    [CmdletBinding()]
    param(
        [string]$Root = '',
        [string]$DesktopPath = (Join-Path $env:USERPROFILE 'Desktop')
    )

    if ($Root) {
        if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
            throw "TRDLab engine folder does not exist: $Root"
        }
        return (Resolve-Path -LiteralPath $Root).Path
    }

    foreach ($name in @('TRDLab', 'Sigma Lab', 'Bet Better')) {
        $candidate = Join-Path $DesktopPath $name
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "TRDLab engine folder was not found on $DesktopPath. Pass its location explicitly."
}

function Resolve-TRDLabRefreshTask {
    [CmdletBinding()]
    param()

    $names = @(
        'TRDLab Personal Data Refresh',
        'Sigma Lab Personal Data Refresh',
        'BetBetter Personal Data Refresh'
    )
    if (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue) {
        foreach ($name in $names) {
            if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
                return $name
            }
        }
    }
    # Existing callers check for the task before pausing or enabling it.
    return $names[0]
}
