@echo off
cd /d "%~dp0"
echo Rebuilding data.json with football-data.org + The Odds API...
python fetch_data.py
echo.
echo If odds failed, copy the diagnostics above.
pause
