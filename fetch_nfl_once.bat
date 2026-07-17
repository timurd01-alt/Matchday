@echo off
cd /d "%~dp0"
echo Fetching nfl data once...
python fetch_data.py --nfl
pause
