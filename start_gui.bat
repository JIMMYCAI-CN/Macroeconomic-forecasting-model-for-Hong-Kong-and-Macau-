@echo off
chcp 65001 >nul
rem 宏觀預測模型（面向港澳）— 圖形介面
cd /d "%~dp0"
python run_macro.py --gui
if errorlevel 1 pause
