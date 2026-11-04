@echo off
chcp 65001 >nul
rem HK/MO Macro Discount Rate Engine
cd /d "%~dp0"
python run_macro.py
echo.
if errorlevel 1 pause
