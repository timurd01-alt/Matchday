# Independent of the Sunday ratings job: publish cards the engine poller graded.
#
# The task runs from a dedicated publisher clone, not from whichever checkout
# this installer happens to sit in. A development checkout has uncommitted
# edits and moves between branches; a scheduled job pinned to it runs whatever
# is on disk that day. The clone is created on first install and is moved to
# origin/main by daily_scorecard.ps1 before every run. Do not develop in it.
#
# Launched windowless (conhost --headless), like the other background tasks.
param(
    [string]$At = '8:00AM',
    [string]$Checkout = (Join-Path $env:LOCALAPPDATA 'Matchday\publisher')
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path (Join-Path $Checkout '.git'))) {
    $origin = git -C (Join-Path $PSScriptRoot '..') remote get-url origin
    if ($LASTEXITCODE -ne 0 -or -not $origin) { throw 'Could not read the origin URL' }
    New-Item -ItemType Directory -Force (Split-Path $Checkout) | Out-Null
    git clone -q $origin $Checkout
    if ($LASTEXITCODE -ne 0) { throw "Could not clone $origin into $Checkout" }
}
git -C $Checkout fetch -q origin main
if ($LASTEXITCODE -ne 0) { throw 'Could not fetch origin/main into the publisher clone' }
git -C $Checkout checkout -q --detach origin/main
if ($LASTEXITCODE -ne 0) { throw 'Could not move the publisher clone to origin/main' }
$script = Join-Path $Checkout 'automation\daily_scorecard.ps1'
if (-not (Test-Path $script)) { throw "origin/main has no $script yet; merge the scorecard change first" }

$action = New-ScheduledTaskAction -Execute 'conhost.exe' -WorkingDirectory $Checkout `
    -Argument "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName 'Matchday Daily NCAAM Scorecard' -Action $action `
    -Trigger $trigger -Settings $settings -Force `
    -Description "Publishes already-graded NCAAM cards daily from $Checkout; no additional provider requests." | Out-Null
Write-Host "Installed daily NCAAM scorecard publication at $At local time from $Checkout."
