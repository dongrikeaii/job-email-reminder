@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   秋招邮件雷达 - Windows 一键安装
echo   ---------------------------------
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-windows.ps1"
echo.
pause
