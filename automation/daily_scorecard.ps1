# Daily NCAAM scorecard publication, run by the scheduled task from the
# dedicated publisher clone (see install_scorecard_task.ps1), never from a
# development checkout: a dev tree carries uncommitted edits and feature
# branches, so what ran would not be what main says runs.
#
# Moves this clone to origin/main first, then runs the ship script in a child
# process so the freshly checked-out version is the one that executes.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
git -C $root fetch -q origin main
if ($LASTEXITCODE -ne 0) { throw 'Could not fetch origin/main; nothing published' }
git -C $root checkout -q --detach origin/main
if ($LASTEXITCODE -ne 0) { throw 'Could not move the publisher clone to origin/main; nothing published' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'automation\sunday_ship.ps1') -Sport ncaam -ScorecardOnly
exit $LASTEXITCODE
