# Sunday ship: refresh Bet Better, then publish its handoff to Matchday.
#
# Runs on the owner's machine because Bet Better (and its SQLite database)
# lives here, not in GitHub. Order matters and is fixed:
#
#   1. refresh run     results, play-by-play, EPA, ratings, settle, power poll
#   2. forecast slate  the coming week's predictions
#   3. upset settle    grade last week's upset card
#   4. upset publish   record the coming week's card (--as-of next Monday,
#                      because Sunday is still the outgoing ISO week)
#   5. matchday export write betbetter_picks.json
#   6. ship            validate + rebuild the snapshot + full test suite in a
#                      private worktree off origin/main, then push to main.
#                      The push triggers deploy.yml, which publishes the site.
#
# Never touches the owner's own Matchday checkout: the ship happens in
# .worktrees/sunday-ship, reset to origin/main each run. If anything fails
# before the push, nothing is published and the last good site stays up.
# The owner's ballot is never written here -- `ballot publish` stays manual.
param(
    [string]$BetBetter = (Join-Path $env:USERPROFILE 'Desktop\Bet Better'),
    [string]$PythonPath = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    [switch]$NoPush,
    # Ship the handoff already on disk; skip the Bet Better refresh.
    [switch]$SkipRefresh
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
if (-not $SkipRefresh -and (Test-Path $marker) -and ((Get-Content $marker -Raw).Trim() -eq $asOf)) {
    Say "week of $asOf already shipped; nothing to do"
    exit 0
}

$poller = 'BetBetter Personal Data Refresh'
$pollerPaused = $false
try {
    if (-not $SkipRefresh -and (Get-ScheduledTask -TaskName $poller -ErrorAction SilentlyContinue)) {
        Stop-ScheduledTask -TaskName $poller -ErrorAction SilentlyContinue
        Disable-ScheduledTask -TaskName $poller | Out-Null
        $pollerPaused = $true
        Start-Sleep -Seconds 5
    }

    if ($SkipRefresh) { Say 'skipping Bet Better refresh (-SkipRefresh)' } else {
        # refresh exits 1 when a backlog remains (e.g. a late game with no
        # play-by-play yet); that is reported, not fatal.
        Run 'refresh run' $BetBetter $PythonPath @('-m','betbetter','refresh','run','--handoff','') -Soft
        Run 'forecast slate' $BetBetter $PythonPath @('-m','betbetter','forecast','slate') -Soft
        Run 'upset settle' $BetBetter $PythonPath @('-m','betbetter','upset','settle') -Soft
        Run "upset publish (as of $asOf)" $BetBetter $PythonPath @('-m','betbetter','upset','publish','--as-of',$asOf) -Soft
        Run 'matchday export' $BetBetter $PythonPath @('-m','betbetter','matchday','export','--out','betbetter_picks.json')
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
    Copy-Item -Force (Join-Path $BetBetter 'betbetter_picks.json') (Join-Path $tree 'betbetter_picks.json')

    Run 'validate handoff' $tree $PythonPath @('-c', "import betbetter_handoff as h, json, sys; d=json.load(open('betbetter_picks.json',encoding='utf-8')); v=d.get('handoff_version'); sys.exit(0 if v in h.SUPPORTED_VERSIONS else 'unsupported handoff_version %r' % v)")
    Run 'rebuild snapshot + AP poll' $tree $PythonPath @('build_cfb_snapshot.py')
    Run 'test suite' $tree $PythonPath @('-m','unittest','discover','-p','test_*.py')

    git add -- betbetter_picks.json matchday-cfb-snapshot.js
    if (Test-Path ap_poll_snapshot.json) { git add -- ap_poll_snapshot.json }
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
