@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
python -m PyInstaller --noconsole --onefile --name WardogsAutoklicker --add-data "index.html;." --add-data "assets\teams;assets\teams" main.py
echo.
echo Fertig! Deine EXE liegt in: dist\WardogsAutoklicker.exe
pause
