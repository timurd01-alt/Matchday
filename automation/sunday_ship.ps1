# Sunday ship: refresh TRDLab, then publish its handoff to Matchday.
#
# Runs on the owner's machine because TRDLab (and its SQLite database)
# lives here, not in GitHub. Order matters and is fixed:
#
#   1. refresh run     results, play-by-play, EPA, ratings, settle, power poll
#   2. forecast slate  current week for desktop updates, upcoming slate for scheduled runs
#   3. upset settle    grade last week's upset card
#   4. upset publish   record the coming week's card (--as-of next Monday,
#                      because Sunday is still the outgoing ISO week)
#   5. matchday export write trdlab_picks.json (copied to Matchday as trdlab_picks.json)
#   6. ship            validate + rebuild the snapshot + full test suite in a
#                      private worktree off origin/main, then push to main.
#                      The push triggers deploy.yml, which publishes the site.
#
# Never touches the owner's own Matchday checkout: the ship happens in
# .worktrees/sunday-ship, reset to origin/main each run. If anything fails
# before the push, nothing is published and the last good site stays up.
# The owner's ballot is published here only when the owner has written this
# week's file (Desktop buttons "Edit My Ballot - ..."): TRDLab/ballots/<ncaaf|ncaam>/<Sunday>.txt.
# No file means last week's ballot stays up; nothing is ever invented.
param(
    [Alias('SigmaLab')][string]$TRDLab = '',
    [string]$PythonPath = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    [ValidateSet('both','ncaaf','ncaam')][string]$Sport = 'both',
    [switch]$NoPush,
    # Publish the poller's graded cards without rerunning weekly ratings.
    [switch]$ScorecardOnly,
    # Ship the handoff already on disk; skip the TRDLab refresh.
    [switch]$SkipRefresh,
    # Run even if this week was already shipped (the desktop button uses this).
    [switch]$Force
)
. (Join-Path $PSScriptRoot 'engine_paths.ps1')
$TRDLab = Resolve-TRDLabRoot -Root $TRDLab
if ($ScorecardOnly -and $Sport -eq 'both') { throw '-ScorecardOnly requires -Sport ncaam or ncaaf' }
$ErrorActionPreference = 'Stop'
$matchday = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDir = Join-Path $matchday 'automation\logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("sunday-ship-{0:yyyy-MM-dd_HHmm}.log" -f (Get-Date))
function Say([string]$m) { $line = "{0:HH:mm:ss} $m" -f (Get-Date); $line | Out-File -FilePath $log -Append -Encoding utf8; Write-Host $line }
function Run([string]$what, [string]$dir, [string]$exe, [string[]]$argv, [switch]$Soft) {
    Say "== $what"
    Push-Location $dir
    # PowerShell 5.1 turns any stderr line from a native exe into a
    # terminating error under 'Stop'; the exit code is the real verdict.
    $ErrorActionPreference = 'Continue'
    try {
        & $exe @argv *>&1 | ForEach-Object { "$_" } | Out-File -FilePath $log -Append -Encoding utf8
        $code = $LASTEXITCODE
    } finally { Pop-Location }
    if ($code -ne 0) {
        if ($Soft) { Say "   (exit $code, continuing)" } else { throw "$what failed (exit $code); see $log" }
    }
}

# Both desktop buttons pass -Force. Capture the current Central week once,
# so a run that crosses midnight does not start forecasting the next week.
$forecastCutoffUtc = $null
if ($Force -and -not $SkipRefresh) {
    $central = [TimeZoneInfo]::FindSystemTimeZoneById('Central Standard Time')
    $today = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $central).Date
    $daysSinceMonday = ([int]$today.DayOfWeek + 6) % 7
    $nextMonday = $today.AddDays(7 - $daysSinceMonday)
    # Sunday belongs to the coming week: Saturday's games are final, and the
    # cutoff would otherwise be hours away, publishing no picks (2026-11-08).
    if ($today.DayOfWeek -eq [DayOfWeek]::Sunday) { $nextMonday = $nextMonday.AddDays(7) }
    $forecastCutoffUtc = [TimeZoneInfo]::ConvertTimeToUtc($nextMonday, $central)
    Say "manual forecast cutoff: $($nextMonday.ToString('yyyy-MM-dd HH:mm')) Central"
}
function RunForecastSlate([string]$sportKey) {
    $days = 8
    if ($null -ne $forecastCutoffUtc) {
        $days = ($forecastCutoffUtc - [DateTime]::UtcNow).TotalDays
        if ($days -le 0) { Say "current week ended; skipping $sportKey forecast slate"; return }
    }
    $horizon = $days.ToString([Globalization.CultureInfo]::InvariantCulture)
    Run "$sportKey forecast slate" $TRDLab $PythonPath @('-m','trdlab','forecast','slate','--sport',$sportKey,'--days',$horizon) -Soft
}

