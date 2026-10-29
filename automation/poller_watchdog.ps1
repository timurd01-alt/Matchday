. (Join-Path $PSScriptRoot 'engine_paths.ps1')
# Hourly: turn the TRDLab data poller back on if it was left off.
#
# 2026-10-18: the poller was off on Saturday -- a Sunday ship or forecast that is
# killed part-way skips the `finally` that re-enables it -- so 29 of 62 FBS
# finals never reached the engine and a week of ratings was published without
# them. This leaves the poller alone while a ship or forecast is running (they
# pause it on purpose) and re-enables it otherwise.
$poller = Resolve-TRDLabRefreshTask
$task = Get-ScheduledTask -TaskName $poller -ErrorAction SilentlyContinue
if (-not $task -or $task.State -ne 'Disabled') { exit 0 }
$busy = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match 'trdlab (refresh|forecast|matchday|hoops)|sunday_ship|forecast_rest_of_season' }
if ($busy) { exit 0 }
Enable-ScheduledTask -TaskName $poller | Out-Null
$log = Join-Path $PSScriptRoot 'logs\poller-watchdog.log'
"{0:o} re-enabled '{1}' (it was left disabled with no job running)" -f (Get-Date), $poller | Out-File $log -Append -Encoding utf8
