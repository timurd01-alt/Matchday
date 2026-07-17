@echo off
cd /d "%~dp0"
echo Fetching seriea data once...
python fetch_data.py --seriea
pause
