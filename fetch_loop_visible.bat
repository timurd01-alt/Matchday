@echo off
cd /d "%~dp0"
python fetch_data.py --loop
pause
