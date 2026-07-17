@echo off
cd /d "%~dp0"
echo Fetching laliga data once...
python fetch_data.py --laliga
pause
