@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 參數 hidden＝背景模式（由 start_bot_hidden.vbs 呼叫）：沒有視窗，訊息改寫進 data\startup.log，結束時不 pause
set HIDDEN=
if /i "%~1"=="hidden" set HIDDEN=1
set LOG=%~dp0data\startup.log

if not defined HIDDEN title 劇團資產管理 bot（關掉這個視窗，bot 就會下線）
if not defined HIDDEN (
    echo 劇團公演資產庫存管理 bot 啟動中...
    echo 看到「待命中」後，請管理員到 Discord 頻道輸入 !上線，bot 才會開始處理照片。這個視窗請保持開著（可以縮小）。
    echo 要停止：按 Ctrl + C，再輸入 Y；或直接關掉視窗。
    echo.
)

:run
if defined HIDDEN goto run_hidden
"%USERPROFILE%\.local\bin\uv.exe" run python -m troupe_bot
goto ran

:run_hidden
if not exist "%~dp0data" mkdir "%~dp0data"
if exist "%LOG%" for %%F in ("%LOG%") do if %%~zF GTR 1000000 del "%LOG%"
set PYTHONIOENCODING=utf-8
"%USERPROFILE%\.local\bin\uv.exe" run python -m troupe_bot >>"%LOG%" 2>&1

:ran
set CODE=%ERRORLEVEL%

rem 0 = 正常結束；2~5 = 設定有問題（重開也沒用）；-1073741510 = 使用者按了 Ctrl + C
if "%CODE%"=="0" goto stopped
if "%CODE%"=="-1073741510" goto stopped
if %CODE% GEQ 2 if %CODE% LEQ 5 goto stopped

if not defined HIDDEN echo.
call :say bot 意外停止（結束碼 %CODE%），10 秒後自動重新啟動。
rem 用 ping 當計時器：背景模式沒有可用的鍵盤輸入，timeout 會立刻失敗而變成無間隔重開
ping -n 11 127.0.0.1 >nul
goto run

:stopped
if not defined HIDDEN echo.
call :say bot 已經停止（結束碼 %CODE%），原因請看上面的訊息或 data\startup.log。
if not defined HIDDEN pause
exit /b %CODE%

:say
if defined HIDDEN (>>"%LOG%" echo %date% %time% %*) else (echo %*)
exit /b 0
