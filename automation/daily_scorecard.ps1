# Daily NCAAM scorecard publication, run by the scheduled task from the
# dedicated publisher clone (see install_scorecard_task.ps1), never from a
# development checkout: a dev tree carries uncommitted edits and feature
# branches, so what ran would not be what main says runs.
#
# Moves this clone to origin/main first, then runs the ship script in a child
# process so the freshly checked-out version is the one that executes.
#
# The task launches through `conhost --headless`, which does not hand the
# script's exit code back to Task Scheduler, so every run appends its own
# start/finish line to automation\logs\daily-scorecard.log. A run that left
# no "finished" line did not complete.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDir = Join-Path $root 'automation\logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$runLog = Join-Path $logDir 'daily-scorecard.log'
function Note([string]$text) {
    Add-Content -Path $runLog -Value ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' ' + $text) -Encoding utf8
}
$code = 1
Note 'started'
try {
    git -C $root fetch -q origin main
    if ($LASTEXITCODE -ne 0) { throw 'Could not fetch origin/main; nothing published' }
    git -C $root checkout -q --detach origin/main
    if ($LASTEXITCODE -ne 0) { throw 'Could not move the publisher clone to origin/main; nothing published' }
    # The child's own output, errors included, goes to the run log: a thrown
    # error otherwise reaches only stderr, which the headless launcher drops.
    # 'Continue' here: under 'Stop', PowerShell 5.1 turns the first redirected
    # stderr line of a native command into a terminating error.
    $ErrorActionPreference = 'Continue'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'automation\sunday_ship.ps1') -Sport ncaam -ScorecardOnly 2>&1 |
        ForEach-Object { "  $_" } | Add-Content -Path $runLog -Encoding utf8
    $code = $LASTEXITCODE
    Note "finished exit=$code at $(git -C $root rev-parse --short origin/main)"
} catch {
    Note "failed: $($_.Exception.Message)"
}
exit $code
