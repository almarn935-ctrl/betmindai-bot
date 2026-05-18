@echo off
chcp 65001 >nul
title BetMindAI Bot

set TELEGRAM_BOT_8626920056:AAGrsygHfLE4ICxmcP3xWdcg4uSqpkOqB1o

set ODDS_API_KEY=
set FOOTBALL_API_KEY=

if "%TELEGRAM_BOT_TOKEN%"=="8626920056:AAGrsygHfLE4ICxmcP3xWdcg4uSqpkOqB1o" (
    echo.
    echo  [ERROR] Token not set!
    echo  Open start_bot.bat in Notepad and replace ВСТАВЬ_ТОКЕН_СЮДА with your token
    echo.
    pause
    exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
    where python3 >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  [ERROR] Python not found!
        echo  Download from python.org and install with "Add to PATH" checked
        echo.
        pause
        exit /b 1
    )
    set PYTHON=python3
) else (
    set PYTHON=python
)

echo  [1/3] Python found OK
echo  [2/3] Installing dependencies...
%PYTHON% -m pip install -r requirements.txt -q
echo  [3/3] Starting bot...
echo.
echo  Bot is running! Open @BetMindAI13_bot in Telegram
echo  Press Ctrl+C to stop
echo.

%PYTHON% bot.py

echo.
echo  Bot stopped.
pause
