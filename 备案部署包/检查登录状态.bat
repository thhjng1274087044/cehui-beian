@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
title 备案登录状态自检

echo.
echo  ===== 备案登录状态自检 =====
echo  目标站: https://hyjg.zrzyt.zj.gov.cn/main.htm
echo  CDP   : http://localhost:9333
echo.

REM ---- 先看 CDP 端口通不通 ----
netstat -ano | findstr ":9333" | findstr LISTENING >nul
if errorlevel 1 (
  echo  [X] 9333 端口没有监听 —— Chrome 没起来，或者不是用 start_chrome.bat 起的。
  echo      请先双击 start_chrome.bat。
  echo.
  pause
  exit /b 2
)
echo  [OK] 9333 端口在监听，Chrome 已就绪
echo.

REM ---- 找一个装了 playwright 的 python ----
set "PY="
python -c "import playwright" >nul 2>&1
if not errorlevel 1 set "PY=python"
if not defined PY (
  py -3 -c "import playwright" >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY if exist "C:/Program Files/Python312/python.exe" set "PY=C:/Program Files\Python312\python.exe"
if not defined PY if exist "C:/Users/lenovo/AppData/Local/Programs/Python/Python312/python.exe" set "PY=C:/Users/lenovo/AppData/Local/Programs/Python/Python312/python.exe"

if not defined PY (
  echo  [X] 找不到装了 playwright 的 python。
  echo      请在 CMD 里跑:  pip install playwright
  echo.
  pause
  exit /b 3
)
echo  用 python: %PY%
echo.
%PY% beian_browser.py state
echo.
echo  ------------------------------------------------------------
echo   has_password_input = false  ->  已登录，可以开跑
echo   has_password_input = true   ->  还没登录 / 登录态已过期，回 Chrome 重新登录
echo  ------------------------------------------------------------
echo.
pause
exit /b 0
