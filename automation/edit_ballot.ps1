# Open this week's ballot in Notepad, for football (ncaaf) or basketball (ncaam).
# If it does not exist yet, start it from the most recent earlier ballot for the
# same sport so only the changes need typing; a sport's first ballot starts from
# the engine's resume scorecard (every team's record, SOR, best win and worst
# loss as comments above the blank list). The next "Update Matchday" run for
# that sport (button or schedule) checks and publishes it.
# One team per line, best first, 25 lines.
param([ValidateSet('ncaaf','ncaam')][string]$Sport = 'ncaaf')
. (Join-Path $PSScriptRoot 'engine_paths.ps1')
$TRDLab = Resolve-TRDLabRoot
$py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
$label = if ($Sport -eq 'ncaam') { 'Basketball' } else { 'College Football' }
$dir = Join-Path $TRDLab "ballots\$Sport"
New-Item -ItemType Directory -Force $dir | Out-Null
$sunday = (Get-Date).Date.AddDays(-[int](Get-Date).DayOfWeek).ToString('yyyy-MM-dd')
$file = Join-Path $dir "$sunday.txt"
if (-not (Test-Path $file)) {
    $last = Get-ChildItem $dir -Filter '????-??-??.txt' | Where-Object { $_.BaseName -lt $sunday } |
        Sort-Object BaseName | Select-Object -Last 1
    if ($last) { Copy-Item $last.FullName $file; Write-Host "Started this week's $label ballot from $($last.BaseName)." }
    else {
        Push-Location $TRDLab
        & $py -m trdlab ballot scorecard $file --sport $Sport --limit 60 | Out-Null
        Pop-Location
        if (-not (Test-Path $file)) { Set-Content -Path $file -Value '' -Encoding utf8 }
        Write-Host "Started a blank $label ballot, with every team's resume listed above it."
    }
}
Write-Host "Editing $file"
Write-Host "One team per line, best first, 25 teams. Save and close Notepad, then press Update Matchday - $label."
Start-Process notepad.exe -ArgumentList "`"$file`"" -Wait
Push-Location $TRDLab
& $py -m trdlab ballot check $file --sport $Sport
Pop-Location
