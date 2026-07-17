@echo off
cd /d "%~dp0"
echo Fetching epl data once...
python fetch_data.py --epl
pause
