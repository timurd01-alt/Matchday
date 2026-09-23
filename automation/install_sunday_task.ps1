# Registers "Matchday Sunday Ship" to run automation\sunday_ship.ps1.
#
# Sunday 14:30 local: Saturday's late games are final and the AP poll (out
# around 13:00 CT) is on the scoreboard. Monday 07:00 is a catch-up that
# changes nothing if Sunday already shipped. StartWhenAvailable runs a missed
# trigger as soon as the machine is back on.
param([string]$At = '2:30PM', [string]$CatchUpAt = '7:00AM')
$ErrorActionPreference = 'Stop'
$script = (Resolve-Path (Join-Path $PSScriptRoot 'sunday_ship.ps1')).Path
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$triggers = @(
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At $At),
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At $CatchUpAt)
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName 'Matchday Sunday Ship' -Action $action -Trigger $triggers `
    -Settings $settings -Force `
    -Description 'Refreshes Bet Better and ships ratings, AP poll and next week''s picks to Matchday.' | Out-Null
Write-Host "Installed 'Matchday Sunday Ship' (Sundays $At, catch-up Mondays $CatchUpAt)"
