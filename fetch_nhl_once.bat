@echo off
cd /d "%~dp0"
echo Fetching nhl data once...
python fetch_data.py --nhl
pause
