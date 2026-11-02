@echo off
title Update CFP Rankings and Bracket
echo Requesting the online Matchday rankings and bracket update.
echo Your computer can be closed after the request is accepted.
echo Tuesday evening updates also run automatically online.
echo.
"C:\Program Files\GitHub CLI\gh.exe" workflow run deploy.yml --repo timurd01-alt/Matchday --ref main
if errorlevel 1 (
  echo Update request failed. Check your internet connection and GitHub sign-in.
) else (
  echo Update requested. Results will appear after the online checks and publishing finish.
  start "" "https://github.com/timurd01-alt/Matchday/actions/workflows/deploy.yml"
)
pause
