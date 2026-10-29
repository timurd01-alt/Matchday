. (Join-Path $PSScriptRoot 'engine_paths.ps1')
# Open this week's ballot in Notepad. If it does not exist yet, start it from
# the most recent earlier ballot so only the changes need typing. The next
# "Update Matchday" run (button or the Sunday schedule) checks and publishes it.
# One team per line, best first, 25 lines.
$TRDLab = Resolve-TRDLabRoot
$dir = Join-Path $TRDLab 'ballots\ncaaf'
New-Item -ItemType Directory -Force $dir | Out-Null
$sunday = (Get-Date).Date.AddDays(-[int](Get-Date).DayOfWeek).ToString('yyyy-MM-dd')
$file = Join-Path $dir "$sunday.txt"
if (-not (Test-Path $file)) {
    $last = Get-ChildItem $dir -Filter '????-??-??.txt' | Where-Object { $_.BaseName -lt $sunday } |
        Sort-Object BaseName | Select-Object -Last 1
    if ($last) { Copy-Item $last.FullName $file; Write-Host "Started this week's ballot from $($last.BaseName)." }
    else { Set-Content -Path $file -Value '' -Encoding utf8; Write-Host 'Started a blank ballot.' }
}
Write-Host "Editing $file"
Write-Host 'One team per line, best first, 25 teams. Save and close Notepad, then press Update Matchday.'
Start-Process notepad.exe -ArgumentList "`"$file`"" -Wait
$py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
Push-Location $TRDLab
& $py -m trdlab ballot check $file
Pop-Location
