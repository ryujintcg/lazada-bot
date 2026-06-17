@echo off
title Lazada Bot - GUI
cd /d "%~dp0"
call venv\Scripts\activate
python gui_app.py
pause
