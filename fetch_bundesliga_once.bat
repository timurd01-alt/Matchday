@echo off
cd /d "%~dp0"
echo Fetching bundesliga data once...
python fetch_data.py --bundesliga
pause
