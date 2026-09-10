@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 秋招邮件雷达

echo.
echo   秋招邮件雷达 - 本地看板
echo   --------------------------
echo.

rem 探测 Python：WorkBuddy 自带 > python > py -3
set "PYEXE="
for /f "delims=" %%i in ('dir /b /s "%USERPROFILE%\.workbuddy\binaries\python\versions\python.exe" 2^>nul') do set "PYEXE=%%i"
if not defined PYEXE (
  where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
  where py >nul 2>nul && set "PYEXE=py -3"
)
if not defined PYEXE (
  echo   未找到 Python 3。
  echo   安装：winget install Python.Python.3.12
  echo.
  pause
  exit /b 1
)

echo   使用: %PYEXE%
echo   浏览器会自动打开 http://127.0.0.1:8787
echo   关闭本窗口即停止服务。
echo.
echo   正在后台刷新数据（约需 30 秒）...
echo.

rem 启动即扫描一次，保证打开看板看到的是最新数据
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-windows.ps1" -ScanOnly -Days 7

%PYEXE% serve.py
pause
