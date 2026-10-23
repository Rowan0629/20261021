@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 劇團資產管理 bot（關掉這個視窗，bot 就會下線）
echo 劇團公演資產庫存管理 bot 啟動中...
echo 看到「已上線」就可以到 Discord 傳照片。這個視窗請保持開著；要停止就按 Ctrl + C 或直接關掉視窗。
echo.
"%USERPROFILE%\.local\bin\uv.exe" run python -m troupe_bot
echo.
echo bot 已經停止（結束碼 %ERRORLEVEL%），原因請看上面的訊息。
pause
