@echo off
title Finlumiq — Smart Student Expense Tracker
color 0A
setlocal

echo ========================================
echo   Finlumiq - Smart Student Tracker
echo ========================================
echo.

REM ---- Step 0: Check/Start MySQL ----
echo [0/3] Checking MySQL...

REM Check if port 3306 is already open
netstat -an 2>nul | findstr /C:"0.0.0.0:3306" /C:"[::]:3306" >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo         MySQL already running on port 3306. OK.
    goto :start_backend
)

REM Try to start the MySQL92 Windows service (needs admin)
sc query MySQL92 >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo         Found MySQL92 service. Trying to start...
    net start MySQL92 >nul 2>&1
    if %ERRORLEVEL% == 0 (
        echo         MySQL92 service started!
        goto :start_backend
    )
    echo         Could not start MySQL92 service (may need to run as Administrator).
)

REM Try XAMPP MySQL if present
if exist "C:\xampp\mysql\bin\mysqld.exe" (
    echo         Trying XAMPP MariaDB...
    start "XAMPP MySQL" /MIN "C:\xampp\mysql\bin\mysqld.exe" "--defaults-file=C:\xampp\mysql\bin\my.ini" "--standalone"
    timeout /t 4 /nobreak >nul
    netstat -an 2>nul | findstr /C:"0.0.0.0:3306" /C:"[::]:3306" >nul 2>&1
    if %ERRORLEVEL% == 0 (
        echo         XAMPP MariaDB started!
        goto :start_backend
    )
    echo         XAMPP MariaDB did not bind to port 3306.
)

echo.
echo [!] WARNING: MySQL is NOT running on port 3306.
echo     The application will not work without a database.
echo.
echo     To fix this, choose ONE of the following:
echo       A) Open XAMPP Control Panel as Administrator and click START next to MySQL
echo       B) Run this batch file as Administrator (right-click → Run as administrator)
echo       C) Open the Windows Services panel and start the MySQL92 service manually
echo.
echo     Continuing anyway — start MySQL, then refresh the browser.
echo.

:start_backend
REM ---- Step 1: Flask Backend ----
echo [1/3] Starting Flask Backend (port 5000)...
start "Finlumiq Backend" cmd /k "cd /d "%~dp0backend" && python app.py"
timeout /t 3 /nobreak >nul

REM ---- Step 2: Frontend HTTP Server ----
echo [2/3] Starting Frontend Server (port 8000)...
start "Finlumiq Frontend" cmd /k "cd /d "%~dp0" && python -m http.server 8000"
timeout /t 2 /nobreak >nul

REM ---- Step 3: Open browser ----
echo [3/3] Opening browser...
start "" "http://127.0.0.1:8000"

echo.
echo ========================================
echo   Finlumiq is running!
echo   Frontend : http://127.0.0.1:8000
echo   Backend  : http://127.0.0.1:5000/api
echo   Database : localhost:3306 (expense_tracker)
echo ========================================
echo.
echo   Both servers are running in their own windows.
echo   Close those windows to stop the servers.
echo   This window can be closed.
echo.
pause >nul
