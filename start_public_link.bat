@echo off
title TiBe Global Public Link
echo ===================================================
echo     GENERATING A GLOBAL PUBLIC LINK
echo ===================================================
echo.
echo Make sure your 'start_server.bat' is ALREADY RUNNING!
echo.
echo Checking security keys...
if not exist "%USERPROFILE%\.ssh" (
    mkdir "%USERPROFILE%\.ssh"
)
if not exist "%USERPROFILE%\.ssh\id_rsa" (
    echo Generating a free security key so it doesn't ask for a password...
    ssh-keygen -t rsa -b 2048 -f "%USERPROFILE%\.ssh\id_rsa" -q -N ""
)
echo.
echo Connecting to the Pinggy tunnel...
echo Look for a URL below that ends in "pinggy.link". That is your global link!
echo.
ssh -p 443 -i "%USERPROFILE%\.ssh\id_rsa" -o StrictHostKeyChecking=no -R0:localhost:8000 a.pinggy.io
echo.
echo [ERROR] The connection closed or failed to start.
cmd /k
