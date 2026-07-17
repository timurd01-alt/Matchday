@echo off
cd /d "%~dp0"
echo Fetching mlb data once...
python fetch_data.py --mlb
pause
