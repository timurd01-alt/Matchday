@echo off
cd /d "%~dp0"
echo Fetching ncaaf data once...
python fetch_data.py --ncaaf
pause
