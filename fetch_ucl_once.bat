@echo off
cd /d "%~dp0"
echo Fetching ucl data once...
python fetch_data.py --ucl
pause
