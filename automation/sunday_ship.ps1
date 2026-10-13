# Sunday ship: refresh Sigma Lab, then publish its handoff to Matchday.
#
# Runs on the owner's machine because Sigma Lab (and its SQLite database)
# lives here, not in GitHub. Order matters and is fixed:
#
#   1. refresh run     results, play-by-play, EPA, ratings, settle, power poll
#   2. forecast slate  the coming week's predictions (8 days; the rest of the
#                      season is forecast separately so it never delays this)
#   3. upset settle    grade last week's upset card
#   4. upset publish   record the coming week's card (--as-of next Monday,
#                      because Sunday is still the outgoing ISO week)
#   5. matchday export write sigmalab_picks.json (copied to Matchday as betbetter_picks.json)
#   6. ship            validate + rebuild the snapshot + full test suite in a
#                      private worktree off origin/main, then push to main.
#                      The push triggers deploy.yml, which publishes the site.
#
# Never touches the owner's own Matchday checkout: the ship happens in
# .worktrees/sunday-ship, reset to origin/main each run. If anything fails
# before the push, nothing is published and the last good site stays up.
# The owner's ballot is never written here -- `ballot publish` stays manual.
param(
    [string]$SigmaLab = (Join-Path $env:USERPROFILE 'Desktop\Sigma Lab'),
    [string]$PythonPath = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    [switch]$NoPush,
    # Ship the handoff already on disk; skip the Sigma Lab refresh.
    [switch]$SkipRefresh,
    # Run even if this week was already shipped (the desktop button uses this).
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$matchday = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDir = Join-Path $matchday 'automation\logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("sunday-ship-{0:yyyy-MM-dd_HHmm}.log" -f (Get-Date))
function Say([string]$m) { $line = "{0:HH:mm:ss} $m" -f (Get-Date); $line | Tee-Object -FilePath $log -Append | Write-Host }
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

# The five-minute data task writes the same SQLite file; two writers at once
# is what once filled the disk. Pause it for the run, always re-enable.
# The week being shipped, named by its Monday. The Monday catch-up trigger
# exits here when Sunday already shipped this week.
$monday = (Get-Date).Date.AddDays(((8 - [int](Get-Date).DayOfWeek) % 7))
$asOf = $monday.ToString('yyyy-MM-dd')
$marker = Join-Path $logDir 'last-shipped-week.txt'
if (-not $Force -and -not $SkipRefresh -and (Test-Path $marker) -and ((Get-Content $marker -Raw).Trim() -eq $asOf)) {
    Say "week of $asOf already shipped; nothing to do"
    exit 0
}

$poller = 'Sigma Lab Personal Data Refresh'
$pollerPaused = $false
try {
    if (-not $SkipRefresh -and (Get-ScheduledTask -TaskName $poller -ErrorAction SilentlyContinue)) {
        Stop-ScheduledTask -TaskName $poller -ErrorAction SilentlyContinue
        Disable-ScheduledTask -TaskName $poller | Out-Null
        $pollerPaused = $true
        Start-Sleep -Seconds 5
    }

    if ($SkipRefresh) { Say 'skipping Sigma Lab refresh (-SkipRefresh)' } else {
        # refresh exits 1 when a backlog remains (e.g. a late game with no
        # play-by-play yet); that is reported, not fatal.
        # The five-minute poller is paused for the run, and it is what fetches
        # final scores -- so fetch them here first, or late Saturday games are
        # still unfinished when the refresh grades the week.
        Run 'fetch finals' $SigmaLab $PythonPath @('-m','sigmalab','once','--force') -Soft
        Run 'refresh run' $SigmaLab $PythonPath @('-m','sigmalab','refresh','run','--handoff=') -Soft
        # Every game of the past week must be graded before the scorecard ships.
        foreach ($attempt in 1..3) {
            Push-Location $SigmaLab
            & $PythonPath -m sigmalab forecast pending *> $null
            $pending = $LASTEXITCODE
            Pop-Location
            if ($pending -eq 0) { Say '   every game of the past week is graded'; break }
            Say "   ungraded games remain (attempt $attempt); fetching finals and grading again"
            Run 'fetch finals' $SigmaLab $PythonPath @('-m','sigmalab','once','--force') -Soft
            Run 'grade' $SigmaLab $PythonPath @('-m','sigmalab','forecast','settle') -Soft
        }
        Run 'pending check' $SigmaLab $PythonPath @('-m','sigmalab','forecast','pending') -Soft
        # The coming week only: the publish is what has to be fresh. The rest
        # of the season (about 560 games, nearly an hour) is a separate job.
        Run 'forecast slate' $SigmaLab $PythonPath @('-m','sigmalab','forecast','slate','--sport','ncaaf','--days','8') -Soft
        # Basketball: posted rosters first (a late transfer or a new posting
        # changes the preseason), then the season rated against its prior, the
        # Top 25, and the picks read from those ratings.
        $hoopsSeason = if ((Get-Date).Month -ge 7) { (Get-Date).Year + 1 } else { (Get-Date).Year }
        Run 'basketball rosters' $SigmaLab $PythonPath @('-m','sigmalab','hoops','rosters') -Soft
        Run 'basketball ratings' $SigmaLab $PythonPath @('-m','sigmalab','hoops','rate','--league','ncaam','--project','--season',"$hoopsSeason") -Soft
        Run 'basketball Top 25' $SigmaLab $PythonPath @('-m','sigmalab','poll','publish','--sport','ncaam') -Soft
        Run 'basketball forecast slate' $SigmaLab $PythonPath @('-m','sigmalab','forecast','slate','--sport','ncaam','--days','8') -Soft
        # Bracketology: the season's schedule topped up, then the field projected
        # with last week's file kept for movement arrows.
        Run 'basketball schedule' $SigmaLab $PythonPath @('-m','sigmalab','hoops','backfill','--season',"$hoopsSeason",'--league','ncaam') -Soft
        $bkOut = Join-Path $SigmaLab 'output\bracketology_ncaam.json'
        $bkPrev = Join-Path $SigmaLab 'output\bracketology_ncaam.previous.json'
        if (Test-Path $bkOut) { Copy-Item -Force $bkOut $bkPrev }
        $bkArgs = @('-m','sigmalab','hoops','bracketology','--season',"$hoopsSeason",'--out',$bkOut)
        if (Test-Path $bkPrev) { $bkArgs += @('--previous',$bkPrev) }
        Run 'basketball bracketology' $SigmaLab $PythonPath $bkArgs -Soft
        Run 'upset settle' $SigmaLab $PythonPath @('-m','sigmalab','upset','settle') -Soft
        Run "upset publish (as of $asOf)" $SigmaLab $PythonPath @('-m','sigmalab','upset','publish','--as-of',$asOf) -Soft
        Run 'matchday export' $SigmaLab $PythonPath @('-m','sigmalab','matchday','export','--out','sigmalab_picks.json')
    }
} finally {
    if ($pollerPaused) { Enable-ScheduledTask -TaskName $poller | Out-Null }
}

# ---- ship ---------------------------------------------------------------
$tree = Join-Path $matchday '.worktrees\sunday-ship'
Push-Location $matchday
try {
    git fetch -q origin main
    if (-not (Test-Path $tree)) { git worktree add -q --detach $tree origin/main }
} finally { Pop-Location }
Push-Location $tree
try {
    git checkout -q --detach origin/main
    git reset -q --hard origin/main
    Copy-Item -Force (Join-Path $SigmaLab 'sigmalab_picks.json') (Join-Path $tree 'betbetter_picks.json')
    $bk = Join-Path $SigmaLab 'output\bracketology_ncaam.json'
    if (Test-Path $bk) { Copy-Item -Force $bk (Join-Path $tree 'bracketology_ncaam.json') }

    Run 'validate handoff' $tree $PythonPath @('-c', "import betbetter_handoff as h, json, sys; d=json.load(open('betbetter_picks.json',encoding='utf-8')); v=d.get('handoff_version'); sys.exit(0 if v in h.SUPPORTED_VERSIONS else 'unsupported handoff_version %r' % v)")
    # Stop before publishing if this week's picks fell sharply against what is live.
    Run 'check pick coverage' $tree $PythonPath @('check_pick_coverage.py')
    Run 'rebuild snapshot + AP poll' $tree $PythonPath @('build_cfb_snapshot.py')
    Run 'test suite' $tree $PythonPath @('-m','unittest','discover','-p','test_*.py')

    git add -- betbetter_picks.json matchday-cfb-snapshot.js
    if (Test-Path ap_poll_snapshot.json) { git add -- ap_poll_snapshot.json }
    if (Test-Path bracketology_ncaam.json) { git add -- bracketology_ncaam.json }
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { Say 'nothing changed; site already current'; if (-not $SkipRefresh) { Set-Content $marker $asOf }; return }
    git -c core.autocrlf=false commit -q -m "Sunday ship: ratings, results, AP poll and next week's picks ($asOf week)"
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
    if (-not $SkipRefresh) { Set-Content $marker $asOf }
    Say "shipped $(git rev-parse --short HEAD); deploy.yml publishes the site"
} finally { Pop-Location }
