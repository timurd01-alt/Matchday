# Independent of the Sunday ratings job: publish cards the engine poller graded.
#
# The task runs from a dedicated publisher clone, not from whichever checkout
# this installer happens to sit in. A development checkout has uncommitted
# edits and moves between branches; a scheduled job pinned to it runs whatever
# is on disk that day. The clone is created on first install and is moved to
# origin/main by daily_scorecard.ps1 before every run. Do not develop in it.
#
# Launched windowless (conhost --headless), like the other background tasks.
#
# The clone lives under the user profile, never under AppData. The Claude
# desktop app is a packaged app, so a shell it runs that writes to AppData\Local
# is silently redirected into the app's private storage: the first install put
# the clone there, the folder existed for that shell, and Task Scheduler could
# not see it, so every run failed while reporting success (2026-11-12).
#
# Runs on battery too. The default settings refuse to start on battery and the
# task then sits Queued, never running; the other Matchday tasks allow it.
param(
    [string]$At = '8:00AM',
    [string]$Checkout = (Join-Path $env:USERPROFILE 'Matchday Publisher')
)
$ErrorActionPreference = 'Stop'
if ($Checkout -like (Join-Path $env:USERPROFILE 'AppData') + '*') {
    throw "Put the publisher clone outside AppData ($Checkout); packaged-app shells redirect writes there"
}
if (-not (Test-Path (Join-Path $Checkout '.git'))) {
    $origin = git -C (Join-Path $PSScriptRoot '..') remote get-url origin
    if ($LASTEXITCODE -ne 0 -or -not $origin) { throw 'Could not read the origin URL' }
    New-Item -ItemType Directory -Force (Split-Path $Checkout) | Out-Null
    git clone -q $origin $Checkout
    if ($LASTEXITCODE -ne 0) { throw "Could not clone $origin into $Checkout" }
}
# The scheduled run commits as the owner. This machine has no global git
# identity (the dev checkout sets it repo-locally), so a fresh clone could
# stage a shipment and then fail at `git commit` (2026-11-12). Copy it over.
foreach ($key in 'user.name', 'user.email') {
    $value = git -C (Join-Path $PSScriptRoot '..') config --get $key
    if (-not $value) { throw "No git $key in the installing checkout; set it there first" }
    git -C $Checkout config $key $value
    if ($LASTEXITCODE -ne 0) { throw "Could not set $key in the publisher clone" }
}
git -C $Checkout fetch -q origin main
if ($LASTEXITCODE -ne 0) { throw 'Could not fetch origin/main into the publisher clone' }
git -C $Checkout checkout -q --detach origin/main
if ($LASTEXITCODE -ne 0) { throw 'Could not move the publisher clone to origin/main' }
$script = Join-Path $Checkout 'automation\daily_scorecard.ps1'
if (-not (Test-Path $script)) { throw "origin/main has no $script yet; merge the scorecard change first" }

# No -WorkingDirectory: with a space in the profile path the task fails to
# start (0x8007010B). daily_scorecard.ps1 resolves its own root.
$action = New-ScheduledTaskAction -Execute 'conhost.exe' `
    -Argument "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName 'Matchday Daily NCAAM Scorecard' -Action $action `
    -Trigger $trigger -Settings $settings -Force `
    -Description "Publishes already-graded NCAAM cards daily from $Checkout; no additional provider requests." | Out-Null
Write-Host "Installed daily NCAAM scorecard publication at $At local time from $Checkout."
