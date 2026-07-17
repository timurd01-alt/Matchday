@echo off
cd /d "%~dp0"
echo Fetching ligue1 data once...
python fetch_data.py --ligue1
pause
