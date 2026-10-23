@echo off
chcp 936 >nul
title 备案专用 Chrome 启动器
setlocal
set "PROFILE=%~dp0browser_profile_beian"
set "PORT=9333"
set "URL=https://hyjg.zrzyt.zj.gov.cn/main.htm"
set "CHROME="

REM ==== 自动探测 Chrome 路径（本机 / 服务器 通用，无需手工改）====
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "C:/Users/admin/AppData/Local/Google/Chrome/Application/chrome.exe" set "CHROME=C:/Users/admin/AppData/Local/Google/Chrome/Application/chrome.exe"

if not defined CHROME goto nochrome
if not exist "%PROFILE%" mkdir "%PROFILE%"

netstat -ano | findstr ":%PORT%" | findstr LISTENING >nul
if not errorlevel 1 goto already

echo.
echo  启动 Chrome  调试端口 %PORT%  独立 profile
echo  Chrome: %CHROME%
echo.
start "" "%CHROME%" --remote-debugging-port=%PORT% --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check --disable-background-networking "%URL%"
goto done

:already
echo.
echo  [!] 端口 %PORT% 已在监听 —— Chrome 已经在跑了，不重复启动。
echo      如果没看到窗口，翻一下任务栏（可能被最小化了）。
echo.
start "" "%CHROME%" "%URL%"
goto done

:done
echo.
echo  下一步：在这个 Chrome 窗口里人工登录
echo    账号 <PLATFORM_ACCOUNT>
echo    密码 + 图形验证码必须手输，脚本不代填
echo.
echo  登录完成后回到本窗口按任意键，自动做一次登录状态自检。
pause >nul
call "%~dp0检查登录状态.bat"
exit /b 0

:nochrome
echo.
echo  [ERROR] 没找到 chrome.exe
echo  请用记事本打开本文件，手工设置 CHROME 变量。
echo.
pause
exit /b 1