# The five-minute data task writes the same SQLite file; two writers at once
# is what once filled the disk. Pause it for the run, always re-enable.
# The week being shipped, named by its Monday. The Monday catch-up trigger
# exits here when Sunday already shipped this week.
$monday = (Get-Date).Date.AddDays(((8 - [int](Get-Date).DayOfWeek) % 7))
$asOf = $monday.ToString('yyyy-MM-dd')
$marker = Join-Path $logDir 'last-shipped-week.txt'
if (-not $ScorecardOnly -and -not $Force -and -not $SkipRefresh -and (Test-Path $marker) -and ((Get-Content $marker -Raw).Trim() -eq $asOf)) {
    Say "week of $asOf already shipped; nothing to do"
    exit 0
}

if ($Sport -ne 'both') {
    $env:TRDLAB_SPORTS = $Sport
    $marker = Join-Path $logDir "last-shipped-$Sport.txt"
}
# The manual buttons and scheduled ship share the same publication worktree.
try {
    $shipLock = [IO.File]::Open((Join-Path $logDir 'ship.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
} catch { throw 'Another Matchday update is running, or the update lock is inaccessible.' }
try {
$poller = Resolve-TRDLabRefreshTask
$pollerPaused = $false
try {
    if (-not $ScorecardOnly -and -not $SkipRefresh -and (Get-ScheduledTask -TaskName $poller -ErrorAction SilentlyContinue)) {
        Stop-ScheduledTask -TaskName $poller -ErrorAction SilentlyContinue
        Disable-ScheduledTask -TaskName $poller | Out-Null
        $pollerPaused = $true
        Start-Sleep -Seconds 5
    }

    if ($ScorecardOnly) { Say 'reading graded cards from the poller; no weekly refresh' } elseif ($SkipRefresh) { Say 'skipping TRDLab refresh (-SkipRefresh)' } else {
        # refresh exits 1 when a backlog remains (e.g. a late game with no
        # play-by-play yet); that is reported, not fatal.
        # The five-minute poller is paused for the run, and it is what fetches
        # final scores -- so fetch them here first, or late Saturday games are
        # still unfinished when the refresh grades the week.
        Run 'fetch finals' $TRDLab $PythonPath @('-m','trdlab','once','--force') -Soft
        Run 'refresh run' $TRDLab $PythonPath @('-m','trdlab','refresh','run','--handoff=') -Soft
        # Refresh already grades completed games. Report any remaining backlog
        # once so missing finals do not restart the fetch and grading steps.
        Run 'pending check' $TRDLab $PythonPath @('-m','trdlab','forecast','pending') -Soft
        if ($Sport -ne 'ncaam') {
        RunForecastSlate 'ncaaf'
        }
        if ($Sport -ne 'ncaaf') {
        # Basketball: posted rosters first (a late transfer or a new posting
        # changes the preseason), then the season rated against its prior, the
        # Top 25, and the picks read from those ratings.
        $hoopsSeason = if ((Get-Date).Month -ge 7) { (Get-Date).Year + 1 } else { (Get-Date).Year }
        Run 'basketball rosters' $TRDLab $PythonPath @('-m','trdlab','hoops','rosters') -Soft
        # This week's results and their box scores before rating: the rating
        # solves on box-score possessions, and without them it re-stored the
        # preseason prior every week (2026-11-06: zero 2026-27 box scores).
        Run 'basketball results' $TRDLab $PythonPath @('-m','trdlab','hoops','backfill','--season',"$hoopsSeason",'--league','ncaam') -Soft
        Run 'basketball box scores' $TRDLab $PythonPath @('-m','trdlab','hoops','boxes','--season',"$hoopsSeason",'--limit','2000') -Soft
        Run 'basketball ratings' $TRDLab $PythonPath @('-m','trdlab','hoops','rate','--league','ncaam','--project','--season',"$hoopsSeason") -Soft
        Run 'basketball Top 25' $TRDLab $PythonPath @('-m','trdlab','poll','publish','--sport','ncaam') -Soft
        RunForecastSlate 'ncaam'
        # Bracketology: the season's schedule topped up, then the field projected
        # with last week's file kept for movement arrows.
        Run 'basketball schedule' $TRDLab $PythonPath @('-m','trdlab','hoops','backfill','--season',"$hoopsSeason",'--league','ncaam') -Soft
        $bkOut = Join-Path $TRDLab 'output\bracketology_ncaam.json'
        $bkPrev = Join-Path $TRDLab 'output\bracketology_ncaam.previous.json'
        if (Test-Path $bkOut) { Copy-Item -Force $bkOut $bkPrev }
        $bkArgs = @('-m','trdlab','hoops','bracketology','--season',"$hoopsSeason",'--out',$bkOut)
        if (Test-Path $bkPrev) { $bkArgs += @('--previous',$bkPrev) }
        Run 'basketball bracketology' $TRDLab $PythonPath $bkArgs -Soft
        }
        Run 'upset settle' $TRDLab $PythonPath @('-m','trdlab','upset','settle') -Soft
        Run "upset publish (as of $asOf)" $TRDLab $PythonPath @('-m','trdlab','upset','publish','--as-of',$asOf) -Soft
        # The owner's ballots, dated this week's Sunday, for each sport being
        # shipped that has one written (Desktop "Edit My Ballot" buttons).
        $ballotDay = (Get-Date).Date.AddDays(-[int](Get-Date).DayOfWeek).ToString('yyyy-MM-dd')
        foreach ($ballotSport in @('ncaaf','ncaam')) {
            if ($Sport -ne 'both' -and $Sport -ne $ballotSport) { continue }
            $ballotFile = Join-Path $TRDLab (Join-Path 'ballots' (Join-Path $ballotSport "$ballotDay.txt"))
            if (Test-Path $ballotFile) {
                Run "$ballotSport ballot publish ($ballotDay)" $TRDLab $PythonPath @('-m','trdlab','ballot','publish',$ballotFile,'--sport',$ballotSport,'--date',$ballotDay) -Soft
            } else { Say "   no $ballotSport ballot file for $ballotDay; last week's ballot stays up" }
        }
        Run 'matchday export' $TRDLab $PythonPath @('-m','trdlab','matchday','export','--sport','ncaaf','--sport','ncaam','--out','trdlab_picks.json')
    }
} finally {
    if ($pollerPaused) { Enable-ScheduledTask -TaskName $poller | Out-Null }
}

# ---- ship ---------------------------------------------------------------
$tree = Join-Path $matchday '.worktrees\sunday-ship'
Push-Location $matchday
try {
    git fetch -q origin main
    if ($LASTEXITCODE -ne 0) { throw 'Could not update from origin/main; nothing published' }
    if (-not (Test-Path $tree)) { git worktree add -q --detach $tree origin/main }
} finally { Pop-Location }
Push-Location $tree
try {
    git checkout -q --detach origin/main
    if ($LASTEXITCODE -ne 0) { throw 'Could not select origin/main' }
    git reset -q --hard origin/main
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare publication checkout' }
    if ($ScorecardOnly) {
        Run 'refresh engine scorecard' $tree $PythonPath @('refresh_engine_scorecard.py','--engine',$TRDLab,'--sport',$Sport)
    } elseif ($Sport -eq 'both') {
        Copy-Item -Force (Join-Path $TRDLab 'trdlab_picks.json') (Join-Path $tree 'trdlab_picks.json')
    } else {
        Run 'merge selected sport into published handoff' $tree $PythonPath @((Join-Path $PSScriptRoot 'merge_sport.py'), $Sport, (Join-Path $TRDLab 'trdlab_picks.json'), (Join-Path $tree 'trdlab_picks.json'))
    }
    $bk = Join-Path $TRDLab 'output\bracketology_ncaam.json'
    if (-not $ScorecardOnly -and $Sport -ne 'ncaaf' -and (Test-Path $bk)) { Copy-Item -Force $bk (Join-Path $tree 'bracketology_ncaam.json') }

    Run 'validate handoff' $tree $PythonPath @('-c', "import trdlab_handoff as h, json, sys; d=json.load(open('trdlab_picks.json',encoding='utf-8')); v=d.get('handoff_version'); sys.exit(0 if v in h.SUPPORTED_VERSIONS else 'unsupported handoff_version %r' % v)")
    # Stop before publishing if this week's picks fell sharply against what is live.
    if (-not $ScorecardOnly) {
    Run 'check pick coverage' $tree $PythonPath @('check_pick_coverage.py')
    # Stop before publishing on missing results, wrong records, or projected
    # scores drifting from the model line (2026-10-18).
    Run 'check handoff integrity' $tree $PythonPath @('check_handoff_integrity.py')
    }
    if ($ScorecardOnly) {
        Run 'rebuild scorecard snapshot' $tree $PythonPath @('build_cfb_snapshot.py','--scorecard-only')
    } else {
        Run 'rebuild snapshot + AP poll' $tree $PythonPath @('build_cfb_snapshot.py')
    }
    git diff --quiet -- trdlab_picks.json matchday-cfb-snapshot.js ap_poll_snapshot.json bracketology_ncaam.json
    if ($LASTEXITCODE -eq 1) {
        Run 'shipment release note' $tree $PythonPath @('write_ship_release.py')
        Run 'rebuild release notes' $tree $PythonPath @('build_updates.py')
    } elseif ($LASTEXITCODE -ne 0) { throw 'Could not inspect shipment changes' }
    Run 'test suite' $tree $PythonPath @('-m','unittest','discover','-p','test_*.py')

    git add -- trdlab_picks.json matchday-cfb-snapshot.js updates updates.js
    if ($LASTEXITCODE -ne 0) { throw 'Could not stage shipment' }
    if (Test-Path ap_poll_snapshot.json) { git add -- ap_poll_snapshot.json; if ($LASTEXITCODE -ne 0) { throw 'Could not stage AP snapshot' } }
    if (Test-Path bracketology_ncaam.json) { git add -- bracketology_ncaam.json; if ($LASTEXITCODE -ne 0) { throw 'Could not stage bracketology' } }
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { Say 'nothing changed; site already current'; if (-not $ScorecardOnly -and -not $SkipRefresh) { Set-Content $marker $asOf }; return }
    $message = if ($ScorecardOnly) { "Daily scorecard: $Sport graded cards ($((Get-Date).ToString('yyyy-MM-dd')))" } else { "Sunday ship: ratings, results, AP poll and next week's picks ($asOf week)" }
    git -c core.autocrlf=false commit -q -m $message
    if ($LASTEXITCODE -ne 0) { throw 'Could not commit shipment; nothing pushed' }
    if ($NoPush) { Say 'committed in worktree, not pushed (-NoPush)'; return }
    $pushed = $false
    foreach ($i in 1..3) {
        git push -q origin HEAD:main
        if ($LASTEXITCODE -eq 0) { $pushed = $true; break }
        Say "push attempt $i lost a race; rebasing"
        git pull -q --rebase origin main
        if ($LASTEXITCODE -ne 0) { cmd /c 'git rebase --abort 2>nul' }
    }
    if (-not $pushed) { throw "could not push after 3 attempts; see $log" }
    if (-not $ScorecardOnly -and -not $SkipRefresh) { Set-Content $marker $asOf }
    Say "shipped $(git rev-parse --short HEAD); deploy.yml publishes the site"
} finally { Pop-Location }

} finally { $shipLock.Dispose() }
