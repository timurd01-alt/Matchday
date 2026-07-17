@echo off
cd /d "%~dp0"
echo Fetching nba data once...
python fetch_data.py --nba
pause
