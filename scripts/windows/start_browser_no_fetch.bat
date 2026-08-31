@echo off
cd /d "%~dp0..\..\"
python app.py --browser --no-fetch
pause
