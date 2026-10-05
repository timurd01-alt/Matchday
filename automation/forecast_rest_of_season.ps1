# Forecast every remaining NCAAF game, then export and ship. Run as a Windows
# scheduled task so it is not bound by an interactive session's time limits
# (a full-season forecast takes ~40 minutes).
$ErrorActionPreference = 'Continue'
$matchday = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$bb = Join-Path $env:USERPROFILE 'Desktop\Bet Better'
$py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
$log = Join-Path $matchday ("automation\logs\forecast-season-{0:yyyy-MM-dd_HHmm}.log" -f (Get-Date))
$poller = 'BetBetter Personal Data Refresh'
"start $(Get-Date -f o)" | Out-File $log -Encoding utf8
try {
    Stop-ScheduledTask -TaskName $poller -ErrorAction SilentlyContinue
    Disable-ScheduledTask -TaskName $poller | Out-Null
    Push-Location $bb
    & $py -m betbetter forecast slate --sport ncaaf *>&1 | Out-File $log -Append -Encoding utf8
    "forecast exit $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
    & $py -m betbetter matchday export --out betbetter_picks.json *>&1 | Out-File $log -Append -Encoding utf8
    "export exit $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
    Pop-Location
} finally {
    Enable-ScheduledTask -TaskName $poller | Out-Null
}
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $matchday 'automation\sunday_ship.ps1') -SkipRefresh *>&1 | Out-File $log -Append -Encoding utf8
"ship exit $LASTEXITCODE; done $(Get-Date -f o)" | Out-File $log -Append -Encoding utf8
